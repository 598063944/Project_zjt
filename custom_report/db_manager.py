"""
数据库管理器

职责:
- MySQL 连接池管理
- Source 表（sr_{api_name}）的创建、写入、查询
- Result 表（cr_{report_id}）的创建、重建、查询
- 元数据表（cr_meta_reports）的管理

与已有的 MysqlCache 类的关系:
- MysqlCache 使用 crm_cache_{api_name} 格式，存 JSON blob
- 本模块管理 sr_{api_name} 格式（列式存储），专用于拼表 SQL
- 两者共用同一个 MySQL 连接配置
"""

import pymysql
import pymysql.cursors
from pymysql.converters import escape_string
from typing import Optional
import logging
import json

from custom_report.constants import get_mysql_type_for_field, is_numeric_field_type, safe_numeric_value, get_mysql_type_for_format, safe_value_by_format

logger = logging.getLogger(__name__)


class ReportDatabase:
    """报表专用数据库管理器"""

    def __init__(self, mysql_config: dict):
        """
        Args:
            mysql_config: config.json → mysql_config 节点
                {host, port, user, password, database, enabled}
        """
        self._cfg = mysql_config
        self._conn = None

    # ---------- 连接管理 ----------

    @property
    def available(self) -> bool:
        return self._get_conn() is not None

    @property
    def status_message(self) -> str:
        if self._conn and self._conn.open:
            db = self._cfg.get('database', '')
            return f"✅ 报表数据库已连接 ({db})"
        if not self._cfg.get('enabled'):
            return "⚠️ MySQL 未启用"
        return "❌ MySQL 连接失败"

    def _get_conn(self):
        """获取或创建连接"""
        if self._conn and self._conn.open:
            return self._conn
        cfg = self._cfg
        if not cfg.get('enabled'):
            return None
        try:
            self._conn = pymysql.connect(
                host=cfg.get('host', '127.0.0.1'),
                port=int(cfg.get('port', 3306)),
                user=cfg.get('user', ''),
                password=cfg.get('password', ''),
                database=cfg.get('database', ''),
                charset='utf8mb4',
                connect_timeout=5,
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True,
            )
            return self._conn
        except Exception as e:
            logger.error(f"[ReportDatabase] 连接失败: {e}")
            return None

    def close(self):
        if self._conn and self._conn.open:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def reconnect(self, new_config: dict = None):
        """更换数据库配置并立即重连

        Args:
            new_config: 新的 mysql_config 字典，为 None 则从当前 config 重连
        """
        self.close()
        if new_config is not None:
            self._cfg = new_config
        self._conn = None
        if self._cfg.get('enabled'):
            self._get_conn()

    def execute(self, sql: str, params=None) -> Optional[list[dict]]:
        """执行 SQL，返回结果行（如果是查询）"""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description:
                    return cur.fetchall()
            return []
        except Exception as e:
            logger.error(f"[ReportDatabase] SQL 执行失败: {e}\nSQL: {sql[:200]}")
            raise

    def execute_many_insert(self, table_name: str, columns: list[dict],
                            rows: list[dict]):
        """批量插入数据（使用 executemany 优化）。

        Args:
            table_name: 目标表名
            columns: 列定义列表 [{'key': 'col_name', ...}, ...]
            rows: 数据行列表 [{col_name: value, ...}, ...]
        """
        if not rows or not columns:
            return
        conn = self._get_conn()
        if not conn:
            return
        col_names = [c['key'].replace('`', '``') for c in columns]
        placeholders = ', '.join(['%s'] * len(col_names))
        sql = (
            f"INSERT INTO `{table_name}` "
            f"(`{'`, `'.join(col_names)}`) "
            f"VALUES ({placeholders})"
        )
        values = []
        for row in rows:
            row_vals = [row.get(c['key']) for c in columns]
            values.append(row_vals)
        try:
            with conn.cursor() as cur:
                cur.executemany(sql, values)
        except Exception as e:
            logger.error(f"[ReportDatabase] 批量插入失败: {e}")
            raise

    # ---------- Source 表管理 ----------

    @staticmethod
    def source_table_name(object_api: str) -> str:
        """Source 表命名: sr_{api_name}"""
        return f"sr_{object_api}"

    def resolve_existing_table(self, object_api: str) -> str:
        """解析对象对应的已有 MySQL 表名。

        优先查找对象查询同步的「对象-{name}」表，
        其次查找 sr_{api_name} 表，最后返回 sr_{api_name}。
        """
        # 尝试从 fxiaoke.crm_objects 配置中获取 display_name 构建表名
        try:
            import sys
            main = sys.modules.get('__main__')
            if main and hasattr(main, 'load_config'):
                cfg = main.load_config()
                crm_objs = cfg.get('fxiaoke', {}).get('crm_objects', [])
                for obj in crm_objs:
                    if isinstance(obj, dict) and obj.get('api_name') == object_api:
                        name = obj.get('name', '')
                        if name:
                            table_name = f'对象-{name}'
                            if self.table_exists(table_name):
                                return table_name
                        break  # 找到匹配的对象后无需继续遍历
        except Exception:
            pass
        # 回退：sr_{api_name}
        return f"sr_{object_api}"

    def ensure_source_table(self, object_api: str, sample_row: dict = None, force_recreate: bool = False) -> bool:
        """
        确保 source 表存在。
        默认增量模式（保留已有列）；force_recreate=True 时先删表再重建。

        Source 表结构:
          _id VARCHAR(128) PRIMARY KEY   — CRM 数据 ID
          _sync_time DATETIME            — 同步时间
          _hash VARCHAR(32)              — 行数据哈希（用于增量变更检测）
          {field_name} LONGTEXT          — CRM 字段（动态列，DYNAMIC 格式存到行外）
        """
        table = self.source_table_name(object_api)
        conn = self._get_conn()
        if not conn:
            return False
        try:
            with conn.cursor() as cur:
                if force_recreate:
                    cur.execute(f"DROP TABLE IF EXISTS `{table}`")
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS `{table}` (
                        `_id` VARCHAR(128) PRIMARY KEY COMMENT 'CRM数据ID',
                        `_sync_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '同步时间',
                        `_hash` VARCHAR(32) DEFAULT '' COMMENT '行数据哈希'
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC
                """)
                cur.execute(f"ALTER TABLE `{table}` ROW_FORMAT=DYNAMIC")

                if sample_row:
                    existing_cols = self._get_columns(table)
                    for key in sample_row.keys():
                        if key in ('_id', '_sync_time', '_hash'):
                            continue
                        safe_key = key
                        if safe_key not in existing_cols:
                            cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{safe_key}` LONGTEXT")
            return True
        except Exception as e:
            logger.error(f"[ReportDatabase] 建 source 表失败 {table}: {e}")
            # 兜底：删表重建后再试一次
            if not force_recreate:
                logger.info(f"[ReportDatabase] 尝试删表重建 {table}...")
                return self.ensure_source_table(object_api, sample_row, force_recreate=True)
            return False

    def truncate_source(self, object_api: str):
        """清空 source 表（已弃用，保留兼容）"""
        table = self.source_table_name(object_api)
        self.execute(f"TRUNCATE TABLE `{table}`")

    def insert_rows(self, object_api: str, rows: list[dict]):
        """批量写入 source 表（已弃用，请用 upsert_rows）"""
        self.upsert_rows(object_api, rows)

    def upsert_rows(self, object_api: str, rows: list[dict], field_type_map: dict = None):
        """增量写入 source 表：新 ID 插入，已有 ID 检查变更后更新，无变更跳过。

        使用 INSERT ... ON DUPLICATE KEY UPDATE + _hash 字段对比变更。
        不会清空旧数据。

        Args:
            object_api: CRM 对象 API 名
            rows: 数据行列表
            field_type_map: {字段名: CRM类型}，数值字段用 DOUBLE 列 + 保留数值
        """
        if not rows:
            return
        table = self.source_table_name(object_api)
        conn = self._get_conn()
        if not conn:
            return
        import hashlib
        type_map = field_type_map or {}

        # 收集所有列名
        all_keys = set()
        for row in rows:
            all_keys.update(k for k in row.keys() if k not in ('_id', '_sync_time', '_hash'))
        all_keys = sorted(all_keys)

        if not all_keys:
            return

        # 确保列存在（数值字段用 DOUBLE，其余 LONGTEXT；已有 LONGTEXT 数值列自动迁移）
        existing = self._get_columns(table)
        with conn.cursor() as cur:
            for key in all_keys:
                ftype = type_map.get(key, '')
                expected_type = get_mysql_type_for_field(ftype)
                if key not in existing:
                    try:
                        cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{key}` {expected_type}")
                        existing.add(key)
                    except Exception:
                        pass
                elif expected_type == 'DOUBLE' and key in existing:
                    # 已有列可能是 LONGTEXT → 查实际类型并尝试迁移为 DOUBLE
                    try:
                        cur.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (key,))
                        col_rows = cur.fetchall()
                        if col_rows:
                            col_type = str(col_rows[0].get('Type', '')).lower()
                            if not any(t in col_type for t in ('double', 'int', 'float', 'decimal')):
                                cur.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{key}` DOUBLE")
                    except Exception:
                        pass

        # 检测 _hash 是否可用（可能因行大小限制无法添加）
        hash_available = '_hash' in existing
        if not hash_available:
            with conn.cursor() as cur:
                try:
                    cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `_hash` VARCHAR(32) DEFAULT ''")
                    existing.add('_hash')
                    hash_available = True
                except Exception:
                    pass

        if hash_available:
            # 使用 hash 比较的增量 upsert：仅变更时更新
            cols = ['_id', '_hash', '_sync_time'] + all_keys
            placeholders = ', '.join(['%s'] * len(cols))
            insert_sql = (
                f"INSERT INTO `{table}` (`{'`, `'.join(cols)}`) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE "
            )
            update_parts = []
            for key in all_keys:
                update_parts.append(f"`{key}` = IF(VALUES(`_hash`) != `_hash`, VALUES(`{key}`), `{key}`)")
            update_parts.append("`_hash` = IF(VALUES(`_hash`) != `_hash`, VALUES(`_hash`), `_hash`)")
            update_parts.append("`_sync_time` = IF(VALUES(`_hash`) != `_hash`, NOW(), `_sync_time`)")
            insert_sql += ', '.join(update_parts)

            batch = []
            seen_ids = set()  # 防止同批次 _id 重复导致 1062 主键冲突
            for row in rows:
                _id = str(row.get('_id', '')).strip()
                if not _id:
                    continue
                if _id in seen_ids:
                    continue
                seen_ids.add(_id)
                row_vals = {}
                for k in all_keys:
                    ftype = type_map.get(k, '')
                    if is_numeric_field_type(ftype):
                        v = row.get(k)
                        row_vals[k] = float(v) if v not in (None, '') else None
                    else:
                        row_vals[k] = str(row.get(k, '') or '')
                row_hash = hashlib.md5(
                    json.dumps(row_vals, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')
                ).hexdigest()
                vals = [_id, row_hash, None]
                for key in all_keys:
                    ftype = type_map.get(key, '')
                    val = safe_numeric_value(row.get(key, ''), ftype)
                    vals.append(val)
                batch.append(vals)

                if len(batch) >= 500:
                    with conn.cursor() as cur:
                        cur.executemany(insert_sql, batch)
                    batch.clear()

            if batch:
                with conn.cursor() as cur:
                    cur.executemany(insert_sql, batch)
        else:
            # 回退：使用 REPLACE INTO（无增量检测，直接覆盖）
            logger.warning(f"[ReportDatabase] _hash 列不可用，使用 REPLACE INTO 回退: {table}")
            cols = ['_id', '_sync_time'] + all_keys
            placeholders = ', '.join(['%s'] * len(cols))
            replace_sql = f"REPLACE INTO `{table}` (`{'`, `'.join(cols)}`) VALUES ({placeholders})"

            batch = []
            for row in rows:
                _id = str(row.get('_id', '')).strip()
                if not _id:
                    continue
                vals = [_id, None]
                for key in all_keys:
                    ftype = type_map.get(key, '')
                    val = safe_numeric_value(row.get(key, ''), ftype)
                    vals.append(val)
                batch.append(vals)

                if len(batch) >= 500:
                    with conn.cursor() as cur:
                        cur.executemany(replace_sql, batch)
                    batch.clear()

            if batch:
                with conn.cursor() as cur:
                    cur.executemany(replace_sql, batch)

    def get_source_count(self, object_api: str) -> int:
        """获取 source 表行数"""
        table = self.source_table_name(object_api)
        result = self.execute(f"SELECT COUNT(*) AS cnt FROM `{table}`")
        if result:
            return result[0].get('cnt', 0)
        return 0

    def row_exists(self, object_api: str, row_id: str) -> bool:
        """检查某行是否已存在"""
        table = self.source_table_name(object_api)
        result = self.execute(f"SELECT 1 FROM `{table}` WHERE `_id` = %s", (row_id,))
        return bool(result)

    # ---------- Result 表管理 ----------

    @staticmethod
    def result_table_name(report_id: str) -> str:
        """Result 表命名: cr_{report_id}"""
        return f"cr_{report_id}"

    def drop_result_table(self, report_id: str):
        """删除结果表"""
        table = self.result_table_name(report_id)
        self.execute(f"DROP TABLE IF EXISTS `{table}`")

    def create_result_table_as(self, report_id: str, select_sql: str,
                               write_mode: str = "overwrite"):
        """
        执行 CREATE TABLE ... AS SELECT

        Args:
            report_id: 报表 ID
            select_sql: 完整的 SELECT 语句（不含 CREATE TABLE 前缀）
            write_mode: "overwrite" (覆盖: DROP+CREATE) | "incremental" (增量: UPSERT)
        """
        table = self.result_table_name(report_id)

        if write_mode == "incremental" and self.table_exists(table):
            try:
                self._upsert_result_table(report_id, select_sql)
                return
            except Exception as e:
                logger.warning(
                    f"[ReportDatabase] 增量写入失败，回退为覆盖模式: {e}"
                )

        # 覆盖模式（默认）
        self.drop_result_table(report_id)
        sql = f"CREATE TABLE `{table}` AS {select_sql}"
        try:
            self.execute(sql)
        except Exception as e:
            logger.error(f"[ReportDatabase] 创建结果表失败: {e}\nSQL:\n{sql[:800]}")
            raise
        self._add_row_id(table)

    def _add_row_id(self, table: str):
        """给结果表添加自增主键 _row_id 和 _hash 列。"""
        try:
            self.execute(f"ALTER TABLE `{table}` ADD COLUMN `_row_id` INT AUTO_INCREMENT PRIMARY KEY FIRST")
        except Exception:
            pass
        self._ensure_result_hash_column(table)

    def _ensure_result_hash_column(self, table: str):
        """确保结果表有 _hash 列并计算初始哈希值。"""
        existing = self._get_columns(table)
        if '_hash' not in existing:
            try:
                self.execute(f"ALTER TABLE `{table}` ADD COLUMN `_hash` VARCHAR(32) DEFAULT ''")
            except Exception:
                return
        # 为已有行计算 hash（仅覆盖模式下首次创建时需要）
        data_cols = [c for c in self._get_columns(table) if c not in ('_row_id', '_hash')]
        if data_cols:
            concat = ", '|', ".join(f'IFNULL(`{c}`, \'\')' for c in data_cols)
            try:
                self.execute(
                    f"UPDATE `{table}` SET `_hash` = MD5(CONCAT({concat})) "
                    f"WHERE `_hash` = '' OR `_hash` IS NULL"
                )
            except Exception:
                pass

    def _add_hash_to_temp_table(self, tmp_table: str):
        """给临时表添加 _hash 列并计算每行的哈希值。"""
        data_cols = [c for c in self._get_columns(tmp_table) if c not in ('_row_id', '_hash')]
        if not data_cols:
            return
        try:
            self.execute(f"ALTER TABLE `{tmp_table}` ADD COLUMN `_hash` VARCHAR(32) DEFAULT ''")
        except Exception:
            return
        concat = ", '|', ".join(f'IFNULL(`{c}`, \'\')' for c in data_cols)
        self.execute(f"UPDATE `{tmp_table}` SET `_hash` = MD5(CONCAT({concat}))")

    def _upsert_result_table(self, report_id: str, select_sql: str):
        """增量模式：将 SELECT 结果 UPSERT 到已有结果表（基于 _hash 变更检测）。

        流程:
        1. 创建临时表存放本次 SELECT 结果
        2. 给临时表加 _hash 列并计算 MD5
        3. 比对列，给主表补全新列（含 _hash）
        4. 确保 _id 有唯一索引
        5. INSERT ... ON DUPLICATE KEY UPDATE（hash 不变跳过写入）
        6. DROP 临时表
        """
        table = self.result_table_name(report_id)
        tmp_table = f"{table}_incr"

        # 创建临时表
        self.execute(f"DROP TABLE IF EXISTS `{tmp_table}`")
        self.execute(f"CREATE TABLE `{tmp_table}` AS {select_sql}")
        self._add_row_id(tmp_table)
        self._add_hash_to_temp_table(tmp_table)

        tmp_cols = [c for c in self._get_columns(tmp_table) if c != '_row_id']
        existing_cols = self._get_columns(table)

        # 若 SELECT 结果无 _id（聚合查询），回退覆盖
        if '_id' not in tmp_cols:
            self.execute(f"DROP TABLE IF EXISTS `{tmp_table}`")
            raise RuntimeError("增量模式不支持无 _id 列的聚合查询，回退覆盖")

        # 补全新列
        for col in tmp_cols:
            if col not in existing_cols:
                try:
                    self.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col}` LONGTEXT")
                except Exception:
                    pass

        # 确保 _id 有唯一索引
        try:
            self.execute(
                f"ALTER TABLE `{table}` ADD UNIQUE INDEX `idx_id` (`_id`)"
            )
        except Exception:
            pass

        # INSERT ... ON DUPLICATE KEY UPDATE（hash 感知）
        cols_list = ', '.join(f'`{c}`' for c in tmp_cols)
        update_parts = []
        for c in tmp_cols:
            if c in ('_id', '_hash'):
                continue
            update_parts.append(
                f"`{c}` = IF(VALUES(`_hash`) != `_hash`, VALUES(`{c}`), `{c}`)"
            )
        update_parts.append(
            "`_hash` = IF(VALUES(`_hash`) != `_hash`, VALUES(`_hash`), `_hash`)"
        )
        update_clause = ', '.join(update_parts)

        upsert_sql = (
            f"INSERT INTO `{table}` ({cols_list}) "
            f"SELECT {cols_list} FROM `{tmp_table}` "
            f"ON DUPLICATE KEY UPDATE {update_clause}"
        )
        self.execute(upsert_sql)

        # 清理临时表
        self.execute(f"DROP TABLE IF EXISTS `{tmp_table}`")

        logger.info(
            f"[ReportDatabase] 增量写入完成: {table} "
            f"(临时表列: {len(tmp_cols)}, 已有列: {len(existing_cols)})"
        )

    def query_result(self, report_id: str,
                     page: int = 1,
                     page_size: int = 50,
                     search: str = None,
                     search_columns: list[str] = None,
                     order_by: str = None,
                     filters: list[dict] = None) -> tuple[list[dict], int]:
        """
        分页查询结果表

        Args:
            filters: 筛选条件列表 [{field: 列名, operator: EQ|CONTAINS|..., value: ...}]

        Returns:
            (rows, total_count)
        """
        table = self.result_table_name(report_id)
        conn = self._get_conn()
        if not conn:
            return [], 0

        # 检查结果表是否存在（不存在时静默返回空，避免错误日志）
        if not self.result_table_exists(report_id):
            return [], 0

        # 获取列名（跳过内部列 _row_id / _id / _hash）
        cols = self._get_columns(table)
        display_cols = [c for c in cols if c not in ('_row_id', '_id', '_hash')]

        # 构建 WHERE 子句
        where_clause = ""
        params = []
        where_parts = []

        # 文本搜索
        if search and display_cols:
            conditions = [f"`{c}` LIKE %s" for c in (search_columns or display_cols)]
            where_parts.append("(" + " OR ".join(conditions) + ")")
            params.extend([f"%{search}%" for _ in conditions])

        # 筛选条件
        if filters:
            for fc in filters:
                cond_sql, cond_params = self._build_filter_sql(fc)
                if cond_sql:
                    where_parts.append(cond_sql)
                    params.extend(cond_params)

        if where_parts:
            where_clause = "WHERE " + " AND ".join(where_parts)

        count_sql = f"SELECT COUNT(*) AS cnt FROM `{table}` {where_clause}"
        import sys
        print(f"[FilterDebug] filters={filters}", file=sys.stderr, flush=True)
        print(f"[FilterDebug] count_sql={count_sql}", file=sys.stderr, flush=True)
        print(f"[FilterDebug] params={params}", file=sys.stderr, flush=True)
        with conn.cursor() as cur:
            cur.execute(count_sql, params)
            total = cur.fetchone().get('cnt', 0)

        # 分页数据
        if not display_cols:
            return [], total

        offset = (page - 1) * page_size
        cols_str = ', '.join(f'`{c}`' for c in display_cols)
        data_sql = f"SELECT {cols_str} FROM `{table}` {where_clause} LIMIT %s OFFSET %s"
        with conn.cursor() as cur:
            cur.execute(data_sql, params + [page_size, offset])
            rows = cur.fetchall()

        return rows, total

    @staticmethod
    def _build_filter_sql(fc: dict) -> tuple[str, list]:
        """将单个筛选条件转为 SQL WHERE 片段

        Returns:
            (sql_fragment, params_list)
        """
        field = fc.get('field_label', fc.get('field', ''))
        if not field:
            return ("", [])
        # 防御：去掉可能带有的 [对象名] 前缀
        if field.startswith('[') and ']' in field:
            end = field.index(']')
            field = field[end + 1:].strip()
        col = f"`{field}`"
        operator = str(fc.get('operator', 'CONTAINS')).upper()
        value = str(fc.get('value', ''))

        # 文字操作符
        if operator == 'EQ':
            return (f"{col} = %s", [value])
        if operator == 'NEQ':
            return (f"{col} != %s", [value])
        if operator == 'CONTAINS':
            return (f"{col} LIKE %s", [f"%{value}%"])
        if operator == 'NOT_CONTAINS':
            return (f"{col} NOT LIKE %s", [f"%{value}%"])
        if operator == 'STARTS_WITH':
            return (f"{col} LIKE %s", [f"{value}%"])
        if operator == 'ENDS_WITH':
            return (f"{col} LIKE %s", [f"%{value}"])
        if operator == 'IN':
            # 支持逗号、中文分号、英文分号分隔
            raw = value.replace('；', ',').replace(';', ',')
            vals = [v.strip() for v in raw.split(',') if v.strip()]
            if not vals:
                return ("", [])
            placeholders = ', '.join(['%s'] * len(vals))
            return (f"{col} IN ({placeholders})", vals)
        if operator == 'NOT_IN':
            raw = value.replace('；', ',').replace(';', ',')
            vals = [v.strip() for v in raw.split(',') if v.strip()]
            if not vals:
                return ("", [])
            placeholders = ', '.join(['%s'] * len(vals))
            return (f"{col} NOT IN ({placeholders})", vals)
        if operator in ('GT', 'GTE', 'LT', 'LTE'):
            op_map = {'GT': '>', 'GTE': '>=', 'LT': '<', 'LTE': '<='}
            return (f"{col} {op_map[operator]} %s", [value])
        if operator in ('EMPTY', 'IS_NULL'):
            return (f"({col} IS NULL OR {col} = '')", [])
        if operator in ('NOT_EMPTY', 'IS_NOT_NULL'):
            return (f"({col} IS NOT NULL AND {col} != '')", [])
        # 日期操作符（结果表中日期通常为字符串格式 yyyy-MM-dd）
        if operator == 'DATE_BEFORE':
            return (f"{col} < %s", [value])
        if operator == 'DATE_AFTER':
            return (f"{col} > %s", [value])
        if operator == 'DATE_BEFORE_EQ':
            return (f"{col} <= %s", [value])
        if operator == 'DATE_AFTER_EQ':
            return (f"{col} >= %s", [value])
        if operator == 'DATE_RANGE':
            parts = value.split('~')
            if len(parts) == 2:
                return (f"({col} >= %s AND {col} <= %s)", [parts[0].strip(), parts[1].strip()])
            return ("", [])
        # 相对日期操作符 — 计算边界后比对
        if operator in ('PAST_N_DAYS_INCLUSIVE', 'PAST_N_DAYS_EXCLUSIVE',
                         'FUTURE_N_DAYS_INCLUSIVE', 'FUTURE_N_DAYS_EXCLUSIVE',
                         'N_DAYS_AGO', 'N_DAYS_LATER'):
            from datetime import datetime, timedelta
            try:
                n = int(value)
            except (ValueError, TypeError):
                return ("", [])
            today = datetime.now()
            if operator == 'PAST_N_DAYS_INCLUSIVE':
                start = today - timedelta(days=n)
                return (f"{col} >= %s", [start.strftime('%Y-%m-%d')])
            if operator == 'PAST_N_DAYS_EXCLUSIVE':
                start = today - timedelta(days=n)
                return (f"({col} >= %s AND {col} < %s)",
                        [start.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')])
            if operator == 'FUTURE_N_DAYS_INCLUSIVE':
                end = today + timedelta(days=n)
                return (f"({col} >= %s AND {col} <= %s)",
                        [today.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')])
            if operator == 'FUTURE_N_DAYS_EXCLUSIVE':
                end = today + timedelta(days=n)
                return (f"({col} > %s AND {col} <= %s)",
                        [today.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')])
            if operator == 'N_DAYS_AGO':
                target = today - timedelta(days=n)
                return (f"{col} <= %s", [target.strftime('%Y-%m-%d')])
            if operator == 'N_DAYS_LATER':
                target = today + timedelta(days=n)
                return (f"{col} >= %s", [target.strftime('%Y-%m-%d')])
        # 未识别操作符 → 回退为 CONTAINS
        return (f"{col} LIKE %s", [f"%{value}%"])

    def get_result_count(self, report_id: str) -> int:
        """获取结果表行数"""
        table = self.result_table_name(report_id)
        result = self.execute(f"SELECT COUNT(*) AS cnt FROM `{table}`")
        if result:
            return result[0].get('cnt', 0)
        return 0

    def update_address_column(self, table: str, display_name: str,
                              source_cols: list, extractor, level: str):
        """
        对结果表中的地址提取列进行逐行填充。

        Args:
            table: 结果表名
            display_name: 地址提取列的显示名（即 MySQL 列名）
            source_cols: 候选列显示名列表
            extractor: AddressExtractor 实例
            level: 提取层级
        """
        # 1. 确认列存在
        table_cols = set()
        has_row_id = False
        try:
            cols_info = self.execute(f"SHOW COLUMNS FROM `{table}`")
            if cols_info:
                table_cols = {r['Field'] for r in cols_info}
                has_row_id = '_row_id' in table_cols
        except Exception as e:
            logger.warning(f"[update_address_column] 获取列信息失败: {e}")
            return

        logger.info(
            f"[update_address_column] 表 `{table}` 有 {len(table_cols)} 列, "
            f"_row_id={has_row_id}, 目标列='{display_name}', 候选列={source_cols}"
        )

        valid_source_cols = [c for c in source_cols if c in table_cols]
        if not valid_source_cols:
            logger.warning(
                f"[update_address_column] 候选列 {source_cols} 在结果表中不存在; "
                f"实际列: {sorted(table_cols)[:10]}..."
            )
            return

        if display_name not in table_cols:
            logger.warning(
                f"[update_address_column] 目标列 '{display_name}' 不在结果表中; "
                f"实际列: {sorted(table_cols)[:10]}..."
            )
            return

        if not has_row_id:
            logger.warning("[update_address_column] 结果表无 _row_id 列，无法逐行更新")
            return

        # 2. 分批读取并批量 UPDATE
        offset = 0
        batch_size = 5000
        updated_total = 0
        scanned_total = 0

        while True:
            cols_str = ", ".join(f"`{c}`" for c in valid_source_cols)
            sql = (f"SELECT `_row_id`, {cols_str} "
                   f"FROM `{table}` LIMIT {batch_size} OFFSET {offset}")
            rows = self.execute(sql)
            if not rows:
                break

            scanned_total += len(rows)

            # 3. 逐行匹配
            updates = {}  # {row_id: extracted_value}
            for row in rows:
                row_id = row.get('_row_id')
                if row_id is None:
                    continue
                result = extractor.extract_from_columns(row, valid_source_cols, level)
                if result:
                    updates[row_id] = result

            # 4. 用 CASE WHEN 批量 UPDATE（高效，一次 SQL 更新整批）
            if updates:
                ids = list(updates.keys())
                # 构建 CASE WHEN 子句
                case_parts = []
                for rid, val in updates.items():
                    escaped = str(val).replace("\\", "\\\\").replace("'", "\\'")
                    case_parts.append(f"WHEN {rid} THEN '{escaped}'")
                case_clause = "\n                    ".join(case_parts)
                id_list = ", ".join(str(i) for i in ids)
                update_sql = (
                    f"UPDATE `{table}`\n"
                    f"SET `{display_name}` = CASE `_row_id`\n"
                    f"                    {case_clause}\n"
                    f"                  END\n"
                    f"WHERE `_row_id` IN ({id_list})"
                )
                self.execute(update_sql)
                updated_total += len(updates)

            offset += batch_size
            if len(rows) < batch_size:
                break

        logger.info(
            f"[update_address_column] '{display_name}': "
            f"扫描 {scanned_total} 行, {updated_total} 行已填充"
        )

    def query_summary(self, report_id: str, columns: list = None,
                      filters: list = None, search: str = None,
                      search_columns: list = None) -> dict:
        """对结果表所有行执行跨页汇总查询（SUM 聚合）。

        用于在预览表底部显示准确的汇总行，不受分页 LIMIT 影响。

        Args:
            report_id: 报表 ID
            columns: FieldColumn 对象列表，用于确定哪些列需要汇总
            filters: 筛选条件（与 query_result 格式相同）
            search: 搜索文本
            search_columns: 搜索范围列

        Returns:
            {col_name: sum_value, ...}  或空 dict
        """
        table = self.result_table_name(report_id)
        if not self.result_table_exists(report_id):
            return {}

        # 获取结果表的实际列
        conn = self._get_conn()
        if not conn:
            return {}
        try:
            with conn.cursor() as cur:
                cur.execute(f"SHOW COLUMNS FROM `{table}`")
                rows = cur.fetchall()
            db_cols = [r.get('Field', '') for r in rows if r.get('Field', '') != '_row_id']
        except Exception:
            return {}

        if not db_cols:
            return {}

        # 收集需要 SUM 的列（可见的数值列）
        if columns:
            target_cols = []
            for col in columns:
                if isinstance(col, dict):
                    if not col.get('visible', True):
                        continue
                    name = col.get('display_name', '')
                elif hasattr(col, 'visible') and not col.visible:
                    continue
                else:
                    name = col.display_name if hasattr(col, 'display_name') else ''
                if name and name in db_cols:
                    target_cols.append(name)
            if not target_cols:
                target_cols = db_cols
        else:
            target_cols = db_cols

        # 构建 SUM 表达式
        agg_parts = [f"SUM(`{c}`) AS `{c}`" for c in target_cols]

        # 构建 WHERE（复用 query_result 的筛选逻辑）
        where_sql, where_params = "", []
        if filters or search:
            where_sql, where_params = self._build_where_for_summary(
                table, filters, search, search_columns
            )

        sql = f"SELECT {', '.join(agg_parts)} FROM `{table}`"
        if where_sql:
            sql += f" {where_sql}"

        try:
            result = self.execute(sql, where_params or None)
            return result[0] if result else {}
        except Exception as e:
            logger.warning(f"[ReportDatabase] query_summary 失败: {e}")
            return {}

    def _build_where_for_summary(self, table: str, filters: list,
                                  search: str, search_columns: list):
        """为汇总查询构建 WHERE 子句（精简版，仅处理文本筛选）。"""
        conditions = []
        params = []

        # 搜索条件
        if search:
            cols = search_columns or []
            if not cols:
                # 自动获取所有列
                try:
                    conn = self._get_conn()
                    with conn.cursor() as cur:
                        cur.execute(f"SHOW COLUMNS FROM `{table}`")
                        cols = [r.get('Field', '') for r in cur.fetchall()
                                if r.get('Field', '') != '_row_id']
                except Exception:
                    cols = []
            like_parts = [f"`{c}` LIKE %s" for c in cols if c]
            if like_parts:
                conditions.append(f"({' OR '.join(like_parts)})")
                params.extend([f"%{search}%"] * len(like_parts))

        # 筛选条件
        if filters:
            for fc in filters:
                if isinstance(fc, dict):
                    field = fc.get('field_label') or fc.get('field', '')
                    op = fc.get('operator', 'CONTAINS')
                    val = fc.get('value', '')
                else:
                    field = getattr(fc, 'field_label', '') or getattr(fc, 'field', '')
                    op = getattr(fc, 'operator', 'CONTAINS')
                    val = getattr(fc, 'value', '')

                if not field:
                    continue

                f_sql, f_params = self._build_filter_sql(field, op, val)
                if f_sql:
                    conditions.append(f_sql)
                    params.extend(f_params)

        if conditions:
            return ("WHERE " + " AND ".join(conditions), params)
        return ("", [])

    def result_table_exists(self, report_id: str) -> bool:
        """检查结果表是否存在（静默模式，不记录错误日志）"""
        conn = self._get_conn()
        if not conn:
            return False
        table = self.result_table_name(report_id)
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM `{table}` LIMIT 0")
            return True
        except Exception:
            return False

    # ---------- 元数据表 ----------

    def ensure_meta_table(self):
        """创建报表元数据表"""
        self.execute("""
            CREATE TABLE IF NOT EXISTS `cr_meta_reports` (
                `id` VARCHAR(64) PRIMARY KEY COMMENT '报表ID',
                `name` VARCHAR(255) NOT NULL COMMENT '报表名称',
                `definition_json` LONGTEXT COMMENT 'ReportDefinition JSON',
                `result_row_count` INT DEFAULT 0 COMMENT '结果行数',
                `last_refresh_time` DATETIME COMMENT '最后刷新时间',
                `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                `modified_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

    def save_report_meta(self, report_id: str, name: str, definition_json: str,
                         row_count: int = 0, refresh_time: str = None):
        """保存/更新报表元数据"""
        refresh_time = refresh_time or ''
        self.ensure_meta_table()
        sql = """
            INSERT INTO `cr_meta_reports` (id, name, definition_json, result_row_count, last_refresh_time)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                definition_json = VALUES(definition_json),
                result_row_count = VALUES(result_row_count),
                last_refresh_time = VALUES(last_refresh_time),
                modified_at = CURRENT_TIMESTAMP
        """
        self.execute(sql, (report_id, name, definition_json, row_count, refresh_time or None))

    def get_report_meta(self, report_id: str) -> Optional[dict]:
        """获取报表元数据"""
        self.ensure_meta_table()
        result = self.execute(
            "SELECT * FROM `cr_meta_reports` WHERE id = %s", (report_id,))
        return result[0] if result else None

    def list_report_metas(self, search: str = None) -> list[dict]:
        """列出所有报表元数据（支持搜索）"""
        self.ensure_meta_table()
        if search:
            like = f"%{search}%"
            return self.execute(
                "SELECT * FROM `cr_meta_reports` WHERE name LIKE %s ORDER BY modified_at DESC",
                (like,)) or []
        return self.execute(
            "SELECT * FROM `cr_meta_reports` ORDER BY modified_at DESC") or []

    def delete_report_meta(self, report_id: str):
        """删除报表元数据"""
        self.execute("DELETE FROM `cr_meta_reports` WHERE id = %s", (report_id,))
        self.drop_result_table(report_id)

    # ---------- 工具方法 ----------

    def _get_columns(self, table: str) -> set:
        """获取表的所有列名"""
        try:
            result = self.execute(f"SHOW COLUMNS FROM `{table}`")
            if result:
                return {r['Field'] for r in result}
        except Exception:
            pass
        return set()

    def table_exists(self, table: str) -> bool:
        """检查表是否存在"""
        if not table or not table.strip():
            return False
        try:
            result = self.execute(f"SELECT 1 FROM `{table}` LIMIT 0")
            return result is not None
        except Exception:
            return False

    def table_row_count(self, table: str) -> int:
        """返回表的行数"""
        try:
            result = self.execute(f"SELECT COUNT(*) AS cnt FROM `{table}`")
            if result:
                return result[0].get('cnt', 0)
        except Exception:
            pass
        return 0

    def sync_filtered_to_mysql(self, report_id: str, table_name: str,
                               filters: list[dict] = None,
                               search: str = None,
                               search_columns: list[str] = None,
                               id_column: str = None,
                               column_order: list[str] = None,
                               write_mode: str = "incremental",
                               field_type_map: dict = None,
                               field_formats: dict = None,
                               sync_id_fields: list = None,
                               sync_id_separator: str = "_") -> tuple:
        """将报表过滤后的数据增量同步到中文表头的 MySQL 表。

        通过 _hash 比对实现增量更新：
        - 新增行 → INSERT
        - 变更行 → UPDATE
        - 未变更行 → 跳过

        Args:
            report_id: 报表 ID
            table_name: 目标表名（如 报表-销售订单统计）
            filters: 筛选条件列表
            search: 搜索文本
            search_columns: 限定搜索的列名
            id_column: 用作主键的结果表列名（如主表 _id 对应的中文列名），
                       为 None 时回退到 _row_id
            field_type_map: {字段名: CRM 字段类型}，用于判断数值字段
            field_formats: {列显示名: field_format}，优先级高于 field_type_map，
                          用于决定 MySQL 列类型和值转换
            sync_id_fields: 用于拼接复合主键的列显示名列表，如 ["单号", "产品"]
            sync_id_separator: 拼接分隔符，默认 "_"

        Returns:
            (success: bool, message: str, stats: dict)
            stats: {'synced': int, 'skipped_empty_id': int, 'skipped_dup_id': int}
        """
        result_table = self.result_table_name(report_id)
        conn = self._get_conn()
        if not conn:
            return False, "MySQL 未连接", {}

        if not self.result_table_exists(report_id):
            return False, "报表结果表不存在，请先「更新数据」", {}

        # 获取结果表全部列名（排除内部列）
        all_cols = list(self._get_columns(result_table))
        display_cols = [c for c in all_cols if c not in ('_row_id', '_id', '_hash')]

        if not display_cols:
            return False, "结果表无数据列", {}

        # 确定主键列：
        #   1. 用户指定的复合主键字段（sync_id_fields，拼接为 VARCHAR）
        #   2. 指定的单列 (id_column，如 _id)
        #   3. _id（如有）
        #   4. 回退 _row_id
        use_composite_id = bool(sync_id_fields)
        if use_composite_id:
            # 直接使用刷新时预生成的「唯一ID」列作为主键
            pk_col = "唯一ID"
            is_row_id_pk = False
            target_pk = 'id'
        elif id_column and id_column in display_cols:
            pk_col = id_column
            target_pk = 'id' if pk_col == '_id' else pk_col
            is_row_id_pk = False
        elif '_id' in display_cols:
            pk_col = '_id'
            target_pk = 'id'
            is_row_id_pk = False
        else:
            pk_col = '_row_id'
            target_pk = pk_col
            is_row_id_pk = True

        # 构建 WHERE 子句
        where_parts = []
        params = []

        if search and display_cols:
            conditions = [f"`{c}` LIKE %s" for c in (search_columns or display_cols)]
            where_parts.append("(" + " OR ".join(conditions) + ")")
            params.extend([f"%{search}%" for _ in conditions])

        if filters:
            for fc in filters:
                cond_sql, cond_params = self._build_filter_sql(fc)
                if cond_sql:
                    where_parts.append(cond_sql)
                    params.extend(cond_params)

        where_clause = ""
        if where_parts:
            where_clause = "WHERE " + " AND ".join(where_parts)

        # 查询全部过滤数据（含 _row_id）
        all_cols_str = ', '.join(f'`{c}`' for c in all_cols)
        sql = f"SELECT {all_cols_str} FROM `{result_table}` {where_clause}"
        rows = self.execute(sql, params)

        if rows is None:
            return False, "查询失败", {}
        if not rows:
            return False, "当前筛选条件下无数据", {}

        # 目标表列名：pk 列 + 业务列 + _sync_time
        safe_display = [h.replace('`', '``') for h in display_cols]

        if use_composite_id:
            # 复合主键：目标表 id = 拼接值，所有列均为业务列
            safe_pk = 'id'
            business_cols = list(safe_display)  # 全部保留
        else:
            target_pk = 'id' if pk_col == '_id' else pk_col
            safe_pk = target_pk.replace('`', '``')
            business_cols = [h for h in safe_display if h != pk_col and h != target_pk]

        # 按 UI 列顺序排列
        if column_order:
            rank = {name: i for i, name in enumerate(column_order)}
            business_cols.sort(key=lambda h: rank.get(h, len(rank)))

        desired_cols = [safe_pk] + business_cols + ['_sync_time']

        with conn.cursor() as cur:
            overwrite = (write_mode == "overwrite")

            if overwrite:
                # 覆盖模式：无条件删表重建
                cur.execute(f"DROP TABLE IF EXISTS `{table_name}`")
            else:
                # 增量模式：仅在列结构不一致时删表重建
                old_cols = []
                try:
                    cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
                    for r in cur.fetchall():
                        col = r.get('Field', '')
                        if col != '_hash':  # 旧版遗留的 _hash 列，忽略
                            old_cols.append(col)
                except Exception:
                    pass

                if old_cols and old_cols != desired_cols:
                    cur.execute(f"DROP TABLE IF EXISTS `{table_name}`")

            # 建表
            if use_composite_id:
                pk_def = f'`{safe_pk}` VARCHAR(512) PRIMARY KEY'
            elif is_row_id_pk:
                pk_def = f'`{safe_pk}` INT PRIMARY KEY'
            else:
                pk_def = f'`{safe_pk}` VARCHAR(128) PRIMARY KEY'
            # 读取 field_type_map / field_formats 用于数值字段类型判断
            has_type_map = bool(field_type_map)
            has_field_formats = bool(field_formats)

            col_defs = [
                pk_def,
                '`_sync_time` DATETIME DEFAULT CURRENT_TIMESTAMP',
            ]
            for h in business_cols:
                # field_formats 优先，否则回退到 field_type_map
                fmt = None
                if has_field_formats:
                    fmt = field_formats.get(h, '')
                if fmt:
                    col_type = get_mysql_type_for_format(fmt)
                elif has_type_map:
                    col_type = get_mysql_type_for_field(field_type_map.get(h, ""))
                else:
                    col_type = "LONGTEXT"
                col_defs.append(f'`{h}` {col_type}')
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS `{table_name}` ({', '.join(col_defs)}) "
                f"ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            )

            # 动态补齐缺失列（仅当表未被重建时）+ 已有 LONGTEXT 列迁移为 DOUBLE
            existing = {}
            cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
            for r in cur.fetchall():
                existing[r.get('Field', '')] = r.get('Type', 'LONGTEXT')
            for h in business_cols + [safe_pk, '_sync_time']:
                if h not in existing:
                    if h == safe_pk:
                        col_type = 'INT' if is_row_id_pk else 'VARCHAR(128)'
                    elif h == '_sync_time':
                        col_type = 'DATETIME DEFAULT CURRENT_TIMESTAMP'
                    else:
                        # field_formats 优先，否则回退到 field_type_map
                        fmt = field_formats.get(h, '') if has_field_formats else ''
                        if fmt:
                            col_type = get_mysql_type_for_format(fmt)
                        elif has_type_map:
                            col_type = get_mysql_type_for_field(field_type_map.get(h, ''))
                        else:
                            col_type = 'LONGTEXT'
                    cur.execute(f"ALTER TABLE `{table_name}` ADD COLUMN `{h}` {col_type}")
                else:
                    # 检查是否需要迁移列类型（field_formats 优先）
                    fmt = field_formats.get(h, '') if has_field_formats else ''
                    if fmt:
                        expected_type = get_mysql_type_for_format(fmt)
                        # 只对数值类型做迁移（LONGTEXT → DOUBLE/BIGINT/DECIMAL）
                        if expected_type not in ('LONGTEXT', 'VARCHAR(32)', 'DATE', 'DATETIME', 'TIME'):
                            existing_type = str(existing.get(h, '')).lower()
                            numeric_keywords = ('double', 'int', 'float', 'decimal', 'bigint')
                            if not any(t in existing_type for t in numeric_keywords):
                                try:
                                    cur.execute(f"ALTER TABLE `{table_name}` MODIFY COLUMN `{h}` {expected_type}")
                                except Exception:
                                    pass
                    elif has_type_map:
                        ftype = field_type_map.get(h, '')
                        expected_type = get_mysql_type_for_field(ftype)
                        if expected_type == 'DOUBLE':
                            existing_type = str(existing.get(h, '')).lower()
                            if not any(t in existing_type for t in ('double', 'int', 'float', 'decimal')):
                                try:
                                    cur.execute(f"ALTER TABLE `{table_name}` MODIFY COLUMN `{h}` DOUBLE")
                                except Exception:
                                    pass

            insert_cols = [safe_pk, '_sync_time'] + business_cols
            placeholders = ', '.join(['%s'] * len(insert_cols))
            if overwrite:
                # 覆盖模式：表已清空，直接 INSERT
                insert_sql = (
                    f"INSERT INTO `{table_name}` "
                    f"(`{'`, `'.join(insert_cols)}`) VALUES ({placeholders})"
                )
            else:
                # 增量模式：INSERT ... ON DUPLICATE KEY UPDATE
                insert_sql = (
                    f"INSERT INTO `{table_name}` "
                    f"(`{'`, `'.join(insert_cols)}`) VALUES ({placeholders}) "
                    f"ON DUPLICATE KEY UPDATE "
                )
                update_parts = ['`_sync_time` = NOW()']
                for h in business_cols:
                    update_parts.append(f"`{h}` = VALUES(`{h}`)")
                insert_sql += ', '.join(update_parts)

            batch = []
            synced = 0
            skipped_empty = 0
            skipped_dup = 0
            seen_pks = set()  # 防止同批次主键重复导致 1062 错误
            for row in rows:
                # 获取主键值
                if use_composite_id:
                    # 直接读「唯一ID」列（刷新时已预生成）
                    pk_val = row.get("唯一ID", '')
                    if pk_val is None or str(pk_val).strip() == '':
                        skipped_empty += 1
                        continue
                    pk_str = str(pk_val).strip()
                else:
                    pk_val = row.get(pk_col)
                    if pk_val is None or str(pk_val).strip() == '':
                        skipped_empty += 1
                        continue
                    pk_str = str(pk_val).strip()

                if pk_str in seen_pks:
                    skipped_dup += 1
                    continue
                seen_pks.add(pk_str)

                if is_row_id_pk:
                    vals = [int(pk_str), None]
                else:
                    vals = [pk_str, None]

                for h in business_cols:
                    # field_formats 优先 → safe_value_by_format
                    # 否则回退 field_type_map → safe_numeric_value
                    fmt = field_formats.get(h, '') if has_field_formats else ''
                    if fmt:
                        val = safe_value_by_format(row.get(h, ''), fmt)
                    elif has_type_map:
                        ftype = field_type_map.get(h, '')
                        val = safe_numeric_value(row.get(h, ''), ftype)
                    else:
                        val = str(row.get(h, '')) if row.get(h, '') not in (None, '') else None
                    vals.append(val)
                batch.append(vals)
                synced += 1

                if len(batch) >= 500:
                    cur.executemany(insert_sql, batch)
                    batch.clear()

            if batch:
                cur.executemany(insert_sql, batch)

        mode_label = "覆盖写入" if overwrite else "增量更新"
        msg = f"已同步 {synced} 条（{mode_label}）"
        if skipped_dup > 0:
            msg += f"，{skipped_dup} 条因 ID 重复跳过"
        if skipped_empty > 0:
            msg += f"，{skipped_empty} 条因 ID 为空跳过"
        return True, msg, {'synced': synced, 'skipped_empty_id': skipped_empty, 'skipped_dup_id': skipped_dup}
