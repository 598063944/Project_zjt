"""
BI 仪表盘模块 — Power BI 风格的交互式可视化报表

提供:
- 30 种 ECharts 图表类型（QWebEngineView 渲染）
- 网格布局仪表盘设计器
- 交叉筛选 / 下钻 / 全屏 / 导出
- 多 AI 提供商自然语言交互（DeepSeek / 小米 MiMo / 智谱 GLM）
- 数据源：自定义报表（cr_*）+ Excel/CSV + MySQL 表

入口:
    from custom_report.dashboard import DashboardManager
"""

from .models import (
    ChartType,
    ChartWidget,
    DashboardDefinition,
    ExcelDataset,
    LLMProvider,
)

__all__ = [
    'ChartType',
    'ChartWidget',
    'DashboardDefinition',
    'ExcelDataset',
    'LLMProvider',
]
