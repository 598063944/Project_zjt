"""
BI 仪表盘数据模型

DashboardDefinition 是一份仪表盘的完整定义，包含:
- 基本信息 (名称、布局、主题)
- 图表列表 (类型、数据源、字段映射、样式)
- 全局筛选器
- AI 提供商配置
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import uuid
import json
import copy


# ==================== 工具函数 ====================

def _new_id(length: int = 8) -> str:
    """生成指定长度的 hex ID"""
    return uuid.uuid4().hex[:length]


# ==================== 枚举 ====================

class ChartType(Enum):
    """图表类型（ECharts 全覆盖）"""

    # 基础图表
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    AREA = "area"
    TABLE = "table"

    # 指标类
    CARD = "card"
    GAUGE = "gauge"

    # 组合 / 变体
    COMBO = "combo"
    STACKED_BAR = "stacked_bar"
    STACKED_AREA = "stacked_area"
    PICTORIAL_BAR = "pictorial_bar"
    EFFECT_SCATTER = "effect_scatter"
    WATERFALL = "waterfall"

    # 比例 / 构成
    FUNNEL = "funnel"
    TREEMAP = "treemap"
    SUNBURST = "sunburst"

    # 分布 / 统计
    BOXPLOT = "boxplot"
    HEATMAP = "heatmap"
    CALENDAR = "calendar"
    CANDLESTICK = "candlestick"

    # 关系 / 流向
    SANKEY = "sankey"
    GRAPH = "graph"
    TREE = "tree"

    # 多维分析
    RADAR = "radar"
    PARALLEL = "parallel"
    THEME_RIVER = "theme_river"

    # 地理
    MAP_CHINA = "map_china"
    MAP_SCATTER = "map_scatter"
    MAP_LINES = "map_lines"

    # 其他
    WORD_CLOUD = "word_cloud"

    @classmethod
    def from_str(cls, s: str):
        for m in cls:
            if m.value == s:
                return m
        return cls.BAR

    @classmethod
    def category_map(cls) -> dict[str, list["ChartType"]]:
        """返回按分类组织的图表类型"""
        return {
            "基础图表": [cls.BAR, cls.LINE, cls.PIE, cls.SCATTER, cls.AREA, cls.TABLE],
            "指标类": [cls.CARD, cls.GAUGE],
            "组合/变体": [cls.COMBO, cls.STACKED_BAR, cls.STACKED_AREA,
                        cls.PICTORIAL_BAR, cls.EFFECT_SCATTER, cls.WATERFALL],
            "比例/构成": [cls.FUNNEL, cls.TREEMAP, cls.SUNBURST],
            "分布/统计": [cls.BOXPLOT, cls.HEATMAP, cls.CALENDAR, cls.CANDLESTICK],
            "关系/流向": [cls.SANKEY, cls.GRAPH, cls.TREE],
            "多维分析": [cls.RADAR, cls.PARALLEL, cls.THEME_RIVER],
            "地理": [cls.MAP_CHINA, cls.MAP_SCATTER, cls.MAP_LINES],
            "其他": [cls.WORD_CLOUD],
        }


def chart_display_name(chart_type: str) -> str:
    """图表类型中文显示名"""
    names = {
        'bar': '柱状图', 'line': '折线图', 'pie': '饼图', 'scatter': '散点图',
        'area': '面积图', 'table': '表格',
        'card': '指标卡', 'gauge': '仪表盘',
        'combo': '组合图', 'stacked_bar': '堆叠柱状', 'stacked_area': '堆叠面积',
        'pictorial_bar': '象形柱状', 'effect_scatter': '涟漪散点', 'waterfall': '瀑布图',
        'funnel': '漏斗图', 'treemap': '树图', 'sunburst': '旭日图',
        'boxplot': '箱线图', 'heatmap': '热力图', 'calendar': '日历图', 'candlestick': 'K线图',
        'sankey': '桑基图', 'graph': '关系图', 'tree': '树形图',
        'radar': '雷达图', 'parallel': '平行坐标', 'theme_river': '主题河流',
        'map_china': '中国地图', 'map_scatter': '地图散点', 'map_lines': '地图飞线',
        'word_cloud': '词云',
    }
    return names.get(chart_type, chart_type)


class DataSourceType(Enum):
    """数据源类型"""
    REPORT = "report"         # 自定义报表（cr_* 结果表）
    EXCEL = "excel"           # Excel 导入（ex_* 表）
    MYSQL_TABLE = "mysql"     # 直接选 MySQL 表/视图


# ==================== 数据类 ====================

@dataclass
class ChartWidget:
    """仪表盘上的一个图表"""
    id: str = field(default_factory=_new_id)
    chart_type: str = "bar"
    title: str = "未命名图表"

    # 渲染引擎
    render_engine: str = "pyecharts"    # "pyecharts" | "plotly" | "seaborn"

    # 数据源
    data_source_type: str = "report"    # DataSourceType 值
    data_source_id: str = ""            # report_id / excel_dataset_id / mysql_table
    data_source_name: str = ""          # 显示用名称

    # 维度与度量
    x_field: str = ""                   # X 轴 / 维度字段
    y_fields: list[str] = field(default_factory=list)   # Y 轴 / 度量字段
    aggregate_funcs: dict = field(default_factory=dict)  # {field: "SUM"|"AVG"|...}
    color_field: str = ""               # 颜色/系列分组字段
    size_field: str = ""                # 气泡大小（散点图/地图用）

    # 筛选与交互
    filters: list = field(default_factory=list)  # list[FilterCondition]
    drill_path: list = field(default_factory=list)  # ["year","quarter","month","day"]
    enable_cross_filter: bool = True
    enable_drill: bool = False
    enable_brush_link: bool = True      # Brush 刷选联动
    enable_chart_connect: bool = True   # 图表十字准星联动
    magic_type: bool = True             # 显示 柱/折/堆叠 切换按钮

    # 告警
    alert_threshold: float = None       # 阈值 (超过变红)
    alert_color: str = "#F44336"
    normal_color: str = "#4CAF50"

    # 标记线
    show_markline_avg: bool = False     # 显示均值线
    markline_target: float = None       # 目标线数值

    # 布局
    position: tuple = (0, 0)      # (row, col)
    size: tuple = (1, 1)          # (row_span, col_span)

    # 样式
    style_config: dict = field(default_factory=lambda: {
        # 主题与色板
        "theme": "white",                # pyecharts: WHITE/DARK/CHALK/ESSOS/INFOGRAPHIC/
                                        #   MACARONS/PURPLE_PASSION/ROMA/ROMANTIC/
                                        #   SHINE/VINTAGE/WALDEN/WESTEROS/WONDERLAND/HALLOWEEN
        "color_palette": "default",      # "default" 或颜色列表 ["#FF6B6B", ...]

        # 字体
        "font_family": "Microsoft YaHei",
        "title_font_size": 16,
        "label_font_size": 11,

        # 图例与标签
        "show_legend": True,
        "show_label": False,
        "label_position": "top",         # inside/top/bottom/left/right/insideTop...

        # 透明度与边框
        "item_opacity": 0.9,
        "bar_border_radius": 4,          # 柱状图圆角 (0=直角)

        # 背景
        "bg_color": "",                  # 空=默认白色, 支持 "#1A1A2E" 等

        # 坐标轴
        "axis_line_color": "#999",
        "axis_line_width": 1,
        "split_line_type": "dashed",     # solid/dashed/dotted
        "split_line_color": "#E0E0E0",

        # 数据标签格式化
        "label_formatter": "",           # "{c} 万元" / "{c}%" 等
    })
    custom_options: str = ""      # 自定义 ECharts option JSON 片段


@dataclass
class DashboardDefinition:
    """一份仪表盘的完整定义"""
    id: str = field(default_factory=lambda: _new_id(12))
    name: str = "未命名仪表盘"
    description: str = ""

    # 布局
    grid_columns: int = 3              # 网格列数（1-6）
    grid_row_height: int = 320         # 每行高度（px）

    # 内容
    charts: list = field(default_factory=list)  # list[ChartWidget]

    # 全局筛选
    global_filters: list = field(default_factory=list)  # list[FilterCondition]
    date_range_field: str = ""
    date_range_start: str = ""
    date_range_end: str = ""

    # 其他
    auto_refresh_seconds: int = 0      # 自动刷新间隔（0=不自动刷新）
    theme: str = "light"               # "light" | "dark"

    created_at: str = ""
    modified_at: str = ""
    version: int = 0

    def to_dict(self) -> dict:
        """序列化为字典"""
        return _serialize(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DashboardDefinition":
        """从字典反序列化"""
        return _deserialize_dashboard(data)


@dataclass
class ExcelDataset:
    """Excel/CSV 导入后的数据集"""
    id: str = field(default_factory=_new_id)
    name: str = ""
    source_file: str = ""             # 原始文件路径
    file_type: str = ""               # "xlsx" | "xls" | "csv"
    columns: list = field(default_factory=list)  # [{key, label, data_type}]
    row_count: int = 0
    mysql_table: str = ""             # 导入后的表名 "ex_{id}"
    created_at: str = ""

    def to_dict(self) -> dict:
        return _serialize(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ExcelDataset":
        return _deserialize_excel_dataset(data)


@dataclass
class LLMProvider:
    """AI 大模型提供商配置"""
    id: str = ""                # "deepseek" | "xiaomi_mimo" | "zhipu_glm"
    name: str = ""              # "DeepSeek" | "小米 MiMo" | "智谱 GLM"
    api_url: str = ""           # API 端点
    default_model: str = ""     # 默认模型
    models: list = field(default_factory=list)  # 可选模型列表
    api_key: str = ""           # API Key（从配置加载）
    enabled: bool = False

    def to_dict(self) -> dict:
        return _serialize(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LLMProvider":
        return _deserialize_llm_provider(data)


# ==================== 预定义 AI 提供商 ====================

LLM_PROVIDERS = {
    "deepseek": LLMProvider(
        id="deepseek",
        name="DeepSeek",
        api_url="https://api.deepseek.com/v1/chat/completions",
        default_model="deepseek-chat",
        models=["deepseek-chat", "deepseek-reasoner"],
    ),
    "xiaomi_mimo": LLMProvider(
        id="xiaomi_mimo",
        name="小米 MiMo",
        api_url="https://api.xiaomimimo.com/v1/chat/completions",
        default_model="mimo-large",
        models=["mimo-large", "mimo-pro"],
    ),
    "zhipu_glm": LLMProvider(
        id="zhipu_glm",
        name="智谱 GLM",
        api_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        default_model="glm-4-plus",
        models=["glm-4-plus", "glm-4-flash", "glm-4-long"],
    ),
}


# ==================== 序列化辅助 ====================

def _serialize(obj) -> dict:
    """递归序列化 dataclass 对象为纯字典"""
    if hasattr(obj, '__dataclass_fields__'):
        result = {}
        for f_name in obj.__dataclass_fields__:
            val = getattr(obj, f_name)
            result[f_name] = _serialize(val)
        return result
    elif isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    elif isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    elif isinstance(obj, Enum):
        return obj.value
    else:
        return obj


def _deserialize_dashboard(data: dict) -> DashboardDefinition:
    """从字典反序列化 DashboardDefinition"""
    d = dict(data)
    # 反序列化图表列表
    if 'charts' in d and isinstance(d['charts'], list):
        d['charts'] = [_deserialize_chart_widget(c) for c in d['charts']]
    # 序列化元组
    if 'position' in d and isinstance(d['position'], list):
        d['position'] = tuple(d['position'])
    if 'size' in d and isinstance(d['size'], list):
        d['size'] = tuple(d['size'])
    return DashboardDefinition(**{k: v for k, v in d.items() if k in DashboardDefinition.__dataclass_fields__})


def _deserialize_chart_widget(data: dict) -> ChartWidget:
    """从字典反序列化 ChartWidget"""
    d = dict(data)
    if 'position' in d and isinstance(d['position'], list):
        d['position'] = tuple(d['position'])
    if 'size' in d and isinstance(d['size'], list):
        d['size'] = tuple(d['size'])
    # 移除不属于 ChartWidget 的键，但补全 style_config 缺失的新增 key (向后兼容)
    valid_keys = set(ChartWidget.__dataclass_fields__.keys())
    filtered = {k: v for k, v in d.items() if k in valid_keys}
    sc = filtered.get('style_config', {}) or {}
    defaults = ChartWidget.__dataclass_fields__['style_config'].default_factory()
    for k, v in defaults.items():
        sc.setdefault(k, v)
    filtered['style_config'] = sc
    return ChartWidget(**filtered)


def _deserialize_excel_dataset(data: dict) -> ExcelDataset:
    """从字典反序列化 ExcelDataset"""
    d = dict(data)
    valid_keys = set(ExcelDataset.__dataclass_fields__.keys())
    return ExcelDataset(**{k: v for k, v in d.items() if k in valid_keys})


def _deserialize_llm_provider(data: dict) -> LLMProvider:
    """从字典反序列化 LLMProvider"""
    d = dict(data)
    valid_keys = set(LLMProvider.__dataclass_fields__.keys())
    return LLMProvider(**{k: v for k, v in d.items() if k in valid_keys})
