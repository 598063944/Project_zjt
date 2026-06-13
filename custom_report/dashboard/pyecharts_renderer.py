"""
pyecharts 渲染引擎 — 完整实现
===============================

将 ChartWidget 数据模型 + 查询结果数据 → pyecharts 图表 → HTML 片段。
替代 html_template.py 中的 buildOption() 手写 JS (331-505 行)。

支持的图表类型 (28 种)：
    基础: bar, line, pie, scatter, area, table
    指标: card, gauge
    变体: combo, stacked_bar, stacked_area, pictorial_bar,
          effect_scatter, waterfall
    构成: funnel, treemap, sunburst
    分布: boxplot, heatmap, calendar, candlestick
    流向: sankey, graph, tree
    多维: radar, parallel, theme_river
    地理: map_china, map_scatter, map_lines
    其他: word_cloud

额外支持的 pyecharts 独有类型：
    liquid (水球图), polar (极坐标), chord (和弦图)

依赖: pyecharts >= 2.0
"""

# ============================================================================
# 导入
# ============================================================================

import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# ============================================================================
# 自动发现 pyecharts 源码路径
# ============================================================================

_pyecharts_loaded = False
_possible_pyecharts_dirs = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pyecharts-master'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'pyecharts-master'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pyecharts-master'),
]
for _d in _possible_pyecharts_dirs:
    _d = os.path.normpath(os.path.abspath(_d))
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)

def _ensure_pyecharts():
    """确保 pyecharts 可用；返回 True/False"""
    try:
        import pyecharts  # noqa: F401
        return True
    except ImportError:
        return False

# ============================================================================
# pyecharts 全局配置 (离线环境)
# ============================================================================

# 让 pyecharts 使用本地 ECharts 文件而非 CDN
# 在初始化时由外部调用 set_echarts_base_url() 配置

_echarts_base_dir: str = ""


def set_echarts_base_dir(dir_path: str):
    """
    设置 ECharts 资源的本地目录。

    Args:
        dir_path: echarts.min.js 等文件所在目录的绝对路径
                  通常是 custom_report/dashboard/echarts/
    """
    global _echarts_base_dir
    _echarts_base_dir = dir_path

    # 配置 pyecharts 使用本地文件
    if _ensure_pyecharts():
        from pyecharts.globals import CurrentConfig
        # 使用 file:// 协议指向本地文件
        CurrentConfig.ONLINE_HOST = f"file:///{dir_path.replace(os.sep, '/')}/"


# ============================================================================
# 工具函数
# ============================================================================

def _safe_float(v: Any, default: float = 0.0) -> float:
    """安全转换为 float"""
    try:
        return float(v) if v is not None else default
    except (ValueError, TypeError):
        return default


def _safe_str(v: Any, default: str = "") -> str:
    """安全转换为 str"""
    if v is None:
        return default
    return str(v)


def _extract_x(data: List[dict], x_field: str) -> list:
    """从数据列表提取 X 轴去重值（保持顺序）"""
    if not x_field:
        return []
    seen = set()
    result = []
    for row in data:
        v = _safe_str(row.get(x_field, ""))
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result


def _extract_y(data: List[dict], x_field: str, y_field: str) -> list:
    """按 X 轴顺序提取 Y 值"""
    if not y_field:
        return []
    x_values = _extract_x(data, x_field)
    mapping = {}
    for row in data:
        xv = _safe_str(row.get(x_field, ""))
        mapping[xv] = _safe_float(row.get(y_field, 0))
    return [mapping.get(x, 0) for x in x_values]


def _group_by_color(
    data: List[dict],
    x_field: str,
    y_field: str,
    color_field: str,
) -> Dict[str, list]:
    """按 color_field 分组，返回 {group_name: [y_value_per_x]}"""
    x_values = _extract_x(data, x_field)
    groups: Dict[str, Dict[str, float]] = {}

    for row in data:
        g = _safe_str(row.get(color_field, ""))
        xv = _safe_str(row.get(x_field, ""))
        yv = _safe_float(row.get(y_field, 0))
        if g not in groups:
            groups[g] = {x: 0.0 for x in x_values}
        groups[g][xv] = yv

    return {g: [vals[x] for x in x_values] for g, vals in groups.items()}


def _pie_pairs(data: List[dict], name_field: str, value_field: str) -> list:
    """生成饼图数据 [(name, value), ...]"""
    return [(_safe_str(r.get(name_field, "")), _safe_float(r.get(value_field, 0)))
            for r in data]


def _apply_filters(rows: list, filters: list) -> list:
    """对数据行应用筛选条件（与 dashboard_designer._apply_filters 同步）"""
    if not filters or not rows:
        return rows
    result = list(rows)
    for f in filters:
        field = (f.get('field') or '').strip()
        op = (f.get('op') or '').strip()
        value = (f.get('value') or '').strip()
        if not field:
            continue
        if op in ('为空', '不为空'):
            result = [r for r in result
                      if (not str(r.get(field, '')).strip()) == (op == '为空')]
        elif op == '属于' and value:
            vals = set(v.strip() for v in value.split(',') if v.strip())
            result = [r for r in result if str(r.get(field, '')).strip() in vals] if vals else result
        elif op == '不属于' and value:
            vals = set(v.strip() for v in value.split(',') if v.strip())
            result = [r for r in result if str(r.get(field, '')).strip() not in vals] if vals else result
        elif op == '包含' and value:
            result = [r for r in result if value.lower() in str(r.get(field, '')).lower()]
        elif op == '不包含' and value:
            result = [r for r in result if value.lower() not in str(r.get(field, '')).lower()]
        elif op in ('等于', '不等于', '大于', '小于', '大于等于', '小于等于') and value:
            # 尝试数值比较，失败则退化为字符串比较
            try:
                v_num = float(value)
                is_numeric = True
            except (ValueError, TypeError):
                v_num = 0
                is_numeric = False
            filtered = []
            for r in result:
                rv_str = str(r.get(field, ''))
                if is_numeric:
                    try:
                        rv = float(rv_str)
                    except (ValueError, TypeError):
                        rv = rv_str
                else:
                    rv = rv_str
                if op == '等于':
                    ok = (rv == v_num) if is_numeric else (rv_str == value)
                elif op == '不等于':
                    ok = (rv != v_num) if is_numeric else (rv_str != value)
                elif op in ('大于', '小于', '大于等于', '小于等于'):
                    if not is_numeric or not isinstance(rv, (int, float)):
                        continue
                    ok = {'大于': rv > v_num, '小于': rv < v_num,
                          '大于等于': rv >= v_num, '小于等于': rv <= v_num}[op]
                else:
                    ok = False
                if ok:
                    filtered.append(r)
            result = filtered
    return result


# ============================================================================
# 图表渲染器
# ============================================================================

class PyechartsRenderer:
    """
    将 ChartWidget + 查询数据 → pyecharts 图表 → HTML 片段。

    用法:
        from pyecharts_renderer import PyechartsRenderer

        html = PyechartsRenderer.render(chart_widget, data_rows)
        # → 可直接嵌入 <div class="card bd"> 的 HTML 字符串
    """

    # ================================================================
    # 主入口
    # ================================================================

    @classmethod
    def render(cls, chart: Any, data: List[dict]) -> str:
        """
        主入口：ChartWidget + 数据 → HTML 片段。
        """
        chart_type = (chart.chart_type or "bar").lower() if hasattr(chart, 'chart_type') else "bar"

        # 纯 HTML 类型
        if chart_type == "card":
            return cls._render_card(chart, data)
        if chart_type == "table":
            return cls._render_table(chart, data)

        # 应用筛选条件
        filters = getattr(chart, 'filters', None) or []
        if filters:
            data = _apply_filters(data, filters)

        # 空数据处理
        if not data:
            return cls._render_empty(chart)

        # 分发到具体渲染方法
        if not _ensure_pyecharts():
            return cls._render_empty(chart)

        handler = cls._DISPATCH.get(chart_type)
        if handler is None:
            return cls._render_unsupported(chart_type)

        try:
            c = handler(chart, data)
            if c is None:
                return cls._render_unsupported(chart_type)

            # 应用样式：色板
            cls._apply_colors(c, chart)
            # 应用样式：主题 / 背景
            style = cls._get_style(chart)
            bg = style.get('bg_color', '')
            if bg:
                c.options.update(backgroundColor=bg)
            theme = (style.get('theme') or 'white').lower()
            if theme == 'dark':
                c.set_dark_mode(dark_mode_bg_color=bg or '#100C2A')

            # 应用全局选项 (标题/图例/toolbox/Brush/DataZoom)
            cls._apply_global_opts(c, chart)

            # 生成 ECharts option — 直接嵌入为 JS 对象字面量，避免 JSON.parse 环节
            opt_json = c.dump_options_with_quotes()

            # 将 option JSON 附着到 chart_widget 对象上 (副作用)
            if hasattr(chart, '__dict__'):
                object.__setattr__(chart, '_echarts_option', opt_json)

            return c.render_embed()
        except Exception as e:
            return cls._render_error(chart, str(e))

    # ================================================================
    # 图表类型分发表
    # ================================================================

    _DISPATCH: Dict[str, Any] = {}  # 在类定义完成后填充

    # ================================================================
    # 空数据 / 错误占位
    # ================================================================

    @classmethod
    def _render_empty(cls, chart: Any) -> str:
        title = getattr(chart, 'title', '') or '图表'
        return (
            f'<div style="color:#999;padding:20px;text-align:center;">'
            f'📭 暂无数据<br><small>{title}</small></div>'
        )

    @classmethod
    def _render_unsupported(cls, chart_type: str) -> str:
        return (
            f'<div style="color:#FF4D4F;padding:20px;text-align:center;">'
            f'❌ 不支持的图表类型: {chart_type}</div>'
        )

    @classmethod
    def _render_error(cls, chart: Any, error_msg: str) -> str:
        title = getattr(chart, 'title', '') or '图表'
        return (
            f'<div style="color:#FF4D4F;padding:16px;text-align:center;font-size:13px;">'
            f'❌ {title} 渲染失败<br><small>{error_msg}</small></div>'
        )

    # ================================================================
    # 纯 HTML 渲染 (card / table)
    # ================================================================

    @classmethod
    def _render_card(cls, chart: Any, data: List[dict]) -> str:
        """指标卡 — 纯 HTML/CSS"""
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        title = getattr(chart, 'title', '') or ''
        if data and y_field:
            v = data[0].get(y_field, 0)
        else:
            v = 0
        if isinstance(v, (int, float)):
            formatted = f"{v:,.0f}"
        else:
            formatted = str(v)
        return (
            f'<div class="kpi">'
            f'<div class="v">{formatted}</div>'
            f'<div class="l">{title}</div>'
            f'</div>'
        )

    @classmethod
    def _render_table(cls, chart: Any, data: List[dict]) -> str:
        """表格 — y_fields 指定显示列，为空则显示全部列"""
        if not data:
            return '<div style="padding:20px;color:#999;text-align:center;">无数据</div>'
        y_fields = getattr(chart, 'y_fields', []) or []
        if y_fields:
            cols = [f for f in y_fields if f in data[0]]
            if not cols:
                cols = list(data[0].keys())
        else:
            cols = list(data[0].keys())
        parts = ['<div class="tbl"><table><thead><tr>']
        for col in cols:
            parts.append(f'<th>{col}</th>')
        parts.append('</tr></thead><tbody>')
        for row in data:
            parts.append('<tr>')
            for col in cols:
                parts.append(f'<td>{row.get(col, "")}</td>')
            parts.append('</tr>')
        parts.append('</tbody></table></div>')
        return ''.join(parts)

    # ================================================================
    # 基础图表
    # ================================================================

    @classmethod
    def _bar(cls, chart: Any, data: List[dict]):
        """柱状图"""
        from pyecharts.charts import Bar
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        x_data = _extract_x(data, x_field)
        c = Bar()
        c.add_xaxis(x_data)

        if color_field:
            groups = _group_by_color(data, x_field, y_field, color_field)
            for g_name, g_vals in groups.items():
                c.add_yaxis(series_name=g_name, y_axis=g_vals)
        else:
            y_data = _extract_y(data, x_field, y_field)
            c.add_yaxis(series_name=getattr(chart, 'title', '') or y_field, y_axis=y_data)

        series_opts = cls._make_series_opts(chart, 'bar')
        c.set_series_opts(**series_opts)
        return c

    @classmethod
    def _stacked_bar(cls, chart: Any, data: List[dict]):
        """堆叠柱状图"""
        from pyecharts.charts import Bar
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        x_data = _extract_x(data, x_field)
        c = Bar()
        c.add_xaxis(x_data)

        if color_field:
            groups = _group_by_color(data, x_field, y_field, color_field)
            for g_name, g_vals in groups.items():
                c.add_yaxis(series_name=g_name, y_axis=g_vals, stack="total")
        else:
            y_data = _extract_y(data, x_field, y_field)
            c.add_yaxis(
                series_name=getattr(chart, 'title', '') or y_field,
                y_axis=y_data, stack="total",
            )

        series_opts = cls._make_series_opts(chart, 'stacked_bar')
        c.set_series_opts(**series_opts)
        return c

    @classmethod
    def _line(cls, chart: Any, data: List[dict]):
        """折线图"""
        from pyecharts.charts import Line
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        x_data = _extract_x(data, x_field)
        c = Line()
        c.add_xaxis(x_data)

        if color_field:
            groups = _group_by_color(data, x_field, y_field, color_field)
            for g_name, g_vals in groups.items():
                c.add_yaxis(
                    series_name=g_name, y_axis=g_vals,
                    is_smooth=True, is_symbol_show=True,
                )
        else:
            y_data = _extract_y(data, x_field, y_field)
            c.add_yaxis(
                series_name=getattr(chart, 'title', '') or y_field,
                y_axis=y_data, is_smooth=True, is_symbol_show=True,
            )

        c.set_series_opts(**cls._make_series_opts(chart, 'line'))
        return c

    @classmethod
    def _area(cls, chart: Any, data: List[dict]):
        """面积图"""
        from pyecharts.charts import Line
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        x_data = _extract_x(data, x_field)
        c = Line()
        c.add_xaxis(x_data)

        area_opts = opts.AreaStyleOpts(opacity=0.5)
        if color_field:
            groups = _group_by_color(data, x_field, y_field, color_field)
            for g_name, g_vals in groups.items():
                c.add_yaxis(
                    series_name=g_name, y_axis=g_vals,
                    areastyle_opts=area_opts, is_smooth=True,
                )
        else:
            y_data = _extract_y(data, x_field, y_field)
            c.add_yaxis(
                series_name=getattr(chart, 'title', '') or y_field,
                y_axis=y_data, areastyle_opts=area_opts, is_smooth=True,
            )
        return c

    @classmethod
    def _stacked_area(cls, chart: Any, data: List[dict]):
        """堆叠面积图"""
        from pyecharts.charts import Line
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        x_data = _extract_x(data, x_field)
        c = Line()
        c.add_xaxis(x_data)

        area_opts = opts.AreaStyleOpts(opacity=0.5)
        if color_field:
            groups = _group_by_color(data, x_field, y_field, color_field)
            for g_name, g_vals in groups.items():
                c.add_yaxis(
                    series_name=g_name, y_axis=g_vals,
                    areastyle_opts=area_opts, stack="total", is_smooth=True,
                )
        else:
            y_data = _extract_y(data, x_field, y_field)
            c.add_yaxis(
                series_name=getattr(chart, 'title', '') or y_field,
                y_axis=y_data, areastyle_opts=area_opts, stack="total", is_smooth=True,
            )
        return c

    @classmethod
    def _pie(cls, chart: Any, data: List[dict]):
        """饼图"""
        from pyecharts.charts import Pie
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        c = Pie()
        pairs = _pie_pairs(data, x_field, y_field)
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data_pair=pairs,
            radius=["35%", "65%"],
        )
        c.set_series_opts(**cls._make_series_opts(chart, 'pie'))
        return c

    @classmethod
    def _scatter(cls, chart: Any, data: List[dict]):
        """散点图"""
        from pyecharts.charts import Scatter
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        x_vals = [_safe_float(r.get(x_field, 0)) for r in data]
        y_vals = [_safe_float(r.get(y_field, 0)) for r in data]

        c = Scatter()
        c.add_xaxis(x_vals)
        c.add_yaxis(
            series_name=getattr(chart, 'title', '') or y_field,
            y_axis=y_vals,
            symbol_size=10,
            label_opts=opts.LabelOpts(is_show=False),
        )
        return c

    # ================================================================
    # 指标类
    # ================================================================

    @classmethod
    def _gauge(cls, chart: Any, data: List[dict]):
        """仪表盘"""
        from pyecharts.charts import Gauge
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        title = getattr(chart, 'title', '') or y_field
        v = _safe_float(data[0].get(y_field, 0)) if data else 0

        c = Gauge()
        c.add(
            series_name=title,
            data_pair=[(title, v)],
            max_=max(v * 1.5, 100),
        )
        return c

    # ================================================================
    # 组合 / 变体
    # ================================================================

    @classmethod
    def _combo(cls, chart: Any, data: List[dict]):
        """组合图 (柱状 + 折线)"""
        from pyecharts.charts import Bar, Line
        from pyecharts.charts.composite_charts import Grid
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_fields = chart.y_fields if hasattr(chart, 'y_fields') else []
        title = getattr(chart, 'title', '')

        x_data = _extract_x(data, x_field)
        bar = Bar()
        bar.add_xaxis(x_data)

        line = Line()
        line.add_xaxis(x_data)

        # 第一个度量用柱状，第二个用折线
        if len(y_fields) >= 1:
            y1 = y_fields[0]
            bar.add_yaxis(series_name=y1, y_axis=_extract_y(data, x_field, y1))
        if len(y_fields) >= 2:
            y2 = y_fields[1]
            line.add_yaxis(
                series_name=y2, y_axis=_extract_y(data, x_field, y2),
                is_smooth=True,
            )

        bar.set_global_opts(
            title_opts=opts.TitleOpts(title=title),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
        )

        c = Grid()
        c.add(bar, grid_opts=opts.GridOpts(pos_left="10%", pos_right="10%"))
        c.add(line, grid_opts=opts.GridOpts(pos_left="10%", pos_right="10%"))
        return c

    @classmethod
    def _pictorial_bar(cls, chart: Any, data: List[dict]):
        """象形柱状图"""
        from pyecharts.charts import PictorialBar
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        x_data = _extract_x(data, x_field)
        y_data = _extract_y(data, x_field, y_field)

        c = PictorialBar()
        c.add_xaxis(x_data)
        c.add_yaxis(
            series_name=getattr(chart, 'title', '') or y_field,
            y_axis=y_data,
            symbol="roundRect",
            symbol_size=[20, 10],
        )
        c.set_series_opts(**cls._make_series_opts(chart, 'pictorial_bar'))
        return c

    @classmethod
    def _effect_scatter(cls, chart: Any, data: List[dict]):
        """涟漪散点图"""
        from pyecharts.charts import EffectScatter
        from pyecharts import options as opts

        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        x_vals = [_safe_float(r.get(x_field, 0)) for r in data]
        y_vals = [_safe_float(r.get(y_field, 0)) for r in data]

        c = EffectScatter()
        c.add_xaxis(x_vals)
        c.add_yaxis(
            series_name=getattr(chart, 'title', '') or y_field,
            y_axis=y_vals,
            effect_opts=opts.EffectOpts(scale=3.5, brush_type="stroke"),
            label_opts=opts.LabelOpts(is_show=False),
        )
        return c

    @classmethod
    def _waterfall(cls, chart: Any, data: List[dict]):
        """瀑布图 (通过堆叠柱状 + 透明底柱实现)"""
        from pyecharts.charts import Bar
        from pyecharts import options as opts

        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        title = getattr(chart, 'title', '')

        vals = [_safe_float(r.get(y_field, 0)) for r in data]
        x_data = [_safe_str(r.get(x_field, "")) for r in data]

        # 瀑布图逻辑：计算累计值
        base = []
        increase = []
        decrease = []
        running = 0.0
        for v in vals:
            if v >= 0:
                base.append(running)
                increase.append(v)
                decrease.append("-")
            else:
                base.append(running + v)
                increase.append("-")
                decrease.append(-v)
            running += v if v else 0

        c = Bar()
        c.add_xaxis(x_data)
        c.add_yaxis("增加", increase, stack="waterfall",
                     itemstyle_opts=opts.ItemStyleOpts(color="#4CAF50"))
        c.add_yaxis("减少", decrease, stack="waterfall",
                     itemstyle_opts=opts.ItemStyleOpts(color="#F44336"))
        c.add_yaxis("base", base, stack="waterfall",
                     itemstyle_opts=opts.ItemStyleOpts(color="transparent"),
                     label_opts=opts.LabelOpts(is_show=False))
        c.set_series_opts(**cls._make_series_opts(chart, 'waterfall'))
        return c

    # ================================================================
    # 比例 / 构成
    # ================================================================

    @classmethod
    def _funnel(cls, chart: Any, data: List[dict]):
        """漏斗图"""
        from pyecharts.charts import Funnel
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        pairs = _pie_pairs(data, x_field, y_field)
        pairs.sort(key=lambda x: x[1], reverse=True)

        c = Funnel()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data_pair=pairs,
            label_opts=opts.LabelOpts(position="inside", formatter="{b}: {c}"),
        )
        return c

    @classmethod
    def _treemap(cls, chart: Any, data: List[dict]):
        """树图"""
        from pyecharts.charts import TreeMap
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        tm_data = [
            {"name": _safe_str(r.get(x_field, "")), "value": _safe_float(r.get(y_field, 0))}
            for r in data
        ]

        c = TreeMap()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data=tm_data,
            label_opts=opts.LabelOpts(position="inside"),
        )
        return c

    @classmethod
    def _sunburst(cls, chart: Any, data: List[dict]):
        """旭日图"""
        from pyecharts.charts import Sunburst
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        pairs = _pie_pairs(data, x_field, y_field)

        c = Sunburst()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data_pair=pairs,
            radius=["15%", "80%"],
            label_opts=opts.LabelOpts(formatter="{b}"),
        )
        return c

    # ================================================================
    # 分布 / 统计
    # ================================================================

    @classmethod
    def _boxplot(cls, chart: Any, data: List[dict]):
        """箱线图"""
        from pyecharts.charts import Boxplot
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        if color_field:
            groups = _group_by_color(data, x_field, y_field, color_field)
            x_data = list(groups.keys())
            c = Boxplot()
            c.add_xaxis(x_data)
            for g_name, g_vals in groups.items():
                c.add_yaxis(series_name=g_name, y_axis=c.prepare_data([g_vals]))
        else:
            x_data = _extract_x(data, x_field)
            y_data = _extract_y(data, x_field, y_field)
            c = Boxplot()
            c.add_xaxis(x_data)
            c.add_yaxis(
                series_name=getattr(chart, 'title', '') or y_field,
                y_axis=c.prepare_data([y_data]),
            )
        return c

    @classmethod
    def _heatmap(cls, chart: Any, data: List[dict]):
        """热力图"""
        from pyecharts.charts import HeatMap
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '') or y_field

        x_cats = _extract_x(data, x_field)
        y_cats = _extract_x(data, color_field)

        hm_data = []
        for r in data:
            xv = _safe_str(r.get(x_field, ""))
            yv = _safe_str(r.get(color_field, ""))
            if xv in x_cats and yv in y_cats:
                hm_data.append([
                    x_cats.index(xv),
                    y_cats.index(yv),
                    _safe_float(r.get(y_field, 0)),
                ])

        max_v = max((d[2] for d in hm_data), default=100)

        c = HeatMap()
        c.add_xaxis(x_cats)
        c.add_yaxis(
            series_name=getattr(chart, 'title', '') or y_field,
            yaxis_data=y_cats,
            value=hm_data,
            label_opts=opts.LabelOpts(is_show=True, position="inside"),
        )
        c.set_global_opts(
            visualmap_opts=opts.VisualMapOpts(
                min_=0, max_=max_v,
                orient="horizontal", pos_left="center", pos_bottom="0",
            )
        )
        return c

    @classmethod
    def _calendar(cls, chart: Any, data: List[dict]):
        """日历热力图"""
        from pyecharts.charts import Calendar
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        cal_data = []
        for r in data:
            date_str = _safe_str(r.get(x_field, ""))
            val = _safe_float(r.get(y_field, 0))
            if date_str and val:
                cal_data.append([date_str, val])

        if not cal_data:
            return None

        max_v = max((d[1] for d in cal_data), default=100)
        # 推断年份
        first_date = cal_data[0][0] if cal_data else "2024"
        year = first_date[:4] if len(first_date) >= 4 else "2024"

        c = Calendar()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data=cal_data,
            calendar_opts=opts.CalendarOpts(
                range_=year,
                cell_size=["auto", 20],
            ),
        )
        c.set_global_opts(
            visualmap_opts=opts.VisualMapOpts(
                min_=0, max_=max_v,
                orient="horizontal", pos_left="center", pos_bottom="0",
            ),
        )
        return c

    @classmethod
    def _candlestick(cls, chart: Any, data: List[dict]):
        """K 线图"""
        from pyecharts.charts import Kline
        x_field = getattr(chart, 'x_field', '')
        x_data = [_safe_str(r.get(x_field, "")) for r in data]

        c = Kline()
        c.add_xaxis(x_data)

        # 数据格式: [open, close, low, high]
        ohlc = []
        for r in data:
            ohlc.append([
                _safe_float(r.get('open', 0)),
                _safe_float(r.get('close', 0)),
                _safe_float(r.get('low', 0)),
                _safe_float(r.get('high', 0)),
            ])

        c.add_yaxis(
            series_name=getattr(chart, 'title', '') or "K线",
            y_axis=ohlc,
        )
        return c

    # ================================================================
    # 关系 / 流向
    # ================================================================

    @classmethod
    def _sankey(cls, chart: Any, data: List[dict]):
        """桑基图 — 自动去重 & 过滤自环避免 DAG 循环错误"""
        from pyecharts.charts import Sankey
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        # 收集节点 & 去重链接
        nodes_set = set()
        seen_links = set()
        links_list = []
        self_loops = 0
        for r in data:
            src = _safe_str(r.get(x_field, ""))
            tgt = _safe_str(r.get(color_field, ""))
            val = _safe_float(r.get(y_field, 0))
            if not src or not tgt:
                continue
            # 过滤自环 (source == target → DAG 循环)
            if src == tgt:
                self_loops += 1
                nodes_set.add(src)
                continue
            # 聚合重复链接
            link_key = (src, tgt)
            if link_key in seen_links:
                # 已存在，累加值
                for lk in links_list:
                    if lk["source"] == src and lk["target"] == tgt:
                        lk["value"] += val
                        break
            else:
                seen_links.add(link_key)
                nodes_set.add(src)
                nodes_set.add(tgt)
                links_list.append({"source": src, "target": tgt, "value": val})

        if not links_list:
            return None  # 无有效链接

        if self_loops > 0:
            import sys
            main_mod = sys.modules.get('__main__')
            if main_mod:
                mf = getattr(main_mod, 'MainFrame', None)
                if mf and hasattr(mf, 'instance') and mf.instance:
                    mf.instance.append_output(
                        f"[BI 报表] Sankey: 已过滤 {self_loops} 条自环链接"
                    )

        nodes_list = [{"name": n} for n in nodes_set]

        c = Sankey()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            nodes=nodes_list,
            links=links_list,
            linestyle_opt=opts.LineStyleOpts(opacity=0.2, curve=0.5),
            label_opts=opts.LabelOpts(position="right"),
        )
        return c

    @classmethod
    def _graph(cls, chart: Any, data: List[dict]):
        """关系图"""
        from pyecharts.charts import Graph
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        nodes_set: Dict[str, int] = {}
        categories_set = set()
        links_list = []
        for r in data:
            src = _safe_str(r.get(x_field, ""))
            tgt = _safe_str(r.get(color_field, ""))
            val = _safe_float(r.get(y_field, 0))
            cat = _safe_str(r.get(color_field, ""))
            if src:
                if src not in nodes_set:
                    nodes_set[src] = val
                else:
                    nodes_set[src] += val
            if tgt and tgt not in nodes_set:
                nodes_set[tgt] = 0
            if src and tgt:
                links_list.append({"source": src, "target": tgt})
            if cat:
                categories_set.add(cat)

        categories = [opts.GraphCategory(name=n) for n in categories_set] if categories_set else None
        nodes_list = [
            opts.GraphNode(name=n, symbol_size=max(5, min(50, v * 2 or 10)))
            for n, v in nodes_set.items()
        ]

        c = Graph()
        c.add(
            series_name=getattr(chart, 'title', '') or x_field,
            nodes=nodes_list,
            links=links_list,
            categories=categories,
            layout="force",
            is_roam=True,
            is_draggable=True,
            force_opts=opts.GraphForceOpts(repulsion=200, edge_length=100),
        )
        return c

    @classmethod
    def _tree(cls, chart: Any, data: List[dict]):
        """树形图"""
        from pyecharts.charts import Tree
        x_field = getattr(chart, 'x_field', '')
        color_field = getattr(chart, 'color_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        # 从平铺数据构建树
        # 期望数据有 id 和 parent_id (通过 color_field 指定)
        parent_field = color_field or "pid"
        tree_data = cls._build_tree(data, x_field, parent_field, y_field)

        c = Tree()
        c.add(
            series_name=getattr(chart, 'title', '') or x_field,
            data=[tree_data],
            orient="TB",
            is_roam=True,
            is_expand_and_collapse=True,
            initial_tree_depth=2,
        )
        return c

    @staticmethod
    def _build_tree(
        items: List[dict],
        name_field: str,
        parent_field: str,
        value_field: str,
    ) -> dict:
        """从平铺数据构建嵌套树结构"""
        nodes: Dict[str, dict] = {}
        children_map: Dict[str, list] = {}
        roots = []

        for r in items:
            name = _safe_str(r.get(name_field, ""))
            pid = _safe_str(r.get(parent_field, ""))
            val = _safe_float(r.get(value_field, 0))
            nodes[name] = {"name": name, "value": val, "children": []}
            children_map.setdefault(pid, []).append(name)
            if not pid:
                roots.append(name)

        # 如果没有指定 parent，把第一个当根
        if not roots and nodes:
            roots = [list(nodes.keys())[0]]

        # 构建树
        for pid, child_names in children_map.items():
            parent_node = nodes.get(pid)
            if parent_node and pid != child_names:
                for cn in child_names:
                    if cn in nodes and cn != pid:
                        parent_node["children"].append(nodes[cn])

        # 返回根节点
        if roots and roots[0] in nodes:
            root = nodes[roots[0]]
            # 如果没有 children，把所有其他节点都挂上去
            if not root["children"] and len(nodes) > 1:
                root["children"] = [v for k, v in nodes.items() if k != roots[0]]
            return root

        # 兜底
        return {"name": "root", "children": list(nodes.values())}

    # ================================================================
    # 多维分析
    # ================================================================

    @classmethod
    def _radar(cls, chart: Any, data: List[dict]):
        """雷达图"""
        from pyecharts.charts import Radar
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        values = [_safe_float(r.get(y_field, 0)) for r in data]
        max_v = max(values) * 1.2 if values else 100

        schema = [
            opts.RadarIndicatorItem(name=_safe_str(r.get(x_field, "")), max_=max_v)
            for r in data
        ]

        c = Radar()
        c.add_schema(schema=schema)
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data=[values],
            areastyle_opts=opts.AreaStyleOpts(opacity=0.3),
            linestyle_opts=opts.LineStyleOpts(width=2),
        )
        return c

    @classmethod
    def _parallel(cls, chart: Any, data: List[dict]):
        """平行坐标图"""
        from pyecharts.charts import Parallel
        from pyecharts import options as opts

        # 使用所有可用数值字段
        y_fields = chart.y_fields if hasattr(chart, 'y_fields') else []
        if not y_fields and data:
            # 自动选择数值型字段
            y_fields = [k for k, v in data[0].items()
                        if isinstance(v, (int, float))][:10]

        dims = y_fields[:10]  # 最多 10 个维度
        if not dims:
            return None

        parallel_axis = []
        for d in dims:
            vals = [_safe_float(r.get(d, 0)) for r in data]
            parallel_axis.append(
                opts.ParallelAxisOpts(dim=dim_ix, name=d, max_=max(vals) * 1.2)
                for dim_ix in range(len(dims))
            )
            break

        # 重新构建
        parallel_axis = []
        for i, d in enumerate(dims):
            vals = [_safe_float(r.get(d, 0)) for r in data]
            parallel_axis.append(
                opts.ParallelAxisOpts(dim=i, name=d, max_=max(vals) * 1.2)
            )

        p_data = []
        for r in data:
            p_data.append([_safe_float(r.get(d, 0)) for d in dims])

        c = Parallel()
        c.add_schema(schema=parallel_axis)
        c.add(
            series_name=getattr(chart, 'title', '') or "平行坐标",
            data=p_data,
        )
        return c

    @classmethod
    def _theme_river(cls, chart: Any, data: List[dict]):
        """主题河流图"""
        from pyecharts.charts import ThemeRiver
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '') or x_field

        # 主题河流数据格式: [[date, value, series_name], ...]
        river_data = []
        series_names = []
        for r in data:
            date_val = _safe_str(r.get(x_field, ""))
            val = _safe_float(r.get(y_field, 0))
            name = _safe_str(r.get(color_field, ""))
            river_data.append([date_val, val, name])
            if name not in series_names:
                series_names.append(name)

        c = ThemeRiver()
        c.add(
            series_name=series_names,
            data=river_data,
        )
        return c

    # ================================================================
    # 地理
    # ================================================================

    @classmethod
    def _map_china(cls, chart: Any, data: List[dict]):
        """中国地图"""
        from pyecharts.charts import Map
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        map_data = [
            (_safe_str(r.get(x_field, "")), _safe_float(r.get(y_field, 0)))
            for r in data
        ]

        max_v = max((v for _, v in map_data), default=100)

        c = Map()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data_pair=map_data,
            maptype="china",
            is_roam=True,
            label_opts=opts.LabelOpts(is_show=True, font_size=8),
        )
        c.set_global_opts(
            visualmap_opts=opts.VisualMapOpts(
                min_=0, max_=max_v, is_calculable=True,
                range_text=["高", "低"], pos_left="left", pos_bottom="15",
            ),
        )
        return c

    @classmethod
    def _map_scatter(cls, chart: Any, data: List[dict]):
        """地图散点图 (使用 Geo 坐标系)"""
        from pyecharts.charts import Geo
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        geo = Geo()
        geo.add_schema(
            maptype="china",
            is_roam=True,
            itemstyle_opts=opts.ItemStyleOpts(color="#E6E6E6", border_color="#111"),
        )

        if color_field:
            groups = _group_by_color(data, x_field, y_field, color_field)
            for g_name, g_vals in groups.items():
                pairs = list(zip(_extract_x(data, x_field), g_vals))
                geo.add(
                    series_name=g_name,
                    data_pair=pairs,
                    type_="scatter",
                    symbol_size=12,
                )
        else:
            pairs = _pie_pairs(data, x_field, y_field)
            geo.add(
                series_name=getattr(chart, 'title', '') or y_field,
                data_pair=pairs,
                type_="scatter",
                symbol_size=12,
            )

        geo.set_series_opts(label_opts=opts.LabelOpts(is_show=False))
        return geo

    @classmethod
    def _map_lines(cls, chart: Any, data: List[dict]):
        """地图飞线图"""
        from pyecharts.charts import Geo
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        # 飞线需要 from → to 格式
        # x_field = 起点, color_field = 终点, y_field = 值
        geo = Geo()
        geo.add_schema(
            maptype="china",
            is_roam=True,
            itemstyle_opts=opts.ItemStyleOpts(color="#323C48", border_color="#111"),
        )

        # 先加散点标记起点
        src_pairs = [(_safe_str(r.get(x_field, "")),
                       _safe_float(r.get(y_field, 0))) for r in data]
        geo.add(
            series_name="起点",
            data_pair=src_pairs,
            type_="effectScatter",
            symbol_size=8,
        )

        # 再加飞线
        if color_field:
            lines_pairs = []
            for r in data:
                frm = _safe_str(r.get(x_field, ""))
                to = _safe_str(r.get(color_field, ""))
                lines_pairs.append((frm, to))
            geo.add(
                series_name="流向",
                data_pair=lines_pairs,
                type_="lines",
                effect_opts=opts.EffectOpts(
                    symbol="arrow", symbol_size=6, color="blue",
                ),
                linestyle_opts=opts.LineStyleOpts(curve=0.2),
            )

        return geo

    # ================================================================
    # 其他
    # ================================================================

    @classmethod
    def _word_cloud(cls, chart: Any, data: List[dict]):
        """词云"""
        from pyecharts.charts import WordCloud
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        pairs = _pie_pairs(data, x_field, y_field)
        c = WordCloud()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data_pair=pairs,
            shape="circle",
            word_size_range=[12, 60],
        )
        return c

    # ================================================================
    # pyecharts 独有增强图表
    # ================================================================

    @classmethod
    def _liquid(cls, chart: Any, data: List[dict]):
        """水球图 (pyecharts 独有)"""
        from pyecharts.charts import Liquid
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        v = _safe_float(data[0].get(y_field, 0)) if data else 0

        # 归一化到 0-1 (如果是百分比形式)
        if v > 1:
            v_norm = v / max(v * 1.1, 100)
        else:
            v_norm = v

        c = Liquid()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data=[v_norm, v_norm * 0.8, v_norm * 0.6],
            shape="circle",
        )
        return c

    @classmethod
    def _polar(cls, chart: Any, data: List[dict]):
        """极坐标图"""
        from pyecharts.charts import Polar
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""

        angle_data = [_safe_str(r.get(x_field, "")) for r in data]
        radius_data = [_safe_float(r.get(y_field, 0)) for r in data]

        c = Polar()
        c.add_schema(
            angleaxis_opts=opts.AngleAxisOpts(data=angle_data, type_="category"),
            radiusaxis_opts=opts.RadiusAxisOpts(),
        )
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data=radius_data,
            type_="bar",  # 默认柱状，也可 line, scatter
            coordinate_system="polar",
        )
        return c

    @classmethod
    def _chord(cls, chart: Any, data: List[dict]):
        """和弦图 (pyecharts 独有)"""
        from pyecharts.charts import Chord
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        # 收集节点和链接
        nodes_set: Dict[str, int] = {}
        links_list = []
        for r in data:
            src = _safe_str(r.get(x_field, ""))
            tgt = _safe_str(r.get(color_field, ""))
            val = max(0, int(_safe_float(r.get(y_field, 0))))
            if src:
                nodes_set[src] = nodes_set.get(src, 0) + val
            if tgt:
                nodes_set[tgt] = nodes_set.get(tgt, 0) + val
            if src and tgt:
                links_list.append(
                    opts.ChordLink(source=src, target=tgt, value=val)
                )

        nodes_list = [opts.ChordData(name=n) for n in nodes_set]

        c = Chord()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            nodes=nodes_list,
            links=links_list,
        )
        return c

    # ================================================================
    # 3D 图表 (需要 echarts-gl)
    # ================================================================

    @classmethod
    def _bar3d(cls, chart: Any, data: List[dict]):
        """3D 柱状图"""
        from pyecharts.charts import Bar3D
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        x_cats = _extract_x(data, x_field)
        y_cats = _extract_x(data, color_field) if color_field else ["值"]

        bar3d_data = []
        for r in data:
            xv = _safe_str(r.get(x_field, ""))
            yv = _safe_str(r.get(color_field, "")) if color_field else "值"
            v = _safe_float(r.get(y_field, 0))
            if xv in x_cats:
                bar3d_data.append([x_cats.index(xv),
                                   y_cats.index(yv) if y_cats else 0, v])

        c = Bar3D()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data=bar3d_data,
            xaxis3d_opts=opts.Axis3DOpts(type_="category", data=x_cats),
            yaxis3d_opts=opts.Axis3DOpts(type_="category", data=y_cats),
            zaxis3d_opts=opts.Axis3DOpts(type_="value"),
        )
        c.set_global_opts(
            visualmap_opts=opts.VisualMapOpts(
                max_=max((d[2] for d in bar3d_data), default=100),
            ),
        )
        return c

    @classmethod
    def _scatter3d(cls, chart: Any, data: List[dict]):
        """3D 散点图"""
        from pyecharts.charts import Scatter3D
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')
        size_field = getattr(chart, 'size_field', '')

        scatter3d_data = []
        for r in data:
            scatter3d_data.append([
                _safe_float(r.get(x_field, 0)),
                _safe_float(r.get(y_field, 0)),
                _safe_float(r.get(color_field, 0) if color_field else 0),
            ])

        c = Scatter3D()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data=scatter3d_data,
            xaxis3d_opts=opts.Axis3DOpts(type_="value"),
            yaxis3d_opts=opts.Axis3DOpts(type_="value"),
            zaxis3d_opts=opts.Axis3DOpts(type_="value"),
        )
        return c

    @classmethod
    def _surface3d(cls, chart: Any, data: List[dict]):
        """3D 曲面图"""
        from pyecharts.charts import Surface3D
        from pyecharts import options as opts
        x_field = getattr(chart, 'x_field', '')
        y_field = (chart.y_fields or [""])[0] if hasattr(chart, 'y_fields') else ""
        color_field = getattr(chart, 'color_field', '')

        surf_data = []
        for r in data:
            surf_data.append([
                _safe_float(r.get(x_field, 0)),
                _safe_float(r.get(y_field, 0)),
                _safe_float(r.get(color_field, 0) if color_field else 0),
            ])

        c = Surface3D()
        c.add(
            series_name=getattr(chart, 'title', '') or y_field,
            data=surf_data,
            xaxis3d_opts=opts.Axis3DOpts(type_="value"),
            yaxis3d_opts=opts.Axis3DOpts(type_="value"),
            zaxis3d_opts=opts.Axis3DOpts(type_="value"),
        )
        c.set_global_opts(
            visualmap_opts=opts.VisualMapOpts(
                max_=max((d[2] for d in surf_data), default=100),
                range_color=["#313695", "#4575B4", "#74ADD1", "#ABD9E9",
                              "#FDAE61", "#F46D43", "#D73027", "#A50026"],
            ),
        )
        return c

    # ================================================================
    # 全局选项 + 样式系统
    # ================================================================

    @classmethod
    def _get_style(cls, cw: Any) -> dict:
        """安全获取 style_config，补全默认值"""
        defaults = {
            "theme": "white", "color_palette": [], "font_family": "Microsoft YaHei",
            "title_font_size": 16, "label_font_size": 11,
            "show_legend": True, "show_label": False, "label_position": "top",
            "item_opacity": 0.9, "bar_border_radius": 4,
            "bg_color": "", "axis_line_color": "#999", "axis_line_width": 1,
            "split_line_type": "dashed", "split_line_color": "#E0E0E0",
            "label_formatter": "",
        }
        raw = getattr(cw, 'style_config', {}) or {}
        for k, v in defaults.items():
            raw.setdefault(k, v)
        return raw

    @classmethod
    def _get_init_opts(cls, cw: Any):
        """生成 InitOpts (主题 + 背景)"""
        from pyecharts import options as opts
        from pyecharts.globals import ThemeType
        style = cls._get_style(cw)
        theme_str = (style.get('theme') or 'white').upper()
        theme = getattr(ThemeType, theme_str, ThemeType.WHITE)
        init = {"theme": theme}
        bg = style.get('bg_color', '')
        if bg:
            init["bg_color"] = bg
        return opts.InitOpts(**init)

    @classmethod
    def _apply_global_opts(cls, chart: Any, cw: Any):
        """应用全局配置：标题、图例、提示框、工具栏、DataZoom、Brush、MagicType"""
        from pyecharts import options as opts

        title = getattr(cw, 'title', '') or '未命名图表'
        style = cls._get_style(cw)
        magic_type = getattr(cw, 'magic_type', True)
        brush_link = getattr(cw, 'enable_brush_link', True)

        # 工具栏 features
        toolbox_features = {
            "saveAsImage": {"title": "保存为图片"},
            "dataZoom": {"title": {"zoom": "区域缩放", "back": "还原"}},
            "restore": {"title": "还原"},
            "dataView": {"title": "数据视图", "readOnly": True},
        }
        if magic_type:
            toolbox_features["magicType"] = {
                "type": ["line", "bar", "stack", "tiled"],
                "title": {"line": "折线图切换", "bar": "柱状图切换",
                          "stack": "堆叠切换", "tiled": "平铺切换"},
            }

        global_opts = {
            "title_opts": opts.TitleOpts(
                title=title,
                title_textstyle_opts=opts.TextStyleOpts(
                    font_size=style.get('title_font_size', 16),
                    font_family=style.get('font_family', 'Microsoft YaHei'),
                ),
                pos_left="center",
            ),
            "tooltip_opts": opts.TooltipOpts(
                trigger="axis",
                axis_pointer_type="cross",     # 十字准星
            ),
            "legend_opts": opts.LegendOpts(
                is_show=style.get('show_legend', True),
                type_="scroll",
                pos_bottom="0",
                textstyle_opts=opts.TextStyleOpts(
                    font_size=style.get('label_font_size', 11),
                    font_family=style.get('font_family', 'Microsoft YaHei'),
                ),
            ),
            "toolbox_opts": opts.ToolboxOpts(
                is_show=True,
                feature=toolbox_features,
            ),
            "datazoom_opts": [
                opts.DataZoomOpts(
                    is_show=True, type_="slider",
                    range_start=0, range_end=100,
                ),
            ],
        }

        # Brush 刷选联动
        if brush_link:
            global_opts["brush_opts"] = opts.BrushOpts(
                tool_box=["rect", "polygon", "clear"],
                brush_link="all",
                series_index="all",
            )

        chart.set_global_opts(**global_opts)

    # ================================================================
    # 通用样式辅助
    # ================================================================

    @classmethod
    def _make_series_opts(cls, cw: Any, chart_type: str):
        """根据 style_config 生成通用的系列样式选项"""
        from pyecharts import options as opts
        style = cls._get_style(cw)

        item_opts = opts.ItemStyleOpts(
            opacity=style.get('item_opacity', 0.9),
        )
        if chart_type in ('bar', 'stacked_bar', 'pictorial_bar', 'waterfall'):
            item_opts.opts['borderRadius'] = [style.get('bar_border_radius', 4)] * 4

        label_formatter = style.get('label_formatter', '')
        label_opts = opts.LabelOpts(
            is_show=style.get('show_label', False),
            position=style.get('label_position', 'top'),
            font_size=style.get('label_font_size', 11),
            font_family=style.get('font_family', 'Microsoft YaHei'),
        )
        if label_formatter:
            label_opts.opts['formatter'] = label_formatter

        series_opts = {
            "label_opts": label_opts,
            "itemstyle_opts": item_opts,
        }

        # MarkLine 均值线 / 目标线
        markline_data = []
        show_avg = getattr(cw, 'show_markline_avg', False)
        target = getattr(cw, 'markline_target', None)
        if show_avg:
            markline_data.append(opts.MarkLineItem(type_="average", name="均值"))
        if target is not None:
            markline_data.append(opts.MarkLineItem(y=target, name="目标线"))
        if markline_data:
            series_opts["markline_opts"] = opts.MarkLineOpts(data=markline_data)

        return series_opts

    @classmethod
    def _apply_colors(cls, chart: Any, cw: Any):
        """应用自定义色板 (兼容 'default' 字符串和颜色列表)"""
        style = cls._get_style(cw)
        palette = style.get('color_palette', 'default')
        # 兼容字符串 "default" (UI 面板使用) 和实际颜色列表
        if isinstance(palette, list) and len(palette) > 0:
            chart.set_colors(palette)
        elif isinstance(palette, str) and palette not in ('', 'default', '默认'):
            # 单个颜色字符串
            chart.set_colors([palette])

    @classmethod
    def _make_label(cls, chart: Any):
        """生成标签配置 (兼容旧接口)"""
        from pyecharts import options as opts
        style = getattr(chart, 'style_config', {}) or {}
        show_label = style.get('show_label', False)
        position = style.get('label_position', 'top')
        font_size = style.get('label_font_size', 11)
        return opts.LabelOpts(
            is_show=show_label, position=position, font_size=font_size,
        )


# ============================================================================
# 填充分发表 (在类定义完成后)
# ============================================================================

PyechartsRenderer._DISPATCH = {
    # 基础图表
    "bar":              PyechartsRenderer._bar,
    "line":             PyechartsRenderer._line,
    "pie":              PyechartsRenderer._pie,
    "scatter":          PyechartsRenderer._scatter,
    "area":             PyechartsRenderer._area,
    "table":            None,  # 由 render() 直接处理
    # 指标
    "card":             None,  # 由 render() 直接处理
    "gauge":            PyechartsRenderer._gauge,
    # 变体
    "combo":            PyechartsRenderer._combo,
    "stacked_bar":      PyechartsRenderer._stacked_bar,
    "stacked_area":     PyechartsRenderer._stacked_area,
    "pictorial_bar":    PyechartsRenderer._pictorial_bar,
    "effect_scatter":   PyechartsRenderer._effect_scatter,
    "waterfall":        PyechartsRenderer._waterfall,
    # 构成
    "funnel":           PyechartsRenderer._funnel,
    "treemap":          PyechartsRenderer._treemap,
    "sunburst":         PyechartsRenderer._sunburst,
    # 分布
    "boxplot":          PyechartsRenderer._boxplot,
    "heatmap":          PyechartsRenderer._heatmap,
    "calendar":         PyechartsRenderer._calendar,
    "candlestick":      PyechartsRenderer._candlestick,
    # 流向
    "sankey":           PyechartsRenderer._sankey,
    "graph":            PyechartsRenderer._graph,
    "tree":             PyechartsRenderer._tree,
    # 多维
    "radar":            PyechartsRenderer._radar,
    "parallel":         PyechartsRenderer._parallel,
    "theme_river":      PyechartsRenderer._theme_river,
    # 地理
    "map_china":        PyechartsRenderer._map_china,
    "map_scatter":      PyechartsRenderer._map_scatter,
    "map_lines":        PyechartsRenderer._map_lines,
    # 其他
    "word_cloud":       PyechartsRenderer._word_cloud,
    # pyecharts 独有增强
    "liquid":           PyechartsRenderer._liquid,
    "polar":            PyechartsRenderer._polar,
    "chord":            PyechartsRenderer._chord,
    # 3D (需要 echarts-gl)
    "bar3d":            PyechartsRenderer._bar3d,
    "scatter3d":        PyechartsRenderer._scatter3d,
    "surface3d":        PyechartsRenderer._surface3d,
}

# ============================================================================
# 便捷函数
# ============================================================================


def render_chart_html(chart: Any, data: List[dict]) -> str:
    """
    快捷入口：ChartWidget + 数据 → HTML 片段。

    Args:
        chart: ChartWidget 对象或任何具有 chart_type/title/x_field/y_fields/
               color_field/size_field/style_config 属性的对象
        data: 查询结果行列表 list[dict]

    Returns:
        可直接嵌入 <div class="bd"> 的 HTML 字符串
    """
    return PyechartsRenderer.render(chart, data)


def render_chart_html_safe(chart: Any, data: List[dict]) -> str:
    """
    安全版渲染入口：始终返回有效 HTML，永不抛异常。
    """
    try:
        return PyechartsRenderer.render(chart, data)
    except Exception as e:
        title = getattr(chart, 'title', '') or '图表'
        return (
            f'<div style="color:#FF4D4F;padding:16px;text-align:center;font-size:13px;">'
            f'❌ {title} 渲染失败<br><small>{e}</small></div>'
        )


# ============================================================================
# 集成入口：在 dashboard_designer 中调用的示例
# ============================================================================

def integrate_with_designer(dashboard_designer_instance):
    """
    将 pyecharts 渲染器挂载到设计器上。

    用法 (在 dashboard_designer.py _refresh_html 中):

        from .pyecharts_renderer import render_chart_html_safe, set_echarts_base_dir

        # 初始化：设置本地 ECharts 目录
        set_echarts_base_dir(os.path.join(os.path.dirname(__file__), 'echarts'))

        # 渲染每个图表
        for chart_widget in self._dashboard.charts:
            data = self._data_map.get(chart_widget.id, [])
            html_fragment = render_chart_html_safe(chart_widget, data)
            chart_widget._prerendered_html = html_fragment
    """
    # 设置本地 ECharts 路径
    echarts_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'echarts'
    )
    if os.path.isdir(echarts_dir):
        set_echarts_base_dir(echarts_dir)


# ============================================================================
# 自测
# ============================================================================

if __name__ == "__main__":
    # 模拟 ChartWidget
    class MockChart:
        chart_type = "bar"
        title = "测试柱状图"
        x_field = "category"
        y_fields = ["sales"]
        color_field = "region"
        size_field = ""
        aggregate_funcs = {"sales": "SUM"}
        filters = []
        style_config = {"show_legend": True, "show_label": False, "theme": "light"}
        enable_cross_filter = True
        enable_drill = False
        drill_path = []

    # 模拟数据
    test_data = [
        {"category": "A", "sales": 120, "region": "华东"},
        {"category": "B", "sales": 200, "region": "华东"},
        {"category": "C", "sales": 150, "region": "华东"},
        {"category": "A", "sales": 90, "region": "华南"},
        {"category": "B", "sales": 180, "region": "华南"},
        {"category": "C", "sales": 220, "region": "华南"},
    ]

    # 测试所有图表类型
    chart_types = [
        "bar", "line", "pie", "scatter", "area",
        "stacked_bar", "stacked_area",
        "gauge", "funnel", "treemap", "sunburst",
        "heatmap", "sankey", "radar",
        "word_cloud",
    ]

    for ct in chart_types:
        chart = MockChart()
        chart.chart_type = ct
        try:
            html = render_chart_html(chart, test_data)
            print(f"[OK]  {ct:15s} -> {len(html):6d} chars")
        except Exception as e:
            print(f"[FAIL] {ct:15s} -> {e}")
