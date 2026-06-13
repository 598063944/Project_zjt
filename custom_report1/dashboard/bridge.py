"""
Python ↔ JavaScript 双向通信桥

使用 QWebChannel 实现 PyQt 与 QWebEngineView 中 JS 的通信。

设计原则:
- 大量数据通过 page.runJavaScript() 直接注入（不经过 QWebChannel，避免序列化瓶颈）
- QWebChannel 仅用于轻量级的控制和回调
"""

import json
import logging
from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal
from ..utils import json_dumps_safe

logger = logging.getLogger(__name__)


class DashboardBridge(QObject):
    """仪表盘 Python ↔ JS 通信桥"""

    # ===== Python → JS 信号 =====
    actionReceived = pyqtSignal(str, str)   # (action, payload_json)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page = None  # QWebEnginePage 引用，初始化时设置

    def set_page(self, page):
        """设置关联的 QWebEnginePage"""
        self._page = page

    # ===== Python → JS（直接注入，不经过 Channel）=====

    def inject_all_data(self, data_map: dict[str, list], option_map: dict[str, str] = None):
        """
        注入全部图表数据到 JS 全局变量。

        Args:
            data_map: {chart_id: [{col: val, ...}, ...]}
            option_map: {chart_id: echarts_option_json, ...} (可选，pyecharts 预渲染)
        """
        # 如果提供了 option_map，先注入 options
        if option_map:
            entries_js = ','.join(
                f"'{cid}':{opt}" for cid, opt in option_map.items()
            )
            self._run_js(
                f"(function(){{"
                f"var optMap={{{entries_js}}};"
                f"(CONFIG.charts||[]).forEach(function(c){{"
                f"if(optMap[c.id])c._echarts_option=optMap[c.id];"
                f"}});"
                f"}})();"
            )

        # 注入数据
        js = f"window.refreshAllData({json_dumps_safe(data_map, ensure_ascii=False)});"
        self._run_js(js)

    def inject_chart_data(self, chart_id: str, data: list):
        """注入单个图表数据"""
        js = f"window.refreshChartData('{chart_id}', {json_dumps_safe(data, ensure_ascii=False)});"
        self._run_js(js)

    def push_filters(self, filters_json: str):
        """推送全局筛选条件变更"""
        js = f"window.applyGlobalFilters({filters_json});"
        self._run_js(js)

    def set_edit_mode(self, enabled: bool):
        """切换编辑模式"""
        js = f"window.setEditMode({str(enabled).lower()});"
        self._run_js(js)

    def navigate_to_chart(self, chart_id: str):
        """在编辑模式下高亮并滚动到指定图表"""
        js = f"window.selectChart('{chart_id}');"
        self._run_js(js)

    def reload_config(self, config_json: str):
        """重新加载仪表盘配置（设计器用）"""
        js = f"window.reloadConfig({config_json});"
        self._run_js(js)

    def export_png(self):
        """请求 JS 端合成并返回 PNG 图片"""
        self._run_js("window.requestExportPNG();")

    def run_js(self, js: str):
        """公开的 JS 执行方法"""
        self._run_js(js)

    def _run_js(self, js: str):
        """安全执行 JS"""
        if self._page:
            self._page.runJavaScript(js)

    # ===== JS → Python（通过 QWebChannel）=====

    @pyqtSlot(str, str)
    def handle_js_action(self, action: str, payload_json: str):
        """
        JS 端回调入口。

        Args:
            action: 动作类型
                - "page_ready"       → 页面加载完成
                - "chart_clicked"    → 点击图表元素
                - "drill_down"       → 下钻请求
                - "card_moved"       → 拖拽卡片新位置（编辑模式）
                - "card_resized"     → 缩放卡片（编辑模式）
                - "chart_selected"   → 选中图表
                - "chart_added"      → 从模板添加新图表
                - "change_query"     → 筛选条件变更，需重查库
                - "export_ready"     → PNG 导出完成
        """
        logger.debug(f"[Bridge] JS → Python: {action}")
        self.actionReceived.emit(action, payload_json)

    @pyqtSlot(str, result=str)
    def get_initial_data(self, chart_id: str) -> str:
        """
        JS 端按需请求图表数据（用于懒加载）。
        返回 JSON 字符串。
        """
        # 子类或外部调用者可重写此逻辑
        return "[]"


# ==================== 动作解析辅助 ====================

def parse_action_payload(payload_json: str) -> dict:
    """安全解析 JS 传来的 payload JSON"""
    try:
        return json.loads(payload_json) if payload_json else {}
    except json.JSONDecodeError:
        logger.warning(f"[Bridge] 无效的 payload JSON: {payload_json[:100]}")
        return {}
