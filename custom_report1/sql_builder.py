"""
拼表 SQL 生成器

核心职责: 根据 ReportDefinition 生成 MySQL 拼表 SQL

支持的 JOIN 拓扑:
1. 星型: 主表 ←→ 多个关联表（各关联表独立与主表 JOIN）
2. 链式: 主表 → 表B → 表C（通过拓扑排序确定 JOIN 顺序）
3. 混合: 以上两种并存

输出: CREATE TABLE xxx AS SELECT ... FROM ... JOIN ... ON ... WHERE ...
"""

import logging
from collections import deque
from .models import ReportDefinition, JoinDefinition, MatchKey, FieldColumn
from .formula_engine import translate_formula_to_sql

logger = logging.getLogger(__name__)


# 相对日期操作符集合（需要 N 值参数）
_RELATIVE_DATE_RANGE_OPS = frozenset({
    'PAST_N_DAYS_EXCLUSIVE', 'PAST_N_DAYS_INCLUSIVE',
    'FUTURE_N_DAYS_EXCLUSIVE', 'FUTURE_N_DAYS_INCLUSIVE',
    'PAST_N_WEEKS_EXCLUSIVE', 'PAST_N_WEEKS_INCLUSIVE',
    'FUTURE_N_WEEKS_EXCLUSIVE', 'FUTURE_N_WEEKS_INCLUSIVE',
    'PAST_N_MONTHS_EXCLUSIVE', 'PAST_N_MONTHS_INCLUSIVE',
    'FUTURE_N_MONTHS_EXCLUSIVE', 'FUTURE_N_MONTHS_INCLUSIVE',
    'PAST_N_QUARTERS_INCLUSIVE',
})

# 相对日期（N天前/N天后)操作符集合 — 前后边界判断
_RELATIVE_DATE_BOUND_OPS = frozenset({
    'N_DAYS_AGO', 'N_DAYS_LATER',
    'N_WEEKS_AGO', 'N_WEEKS_LATER',
})


class JoinSQLBuilder:
    """根据 ReportDefinition 生成拼表 SQL"""

    def __init__(self, report: ReportDefinition, db=None):
        self._report = report
        self._db = db
        self._aliases: dict[str, str] = {}   # {api_name: "t0", "t1", ...}
        self._alias_counter = 0
        self._join_order: list[str] = []      # 拓扑排序后的对象顺序
        self._field_labels = self._load_field_labels()
        self._table_columns_cache: dict[str, set] = {}  # {api: {col_name, ...}}

    @staticmethod
    def _load_field_labels() -> dict:
        """从配置加载字段映射 {api_name: {field_key: field_label}}。"""
        import sys, json, os
        cfg = None
        # 方法1: 从主模块的 load_config 函数加载
        try:
            main = sys.modules.get('__main__')
            if main and hasattr(main, 'load_config'):
                cfg = main.load_config()
        except Exception:
            pass
        # 方法2: 从 get_config_path 直接读取 JSON 文件（后台线程兜底）
        if not cfg:
            try:
                if main and hasattr(main, 'get_config_path'):
                    config_path = main.get_config_path()
                    if os.path.exists(str(config_path)):
                        with open(str(config_path), 'r', encoding='utf-8') as f:
                            cfg = json.load(f)
            except Exception:
                pass
        # 方法3: 直接搜索 .config 目录下的配置文件（后台线程兜底，不依赖主模块全局变量）
        if not cfg:
            try:
                # 程序目录下的 .config 子目录
                config_dir_candidates = []
                if main and hasattr(main, '__file__'):
                    base = os.path.dirname(os.path.abspath(main.__file__))
                    config_dir_candidates.append(os.path.join(base, '.config'))
                # 当前工作目录下的 .config
                cwd = os.getcwd()
                config_dir_candidates.append(os.path.join(cwd, '.config'))
                for config_dir in config_dir_candidates:
                    if not os.path.isdir(config_dir):
                        continue
                    # 优先加载 admin.json（含完整字段配置），其次加载 001.json（默认配置）
                    # 也搜索 profiles 子目录（用户个性化配置）
                    search_paths = [config_dir]
                    profiles_dir = os.path.join(config_dir, 'profiles')
                    if os.path.isdir(profiles_dir):
                        search_paths.append(profiles_dir)
                    for search_dir in search_paths:
                        for fname in ('admin.json', '001.json', 'default.json'):
                            fpath = os.path.join(search_dir, fname)
                            if os.path.exists(fpath):
                                try:
                                    with open(fpath, 'r', encoding='utf-8') as f:
                                        cfg = json.load(f)
                                    if cfg:
                                        break
                                except Exception:
                                    pass
                        if cfg:
                            break
                    if cfg:
                        break
            except Exception:
                pass
        if not cfg:
            return {}
        # 兼容两种路径：直接根级 crm_object_fields，或嵌套在 fxiaoke 下
        crm_fields = cfg.get('crm_object_fields', {})
        if not crm_fields:
            crm_fields = cfg.get('fxiaoke', {}).get('crm_object_fields', {})
        result = {}
        for api, fields in (crm_fields or {}).items():
            if isinstance(fields, dict):
                result[api] = {
                    k: (v.get('label', k) if isinstance(v, dict) else str(v))
                    for k, v in fields.items()
                }
        return result

    def _is_literal_table(self, api: str) -> bool:
        """判断 api 是否是非 CRM 的直连表名（ex_ 前缀等）。"""
        if not api:
            return False
        if api.startswith('ex_'):
            return True
        # 不在 CRM field_labels 中，且不是对象- / sr_ 前缀
        if api not in self._field_labels and not api.startswith(('对象-', 'sr_')):
            return True
        return False

    def _resolve_field(self, api: str, field_key: str) -> str:
        """将字段 API 名解析为 MySQL 表中的中文列名。
        优先使用 field_labels 映射，回退到原始 field_key。
        同时支持按标签值反查（处理 _normalize_field_key 返回标签的情况）。
        """
        if self._is_literal_table(api):
            return field_key
        if self._field_labels:
            obj_labels = self._field_labels.get(api, {})
            if field_key in obj_labels:
                return obj_labels[field_key]
            # 按标签值反查：field_key 可能是中文标签（含括号等特殊字符）
            for k, v in obj_labels.items():
                if v == field_key:
                    return v
        return field_key

    def _field_has_key(self, api: str, field_key: str) -> bool:
        """检查 field_key（API 名或中文标签）是否存在于指定对象的字段映射中。"""
        if not self._field_labels:
            return False
        obj_labels = self._field_labels.get(api, {})
        if not obj_labels:
            return False
        if field_key in obj_labels:
            return True
        # 也按中文标签（value）匹配
        return field_key in obj_labels.values()

    def _get_table_columns(self, api: str) -> set:
        """获取指定对象 MySQL 清洗表的所有列名（带缓存）。"""
        if api in self._table_columns_cache:
            return self._table_columns_cache[api]
        cols = set()
        if self._db and hasattr(self._db, 'resolve_existing_table'):
            try:
                table = self._db.resolve_existing_table(api)
                rows = self._db.execute(f"SHOW COLUMNS FROM `{table}`")
                if rows:
                    cols = {r['Field'] for r in rows}
                    logger.info(f"[SQLBuilder] 获取列信息: api={api} → table=`{table}` | {len(cols)} 列")
                else:
                    logger.warning(f"[SQLBuilder] 获取列信息为空: api={api} → table=`{table}` | 表可能不存在")
            except Exception as e:
                logger.warning(f"[SQLBuilder] 获取列信息失败: api={api} | {e}")
        else:
            logger.warning(f"[SQLBuilder] 无法获取列信息: db={self._db is not None}, has_resolve={hasattr(self._db, 'resolve_existing_table') if self._db else 'N/A'}")
        self._table_columns_cache[api] = cols
        return cols

    def _find_column_owner(self, field_name: str, exclude_apis: set = None) -> str | None:
        """在所有 JOIN 对象中查找哪个对象的 MySQL 表实际包含指定列名。

        返回对象 API 名，未找到返回 None。
        exclude_apis: 要排除的 API 集合（避免返回已经验证不存在的 API）。
        """
        exclude = exclude_apis or set()
        # 第一遍：按原始列名精确匹配
        for api in self._aliases:
            if api in exclude:
                continue
            if field_name in self._get_table_columns(api):
                return api
        # 第二遍：将 CRM API 字段名翻译为中文标签后匹配
        # （MySQL 表使用中文列名，而 field_name 可能是 CRM API 名如 'opportunity_id'）
        for api in self._aliases:
            if api in exclude:
                continue
            labels = self._field_labels.get(api, {})
            for api_key, label in labels.items():
                if label == field_name or api_key == field_name:
                    if label in self._get_table_columns(api):
                        return api
        return None

    @staticmethod
    def _quote_ident(name: str) -> str:
        """安全引用 MySQL 标识符（支持中文等 Unicode 字符）。
        将内部的 ` 转义为 ``，然后用反引号包裹。
        """
        return f"`{name.replace('`', '``')}`"

    # ==================== 主入口 ====================

    def build_create_sql(self) -> str:
        """
        生成完整的 CREATE TABLE AS SELECT 语句

        公式列通过外层子查询计算并写入结果表：
            SELECT _base.*, 公式表达式 AS '显示名', ...
            FROM (内层拼表 SELECT) _base

        Returns:
            CREATE TABLE cr_xxx AS SELECT ... FROM ... JOIN ... WHERE ... GROUP BY ...
        """
        self._assign_aliases()
        select, base_names = self._build_select()
        from_clause = self._build_from()

        # 拆分筛选条件：主表→WHERE，JOIN表→ON（避免 LEFT JOIN 退化为 INNER JOIN）
        where_conds, join_conds = self._split_filter_conditions()
        joins, orphan_conds = self._build_joins(join_conds)

        # 孤儿条件（未匹配到 JOIN 的）追加到 WHERE
        all_where = where_conds + orphan_conds
        where = "WHERE " + "\n  AND ".join(all_where) if all_where else ""
        group_by = self._build_group_by()

        # 构建内层 SQL
        inner_sql = f"{select} {from_clause}"
        if joins:
            inner_sql += f" {joins}"
        if where:
            inner_sql += f" {where}"
        if group_by:
            inner_sql += f" {group_by}"

        # 获取公式列
        formula_cols = self._get_formula_columns()

        if not formula_cols:
            logger.info(f"[SQLBuilder] 无公式列，直接返回内层 SQL ({len(inner_sql)} 字符)")
            return inner_sql

        # 有公式列：外层包装子查询
        base_name_set = self._get_base_display_names()
        outer_parts = ["_base.*"]
        translated_count = 0
        for fc in formula_cols:
            display = fc.display_name if hasattr(fc, 'display_name') else fc.get('display_name', '计算列')
            display = display or '计算列'
            if display in base_name_set:
                logger.warning(
                    f"[SQLBuilder] 公式列 '{display}' 与基础列重名，"
                    f"退回 pandas 计算（避免 MySQL Duplicate column 错误）"
                )
                continue
            expr = getattr(fc, 'formula_expression', '') or ''
            try:
                sql_expr = translate_formula_to_sql(expr, base_names, table_alias='_base')
            except Exception as e:
                logger.warning(f"[SQLBuilder] 公式翻译异常 '{display}': {e}")
                continue
            if sql_expr is None:
                logger.info(f"[SQLBuilder] 公式 '{display}' 含不支持的函数，退回 pandas 计算")
                continue
            outer_parts.append(f"{sql_expr} AS {self._quote_ident(display)}")
            base_name_set.add(display)  # 避免后续公式列与已翻译的公式列重名
            translated_count += 1

        if translated_count == 0:
            return inner_sql

        outer_select = "SELECT " + ",\n       ".join(outer_parts)
        sql = f"{outer_select}\nFROM (\n  {inner_sql}\n) _base"

        # 记录生成的 SQL 便于排查问题
        logger.info(f"[SQLBuilder] 生成拼表 SQL ({translated_count} 个公式列, {len(sql)} 字符):\n{sql}")

        return sql

    def build_preview_sql(self, page: int = 1, page_size: int = 50) -> str:
        """生成预览查询 SQL（从结果表查询）"""
        table = self._report.result_table
        return f"SELECT * FROM {self._quote_ident(table)} LIMIT {page_size} OFFSET {(page - 1) * page_size}"

    # ==================== 别名分配 + 拓扑排序 ====================

    def _assign_aliases(self):
        """为每个涉及的对象分配表别名 (t0, t1, t2 ...)"""
        apis = list(dict.fromkeys(self._get_apis_in_join_order()))
        self._aliases = {api: f"t{i}" for i, api in enumerate(apis)}
        self._join_order = apis

    def _get_apis_in_join_order(self) -> list[str]:
        """
        拓扑排序，确定 JOIN 顺序。

        规则:
        1. 主表永远排第一 (t0)
        2. 以主表为起点 BFS：找出所有与已排序表直接关联的表
        3. 未连通的表（孤立表）放到最后
        """
        main = self._report.main_object_api
        if not main:
            return []

        apis = set()
        joins = self._normalize_joins()
        for j in joins:
            apis.add(j.left_object_api)
            apis.add(j.right_object_api)
        if main not in apis:
            apis.add(main)

        # BFS 排序
        ordered = [main]
        visited = {main}
        remaining = apis - visited

        while remaining:
            added = False
            for api in list(remaining):
                for j in joins:
                    left = j.left_object_api
                    right = j.right_object_api
                    if (left in visited and right == api) or (right in visited and left == api):
                        ordered.append(api)
                        visited.add(api)
                        remaining.discard(api)
                        added = True
                        break
            if not added:
                # 有孤立表，直接追加
                ordered.extend(remaining)
                break

        # 不在 JOIN 中的表不加到别名列表（避免产生无 FROM/JOIN 的悬挂引用）
        return ordered

    def _normalize_joins(self) -> list[JoinDefinition]:
        """确保所有 JoinDefinition 的左右表方向一致（左表在右表之前出现于拓扑序）

        拓扑序在 _assign_aliases() 中确定。此方法在拓扑序确定前也会被调用
        （仅用于收集参与 JOIN 的对象集合），此时不做方向归一化。
        """
        result = []
        for j in self._report.joins:
            jd = j if isinstance(j, JoinDefinition) else JoinDefinition(**j)
            result.append(jd)

        # 拓扑序确定后：确保左表在序中先于右表，保证 JOIN 链正确
        if self._join_order:
            api_order = {api: i for i, api in enumerate(self._join_order)}
            for jd in result:
                left_order = api_order.get(jd.left_object_api, 999)
                right_order = api_order.get(jd.right_object_api, 999)
                if left_order > right_order:
                    # 交换左右表，同时交换所有 match_keys
                    jd.left_object_api, jd.right_object_api = jd.right_object_api, jd.left_object_api
                    new_keys = []
                    for mk in jd.match_keys:
                        mk_obj = mk if isinstance(mk, MatchKey) else MatchKey(**mk)
                        mk_obj.left_field, mk_obj.right_field = mk_obj.right_field, mk_obj.left_field
                        new_keys.append(mk_obj)
                    jd.match_keys = new_keys

        return result

    # ==================== SQL 子句生成 ====================

    def _build_select(self) -> tuple[str, list[str]]:
        """生成 SELECT 子句（支持聚合列、GROUP BY，公式列由外层处理）。

        Returns:
            (select_sql, base_display_names) — base_display_names 供公式列 SQL 翻译用
        """
        main_alias = self._aliases.get(self._report.main_object_api, 't0')
        has_aggregate = self._has_aggregate_columns()
        has_group_by = bool(self._report.group_by_fields)

        if not self._report.columns:
            return f"SELECT {main_alias}.*", []

        # 始终包含主表 _id（除非是分组聚合模式，聚合结果无单一 _id）
        # Excel 导入表没有 CRM 的 _id 列，需跳过
        parts = []
        if not (has_aggregate and has_group_by):
            main_api = self._report.main_object_api
            if main_api.startswith('ex_') and self._db and '_id' not in self._db._get_columns(main_api):
                pass  # Excel 表无 _id，跳过
            else:
                parts = [f"{main_alias}.`_id` AS '_id'"]

        # 第一遍：收集所有列信息（按 sort_order 排序，保证 MySQL 表列顺序与编辑界面一致）
        col_infos = []
        sorted_columns = sorted(
            self._report.columns,
            key=lambda c: c.sort_order if isinstance(c, FieldColumn) else (c.get('sort_order', 0) if isinstance(c, dict) else 0)
        )

        # 预扫描：为 date_part 列建立 display_name → (alias, quoted_field) 映射
        direct_col_map = {}
        for col in sorted_columns:
            if not isinstance(col, FieldColumn):
                col = FieldColumn(**col)
            if not col.visible:
                continue
            comp_type = getattr(col, 'computation_type', 'direct')
            if comp_type == 'direct' and col.source_field:
                api = col.source_object_api or self._report.main_object_api
                alias = self._aliases.get(api)
                if alias:
                    resolved_field = self._resolve_field(api, col.source_field)
                    direct_col_map[col.display_name] = (alias, resolved_field)

        for col in sorted_columns:
            if not isinstance(col, FieldColumn):
                col = FieldColumn(**col)
            if not col.visible:
                continue

            # 公式列不进入内层 SQL，由外层子查询包装计算
            if getattr(col, 'computation_type', 'direct') == 'formula':
                continue
            if col.source_field and str(col.source_field).startswith('='):
                continue

            # 地址提取列：SQL 阶段留 NULL 占位，刷新后由 Python 后处理填充
            if getattr(col, 'computation_type', 'direct') == 'address_extract':
                display = col.display_name or '地址提取'
                col_infos.append({
                    'alias': '',
                    'field': '',
                    'display': display,
                    'api': '',
                    'is_aggregate': False,
                    'agg_func': '',
                    'is_address_extract': True,
                })
                continue

            # 时间成分列：直接生成 SQL 日期函数表达式
            if getattr(col, 'computation_type', 'direct') == 'date_part':
                display = col.display_name or '时间成分'
                src_field_display = getattr(col, 'date_part_source_field', '') or ''
                unit = getattr(col, 'date_part_unit', 'year') or 'year'
                src_info = direct_col_map.get(src_field_display, (None, None))
                src_alias, src_quoted_field = src_info
                if src_alias and src_quoted_field:
                    func_map = {
                        'year': f"CAST(YEAR({src_alias}.{src_quoted_field}) AS UNSIGNED)",
                        'month': f"CAST(MONTH({src_alias}.{src_quoted_field}) AS UNSIGNED)",
                        'week': f"CAST(WEEK({src_alias}.{src_quoted_field}, 3) AS UNSIGNED)",
                        'quarter': f"CAST(QUARTER({src_alias}.{src_quoted_field}) AS UNSIGNED)",
                    }
                    sql_expr = func_map.get(unit, f"YEAR({src_alias}.{src_quoted_field})")
                else:
                    sql_expr = "NULL"
                col_infos.append({
                    'alias': '',
                    'field': '',
                    'display': display,
                    'api': '',
                    'is_aggregate': False,
                    'agg_func': '',
                    'is_date_part': True,
                    '_sql_expr': sql_expr,
                })
                continue

            # 聚合列：source_field 仍然指向原始字段，但 SELECT 使用聚合函数包裹
            if getattr(col, 'computation_type', 'direct') == 'aggregate' and col.aggregate_func:
                if not col.source_field:
                    continue
                api = col.source_object_api or self._report.main_object_api
                resolved_field = self._resolve_field(api, col.source_field)
                alias = self._aliases.get(api)
                if not alias:
                    continue
                # DB 层校验：确认该列在指定对象的 MySQL 清洗表中确实存在
                if self._db and hasattr(self._db, 'resolve_existing_table'):
                    db_cols_agg = self._get_table_columns(api)
                    if db_cols_agg and resolved_field not in db_cols_agg:
                        correct_api_agg = self._find_column_owner(resolved_field, exclude_apis={api})
                        if not correct_api_agg:
                            correct_api_agg = self._find_column_owner(col.source_field, exclude_apis={api})
                        if correct_api_agg and correct_api_agg in self._aliases:
                            api = correct_api_agg
                            alias = self._aliases[api]
                            resolved_field = self._resolve_field(api, col.source_field)
                        else:
                            # 回退：用 display_name 匹配列名（MySQL 表用中文列名）
                            display_agg = col.display_name or ''
                            if display_agg and display_agg in db_cols_agg:
                                resolved_field = display_agg
                            elif display_agg:
                                owner_api = self._find_column_owner(display_agg, exclude_apis={api})
                                if owner_api and owner_api in self._aliases:
                                    api = owner_api
                                    alias = self._aliases[api]
                                    resolved_field = display_agg
                display = col.display_name or f"{col.aggregate_func}({col.source_field})"
                agg_func = col.aggregate_func.upper()
                col_infos.append({
                    'alias': alias,
                    'field': resolved_field,
                    'display': display,
                    'api': api,
                    'is_aggregate': True,
                    'agg_func': agg_func,
                })
                continue

            # 直接列（现有逻辑）
            if not col.source_field:
                continue
            api = col.source_object_api or self._report.main_object_api
            # 解析 MySQL 列名
            resolved_field = self._resolve_field(api, col.source_field)
            original_api = api
            # DB 层校验：确认该列在指定对象的 MySQL 清洗表中确实存在
            if self._db and hasattr(self._db, 'resolve_existing_table'):
                db_cols = self._get_table_columns(api)
                # 仅当 db_cols 非空时才做列存在性校验（空集合说明表不存在/无列，不应触发重分配）
                if db_cols and resolved_field not in db_cols:
                    # 当前对象表中不存在该列 → 在所有 JOIN 对象中搜索
                    correct_api = self._find_column_owner(resolved_field, exclude_apis={api})
                    if not correct_api:
                        # 也尝试用原始 field_key 搜索
                        correct_api = self._find_column_owner(col.source_field, exclude_apis={api})
                    if correct_api and correct_api in self._aliases:
                        logger.info(
                            f"[SQLBuilder] 列 '{resolved_field}' 从 {api} 重分配到 {correct_api}"
                        )
                        api = correct_api
                    else:
                        # 在所有表中都找不到该列名 → 尝试用 display_name 作为列名回退
                        # （MySQL 清洗表以中文显示名作为列名，而 CRM API 字段名可能未被翻译）
                        display = col.display_name or ''
                        if display and display in db_cols:
                            logger.info(
                                f"[SQLBuilder] 列 '{resolved_field}' 在表 {api} 中不存在，"
                                f"使用 display_name '{display}' 作为列名"
                            )
                            resolved_field = display
                        elif display:
                            # 当前表没有，尝试在关联表中搜索 display_name
                            owner_api = self._find_column_owner(display, exclude_apis={api})
                            if owner_api and owner_api in self._aliases:
                                logger.info(
                                    f"[SQLBuilder] 列 '{display}' 在表 {owner_api} 中找到，"
                                    f"从 {api} 重分配"
                                )
                                api = owner_api
                                resolved_field = display
                elif not db_cols:
                    logger.warning(
                        f"[SQLBuilder] 表 '{api}' 的列信息为空（表不存在或无数据），"
                        f"列 '{resolved_field}' 保持原分配"
                    )
            alias = self._aliases.get(api)
            if not alias:
                # api 可能是中文显示名而非 CRM API 名，尝试在所有已关联表中查找该列
                correct_api = self._find_column_owner(resolved_field)
                if not correct_api:
                    correct_api = self._find_column_owner(col.source_field)
                if correct_api and correct_api in self._aliases:
                    api = correct_api
                    alias = self._aliases[api]
            if not alias:
                logger.warning(f"[SQLBuilder] 列 '{col.display_name or col.source_field}' 无法关联到任何表，已跳过")
                continue
            # 仅当 api 被更正时才重新解析字段名（保留 display_name 回退的结果）
            if api != original_api:
                resolved_field = self._resolve_field(api, col.source_field)
            display = col.display_name or col.source_field
            col_infos.append({
                'alias': alias,
                'field': resolved_field,
                'display': display,
                'api': api,
                'is_aggregate': False,
                'agg_func': '',
            })

        if not col_infos:
            if not (has_aggregate and has_group_by):
                logger.warning(f"[SQLBuilder] 所有列解析失败，回退为 SELECT {main_alias}.*")
                main_alias = self._aliases.get(self._report.main_object_api, 't0')
                return f"SELECT {main_alias}.*", []
            logger.warning(f"[SQLBuilder] 聚合模式下所有列解析失败，回退为 SELECT 1")
            return "SELECT 1", []

        # 第二遍：检测重复的 display 名，冲突时追加 _N 后缀去重
        display_counts: dict[str, int] = {}
        if not (has_aggregate and has_group_by):
            display_counts['_id'] = 1
        dedup_names: dict[str, int] = {}

        for ci in col_infos:
            display = ci['display']
            if display_counts.get(display, 0) > 0:
                base = display
                idx = dedup_names.get(base, 2)
                while True:
                    candidate = f"{base}_{idx}"
                    if candidate not in display_counts:
                        break
                    idx += 1
                dedup_names[base] = idx + 1
                if display_counts.get(display, 0) == 1:
                    for j, p in enumerate(parts):
                        if p.endswith(f"AS {self._quote_ident(display)}"):
                            parts[j] = p.replace(
                                f"AS {self._quote_ident(display)}",
                                f"AS {self._quote_ident(display + '_1')}"
                            )
                            break
                    display_counts[display] = 2
                    dedup_names[base] = max(dedup_names.get(base, 2), 3)
                display = candidate
                display_counts[display] = 1
            else:
                display_counts[display] = 1

            quoted_field = self._quote_ident(ci['field'])
            if ci.get('is_address_extract'):
                parts.append(f"CAST(NULL AS CHAR(100)) AS {self._quote_ident(display)}")
            elif ci.get('is_date_part'):
                sql_expr = ci.get('_sql_expr', 'NULL')
                parts.append(f"{sql_expr} AS {self._quote_ident(display)}")
            elif ci['is_aggregate']:
                parts.append(
                    f"{ci['agg_func']}({ci['alias']}.{quoted_field}) AS {self._quote_ident(display)}"
                )
            else:
                parts.append(f"{ci['alias']}.{quoted_field} AS {self._quote_ident(display)}")

        # 拼接 ID 列（如果配置了 sync_id_fields）
        composite_id_sql = self._build_composite_id_sql(col_infos, main_alias)
        if composite_id_sql:
            parts.append(composite_id_sql)

        # 收集基础列显示名（供公式列 SQL 翻译使用）
        base_names = [ci['display'] for ci in col_infos]

        return "SELECT " + ",\n       ".join(parts), base_names

    def _build_composite_id_sql(self, col_infos: list[dict],
                                 main_alias: str) -> str | None:
        """如果配置了 sync_id_fields，生成 CONCAT_WS 表达式 AS '唯一ID'。

        查找逻辑：
        1. 先在 col_infos（报表列）中按 display_name 匹配
        2. 未命中则在所有别名表的 field_labels 中按标签反查
        """
        id_fields = getattr(self._report, 'sync_id_fields', None) or []
        if not id_fields:
            return None
        separator = getattr(self._report, 'sync_id_separator', '_') or '_'

        import sys
        print(f"[SQLBuilder] sync_id_fields={id_fields}, separator={separator}", file=sys.stderr, flush=True)
        print(f"[SQLBuilder] aliases={self._aliases}", file=sys.stderr, flush=True)

        # 构建 display → (alias, mysql_field) 映射
        display_map = {}
        for ci in col_infos:
            if not ci.get('is_address_extract') and not ci.get('is_date_part') and ci.get('display'):
                display_map[ci['display']] = (ci['alias'], ci['field'])

        parts = []
        for df in id_fields:
            # 解析格式：可能是 "api|label" 或纯 "label"（兼容旧数据）
            if '|' in df:
                target_api, target_label = df.split('|', 1)
            else:
                target_api, target_label = None, df

            print(f"[SQLBuilder] 处理字段: df={df}, api={target_api}, label={target_label}", file=sys.stderr, flush=True)

            if target_label == '_id':
                # _id 是源表直列，不需要翻译
                alias = self._aliases.get(target_api) if target_api else None
                if not alias:
                    alias = main_alias
                parts.append(f"{alias}.`_id`")
                print(f"[SQLBuilder]   → _id 直列: {alias}._id", file=sys.stderr, flush=True)
            elif target_label in display_map:
                alias, field = display_map[target_label]
                parts.append(f"{alias}.{self._quote_ident(field)}")
                print(f"[SQLBuilder]   → display_map 命中: {alias}.`{field}`", file=sys.stderr, flush=True)
            elif target_api and target_api in self._aliases:
                # 按指定 API 查找
                alias = self._aliases[target_api]
                labels = self._field_labels.get(target_api, {})
                found = False
                for fkey, flabel in labels.items():
                    if flabel == target_label:
                        resolved = self._resolve_field(target_api, fkey)
                        parts.append(f"{alias}.{self._quote_ident(resolved)}")
                        print(f"[SQLBuilder]   → field_labels 命中 ({target_api}): {alias}.`{resolved}`", file=sys.stderr, flush=True)
                        found = True
                        break
                if not found:
                    logger.warning(f"[SQLBuilder] 拼接 ID 字段 '{df}' 在表 {target_api} 中未找到")
                    print(f"[SQLBuilder]   → 表 {target_api} 中未找到 label='{target_label}'", file=sys.stderr, flush=True)
                    parts.append(f"'?'")
            else:
                # 在 field_labels 中按标签反查
                found = False
                for api, alias in self._aliases.items():
                    labels = self._field_labels.get(api, {})
                    for fkey, flabel in labels.items():
                        if flabel == target_label:
                            resolved = self._resolve_field(api, fkey)
                            parts.append(f"{alias}.{self._quote_ident(resolved)}")
                            print(f"[SQLBuilder]   → 全扫描命中 ({api}): {alias}.`{resolved}`", file=sys.stderr, flush=True)
                            found = True
                            break
                    if found:
                        break
                if not found:
                    logger.warning(f"[SQLBuilder] 拼接 ID 字段 '{df}' 未在任何表中找到")
                    print(f"[SQLBuilder]   → 未在任何表中找到", file=sys.stderr, flush=True)
                    parts.append(f"'?'")

        if not parts:
            print(f"[SQLBuilder] 无有效字段，跳过", file=sys.stderr, flush=True)
            return None

        concat = f"CONCAT_WS('{separator}', {', '.join(parts)})"
        result = f"{concat} AS {self._quote_ident('唯一ID')}"
        print(f"[SQLBuilder] 生成 SQL: {result}", file=sys.stderr, flush=True)
        return result

    def _get_base_display_names(self) -> set[str]:
        """获取基础列（非公式列）的所有显示名，用于冲突检测。"""
        names = set()
        has_aggregate = self._has_aggregate_columns()
        has_group_by = bool(self._report.group_by_fields)
        if not (has_aggregate and has_group_by):
            names.add('_id')
        for col in self._report.columns:
            if isinstance(col, dict):
                if not col.get('visible', True):
                    continue
                comp_type = col.get('computation_type', 'direct')
                if comp_type in ('formula', 'address_extract', 'date_part'):
                    continue
                sf = col.get('source_field', '')
            else:
                if not col.visible:
                    continue
                if getattr(col, 'computation_type', 'direct') in ('formula', 'address_extract'):
                    continue
                sf = col.source_field or ''
            if sf and str(sf).startswith('='):
                continue
            display = col.get('display_name', '') if isinstance(col, dict) else col.display_name
            if display:
                names.add(display)
        return names

    def _get_formula_columns(self) -> list[FieldColumn]:
        """获取所有可见的公式列（computation_type='formula' 或有非空 formula_expression）。"""
        result = []
        for col in self._report.columns:
            if isinstance(col, dict):
                if not col.get('visible', True):
                    continue
                comp_type = col.get('computation_type', 'direct')
                formula_expr = col.get('formula_expression', '')
                sf = col.get('source_field', '')
            else:
                if not col.visible:
                    continue
                comp_type = getattr(col, 'computation_type', 'direct')
                formula_expr = getattr(col, 'formula_expression', '') or ''
                sf = col.source_field or ''
            if comp_type == 'formula' or (sf and str(sf).startswith('=')):
                if formula_expr.strip():
                    result.append(col if not isinstance(col, dict) else FieldColumn(**col))
        return result

    def _table_name(self, api: str) -> str:
        """解析 API 名对应的 MySQL 实际表名。
        优先使用「对象-{name}」已有表，回退到 sr_{api_name}。
        对于非 CRM 表（ex_ 前缀或直接表名），直接返回 api。
        """
        if self._db and hasattr(self._db, 'resolve_existing_table'):
            resolved = self._db.resolve_existing_table(api)
            # 如果解析结果是默认的 sr_{api} 模式但该表不存在，
            # 且 api 本身是一个存在的表名 → 使用 api 直接作为表名
            if resolved == f"sr_{api}" and not self._db.table_exists(resolved):
                if self._db.table_exists(api):
                    return api
            return resolved
        return f"sr_{api}"

    def _build_from(self) -> str:
        """生成 FROM 子句"""
        main = self._report.main_object_api
        alias = self._aliases.get(main, 't0')
        table = self._table_name(main)
        logger.info(f"[SQLBuilder] FROM: api={main} → table=`{table}` alias={alias}")
        return f"FROM {self._quote_ident(table)} {alias}"

    def _build_joins(self, join_conds: dict[str, list[str]] = None) -> str:
        """
        生成 JOIN 子句

        对每个 JoinDefinition：
        - 确定左右表别名
        - 生成 ON 条件（包含 match_keys + 该 JOIN 表专属的筛选条件）
        - 根据 join_type 选择 JOIN 关键字

        Args:
            join_conds: {right_api: [cond_str, ...]} — JOIN 表专属的筛选条件
                        从 _split_filter_conditions 获取，挂载到 ON 子句
                        避免 LEFT JOIN 时 WHERE 条件将之退化为 INNER JOIN
        """
        join_conds = join_conds or {}
        main = self._report.main_object_api
        joins = self._normalize_joins()
        parts = []

        for jd in joins:
            left_api = jd.left_object_api
            right_api = jd.right_object_api

            left_alias = self._aliases.get(left_api)
            right_alias = self._aliases.get(right_api)

            if not left_alias or not right_alias:
                if not left_alias:
                    left_alias = f"t{self._alias_counter}"
                    self._aliases[left_api] = left_alias
                    self._alias_counter += 1
                if not right_alias:
                    right_alias = f"t{self._alias_counter}"
                    self._aliases[right_api] = right_alias
                    self._alias_counter += 1

            join_keyword = self._join_keyword(jd.join_type)
            right_table = self._table_name(right_api)
            logger.info(f"[SQLBuilder] JOIN: api={right_api} → table=`{right_table}` alias={right_alias} type={jd.join_type}")

            # ON 条件：match_keys
            on_conditions = []
            for mk in jd.match_keys:
                mk_obj = mk if isinstance(mk, MatchKey) else MatchKey(**mk)
                if mk_obj.left_field and mk_obj.right_field:
                    left_field = self._resolve_field(left_api, mk_obj.left_field)
                    right_field = self._resolve_field(right_api, mk_obj.right_field)
                    on_conditions.append(
                        f"{left_alias}.{self._quote_ident(left_field)} = "
                        f"{right_alias}.{self._quote_ident(right_field)}"
                    )

            # ON 条件：该 JOIN 表专属的筛选条件（防止 LEFT JOIN 退化为 INNER JOIN）
            extra_conds = join_conds.pop(right_api, [])
            on_conditions.extend(extra_conds)

            if not on_conditions:
                continue

            on_clause = " AND ".join(on_conditions)
            parts.append(
                f"{join_keyword} {self._quote_ident(right_table)} {right_alias}\n"
                f"    ON {on_clause}"
            )

        # 剩余未匹配到任何 JOIN 的筛选条件（罕见：过滤字段在别名表中但没有对应 JOIN）
        # 放回 WHERE 子句作为兜底
        orphan_conds = []
        for conds in join_conds.values():
            orphan_conds.extend(conds)
        if orphan_conds:
            logger.info(f"[SQLBuilder] {len(orphan_conds)} 个筛选条件未匹配到 JOIN，放入 WHERE")

        return "\n".join(parts), orphan_conds

    def _build_where(self) -> str:
        """生成 WHERE 子句（仅包含主表的筛选条件）。

        JOIN 表的筛选条件移至 ON 子句，避免 LEFT JOIN 退化为 INNER JOIN
        导致主表中无匹配右表的行被静默丢弃。
        """
        where_conds, _ = self._split_filter_conditions()
        if where_conds:
            return "WHERE " + "\n  AND ".join(where_conds)
        return ""

    def _split_filter_conditions(self) -> tuple[list[str], dict[str, list[str]]]:
        """拆分筛选条件为 WHERE 条件（主表）和 JOIN ON 条件（各 JOIN 表）。

        Returns:
            (where_conditions, join_conditions)
            其中 join_conditions = {target_api: [cond_str, ...]}
        """
        main_api = self._report.main_object_api
        where_conds = []
        join_conds: dict[str, list[str]] = {}  # {target_api: [cond_str, ...]}

        for fc in self._report.filters:
            if isinstance(fc, dict):
                field_api = fc.get('field_api', '')
                operator = fc.get('operator', 'EQ')
                value = fc.get('value', '')
                target_api = fc.get('target_object_api', '')
            elif hasattr(fc, 'field_api'):
                field_api = fc.field_api
                operator = fc.operator
                value = fc.value
                target_api = fc.target_object_api
            else:
                continue

            if not field_api:
                continue

            # 解析字段所属对象
            if not target_api:
                target_api = self._find_field_owner(field_api)
            if not target_api:
                target_api = main_api

            alias = self._aliases.get(target_api, 't0')
            resolved_field = self._resolve_field(target_api, field_api)
            cond = self._build_filter_condition(alias, resolved_field, operator, value)
            if not cond:
                continue

            # 主表条件 → WHERE；JOIN 表条件 → ON
            if target_api == main_api or not target_api:
                where_conds.append(cond)
            else:
                join_conds.setdefault(target_api, []).append(cond)

        return where_conds, join_conds

    def _has_aggregate_columns(self) -> bool:
        """检查是否有任何聚合列。"""
        for col in self._report.columns:
            if isinstance(col, dict):
                if col.get('computation_type') == 'aggregate' and col.get('aggregate_func'):
                    return True
            elif getattr(col, 'computation_type', 'direct') == 'aggregate' and col.aggregate_func:
                return True
        return False

    def _build_group_by(self) -> str:
        """为非聚合的直接列生成 GROUP BY 子句。

        只有当存在聚合列时才生成 GROUP BY。
        GROUP BY 键 = 所有 computation_type='direct' 的可见列。
        """
        if not self._has_aggregate_columns():
            return ""
        if not self._report.columns:
            return ""

        group_parts = []
        for col in self._report.columns:
            if isinstance(col, dict):
                if col.get('computation_type', 'direct') != 'direct':
                    continue
                if not col.get('visible', True):
                    continue
                api = col.get('source_object_api') or self._report.main_object_api
                sf = col.get('source_field', '')
            else:
                if getattr(col, 'computation_type', 'direct') != 'direct':
                    continue
                if not col.visible:
                    continue
                api = col.source_object_api or self._report.main_object_api
                sf = col.source_field

            if not sf:
                continue

            resolved = self._resolve_field(api, sf)
            alias = self._aliases.get(api)
            if not alias:
                continue

            group_parts.append(f"{alias}.{self._quote_ident(resolved)}")

        if not group_parts:
            return ""

        # 如果有显式指定的分组键，优先使用
        if self._report.group_by_fields:
            explicit_parts = []
            for gf in self._report.group_by_fields:
                api = self._report.main_object_api
                resolved = self._resolve_field(api, gf)
                alias = self._aliases.get(api, 't0')
                explicit_parts.append(f"{alias}.{self._quote_ident(resolved)}")
            if explicit_parts:
                group_parts = explicit_parts

        return "GROUP BY " + ", ".join(group_parts)

    def _build_filter_condition(self, alias: str, field: str,
                                 operator: str, value: str) -> str:
        """生成单个筛选条件的 SQL（支持文字和日期操作符）"""
        col = f"{alias}.{self._quote_ident(field)}"
        op = operator.upper()
        escaped = self._escape(value)

        # --- 文字操作符 ---
        if op == 'EQ':
            return f"{col} = '{escaped}'"
        if op == 'NEQ':
            return f"{col} != '{escaped}'"
        if op == 'CONTAINS':
            return f"{col} LIKE '%{escaped}%'"
        if op == 'NOT_CONTAINS':
            return f"{col} NOT LIKE '%{escaped}%'"
        if op == 'STARTS_WITH':
            return f"{col} LIKE '{escaped}%'"
        if op == 'ENDS_WITH':
            return f"{col} LIKE '%{escaped}'"
        if op == 'IN':
            raw = value.replace('；', ',').replace(';', ',')
            vals = [v.strip() for v in raw.split(',') if v.strip()]
            if not vals:
                return ""
            quoted = ", ".join(f"'{self._escape(v)}'" for v in vals)
            return f"{col} IN ({quoted})"
        if op == 'NOT_IN':
            raw = value.replace('；', ',').replace(';', ',')
            vals = [v.strip() for v in raw.split(',') if v.strip()]
            if not vals:
                return ""
            quoted = ", ".join(f"'{self._escape(v)}'" for v in vals)
            return f"{col} NOT IN ({quoted})"
        if op == 'GT':
            return f"{col} > '{escaped}'"
        if op == 'LT':
            return f"{col} < '{escaped}'"
        if op == 'GTE':
            return f"{col} >= '{escaped}'"
        if op == 'LTE':
            return f"{col} <= '{escaped}'"
        if op in ('EMPTY', 'IS_NULL'):
            return f"({col} IS NULL OR {col} = '')"
        if op in ('NOT_EMPTY', 'IS_NOT_NULL'):
            return f"({col} IS NOT NULL AND {col} != '')"

        # --- 日期操作符 ---
        if op == 'DATE_BEFORE':
            return f"{col} < {self._date_to_ts(value)}"
        if op == 'DATE_AFTER':
            return f"{col} > {self._date_to_ts(value)}"
        if op == 'DATE_BEFORE_EQ':
            return f"{col} <= {self._date_to_ts(value, end_of_day=True)}"
        if op == 'DATE_AFTER_EQ':
            return f"{col} >= {self._date_to_ts(value)}"
        if op == 'DATE_RANGE':
            parts = value.split('~')
            if len(parts) == 2:
                ts_start = self._date_to_ts(parts[0].strip())
                ts_end = self._date_to_ts(parts[1].strip(), end_of_day=True)
                return f"({col} >= {ts_start} AND {col} <= {ts_end})"
            return ""

        # --- 相对日期（范围）操作符 ---
        if op in _RELATIVE_DATE_RANGE_OPS:
            ts_pair = self._compute_relative_ts_range(op, value)
            if ts_pair:
                return f"({col} >= {ts_pair[0]} AND {col} <= {ts_pair[1]})"
            return ""

        # --- 相对日期（边界）操作符: N天前/N天后等 ---
        if op in _RELATIVE_DATE_BOUND_OPS:
            ts_bound = self._compute_relative_ts_bound(op, value)
            if ts_bound is not None:
                if 'AGO' in op:
                    return f"{col} <= {ts_bound}"
                else:
                    return f"{col} >= {ts_bound}"
            return ""

        return ""

    def _find_field_owner(self, field_api: str) -> str:
        """查找字段所属的对象 API 名。

        在所有已知对象的字段映射中按 API 名和中文标签搜索 field_api，
        返回对象 API 名；未找到时返回主表 API 名。
        """
        # 先按 key（API 名）精确匹配
        for api in self._aliases:
            field_labels = self._field_labels.get(api, {})
            if field_api in field_labels:
                return api
        # 再按 value（中文标签）匹配
        for api in self._aliases:
            field_labels = self._field_labels.get(api, {})
            if field_api in field_labels.values():
                return api
        main = self._report.main_object_api
        return main or ''

    # ==================== 工具方法 ====================

    def _join_keyword(self, join_type: str) -> str:
        """JOIN 类型 → SQL 关键字"""
        return {
            'left': 'LEFT JOIN',
            'inner': 'INNER JOIN',
            'one_to_one': 'LEFT JOIN',  # MySQL 不支持 LIMIT 1 子查询，引擎层面处理
        }.get(join_type, 'LEFT JOIN')

    @staticmethod
    def _date_to_ts(date_str: str, end_of_day: bool = False) -> int:
        """日期字符串 (yyyy-mm-dd) → Unix 毫秒时间戳"""
        from datetime import datetime
        try:
            if end_of_day:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                dt = dt.replace(hour=23, minute=59, second=59)
            else:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0

    @staticmethod
    def _compute_relative_ts_range(operator: str, n_str: str):
        """计算相对日期范围操作符的时间戳区间。

        Returns:
            (start_ts, end_ts) 毫秒时间戳对，或 None
        """
        from datetime import datetime, timedelta
        try:
            n = int(n_str)
        except (ValueError, TypeError):
            return None
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)

        def _ts(dt):
            return int(dt.timestamp() * 1000)

        op = operator.upper()
        if op == 'PAST_N_DAYS_EXCLUSIVE':
            start = today_start - timedelta(days=n)
            end = today_start - timedelta(seconds=1)
            return (_ts(start), _ts(end))
        if op == 'PAST_N_DAYS_INCLUSIVE':
            start = today_start - timedelta(days=n)
            return (_ts(start), _ts(today_end))
        if op == 'FUTURE_N_DAYS_EXCLUSIVE':
            end = today_start + timedelta(days=n)
            start = today_end + timedelta(seconds=1)
            return (_ts(start), _ts(end - timedelta(seconds=1)))
        if op == 'FUTURE_N_DAYS_INCLUSIVE':
            end = today_start + timedelta(days=n)
            return (_ts(today_start), _ts(end.replace(hour=23, minute=59, second=59)))

        if op == 'PAST_N_WEEKS_EXCLUSIVE':
            start = today_start - timedelta(weeks=n)
            end = today_start - timedelta(seconds=1)
            return (_ts(start), _ts(end))
        if op == 'PAST_N_WEEKS_INCLUSIVE':
            start = today_start - timedelta(weeks=n)
            return (_ts(start), _ts(today_end))
        if op == 'FUTURE_N_WEEKS_EXCLUSIVE':
            end = today_start + timedelta(weeks=n)
            start = today_end + timedelta(seconds=1)
            return (_ts(start), _ts(end - timedelta(seconds=1)))
        if op == 'FUTURE_N_WEEKS_INCLUSIVE':
            end = today_start + timedelta(weeks=n)
            return (_ts(today_start), _ts(end.replace(hour=23, minute=59, second=59)))

        if op == 'PAST_N_MONTHS_EXCLUSIVE':
            start_month = now.month - 1 - n
            start_year = now.year + start_month // 12
            start_month = start_month % 12 + 1
            start = datetime(start_year, start_month, 1)
            end = today_start - timedelta(seconds=1)
            return (_ts(start), _ts(end))
        if op == 'PAST_N_MONTHS_INCLUSIVE':
            start_month = now.month - 1 - n
            start_year = now.year + start_month // 12
            start_month = start_month % 12 + 1
            start = datetime(start_year, start_month, 1)
            return (_ts(start), _ts(today_end))
        if op == 'FUTURE_N_MONTHS_EXCLUSIVE':
            end_month = now.month - 1 + n
            end_year = now.year + end_month // 12
            end_month = end_month % 12 + 1
            if end_month == 12:
                end_dt = datetime(end_year + 1, 1, 1) - timedelta(seconds=1)
            else:
                end_dt = datetime(end_year, end_month + 1, 1) - timedelta(seconds=1)
            start = today_end + timedelta(seconds=1)
            return (_ts(start), _ts(end_dt))
        if op == 'FUTURE_N_MONTHS_INCLUSIVE':
            end_month = now.month - 1 + n
            end_year = now.year + end_month // 12
            end_month = end_month % 12 + 1
            if end_month == 12:
                end_dt = datetime(end_year + 1, 1, 1) - timedelta(seconds=1)
            else:
                end_dt = datetime(end_year, end_month + 1, 1) - timedelta(seconds=1)
            return (_ts(today_start), _ts(end_dt))

        if op == 'PAST_N_QUARTERS_INCLUSIVE':
            current_quarter = (now.month - 1) // 3
            total_months = current_quarter * 3 - n * 3
            start_year = now.year + total_months // 12
            start_month = total_months % 12 + 1
            start = datetime(start_year, start_month, 1)
            return (_ts(start), _ts(today_end))

        return None

    @staticmethod
    def _compute_relative_ts_bound(operator: str, n_str: str):
        """计算相对日期边界操作符的时间戳。

        Returns:
            毫秒时间戳，或 None
        """
        from datetime import datetime, timedelta
        try:
            n = int(n_str)
        except (ValueError, TypeError):
            return None
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        def _ts(dt):
            return int(dt.timestamp() * 1000)

        op = operator.upper()
        if op == 'N_DAYS_AGO':
            target = today_start - timedelta(days=n)
            return _ts(target.replace(hour=23, minute=59, second=59))
        if op == 'N_DAYS_LATER':
            return _ts(today_start + timedelta(days=n))
        if op == 'N_WEEKS_AGO':
            target = today_start - timedelta(weeks=n)
            return _ts(target.replace(hour=23, minute=59, second=59))
        if op == 'N_WEEKS_LATER':
            return _ts(today_start + timedelta(weeks=n))
        return None

    @staticmethod
    def _escape(value: str) -> str:
        """转义 SQL 字符串中的特殊字符"""
        return value.replace("\\", "\\\\").replace("'", "\\'")


class PreviewQueryBuilder:
    """生成预览查询 SQL"""

    @staticmethod
    def query(report: ReportDefinition,
              page: int = 1,
              page_size: int = 50,
              search: str = None) -> tuple[str, list]:
        """
        生成结果表的查询 SQL

        Returns:
            (sql, params)
        """
        table = report.result_table
        params = []
        where = ""
        if search:
            # 搜索所有可见列
            cols = [c for c in report.columns
                    if (isinstance(c, FieldColumn) and c.visible) or
                       (isinstance(c, dict) and c.get('visible', True))]
            if cols:
                conditions = []
                for col in cols:
                    name = col.display_name if isinstance(col, FieldColumn) else col.get('display_name', '')
                    if name:
                        conditions.append(f"`{name.replace('`', '``')} LIKE %s")
                        params.append(f"%{search}%")
                if conditions:
                    where = "WHERE " + " OR ".join(conditions)

        offset = (page - 1) * page_size
        sql = f"SELECT * FROM `{table}` {where} LIMIT {page_size} OFFSET {offset}"
        return sql, params

    @staticmethod
    def count(report: ReportDefinition, search: str = None) -> tuple[str, list]:
        """生成计数 SQL"""
        table = report.result_table
        params = []
        if search:
            cols = [c for c in report.columns
                    if (isinstance(c, FieldColumn) and c.visible) or
                       (isinstance(c, dict) and c.get('visible', True))]
            conditions = []
            for col in cols:
                name = col.display_name if isinstance(col, FieldColumn) else col.get('display_name', '')
                if name:
                    conditions.append(f"`{name.replace('`', '``')} LIKE %s")
                    params.append(f"%{search}%")
            where = "WHERE " + " OR ".join(conditions) if conditions else ""
        else:
            where = ""
        return f"SELECT COUNT(*) AS cnt FROM `{table}` {where}", params
