"""
报表管理器（对外 API）

整合 repository、db_manager、syncer、fetcher，提供统一的 API 供主程序调用。

用法:
    from custom_report.manager import ReportManager

    mgr = ReportManager(mysql_config, crm_client)
    mgr.initialize()  # 初始化连接 + 迁移

    # 获取页面
    list_page = mgr.get_list_page()
    editor_page = mgr.get_editor_page()

    # 加载对象元数据
    mgr.set_object_meta({...})

    # 编辑报表
    mgr.open_report(report_id)
    mgr.new_report(main_api)
"""

import logging
from typing import Optional

from .models import ReportDefinition
from .repository import ReportRepository, migrate_v1_to_v2, run_migration_if_needed
from .db_manager import ReportDatabase
from .fetcher import DataFetcher
from .syncer import SourceTableSyncer, ReportRefreshWorker
from .utils import guess_field_label

logger = logging.getLogger(__name__)


def _mysql_type_to_generic(mysql_type: str) -> str:
    """将 MySQL 数据类型映射为通用类型"""
    t = (mysql_type or '').lower()
    if any(x in t for x in ('int', 'decimal', 'float', 'double', 'numeric')):
        return 'number'
    elif any(x in t for x in ('date', 'time', 'timestamp')):
        return 'date'
    return 'text'


class ReportManager:
    """报表功能管理器 — 门面类"""

    def __init__(self, mysql_config: dict = None, crm_client=None, app_config: dict = None,
                 save_config_fn=None, load_config_fn=None):
        """
        Args:
            mysql_config: config.json → mysql_config
            crm_client: FXiaokeCRM 实例
            app_config: 完整应用配置
            save_config_fn: callable(config_dict)，保存配置到用户个人文件
            load_config_fn: callable() → config_dict，重新加载最新配置
        """
        self._config = app_config or {}
        self._save_config_fn = save_config_fn
        self._load_config_fn = load_config_fn

        # 数据库
        mysql_cfg = mysql_config or self._config.get('mysql_config', {})
        self._db = ReportDatabase(mysql_cfg) if mysql_cfg.get('enabled') else None

        # 持久化
        self._repo = ReportRepository()

        # 数据获取
        self._fetcher = DataFetcher(crm_client, self._config)

        # 同步和刷新
        self._syncer = SourceTableSyncer(self._db, self._fetcher) if self._db else None
        self._refresh_worker = ReportRefreshWorker(self._db, self._syncer) if self._db else None

        # UI 页面（延迟创建）
        self._list_page = None
        self._editor_page = None

        # 对象元数据
        self._object_meta: dict[str, dict] = {}

        self._initialized = False

    # ==================== 初始化 ====================

    @property
    def db_available(self) -> bool:
        return self._db is not None and self._db.available

    @property
    def db_status(self) -> str:
        if self._db:
            return self._db.status_message
        return "⚠️ MySQL 未配置"

    def initialize(self):
        """初始化：检查数据库连接、执行迁移"""
        if self._initialized:
            return

        # 设置 UI 日志：所有 logger.info/warning/error → 运行时窗口
        from . import setup_ui_logging
        setup_ui_logging()

        # 执行 v1→v2 迁移
        try:
            run_migration_if_needed(self._config)
        except Exception as e:
            logger.warning(f"配置迁移失败（非致命）: {e}")

        self._initialized = True

        if self._db:
            logger.info(f"报表数据库: {self._db.status_message}")
        else:
            logger.info("报表数据库未启用（使用文件存储）")

    # ==================== 对象元数据 ====================

    def load_object_meta_from_config(self):
        """从配置加载 CRM 对象元数据"""
        # 从磁盘重新加载最新配置（避免读取到过时的 _config 引用）
        if self._load_config_fn:
            try:
                cfg = self._load_config_fn()
                if cfg:
                    self._config = cfg
            except Exception:
                pass
        crm_objs = self._config.get('fxiaoke', {}).get('crm_objects', [])
        if not crm_objs:
            # 默认对象列表
            crm_objs = [
                {'name': '商机', 'api_name': 'NewOpportunityObj'},
                {'name': '销售订单', 'api_name': 'SalesOrderObj'},
                {'name': '发货单', 'api_name': 'DeliveryNoteObj'},
                {'name': '发货单产品', 'api_name': 'DeliveryNoteProductObj'},
                {'name': '客户', 'api_name': 'AccountObj'},
                {'name': '联系人', 'api_name': 'ContactObj'},
                {'name': '公立项目授权', 'api_name': 'public_project_authorizati__c'},
            ]

        meta = {}
        for obj in crm_objs:
            if isinstance(obj, dict):
                api = obj.get('api_name', '')
                name = obj.get('name', api)
                if api:
                    # 从配置获取字段列表
                    field_cfg = self._config.get('fxiaoke', {}).get('crm_object_fields', {}).get(api, {})
                    fields = []
                    if field_cfg and isinstance(field_cfg, dict):
                        for key, info in field_cfg.items():
                            if isinstance(info, dict) and info.get('enabled', True):
                                label = info.get('label', '') or guess_field_label(key)
                                # 推断是否为日期/时间字段
                                is_time = bool(info.get('is_time', False))
                                if not is_time:
                                    dt = (info.get('dataType', '') or '').lower()
                                    if dt in ('datetime', 'timestamp', 'date'):
                                        is_time = True
                                fields.append((key, label, is_time))
                            elif isinstance(info, str):
                                fields.append((key, info, False))
                    meta[api] = {'name': name, 'fields': fields}

        # 校验：用 MySQL 中实际存在的表名修正可能的配置名称错误
        if self._db and self._db.available:
            for api, info in meta.items():
                config_name = info.get('name', api)
                try:
                    db_table = self._db.resolve_existing_table(api)
                    if db_table and db_table.startswith('对象-'):
                        db_name = db_table[3:]
                        if db_name and db_name != config_name:
                            info['name'] = db_name
                except Exception:
                    pass

        self._object_meta = meta

    def set_object_meta(self, meta: dict[str, dict]):
        """
        设置对象元数据

        Args:
            meta: {api_name: {name: "中文名", fields: [(key, label, is_time), ...]}}
                  兼容旧格式 [(key, label), ...]
        """
        self._object_meta = meta

    def get_object_meta(self) -> dict[str, dict]:
        return dict(self._object_meta)

    def get_object_name(self, api_name: str) -> str:
        """获取对象中文名"""
        return self._object_meta.get(api_name, {}).get('name', api_name)

    # ==================== 报表 CRUD ====================

    def list_reports(self, search: str = None) -> list[ReportDefinition]:
        return self._repo.list_all(search=search)

    def get_report(self, report_id: str) -> Optional[ReportDefinition]:
        return self._repo.get(report_id)

    def save_report(self, report: ReportDefinition):
        self._repo.save(report)

    def save_report_filters(self, report_id: str, filters: list):
        """仅保存筛选条件，不改变版本号"""
        self._repo.save_filters(report_id, filters)

    def delete_report(self, report_id: str):
        self._repo.delete(report_id)
        if self._db:
            try:
                self._db.delete_report_meta(report_id)
            except Exception:
                pass

    def duplicate_report(self, report_id: str, new_name: str) -> Optional[ReportDefinition]:
        return self._repo.duplicate(report_id, new_name)

    def create_empty_report(self, main_api: str = "") -> ReportDefinition:
        rpt = ReportDefinition(main_object_api=main_api)
        return rpt

    # ==================== 文件夹管理 ====================

    def create_folder(self, folder_path: str) -> bool:
        """创建空文件夹"""
        return self._repo.create_folder(folder_path)

    def list_folders(self) -> list[dict]:
        """获取文件夹树结构"""
        return self._repo.list_folders()

    def list_reports_by_folder(self, folder_path: str, search: str = None) -> list[ReportDefinition]:
        """按文件夹过滤报表列表"""
        return self._repo.list_by_folder(folder_path, search=search)

    def move_report_to_folder(self, report_id: str, folder_path: str) -> bool:
        """移动报表到指定文件夹"""
        return self._repo.move_to_folder(report_id, folder_path)

    def rename_folder(self, old_path: str, new_path: str) -> int:
        """重命名文件夹，返回受影响报表数"""
        return self._repo.rename_folder(old_path, new_path)

    def delete_folder(self, folder_path: str, delete_reports: bool = False) -> int:
        """删除文件夹，返回受影响报表数"""
        return self._repo.delete_folder(folder_path, delete_reports)

    # ==================== 数据操作 ====================

    def refresh_report(self, report: ReportDefinition,
                       progress_callback=None) -> dict:
        """
        刷新报表数据（仅拼表，不从 CRM 拉取）

        Returns:
            {'success': bool, 'row_count': int, 'error': str, 'duration': float}
        """
        if not self._refresh_worker:
            return {'success': False, 'row_count': 0, 'error': '数据库未连接', 'duration': 0}

        result = self._refresh_worker.refresh(report, progress_callback)
        # 不在此处保存 report，因为调用者可能临时修改了 report（如清空 filters 以拉取全量数据）。
        # 调用者应在恢复临时修改后自行调用 save_report() 持久化。
        return result

    def full_refresh_report(self, report: ReportDefinition,
                            progress_callback=None) -> dict:
        """
        完整刷新：从 CRM 拉取最新数据 → 写入 MySQL → 拼表生成结果表。

        Returns:
            {'success': bool, 'row_count': int, 'error': str, 'duration': float}
        """
        if not self._refresh_worker:
            return {'success': False, 'row_count': 0, 'error': '数据库未连接', 'duration': 0}

        result = self._refresh_worker.full_refresh(report, progress_callback)
        if result['success']:
            self._repo.save(report)
        return result

    def query_preview(self, report_id: str, page: int = 1, page_size: int = 50,
                      search: str = None) -> tuple[list[dict], int]:
        """查询预览数据"""
        if not self._db:
            return [], 0
        return self._db.query_result(report_id, page=page, page_size=page_size, search=search)

    def sync_object(self, object_api: str, max_records: int = 10000) -> dict:
        """同步单个对象"""
        if not self._syncer:
            return {'rows': 0, 'error': '数据库未连接', 'duration': 0}
        return self._syncer.sync_single(object_api, max_records=max_records)

    def get_result_table_name(self, report_id: str) -> str:
        return ReportDatabase.result_table_name(report_id)

    # ==================== UI 页面 ====================

    def get_list_page(self):
        """获取报表列表页"""
        if self._list_page is None:
            from .views.report_list_page import ReportListPage
            self._list_page = ReportListPage(
                self._repo,
                save_config_fn=self._save_config_fn,
                load_config_fn=self._load_config_fn,
            )
            # 传递对象名映射（API 名 → 中文名）
            name_map = {api: meta.get('name', api) for api, meta in self._object_meta.items()}
            self._list_page.set_object_name_map(name_map)

            # 连接信号
            self._list_page.reportEdit.connect(self._on_list_edit)
            self._list_page.newReport.connect(self._on_list_new)
            self._list_page.newReportWithMain.connect(self._on_list_new_with_main)

        return self._list_page

    def get_editor_page(self):
        """获取报表编辑器页"""
        if self._editor_page is None:
            from .views.report_editor_page import ReportEditorPage

            def _save_filters(report_id, conditions):
                """自动保存筛选条件到 report（与详情页同步，重启后不清空）。"""
                from .models import FilterCondition
                filters = [
                    FilterCondition(
                        field_api=c.get('field', ''),
                        operator=c.get('operator', 'EQ'),
                        value=c.get('value', ''),
                        target_object_api=c.get('target_object_api', ''),
                        field_label=c.get('field_label', ''),
                        expose=c.get('expose', False),
                        is_date_field=c.get('is_date', False),
                    )
                    for c in conditions
                ]
                self._repo.save_filters(report_id, filters)

            self._editor_page = ReportEditorPage(
                self._repo, self._db, self._fetcher,
                app_config=self._config,
                save_config_fn=self._save_config_fn,
                load_config_fn=self._load_config_fn,
                save_filters_fn=_save_filters,
                excel_repo=self.excel_dataset_repo,
            )
            self._editor_page.set_object_meta(self._object_meta)

            # 连接信号
            self._editor_page.backRequested.connect(self._on_editor_back)

        return self._editor_page

    def open_report_in_editor(self, report_id: str):
        """在编辑器中打开报表"""
        rpt = self._repo.get(report_id)
        if rpt:
            editor = self.get_editor_page()
            editor.set_object_meta(self._object_meta)
            editor.load_report(rpt)
            return editor
        return None

    def new_report_in_editor(self, main_api: str = "", folder_path: str = ""):
        """在编辑器中新建报表"""
        editor = self.get_editor_page()
        editor.set_object_meta(self._object_meta)
        editor.new_report(main_api)
        # 设置文件夹路径
        if folder_path:
            editor._pending_folder_path = folder_path
        return editor

    # ==================== 信号处理 ====================

    def _on_list_edit(self, report_id: str):
        """列表页请求编辑 → 由主程序处理页面切换"""
        pass

    def _on_list_new(self):
        pass

    def _on_list_new_with_main(self, main_api: str):
        pass

    def _on_editor_back(self):
        pass

    # ==================== 仪表盘管理 ====================

    @property
    def dashboard_repo(self):
        """获取仪表盘仓库（懒加载）"""
        if not hasattr(self, '_dashboard_repo') or self._dashboard_repo is None:
            from .dashboard.repository import DashboardRepository, ExcelDatasetRepository
            self._dashboard_repo = DashboardRepository()
            self._excel_dataset_repo = ExcelDatasetRepository()
        return self._dashboard_repo

    @property
    def excel_dataset_repo(self):
        """获取 Excel 数据集仓库（懒加载）"""
        if not hasattr(self, '_excel_dataset_repo') or self._excel_dataset_repo is None:
            _ = self.dashboard_repo  # 触发初始化
        return self._excel_dataset_repo

    def get_dashboard_list_page(self):
        """获取仪表盘列表页"""
        from .dashboard.dashboard_list_page import DashboardListPage
        page = DashboardListPage(self.dashboard_repo)
        return page

    def get_dashboard_view_page(self):
        """获取仪表盘查看页"""
        from .dashboard.dashboard_view_page import DashboardViewPage
        from .dashboard.bridge import DashboardBridge
        bridge = DashboardBridge()
        page = DashboardViewPage(bridge)
        page.backRequested.connect(self._on_editor_back)
        return page

    def get_dashboard_designer(self):
        """获取仪表盘设计器"""
        from .dashboard.dashboard_designer import DashboardDesigner
        from .dashboard.bridge import DashboardBridge
        bridge = DashboardBridge()
        designer = DashboardDesigner(bridge, db=self._db, excel_repo=self.excel_dataset_repo, report_manager=self)
        designer.backRequested.connect(self._on_editor_back)
        return designer

    # ===== 仪表盘 CRUD =====

    def list_dashboards(self, search: str = None) -> list:
        return self.dashboard_repo.list_all(search=search)

    def get_dashboard(self, dashboard_id: str):
        return self.dashboard_repo.get(dashboard_id)

    def save_dashboard(self, dashboard):
        self.dashboard_repo.save(dashboard)

    def delete_dashboard(self, dashboard_id: str):
        self.dashboard_repo.delete(dashboard_id)

    def duplicate_dashboard(self, dashboard_id: str, new_name: str):
        return self.dashboard_repo.duplicate(dashboard_id, new_name)

    # ===== 数据源发现 =====

    def get_available_data_sources(self) -> dict:
        """
        返回所有可用于 BI 仪表盘的数据源。

        Returns:
            {
                'reports': [{id, name, row_count, fields: [{key, label, data_type}], table_name}],
                'excel_datasets': [{id, name, row_count, columns: [{key, label, data_type}], table_name}],
                'mysql_tables': [{name, row_count, columns: [{key, label, data_type}]}],
            }
        """
        result = {'reports': [], 'excel_datasets': [], 'mysql_tables': []}

        # 自定义报表：仅加载"报表-"前缀的直连表（用户从报表编辑器同步过来的）
        if self._db and self._db.available:
            try:
                rpt_tables = self._db.execute(
                    "SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE '报表-%'"
                )
                if rpt_tables:
                    for t in rpt_tables:
                        name = t.get('TABLE_NAME', '')
                        row_count = t.get('TABLE_ROWS', 0) or 0
                        # 去掉"报表-"前缀作为显示名
                        display_name = name[3:] if name.startswith('报表-') else name
                        # 查询字段列表
                        fields = []
                        try:
                            cols = self._db.execute(
                                "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT "
                                "FROM information_schema.COLUMNS "
                                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                                (name,)
                            )
                            if cols:
                                for c in cols:
                                    col_name = c['COLUMN_NAME']
                                    # 过滤系统字段和 ID 字段（不适合做维度/度量）
                                    if col_name in ('_id', '_hash', '_sync_time', '_row_id', 'id'):
                                        continue
                                    if col_name.endswith('_id') and col_name != '_id':
                                        continue
                                    fields.append({
                                        'key': col_name,
                                        'label': c.get('COLUMN_COMMENT', '') or col_name,
                                        'data_type': _mysql_type_to_generic(c.get('DATA_TYPE', 'text')),
                                    })
                        except Exception:
                            pass
                        result['reports'].append({
                            'id': name,           # 用表名作为 id
                            'name': display_name,
                            'row_count': row_count,
                            'fields': fields,
                            'table_name': name,
                        })
            except Exception:
                pass

        # Excel 数据集
        for ds in self.excel_dataset_repo.list_all():
            result['excel_datasets'].append({
                'id': ds.id,
                'name': ds.name,
                'row_count': ds.row_count,
                'columns': ds.columns,
                'table_name': ds.mysql_table,
            })

        # MySQL 表：仅显示用户通过"导入 MySQL"显式添加的表，
        # 不在初始加载时列出所有库表，避免展示未导入的表。
        # 导入后的表由 DashboardDesigner._refresh_data_sources() 管理。

        return result

    def get_data_source_fields(self, source_type: str, source_id: str) -> list[dict]:
        """获取数据源的字段列表"""
        sources = self.get_available_data_sources()
        key_map = {'report': 'reports', 'excel': 'excel_datasets', 'mysql': 'mysql_tables'}
        key = key_map.get(source_type, '')
        if not key:
            return []
        for src in sources.get(key, []):
            src_id = src.get('id') or src.get('name', '')
            if src_id == source_id:
                fields = src.get('fields') or src.get('columns', [])
                break
        else:
            # MySQL 表：按需查询列
            if source_type == 'mysql' and self._db and self._db.available:
                try:
                    cols = self._db.execute(
                        f"SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT "
                        f"FROM information_schema.COLUMNS "
                        f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                        (source_id,)
                    )
                    if cols:
                        fields = [{'key': c['COLUMN_NAME'], 'label': c.get('COLUMN_COMMENT', '') or c['COLUMN_NAME'], 'data_type': _mysql_type_to_generic(c.get('DATA_TYPE', 'text'))} for c in cols]
                except Exception:
                    fields = []
            else:
                fields = []
        return fields or []

    # ===== 图表数据查询 =====

    def query_chart_data(self, chart, global_filters: list = None) -> list[dict]:
        """查询单个图表的数据（筛选条件推入 SQL WHERE）"""
        if not self._db or not self._db.available:
            return []
        table_name = self._resolve_table(chart.data_source_type, chart.data_source_id)
        if not table_name:
            return []

        x_field = chart.x_field
        y_fields = chart.y_fields or []
        color_field = chart.color_field
        agg_funcs = chart.aggregate_funcs or {}

        # 构建 SELECT
        select_parts = [f"`{x_field}`"]
        if color_field:
            select_parts.append(f"`{color_field}`")
        for yf in y_fields:
            func = agg_funcs.get(yf, 'SUM')
            select_parts.append(f"{func}(`{yf}`) AS `{yf}`")

        # GROUP BY
        group_parts = [f"`{x_field}`"]
        if color_field:
            group_parts.append(f"`{color_field}`")

        # 构建 WHERE（筛选条件推到 SQL 层）
        filters = (getattr(chart, 'filters', None) or []) + (global_filters or [])
        where_clauses = []
        for f in filters:
            field = (f.get('field') or '').strip()
            op = (f.get('op') or '').strip()
            value = (f.get('value') or '').strip()
            if not field:
                continue
            safe_field = f"`{field}`"
            if op in ('为空', '不为空'):
                where_clauses.append(
                    f"({safe_field} IS NULL OR {safe_field} = '')" if op == '为空'
                    else f"({safe_field} IS NOT NULL AND {safe_field} != '')"
                )
            elif op == '属于' and value:
                vals = [v.strip() for v in value.split(',') if v.strip()]
                if vals:
                    quoted = ','.join(f"'{v}'" for v in vals)
                    where_clauses.append(f"{safe_field} IN ({quoted})")
            elif op == '不属于' and value:
                vals = [v.strip() for v in value.split(',') if v.strip()]
                if vals:
                    quoted = ','.join(f"'{v}'" for v in vals)
                    where_clauses.append(f"{safe_field} NOT IN ({quoted})")
            elif op == '包含' and value:
                where_clauses.append(f"{safe_field} LIKE '%{value}%'")
            elif op == '不包含' and value:
                where_clauses.append(f"{safe_field} NOT LIKE '%{value}%'")
            elif op in ('等于', '不等于', '大于', '小于', '大于等于', '小于等于') and value:
                op_map = {'等于': '=', '不等于': '!=', '大于': '>',
                          '小于': '<', '大于等于': '>=', '小于等于': '<='}
                sql_op = op_map.get(op, '=')
                try:
                    float(value)
                    where_clauses.append(f"{safe_field} {sql_op} {value}")
                except ValueError:
                    where_clauses.append(f"{safe_field} {sql_op} '{value}'")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # ORDER BY 第一个 Y 值列，按值降序
        order_col = len(select_parts)
        sql = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM `{table_name}` "
            f"{where_sql} "
            f"GROUP BY {', '.join(group_parts)} "
            f"ORDER BY {order_col} DESC "
            f"LIMIT 1000"
        )

        try:
            rows = self._db.execute(sql)
            logger.info(f"[BI 查询] chart={chart.id} type={chart.chart_type} src={chart.data_source_type}:{chart.data_source_id} → {len(rows) if rows else 0} 行")
            if not rows:
                logger.info(f"[BI 查询] SQL: {sql}")
            return rows if rows else []
        except Exception as e:
            logger.warning(f"[BI 查询] 失败: {e}\nSQL: {sql}")
            return []

    def query_all_chart_data(self, dashboard) -> dict[str, list]:
        """查询仪表盘所有图表的数据"""
        result = {}
        for chart in (dashboard.charts or []):
            result[chart.id] = self.query_chart_data(chart)
        return result

    def query_distinct_values(self, source_type: str, source_id: str,
                              field_name: str, limit: int = 500) -> list:
        """查询某字段的去重值列表（用于筛选多选选项）"""
        table_name = self._resolve_table(source_type, source_id)
        if not table_name or not field_name:
            return []
        try:
            sql = (
                f"SELECT DISTINCT `{field_name}` FROM `{table_name}` "
                f"WHERE `{field_name}` IS NOT NULL AND `{field_name}` != '' "
                f"ORDER BY `{field_name}` LIMIT {limit}"
            )
            rows = self._db.execute(sql) if self._db and self._db.available else []
            if rows:
                return sorted([str(list(r.values())[0]) for r in rows])
        except Exception:
            pass
        return []

    def _resolve_table(self, source_type: str, source_id: str) -> str:
        """根据数据源类型和 ID 解析 MySQL 表名"""
        if not source_id or not source_id.strip():
            return ''
        if source_type == 'report':
            rpt = self.get_report(source_id)
            if rpt and rpt.result_table_name:
                return rpt.result_table_name
            # "报表-"直连表：source_id 即为表名，验证表存在
            if self._db and self._db.table_exists(source_id):
                return source_id
            return ''
        elif source_type == 'excel':
            ds = self.excel_dataset_repo.get(source_id)
            return ds.mysql_table if ds else ''
        elif source_type == 'mysql':
            return source_id
        return ''

    # ===== Excel 导入 =====

    def import_excel_dataset(self, file_path: str) -> object:
        """导入 Excel/CSV 文件为数据集"""
        from .dashboard.excel_importer import ExcelImporter
        importer = ExcelImporter(self._db)
        dataset = importer.import_file(file_path)
        self.excel_dataset_repo.save(dataset)
        return dataset

    def delete_excel_dataset(self, dataset_id: str):
        """删除 Excel 数据集"""
        ds = self.excel_dataset_repo.get(dataset_id)
        if ds and ds.mysql_table and self._db:
            try:
                self._db.execute(f"DROP TABLE IF EXISTS `{ds.mysql_table}`")
            except Exception:
                pass
        self.excel_dataset_repo.delete(dataset_id)

    # ===== AI 助手 =====

    def get_ai_assistant(self):
        """获取 AI 助手实例"""
        from .dashboard.ai_assistant import AIAssistant
        providers_config = self._config.get('llm_providers', {})
        return AIAssistant(providers_config)

    # ==================== 清理 ====================

    def close(self):
        if self._db:
            self._db.close()
