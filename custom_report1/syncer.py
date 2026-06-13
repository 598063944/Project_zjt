"""
Source 表同步器

职责: 将 CRM API 数据同步到 MySQL source 表（sr_{api_name}）

流程:
1. DataFetcher 从 CRM API 拉取数据
2. 增量写入 MySQL source 表（upsert: 新ID插入，同ID比对hash有变更则更新，无变更跳过）
3. 不清空历史数据
"""

import logging
import time
from datetime import datetime
from typing import Optional, Callable

from .db_manager import ReportDatabase
from .fetcher import DataFetcher
from .models import ReportDefinition
from .address_extractor import AddressExtractor

logger = logging.getLogger(__name__)


class SourceTableSyncer:
    """CRM 对象 → MySQL source 表同步器"""

    def __init__(self, db: ReportDatabase, fetcher: DataFetcher = None):
        self._db = db
        self._fetcher = fetcher or DataFetcher()

    @property
    def available(self) -> bool:
        return self._db.available

    def _is_literal_table(self, api: str) -> bool:
        """判断是否为非 CRM 直连表（Excel导入 / 直连MySQL表）。

        判断逻辑：该名称不需要 CRM 翻译，直接在 MySQL 中作为表名存在。
        """
        if not api:
            return False
        if api.startswith('ex_'):
            return True
        # CRM API 名通常为驼峰式（如 NewOpportunityObj），不存在为直接 MySQL 表名
        # 如果 resolve_existing_table 返回的 sr_{api} 不存在，且 api 本身是表 → 直连表
        if self._db and hasattr(self._db, 'resolve_existing_table'):
            resolved = self._db.resolve_existing_table(api)
            if resolved.startswith('sr_') and not self._db.table_exists(resolved):
                return self._db.table_exists(api)
        return False

    def sync_all_for_report(self,
                            report: ReportDefinition,
                            progress_callback: Callable = None) -> dict:
        """
        同步报表涉及的所有对象的 source 表

        Args:
            report: 报表定义
            progress_callback: 进度回调 (step, message, percent)

        Returns:
            {api_name: {'rows': int, 'error': str|None, 'duration': float}}
        """
        apis = report.get_object_apis()
        if not apis:
            return {}

        # 拆分为 CRM API（需拉取）和直连表（已验证存在即可）
        crm_apis = [a for a in apis if not self._is_literal_table(a)]
        literal_tables = [a for a in apis if self._is_literal_table(a)]

        # 直连表：只需验证存在
        results = {}
        for table_name in literal_tables:
            if self._db.table_exists(table_name):
                row_count = self._db.table_row_count(table_name)
                results[table_name] = {'rows': row_count, 'error': None, 'duration': 0}
            else:
                results[table_name] = {'rows': 0,
                    'error': f'表 {table_name} 不存在', 'duration': 0}
            if progress_callback:
                progress_callback('sync', f"已就绪: {table_name} ({results[table_name]['rows']} 行)", 10)

        total = len(crm_apis)
        for i, api in enumerate(crm_apis):
            if progress_callback:
                progress_callback('sync', f"正在同步 {api} ({i+1}/{total})...",
                                  int((i / total) * 40))  # 0-40% 用于同步阶段

            # 子进度：对象内拉取进度
            def _fetch_progress(fetched, obj_total, _api=api, _i=i, _n=total):
                if progress_callback and obj_total:
                    pct = int(((_i + fetched / obj_total) / _n) * 40)
                    progress_callback('sync',
                        f"正在同步 {_api} ({_i+1}/{_n}): {fetched}/{obj_total} 条", pct)

            t0 = time.time()
            rows, total_count, err = self._fetcher.fetch_object(
                api, progress_callback=_fetch_progress)
            duration = time.time() - t0

            if err:
                results[api] = {'rows': 0, 'error': err, 'duration': duration}
                if progress_callback:
                    progress_callback('sync', f"{api} 同步失败: {err}",
                                      int(((i + 1) / total) * 40))
                continue

            if progress_callback:
                progress_callback('sync', f"正在写入 {api}: {len(rows)} 条...",
                                  int(((i + 0.5) / total) * 40))

            # 增量写入 MySQL source 表（不清空，按 _id 比对更新）
            if not self._db.ensure_source_table(api, sample_row=rows[0] if rows else None):
                results[api] = {'rows': 0, 'error': f'建表失败: {api}', 'duration': duration}
                if progress_callback:
                    progress_callback('sync', f"{api} 建表失败",
                                      int(((i + 1) / total) * 40))
                continue
            self._db.upsert_rows(api, rows)

            results[api] = {
                'rows': len(rows),
                'total': total_count,
                'error': None,
                'duration': duration,
            }

            if progress_callback:
                progress_callback('sync', f"已同步 {api}: {len(rows)} 条",
                                  int(((i + 1) / total) * 40))

        return results

    def sync_single(self, object_api: str,
                    max_records: int = 10000,
                    progress_callback: Callable = None) -> dict:
        """
        同步单个对象

        Returns:
            {'rows': int, 'error': str|None, 'duration': float}
        """
        t0 = time.time()
        rows, total, err = self._fetcher.fetch_object(object_api, max_records=max_records)
        duration = time.time() - t0

        if err:
            return {'rows': 0, 'error': err, 'duration': duration}

        self._db.ensure_source_table(object_api, sample_row=rows[0] if rows else None)
        self._db.upsert_rows(object_api, rows)

        return {'rows': len(rows), 'total': total, 'error': None, 'duration': duration}

    def check_source_status(self, report: ReportDefinition) -> dict:
        """
        检查报表所需的 source 表状态

        Returns:
            {api_name: {'exists': bool, 'row_count': int}}
        """
        status = {}
        for api in report.get_object_apis():
            table = ReportDatabase.source_table_name(api)
            exists = self._db.table_exists(table)
            count = self._db.get_source_count(api) if exists else 0
            status[api] = {'exists': exists, 'row_count': count}
        return status


def _wrap_phase2_progress(progress_callback):
    """将 refresh 内部的 0–100 进度映射到 full_refresh 的 45–90 区间。"""
    if not progress_callback:
        return None
    def _wrapped(phase, message, percent):
        mapped = 45 + int(percent * 0.45)
        progress_callback(phase, message, mapped)
    return _wrapped


class ReportRefreshWorker:
    """
    报表刷新流程编排器

    完整刷新流程:
    1. sync: 同步 source 表（CRM API → MySQL）
    2. join: 生成拼表 SQL 并执行（CREATE TABLE AS SELECT）
    3. done: 更新元数据
    """

    def __init__(self, db: ReportDatabase, syncer: SourceTableSyncer = None):
        self._db = db
        self._syncer = syncer or SourceTableSyncer(db)

    def full_refresh(self,
                     report: ReportDefinition,
                     progress_callback: Callable = None) -> dict:
        """
        完整刷新：从 CRM 拉取最新数据 → 写入 MySQL → 拼表生成结果表。

        Args:
            report: 报表定义
            progress_callback: (phase, message, percent) 三阶段进度

        Returns:
            {'success': bool, 'row_count': int, 'error': str, 'duration': float,
             'sync_results': dict}
        """
        t0 = time.time()
        apis = report.get_object_apis()
        if not apis:
            return {'success': False, 'row_count': 0,
                    'error': '报表未配置数据对象', 'duration': 0}

        # Phase 1: 同步 source 表（CRM → MySQL） 0%–40%
        if progress_callback:
            progress_callback('sync', f'开始同步 {len(apis)} 个对象...', 0)

        sync_results = self._syncer.sync_all_for_report(report, progress_callback)

        sync_errors = {k: v for k, v in sync_results.items() if v.get('error')}
        if sync_errors:
            err_msgs = [f"{k}: {v['error']}" for k, v in sync_errors.items()]
            return {'success': False, 'row_count': 0,
                    'error': 'CRM 同步失败:\n' + '\n'.join(err_msgs),
                    'duration': time.time() - t0, 'sync_results': sync_results}

        if progress_callback:
            progress_callback('join', '正在执行拼表...', 45)

        # Phase 2: 拼表生成结果表 45%–90%
        result = self.refresh(report, progress_callback=_wrap_phase2_progress(progress_callback))

        if not result['success']:
            result['sync_results'] = sync_results
            return result

        if progress_callback:
            progress_callback('done', result.get('message', '刷新完成'),
                              100)

        result['sync_results'] = sync_results
        return result

    def refresh(self,
                report: ReportDefinition,
                progress_callback: Callable = None) -> dict:
        """
        拼表生成结果表（直接使用已有 MySQL source 表，不从 CRM 拉取数据）。

        Args:
            report: 报表定义
            progress_callback: (phase, message, percent) 三阶段进度

        Returns:
            {'success': bool, 'row_count': int, 'error': str, 'duration': float}
        """
        from .sql_builder import JoinSQLBuilder

        t0 = time.time()

        # Phase 1: 检查已有表（不再从 CRM 同步）
        if progress_callback:
            progress_callback('sync', '检查已有数据表...', 5)

        apis = report.get_object_apis()
        if not apis:
            return {'success': False, 'row_count': 0,
                    'error': '报表未配置数据对象', 'duration': 0}

        # 检查各对象对应的 MySQL 表是否存在
        missing = []
        for api in apis:
            # 非 CRM 直连表：直接用 api 作为表名
            if self._syncer._is_literal_table(api):
                table = api
            else:
                table = self._db.resolve_existing_table(api)
            row_count = self._db.table_row_count(table) if self._db.table_exists(table) else 0
            logger.info(f"[ReportRefresh] 对象 '{api}' → 表 `{table}` | 存在={self._db.table_exists(table)} | 行数={row_count}")
            if not self._db.table_exists(table):
                missing.append(f"{api}（表 {table} 不存在）")
        if missing:
            return {'success': False, 'row_count': 0,
                    'error': f"以下数据表不存在，请先在对象查询中同步数据：\n" + '\n'.join(missing),
                    'duration': time.time() - t0}

        if progress_callback:
            progress_callback('join', '正在执行拼表...', 20)

        # Phase 2: 生成并执行拼表 SQL
        try:
            builder = JoinSQLBuilder(report, db=self._db)
            select_sql = builder.build_create_sql()
            self._db.create_result_table_as(report.id, select_sql,
                                            write_mode=report.write_mode)
        except Exception as e:
            logger.error(f"[ReportRefresh] 拼表失败: {e}")
            return {'success': False, 'row_count': 0, 'error': f"拼表 SQL 执行失败: {e}",
                    'duration': time.time() - t0}

        if progress_callback:
            progress_callback('join', '拼表完成，正在统计...', 80)

        # Phase 2.5: 地址提取后处理
        self._run_address_extraction(report, progress_callback)

        # Phase 2.6: 公式列后处理（对 SQL 无法翻译的公式列，通过 pandas 计算并写回 MySQL）
        self._run_formula_backfill(report, progress_callback)

        # Phase 3: 更新元数据
        row_count = self._db.get_result_count(report.id)
        report.result_row_count = row_count
        report.result_table_name = ReportDatabase.result_table_name(report.id)
        report.last_refresh_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 保存定义 JSON 到元数据表
        import json
        self._db.save_report_meta(
            report.id, report.name,
            json.dumps(report.to_dict(), ensure_ascii=False),
            row_count=row_count,
            refresh_time=report.last_refresh_time,
        )

        duration = time.time() - t0

        if progress_callback:
            progress_callback('done', f'刷新完成: {row_count} 条记录 ({duration:.1f}s)', 100)

        return {
            'success': True,
            'row_count': row_count,
            'error': None,
            'duration': duration,
        }

    def _run_address_extraction(self, report: ReportDefinition,
                                 progress_callback: Callable = None):
        """对结果表中地址提取列进行后处理填充。

        读取结果表 → 逐行匹配 ChinaCitys.json → UPDATE 写回。
        """
        addr_cols = []
        for col in report.columns:
            if isinstance(col, dict):
                if col.get('computation_type') == 'address_extract' and col.get('visible', True):
                    addr_cols.append(col)
            elif hasattr(col, 'computation_type'):
                if col.computation_type == 'address_extract' and col.visible:
                    addr_cols.append(col)

        logger.info(
            f"[AddressExtract] 共 {len(report.columns)} 列，"
            f"其中地址提取列 {len(addr_cols)} 个"
        )

        if not addr_cols:
            logger.info("[AddressExtract] 无地址提取列，跳过")
            return

        table = report.result_table
        logger.info(f"[AddressExtract] 结果表: {table}")

        if not self._db.table_exists(table):
            logger.warning(f"[AddressExtract] 结果表 `{table}` 不存在，跳过")
            return

        # 获取结果表实际列名（用于诊断）
        try:
            db_cols = set()
            cols_info = self._db.execute(f"SHOW COLUMNS FROM `{table}`")
            if cols_info:
                db_cols = {r['Field'] for r in cols_info}
            logger.info(f"[AddressExtract] 结果表列名({len(db_cols)}): {sorted(db_cols)[:20]}...")
        except Exception as e:
            logger.warning(f"[AddressExtract] 获取表列信息失败: {e}")
            db_cols = set()

        total = len(addr_cols)
        for i, col in enumerate(addr_cols):
            # Resolve fields (handles both dict and FieldColumn)
            if isinstance(col, dict):
                source_cols = col.get('address_source_fields', []) or []
                level = col.get('address_target_level', 'city') or 'city'
                display_name = col.get('display_name', '地址提取') or '地址提取'
            else:
                source_cols = getattr(col, 'address_source_fields', []) or []
                level = getattr(col, 'address_target_level', 'city') or 'city'
                display_name = col.display_name or '地址提取'

            logger.info(
                f"[AddressExtract] [{i+1}/{total}] 列='{display_name}' "
                f"level={level} source_cols={source_cols}"
            )

            if progress_callback:
                progress_callback(
                    'extract',
                    f"正在提取地址信息 ({display_name}) {i+1}/{total}...",
                    80 + int((i / total) * 15)
                )

            if not source_cols:
                logger.warning(f"[AddressExtract] '{display_name}' 未配置候选列，跳过")
                continue

            # 诊断：检查候选列是否在结果表中
            missing_cols = [c for c in source_cols if c not in db_cols]
            if missing_cols:
                logger.warning(
                    f"[AddressExtract] '{display_name}' 候选列在结果表中不存在: {missing_cols}"
                )
            if display_name not in db_cols:
                logger.warning(
                    f"[AddressExtract] 目标列 '{display_name}' 不在结果表中"
                )

            try:
                extractor = AddressExtractor()
                self._db.update_address_column(
                    table, display_name, source_cols, extractor, level
                )
            except Exception as e:
                logger.error(f"[AddressExtract] '{display_name}' 提取失败: {e}")
                import traceback
                traceback.print_exc()

    def _run_date_part_extraction(self, report: ReportDefinition,
                                   progress_callback: Callable = None):
        """对结果表中时间成分列进行后处理填充。

        读取结果表 → 逐行解析源日期字段 → 提取年/月/周/季度 → UPDATE 写回。
        """
        from datetime import datetime as dt

        dp_cols = []
        for col in report.columns:
            if isinstance(col, dict):
                if col.get('computation_type') == 'date_part' and col.get('visible', True):
                    dp_cols.append(col)
            elif hasattr(col, 'computation_type'):
                if col.computation_type == 'date_part' and col.visible:
                    dp_cols.append(col)

        if not dp_cols:
            return

        table = report.result_table
        if not self._db.table_exists(table):
            logger.warning(f"[DatePart] 结果表 `{table}` 不存在，跳过")
            return

        # 获取现有列，检查 _row_id
        try:
            cols_info = self._db.execute(f"SHOW COLUMNS FROM `{table}`")
            existing_cols = {r['Field'] for r in cols_info} if cols_info else set()
            has_row_id = '_row_id' in existing_cols
        except Exception as e:
            logger.warning(f"[DatePart] 获取列信息失败: {e}")
            return

        if not has_row_id:
            logger.warning("[DatePart] 结果表无 _row_id 列，无法逐行更新")
            return

        # 收集所有有效的时间成分别
        pending_cols = []
        for dc in dp_cols:
            display_name = dc.get('display_name', '') if isinstance(dc, dict) else dc.display_name
            src_field = dc.get('date_part_source_field', '') if isinstance(dc, dict) else getattr(dc, 'date_part_source_field', '')
            if display_name and src_field:
                pending_cols.append(dc)

        if not pending_cols:
            return

        logger.info(f"[DatePart] 发现 {len(pending_cols)} 个时间成分别，将逐行计算并写回")

        # 确保目标列存在（缺失则添加）
        for dc in pending_cols[:]:
            display_name = dc.get('display_name', '') if isinstance(dc, dict) else dc.display_name
            if display_name not in existing_cols:
                try:
                    self._db.execute(
                        f"ALTER TABLE `{table}` ADD COLUMN `{display_name}` VARCHAR(32) DEFAULT ''"
                    )
                    existing_cols.add(display_name)
                except Exception as e:
                    logger.warning(f"[DatePart] 添加列 `{display_name}` 失败: {e}")
                    pending_cols.remove(dc)

        if not pending_cols:
            return

        # 分批读取、计算并批量更新
        batch_size = 5000
        offset = 0
        total = 0

        while True:
            rows = self._db.execute(
                f"SELECT * FROM `{table}` LIMIT {batch_size} OFFSET {offset}"
            )
            if not rows:
                break

            for row in rows:
                row_id = row.get('_row_id')
                if row_id is None:
                    continue

                updates = {}
                for dc in pending_cols:
                    if isinstance(dc, dict):
                        src_field = dc.get('date_part_source_field', '')
                        unit = dc.get('date_part_unit', 'year') or 'year'
                        display_name = dc.get('display_name', '')
                    else:
                        src_field = getattr(dc, 'date_part_source_field', '')
                        unit = getattr(dc, 'date_part_unit', 'year') or 'year'
                        display_name = dc.display_name or ''

                    if not src_field or not display_name:
                        continue

                    raw_value = row.get(src_field, '')
                    date_val = self._parse_date_value(raw_value)
                    if date_val is None:
                        result_value = ''
                    elif unit == 'year':
                        result_value = str(date_val.year)
                    elif unit == 'month':
                        result_value = str(date_val.month)
                    elif unit == 'week':
                        result_value = str(date_val.isocalendar()[1])
                    elif unit == 'quarter':
                        result_value = str((date_val.month - 1) // 3 + 1)
                    else:
                        result_value = ''

                    updates[display_name] = result_value

                if updates:
                    set_clause = ', '.join(
                        f"`{col}` = %s" for col in updates.keys()
                    )
                    values = list(updates.values()) + [int(row_id)]
                    try:
                        self._db.execute(
                            f"UPDATE `{table}` SET {set_clause} WHERE `_row_id` = %s",
                            tuple(values)
                        )
                        total += 1
                    except Exception as e:
                        logger.warning(f"[DatePart] 更新行 {row_id} 失败: {e}")

            offset += batch_size

        logger.info(f"[DatePart] 完成: {total} 行已处理")

    @staticmethod
    def _parse_date_value(raw_value):
        """解析日期值 → datetime，失败返回 None。"""
        if raw_value is None:
            return None
        from datetime import datetime as dt
        if isinstance(raw_value, dt):
            return raw_value
        if isinstance(raw_value, (int, float)):
            try:
                ts = float(raw_value)
                if ts > 1e12:
                    return dt.fromtimestamp(ts / 1000)
                else:
                    return dt.fromtimestamp(ts)
            except (ValueError, OSError):
                pass
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
            if not raw_value:
                return None
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S',
                         '%Y/%m/%d %H:%M:%S', '%Y/%m/%d', '%Y年%m月%d日',
                         '%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M'):
                try:
                    return dt.strptime(raw_value, fmt)
                except ValueError:
                    continue
        return None

    def _run_formula_backfill(self, report: ReportDefinition,
                               progress_callback: Callable = None):
        """对结果表中未能翻译为 SQL 的公式列进行后处理填充。

        识别结果表中缺失的公式列 → pandas 计算 → 写回 MySQL。
        这确保所有公式列（包括 DATE、TEXT 等已支持翻译的函数兜底）
        都能正确写入 MySQL 结果表。
        """
        # 1. 收集所有公式列
        formula_cols = []
        for col in report.columns:
            if isinstance(col, dict):
                if col.get('computation_type') == 'formula' and col.get('visible', True):
                    formula_cols.append(col)
            elif hasattr(col, 'computation_type'):
                if col.computation_type == 'formula' and col.visible:
                    formula_cols.append(col)

        if not formula_cols:
            return

        table = report.result_table
        if not self._db.table_exists(table):
            return

        # 2. 获取结果表现有列
        try:
            cols_info = self._db.execute(f"SHOW COLUMNS FROM `{table}`")
            existing_cols = {r['Field'] for r in cols_info} if cols_info else set()
            has_row_id = '_row_id' in existing_cols
        except Exception as e:
            logger.warning(f"[FormulaBackfill] 获取列信息失败: {e}")
            return

        if not has_row_id:
            logger.warning("[FormulaBackfill] 结果表无 _row_id 列，无法逐行更新")
            return

        # 3. 找出缺失的公式列
        missing_formula_cols = []
        for fc in formula_cols:
            display_name = fc.get('display_name', '') if isinstance(fc, dict) else fc.display_name
            if display_name and display_name not in existing_cols:
                missing_formula_cols.append(fc)

        if not missing_formula_cols:
            return

        logger.info(
            f"[FormulaBackfill] 发现 {len(missing_formula_cols)} 个缺失的公式列，"
            f"将通过 pandas 计算并写回 MySQL"
        )

        # 4. 先为缺失列执行 ALTER TABLE ADD COLUMN
        for fc in missing_formula_cols:
            display_name = fc.get('display_name', '') if isinstance(fc, dict) else fc.display_name
            try:
                self._db.execute(
                    f"ALTER TABLE `{table}` ADD COLUMN `{display_name}` LONGTEXT"
                )
                logger.info(f"[FormulaBackfill] 已添加列 `{display_name}`")
            except Exception as e:
                logger.warning(f"[FormulaBackfill] 添加列 `{display_name}` 失败: {e}")
                # 移除添加失败的列
                missing_formula_cols.remove(fc)

        if not missing_formula_cols:
            return

        # 5. 分批读取数据、计算并写回
        batch_size = 5000
        offset = 0
        total_updated = 0

        import pandas as pd
        from .formula_engine import eval_formula_columns

        while True:
            rows = self._db.execute(
                f"SELECT * FROM `{table}` LIMIT {batch_size} OFFSET {offset}"
            )
            if not rows:
                break

            df = pd.DataFrame(rows)
            if df.empty:
                break

            # 计算所有缺失的公式列（只针对缺失列）
            try:
                df = eval_formula_columns(df, missing_formula_cols)
            except Exception as e:
                logger.warning(f"[FormulaBackfill] 公式计算失败 (offset={offset}): {e}")
                offset += len(rows)
                continue

            # 批量 UPDATE
            conn = self._db._get_conn() if hasattr(self._db, '_get_conn') else None
            for fc in missing_formula_cols:
                display_name = fc.get('display_name', '') if isinstance(fc, dict) else fc.display_name
                if display_name not in df.columns:
                    continue

                updates = []
                for _, row_data in df.iterrows():
                    row_id = row_data.get('_row_id')
                    if row_id is None:
                        continue
                    val = row_data.get(display_name)
                    if val is None or (isinstance(val, float) and pd.isna(val)):
                        val_str = None
                    else:
                        val_str = str(val)
                    updates.append((val_str, int(row_id)))

                if updates and conn:
                    try:
                        with conn.cursor() as cur:
                            cur.executemany(
                                f"UPDATE `{table}` SET `{display_name}` = %s "
                                f"WHERE `_row_id` = %s",
                                updates,
                            )
                        total_updated += len(updates)
                    except Exception as e:
                        logger.warning(
                            f"[FormulaBackfill] 更新列 `{display_name}` 失败: {e}"
                        )

            offset += len(rows)

        logger.info(
            f"[FormulaBackfill] 完成: {len(missing_formula_cols)} 个公式列, "
            f"共更新 {total_updated} 行"
        )

    def _build_composite_id_column(self, report: ReportDefinition,
                                   progress_callback=None):
        """如果配置了 sync_id_fields，在结果表中追加拼接 ID 列供预览。"""
        id_fields = getattr(report, 'sync_id_fields', None) or []
        import sys
        print(f"[CompositeID] sync_id_fields={id_fields}", file=sys.stderr, flush=True)
        if not id_fields:
            print("[CompositeID] 跳过：未配置 ID 字段", file=sys.stderr, flush=True)
            return
        separator = getattr(report, 'sync_id_separator', '_') or '_'
        table = report.result_table
        print(f"[CompositeID] 结果表={table}, 分隔符='{separator}'", file=sys.stderr, flush=True)
        if not self._db.table_exists(table):
            print(f"[CompositeID] 跳过：表 {table} 不存在", file=sys.stderr, flush=True)
            return

        col_name = "唯一ID"

        # 获取结果表实际列名
        try:
            db_cols = set()
            cols_info = self._db.execute(f"SHOW COLUMNS FROM `{table}`")
            if cols_info:
                db_cols = {r['Field'] for r in cols_info}
        except Exception as e:
            print(f"[CompositeID] 获取列信息失败: {e}", file=sys.stderr, flush=True)
            return

        print(f"[CompositeID] 结果表列名({len(db_cols)}): {sorted(db_cols)}", file=sys.stderr, flush=True)

        # 验证 ID 字段在结果表中存在
        valid_fields = [f for f in id_fields if f in db_cols]
        if not valid_fields:
            missing = [f for f in id_fields if f not in db_cols]
            print(f"[CompositeID] 跳过：以下字段不在结果表中: {missing}", file=sys.stderr, flush=True)
            logger.warning(f"[CompositeID] ID 字段在结果表中不存在: {id_fields}, db_cols={sorted(db_cols)[:10]}...")
            return

        if progress_callback:
            progress_callback('composite_id', f"正在生成拼接 ID 列...", 87)

        try:
            # 添加列（如不存在）
            if col_name not in db_cols:
                self._db.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col_name}` LONGTEXT")
                print(f"[CompositeID] 已添加列 `{col_name}`", file=sys.stderr, flush=True)

            # 用 CONCAT_WS 生成拼接值
            concat_parts = ', '.join(f'`{f}`' for f in valid_fields)
            sql = f"UPDATE `{table}` SET `{col_name}` = CONCAT_WS('{separator}', {concat_parts})"
            print(f"[CompositeID] 执行: {sql[:200]}", file=sys.stderr, flush=True)
            self._db.execute(sql)
            print(f"[CompositeID] ✅ 已生成 '{col_name}' 列: {len(valid_fields)} 字段", file=sys.stderr, flush=True)
            logger.info(f"[CompositeID] 已生成 '{col_name}' 列: {len(valid_fields)} 字段, 分隔符='{separator}'")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[CompositeID] ❌ 生成失败: {e}", file=sys.stderr, flush=True)
            logger.error(f"[CompositeID] 生成失败: {e}")
