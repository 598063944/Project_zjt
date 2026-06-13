"""
报表持久化层

支持两种存储后端:
1. JSON 文件 (默认) — 兼容旧版 config.json
2. MySQL 元数据表 — 可选，多用户共享

v1→v2 迁移: 将 config.json → custom_reports → presets 转为 ReportDefinition 格式
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional
from copy import deepcopy

from .models import ReportDefinition, JoinDefinition, MatchKey, FieldColumn, FilterCondition

logger = logging.getLogger(__name__)


# 配置文件路径
def _get_storage_path() -> str:
    """获取报表配置存储文件路径"""
    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              '.config')
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, 'custom_reports_v2.json')


class ReportRepository:
    """报表配置 CRUD"""

    def __init__(self, storage_path: str = None):
        self._path = storage_path or _get_storage_path()
        self._cache: dict[str, ReportDefinition] = {}
        self._empty_folders: set = set()  # 空文件夹集合
        self._load()

    def _load(self):
        """从文件加载所有报表"""
        if not os.path.exists(self._path):
            self._cache = {}
            self._empty_folders = set()
            return
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            reports_data = data.get('reports', {}) if isinstance(data, dict) else {}
            for rid, rdata in reports_data.items():
                try:
                    self._cache[rid] = ReportDefinition.from_dict(rdata)
                except Exception as e:
                    logger.warning(f"加载报表 {rid} 失败: {e}")
            # 加载空文件夹列表
            folders_data = data.get('empty_folders', [])
            self._empty_folders = set(folders_data) if isinstance(folders_data, list) else set()
        except Exception as e:
            logger.error(f"加载报表配置失败: {e}")
            self._cache = {}
            self._empty_folders = set()

    def _save(self):
        """保存所有报表到文件（原子写入：先写临时文件，再重命名）"""
        import os
        data = {
            'version': 2,
            'reports': {rid: rpt.to_dict() for rid, rpt in self._cache.items()},
            'empty_folders': sorted(list(self._empty_folders)),
        }
        tmp_path = self._path + '.tmp'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)  # 原子操作（同文件系统内）
        except Exception:
            # 清理临时文件
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise

    # ---------- CRUD ----------

    def get(self, report_id: str) -> Optional[ReportDefinition]:
        return self._cache.get(report_id)

    def get_by_name(self, name: str) -> Optional[ReportDefinition]:
        for rpt in self._cache.values():
            if rpt.name == name:
                return rpt
        return None

    def list_all(self, search: str = None) -> list[ReportDefinition]:
        """列出所有报表（支持按名称搜索），按修改时间倒序"""
        reports = list(self._cache.values())
        if search:
            kw = search.lower()
            reports = [r for r in reports if kw in r.name.lower()]
        reports.sort(key=lambda r: r.modified_at or r.created_at or '', reverse=True)
        return reports

    def save(self, report: ReportDefinition):
        """保存报表（新增或更新）"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if not report.created_at:
            report.created_at = now
        report.modified_at = now
        report.version += 1
        self._cache[report.id] = report
        self._save()

    def save_filters(self, report_id: str, filters: list):
        """仅更新筛选条件（不递增版本号，避免无意义的版本变化）"""
        rpt = self._cache.get(report_id)
        if not rpt:
            return
        rpt.filters = list(filters)
        rpt.modified_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._save()

    def delete(self, report_id: str) -> bool:
        if report_id in self._cache:
            del self._cache[report_id]
            self._save()
            return True
        return False

    def duplicate(self, report_id: str, new_name: str) -> Optional[ReportDefinition]:
        """复制报表"""
        original = self._cache.get(report_id)
        if not original:
            return None
        new_report = ReportDefinition.from_dict(deepcopy(original.to_dict()))
        new_report.id = ''  # 由 __post_init__ 重新生成
        # 让 dataclass 重新生成 id
        from uuid import uuid4
        new_report.id = uuid4().hex[:12]
        new_report.name = new_name
        new_report.created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_report.modified_at = new_report.created_at
        new_report.result_table_name = f"cr_{new_report.id}"
        new_report.result_row_count = 0
        new_report.last_refresh_time = ''
        self._cache[new_report.id] = new_report
        self._save()
        return new_report

    def count(self) -> int:
        return len(self._cache)

    # ---------- 文件夹管理 ----------

    def list_folders(self) -> list[dict]:
        """扫描所有报表的 folder_path，构建文件夹树结构。
        Returns:
            [{name, path, count, children: [...]}, ...]
            根节点: {name: "全部报表", path: "__root__", count, children}
        """
        # 统计每个文件夹路径下的报表数量
        folder_counts: dict[str, int] = {}
        for rpt in self._cache.values():
            fp = (rpt.folder_path or "").strip()
            if fp:
                # 统计所有层级
                parts = fp.replace("\\", "/").split("/")
                for i in range(len(parts)):
                    sub = "/".join(parts[:i + 1])
                    folder_counts[sub] = folder_counts.get(sub, 0) + 1
            else:
                folder_counts["__root__"] = folder_counts.get("__root__", 0) + 1

        # 补充空文件夹（count=0 但有子文件夹的也会显示）
        for ef in self._empty_folders:
            fp = ef.strip()
            if fp and fp not in folder_counts:
                folder_counts[fp] = 0
                # 确保所有父级路径也存在
                parts = fp.replace("\\", "/").split("/")
                for i in range(len(parts) - 1):
                    parent = "/".join(parts[:i + 1])
                    if parent not in folder_counts:
                        folder_counts[parent] = folder_counts.get(parent, 0)

        # 构建嵌套树
        def _build_tree(parent_path: str, entries: dict[str, int]) -> list[dict]:
            children = []
            # 找出直接子节点
            direct_children = set()
            for path in entries:
                if path == parent_path:
                    continue
                parent = "/".join(path.split("/")[:-1]) if "/" in path else "__root__"
                if parent == parent_path:
                    direct_children.add(path)

            for path in sorted(direct_children):
                name = path.split("/")[-1]
                sub_children = _build_tree(path, entries)
                children.append({
                    "name": name,
                    "path": path,
                    "count": entries.get(path, 0),
                    "children": sub_children,
                })
            return children

        root_count = folder_counts.get("__root__", 0)
        total_count = len(self._cache)
        tree = _build_tree("__root__", folder_counts)

        return [{
            "name": "全部报表",
            "path": "__root__",
            "count": total_count,
            "children": tree,
        }]

    def list_by_folder(self, folder_path: str, search: str = None) -> list:
        """按文件夹过滤报表（支持搜索）。
        Args:
            folder_path: "__root__" 表示根目录，空字符串也视为根目录，其他为具体路径
        """
        reports = list(self._cache.values())
        if search:
            kw = search.lower()
            reports = [r for r in reports if kw in r.name.lower()]

        if not folder_path or folder_path == "__root__":
            reports = [r for r in reports if not (r.folder_path or "").strip()]
        else:
            reports = [r for r in reports if (r.folder_path or "").strip() == folder_path]

        reports.sort(key=lambda r: r.modified_at or r.created_at or "", reverse=True)
        return reports

    def create_folder(self, folder_path: str) -> bool:
        """创建空文件夹。"""
        fp = folder_path.strip()
        if not fp or fp in self._empty_folders:
            return False
        # 检查是否已被报表使用
        for rpt in self._cache.values():
            if (rpt.folder_path or "").strip() == fp:
                return False  # 文件夹已存在（有报表使用）
        self._empty_folders.add(fp)
        self._save()
        return True

    def move_to_folder(self, report_id: str, folder_path: str):
        """移动报表到指定文件夹。"""
        rpt = self._cache.get(report_id)
        if not rpt:
            return False
        rpt.folder_path = folder_path.strip()
        rpt.modified_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 如果目标文件夹之前是空文件夹，移除空标记
        target = folder_path.strip()
        if target and target in self._empty_folders:
            self._empty_folders.discard(target)
        self._save()
        return True

    def rename_folder(self, old_path: str, new_path: str):
        """重命名文件夹，批量更新所有匹配路径前缀的报表。
        例如 old_path="销售" → new_path="销售管理"，则 "销售/月度" → "销售管理/月度"。
        """
        old = old_path.strip()
        new = new_path.strip()
        if not old or old == new:
            return 0
        count = 0
        for rpt in self._cache.values():
            fp = (rpt.folder_path or "").strip()
            if fp == old or fp.startswith(old + "/"):
                if fp == old:
                    rpt.folder_path = new
                else:
                    rpt.folder_path = new + fp[len(old):]
                rpt.modified_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                count += 1
        # 更新空文件夹
        new_empty = set()
        for ef in self._empty_folders:
            if ef == old:
                new_empty.add(new)
                count += 1
            elif ef.startswith(old + "/"):
                new_empty.add(new + ef[len(old):])
                count += 1
            else:
                new_empty.add(ef)
        self._empty_folders = new_empty
        if count > 0:
            self._save()
        return count

    def delete_folder(self, folder_path: str, delete_reports: bool = False) -> int:
        """删除文件夹。
        Args:
            folder_path: 要删除的文件夹路径
            delete_reports: True=同时删除文件夹下的报表，False=将报表移到根目录
        Returns: 受影响的报表数量
        """
        fp = folder_path.strip()
        if not fp:
            return 0
        count = 0
        ids_to_delete = []
        for rid, rpt in list(self._cache.items()):
            rfp = (rpt.folder_path or "").strip()
            if rfp == fp or rfp.startswith(fp + "/"):
                if delete_reports:
                    ids_to_delete.append(rid)
                else:
                    rpt.folder_path = ""
                    rpt.modified_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                count += 1
        for rid in ids_to_delete:
            del self._cache[rid]

        # 删除空文件夹及其子文件夹
        to_remove = {ef for ef in self._empty_folders if ef == fp or ef.startswith(fp + "/")}
        self._empty_folders -= to_remove
        count += len(to_remove)

        if count > 0:
            self._save()
        return count


# ==================== v1 → v2 迁移 ====================

def migrate_v1_to_v2(config: dict) -> dict[str, ReportDefinition]:
    """
    将 v1 格式 (config.json → custom_reports → presets) 迁移为 ReportDefinition 列表

    v1 格式:
      {
        "报表名": {
          "data_objects": [{"name": "商机", "api_name": "NewOpportunityObj", "enabled": true, "match_field": "..."}],
          "main_source": "NewOpportunityObj",
          "field_configs": [
            {
              "display_name": "商机名称",
              "source_api_name": "NewOpportunityObj",
              "field_name": "name",
              "main_link_field": "",
              "source_link_field": ""
            }
          ],
          "date_start": "2026-01-01",
          "date_end": "2026-05-24",
          "filter_conditions": [...],
          "visible_headers": [...],
          "header_order": [...]
        }
      }
    """
    custom_reports = config.get('custom_reports', {})
    if not isinstance(custom_reports, dict):
        return {}

    presets = custom_reports.get('presets', {})
    if not isinstance(presets, dict):
        return {}

    migrated = {}
    for name, state in presets.items():
        if not isinstance(state, dict):
            continue
        if state.get('type') == 'folder':
            continue

        # 解析 data_objects → 提取 joins
        data_objects = state.get('data_objects', [])
        main_source = state.get('main_source', '')
        if not main_source and data_objects:
            main_source = data_objects[0].get('api_name', 'NewOpportunityObj')

        joins = []
        for obj in data_objects:
            if not isinstance(obj, dict):
                continue
            api = obj.get('api_name', '')
            match_raw = obj.get('match_field', '')
            if not api or api == main_source:
                continue
            if match_raw:
                try:
                    match_info = json.loads(match_raw) if isinstance(match_raw, str) else match_raw
                    if isinstance(match_info, dict):
                        joins.append(JoinDefinition(
                            left_object_api=main_source,
                            right_object_api=api,
                            match_keys=[MatchKey(
                                left_field=match_info.get('main', ''),
                                right_field=match_info.get('source', ''),
                            )],
                        ))
                except (json.JSONDecodeError, TypeError):
                    pass

        # 解析 field_configs → columns
        field_configs = state.get('field_configs', [])
        columns = []
        for i, fc in enumerate(field_configs):
            if not isinstance(fc, dict):
                continue
            display_name = fc.get('display_name', '')
            field_name = fc.get('field_name', '')
            if not display_name and not field_name:
                continue
            columns.append(FieldColumn(
                display_name=display_name or field_name,
                source_object_api=fc.get('source_api_name', main_source),
                source_field=field_name,
                sort_order=i,
            ))

        # 解析 filter_conditions → filters
        v1_filters = state.get('filter_conditions', [])
        filters = []
        for fc in v1_filters:
            if not isinstance(fc, dict):
                continue
            filters.append(FilterCondition(
                field_api=fc.get('field', ''),
                operator=fc.get('operator', 'EQ'),
                value=fc.get('value', ''),
            ))

        report = ReportDefinition(
            name=name,
            main_object_api=main_source,
            joins=joins,
            columns=columns,
            filters=filters,
            date_start=state.get('date_start', ''),
            date_end=state.get('date_end', ''),
            date_range_enabled=bool(state.get('date_start')),
            created_at=state.get('created', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            modified_at=state.get('modified', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        )
        migrated[report.id] = report

    return migrated


def run_migration_if_needed(config: dict) -> Optional[dict[str, ReportDefinition]]:
    """检查并执行 v1→v2 迁移，返回迁移后的报表或 None"""
    custom_reports = config.get('custom_reports', {})
    if not isinstance(custom_reports, dict):
        return None

    presets = custom_reports.get('presets', {})
    if not presets or not isinstance(presets, dict):
        return None

    # 检查是否已经有 v2 配置
    v2_path = _get_storage_path()
    if os.path.exists(v2_path):
        return None  # 已迁移

    logger.info("检测到 v1 报表配置，开始迁移...")
    migrated = migrate_v1_to_v2(config)

    if migrated:
        repo = ReportRepository()
        for rpt in migrated.values():
            repo.save(rpt)
        logger.info(f"已迁移 {len(migrated)} 个报表到 v2 格式")

    return migrated
