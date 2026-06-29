# -*- coding: utf-8 -*-
"""
chart_engine.py — 纯 Python ECharts 图表引擎
─────────────────────────────────────────────
不依赖 pyecharts，直接构建 ECharts options dict → JSON。
供 bitable.py（图表视图）和 dashboard.py（仪表盘）共用。
"""

import json
import logging
import re
from datetime import datetime, date, time as dtime
from decimal import Decimal

logger = logging.getLogger(__name__)

# 聚合函数 SQL 映射
_AGG_MAP = {
    'sum': 'SUM',
    'count': 'COUNT',
    'avg': 'AVG',
    'max': 'MAX',
    'min': 'MIN',
}

# 默认调色板（ECharts 5 默认配色）
_DEFAULT_COLORS = [
    '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
    '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#5ab1ef',
    '#d87c7c', '#8d98b3', '#e5cf0d', '#97b552', '#95706d',
    '#dc69aa', '#07a2a4', '#9a7fd1', '#588dd5', '#f5994e',
]


def _safe_col(field: str) -> str:
    """校验并转义列名。"""
    if not field or not re.match(r'^[a-zA-Z0-9_一-鿿]+$', field):
        raise ValueError(f"非法列名: {field!r}")
    return f'`{field}`'


def _json_safe(val):
    """值转 JSON 安全类型。"""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float, str)):
        return val
    if isinstance(val, (datetime, date, dtime)):
        return str(val)
    if isinstance(val, Decimal):
        try:
            return float(val)
        except (ValueError, OverflowError):
            return str(val)
    if hasattr(val, 'item'):
        try:
            return _json_safe(val.item())
        except Exception:
            return str(val)
    return str(val)


# ============================================================
# ChartEngine — 图表数据查询 + ECharts options 生成
# ============================================================

class ChartEngine:
    """图表引擎：从 MySQL 查询数据并生成 ECharts options。"""

    def __init__(self, db):
        """
        Args:
            db: ReportDatabase 实例（custom_report.py:27367）
        """
        self._db = db

    # ──── 数据查询 ────

    def query_data(self, table: str, x_field: str, y_fields: list,
                   group_field: str = None, agg: str = 'sum',
                   filters: list = None, limit: int = 1000) -> list:
        """从 MySQL 查询图表聚合数据。

        Args:
            table: MySQL 表名（如 '报表-销售订单'）
            x_field: X 轴字段（维度）
            y_fields: Y 轴字段列表（度量）
            group_field: 分组字段（可选，用于多系列）
            agg: 聚合函数 sum/count/avg/max/min
            filters: 过滤条件 [{'field': str, 'op': str, 'value': any}, ...]
            limit: 最大返回行数

        Returns:
            list[dict] — 查询结果
        """
        if not self._db or not self._db.available:
            return []

        safe_x = _safe_col(x_field)
        agg_fn = _AGG_MAP.get(agg, 'SUM')

        # SELECT 子句
        select_parts = [safe_x]
        if group_field:
            select_parts.append(_safe_col(group_field))
        for yf in y_fields:
            select_parts.append(f"{agg_fn}({_safe_col(yf)}) AS {_safe_col(yf)}")

        select_sql = ', '.join(select_parts)

        # WHERE 子句
        where_parts = []
        params = []
        for f in (filters or []):
            field = f.get('field', '')
            op = f.get('op', '')
            value = f.get('value')
            try:
                sf = _safe_col(field)
            except ValueError:
                continue
            if op == 'eq' and value is not None:
                where_parts.append(f"{sf} = %s")
                params.append(value)
            elif op == 'ne' and value is not None:
                where_parts.append(f"{sf} != %s")
                params.append(value)
            elif op == 'gt':
                where_parts.append(f"{sf} > %s")
                params.append(value)
            elif op == 'lt':
                where_parts.append(f"{sf} < %s")
                params.append(value)
            elif op == 'contains' and value:
                where_parts.append(f"{sf} LIKE %s")
                params.append(f"%{value}%")
            elif op == 'in' and value:
                placeholders = ', '.join(['%s'] * len(value))
                where_parts.append(f"{sf} IN ({placeholders})")
                params.extend(value)
            elif op == 'not_empty':
                where_parts.append(f"({sf} IS NOT NULL AND {sf} != '')")

        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # GROUP BY
        group_parts = [safe_x]
        if group_field:
            group_parts.append(_safe_col(group_field))
        group_sql = "GROUP BY " + ", ".join(group_parts)

        # ORDER BY + LIMIT
        order_sql = f"ORDER BY {safe_x}"
        limit_sql = f"LIMIT {int(limit)}"

        sql = f"SELECT {select_sql} FROM `{table}` {where_sql} {group_sql} {order_sql} {limit_sql}"

        try:
            rows = self._db.execute(sql, params)
            return [{k: _json_safe(v) for k, v in row.items()} for row in (rows or [])]
        except Exception as e:
            logger.error(f"[ChartEngine] Query failed: {e}\nSQL: {sql}")
            return []

    # ──── ECharts options 构建 ────

    def build_option(self, chart_type: str, data: list, x_field: str,
                     y_fields: list, group_field: str = None,
                     title: str = '') -> dict:
        """根据图表类型和数据生成 ECharts options dict。

        Args:
            chart_type: 图表类型 (bar/line/pie/scatter/area/stacked_bar/funnel/radar)
            data: 查询结果 list[dict]
            x_field: X 轴字段名
            y_fields: Y 轴字段名列表
            group_field: 分组字段名（可选）
            title: 图表标题

        Returns:
            dict — ECharts options，可直接 json.dumps 后传给 JS setOption()
        """
        dispatch = {
            'bar': self._build_bar,
            'line': self._build_line,
            'pie': self._build_pie,
            'scatter': self._build_scatter,
            'area': self._build_area,
            'stacked_bar': self._build_stacked_bar,
            'funnel': self._build_funnel,
            'radar': self._build_radar,
        }
        builder = dispatch.get(chart_type, self._build_bar)
        option = builder(data, x_field, y_fields, group_field)

        # 通用设置
        if title:
            option.setdefault('title', {})
            option['title']['text'] = title
            option['title']['left'] = 'center'

        option.setdefault('tooltip', {})
        option['tooltip']['trigger'] = 'item' if chart_type in ('pie', 'funnel') else 'axis'

        option.setdefault('legend', {})
        option['legend']['bottom'] = 0

        option['color'] = _DEFAULT_COLORS
        return option

    def to_json(self, option: dict) -> str:
        """序列化为 JSON 字符串。"""
        return json.dumps(option, ensure_ascii=False, default=str)

    # ──── 内部构建方法 ────

    def _extract_series_data(self, data, x_field, y_field, group_field=None):
        """提取系列数据。返回 (x_values, {series_name: [y_values]})。"""
        if group_field:
            # 按分组字段拆分系列
            x_set = []
            x_seen = set()
            groups = {}
            for row in data:
                x = row.get(x_field, '')
                g = str(row.get(group_field, ''))
                y = row.get(y_field, 0) or 0
                if x not in x_seen:
                    x_set.append(x)
                    x_seen.add(x)
                groups.setdefault(g, {})
                groups[g][x] = y
            # 对齐
            result = {}
            for g, vals in groups.items():
                result[g] = [vals.get(x, 0) for x in x_set]
            return x_set, result
        else:
            x_values = []
            y_values = []
            for row in data:
                x_values.append(row.get(x_field, ''))
                y_values.append(row.get(y_field, 0) or 0)
            return x_values, {'': y_values}

    def _base_axis_option(self, x_values, series_dict, chart_type='bar'):
        """构建基础的 xAxis + yAxis + series 结构。"""
        series = []
        for name, y_vals in series_dict.items():
            s = {
                'name': name or '数据',
                'type': chart_type,
                'data': y_vals,
            }
            if chart_type == 'bar':
                s['barMaxWidth'] = 40
            series.append(s)

        return {
            'xAxis': {
                'type': 'category',
                'data': x_values,
                'axisLabel': {'rotate': 30 if len(x_values) > 10 else 0},
            },
            'yAxis': {'type': 'value'},
            'series': series,
        }

    def _build_bar(self, data, x_field, y_fields, group_field):
        """柱状图。"""
        x_vals, series_dict = self._extract_series_data(
            data, x_field, y_fields[0] if y_fields else '', group_field)
        option = self._base_axis_option(x_vals, series_dict, 'bar')
        option.setdefault('tooltip', {})['trigger'] = 'axis'
        return option

    def _build_line(self, data, x_field, y_fields, group_field):
        """折线图。"""
        x_vals, series_dict = self._extract_series_data(
            data, x_field, y_fields[0] if y_fields else '', group_field)
        option = self._base_axis_option(x_vals, series_dict, 'line')
        for s in option['series']:
            s['smooth'] = True
        option.setdefault('tooltip', {})['trigger'] = 'axis'
        return option

    def _build_area(self, data, x_field, y_fields, group_field):
        """面积图。"""
        x_vals, series_dict = self._extract_series_data(
            data, x_field, y_fields[0] if y_fields else '', group_field)
        option = self._base_axis_option(x_vals, series_dict, 'line')
        for s in option['series']:
            s['smooth'] = True
            s['areaStyle'] = {'opacity': 0.3}
        option.setdefault('tooltip', {})['trigger'] = 'axis'
        return option

    def _build_pie(self, data, x_field, y_fields, group_field):
        """饼图。"""
        y_field = y_fields[0] if y_fields else ''
        pie_data = []
        for row in data:
            name = str(row.get(x_field, ''))
            value = row.get(y_field, 0) or 0
            pie_data.append({'name': name, 'value': value})
        return {
            'series': [{
                'type': 'pie',
                'radius': ['30%', '65%'],
                'data': pie_data,
                'label': {'show': True, 'formatter': '{b}: {d}%'},
                'emphasis': {
                    'itemStyle': {
                        'shadowBlur': 10,
                        'shadowColor': 'rgba(0,0,0,0.3)',
                    }
                },
            }],
        }

    def _build_scatter(self, data, x_field, y_fields, group_field):
        """散点图。"""
        x_vals, series_dict = self._extract_series_data(
            data, x_field, y_fields[0] if y_fields else '', group_field)
        # 散点图需要 [x, y] 配对
        series = []
        for name, y_vals in series_dict.items():
            points = [[i, v] for i, v in enumerate(y_vals)]
            series.append({
                'name': name or '数据',
                'type': 'scatter',
                'data': points,
                'symbolSize': 8,
            })
        return {
            'xAxis': {'type': 'category', 'data': x_vals},
            'yAxis': {'type': 'value'},
            'series': series,
        }

    def _build_stacked_bar(self, data, x_field, y_fields, group_field):
        """堆叠柱状图。"""
        x_vals, series_dict = self._extract_series_data(
            data, x_field, y_fields[0] if y_fields else '', group_field)
        option = self._base_axis_option(x_vals, series_dict, 'bar')
        for s in option['series']:
            s['stack'] = 'total'
        option.setdefault('tooltip', {})['trigger'] = 'axis'
        return option

    def _build_funnel(self, data, x_field, y_fields, group_field):
        """漏斗图。"""
        y_field = y_fields[0] if y_fields else ''
        funnel_data = []
        for row in data:
            funnel_data.append({
                'name': str(row.get(x_field, '')),
                'value': row.get(y_field, 0) or 0,
            })
        # 按值降序排列
        funnel_data.sort(key=lambda x: x['value'], reverse=True)
        return {
            'series': [{
                'type': 'funnel',
                'data': funnel_data,
                'label': {'show': True, 'position': 'inside'},
            }],
        }

    def _build_radar(self, data, x_field, y_fields, group_field):
        """雷达图。"""
        y_field = y_fields[0] if y_fields else ''
        # 构建 indicator（维度）和数据
        indicators = []
        values = []
        for row in data:
            name = str(row.get(x_field, ''))
            val = row.get(y_field, 0) or 0
            indicators.append({'name': name, 'max': 0})  # max 后续自动计算
            values.append(val)

        # 自动计算 max
        max_val = max(values) if values else 100
        for ind in indicators:
            ind['max'] = max_val * 1.2

        return {
            'radar': {
                'indicator': indicators,
                'shape': 'polygon',
            },
            'series': [{
                'type': 'radar',
                'data': [{'value': values, 'name': '数据'}],
            }],
        }
