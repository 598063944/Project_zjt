"""
仪表盘查看页

只读展示模式 + 全屏 + 导出。
用户看到的是 QWebEngineView 渲染的 ECharts 仪表盘。
"""

import os
import json
import base64
import logging
from io import BytesIO
from ..utils import json_dumps_safe

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMenu, QFileDialog, QMessageBox, QFrame, QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtGui import QColor

import pandas as pd

from .bridge import DashboardBridge, parse_action_payload
from .html_template import build_dashboard_html

logger = logging.getLogger(__name__)


class DashboardViewPage(QWidget):
    """仪表盘查看页（只读）"""

    backRequested = pyqtSignal()
    editRequested = pyqtSignal(str)  # dashboard_id
    dataRefreshRequested = pyqtSignal(str)  # dashboard_id

    def __init__(self, bridge: DashboardBridge = None, parent=None):
        super().__init__(parent)
        self._dashboard = None   # DashboardDefinition
        self._data_map = {}      # {chart_id: [rows]}
        self._bridge = bridge or DashboardBridge(self)
        self._fullscreen = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ===== 工具栏 =====
        toolbar = QFrame()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet("QFrame { background: #FAFAFA; border-bottom: 1px solid #E8E8E8; }")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(12, 4, 12, 4)

        back_btn = QPushButton("← 返回")
        back_btn.clicked.connect(self.backRequested.emit)
        back_btn.setFixedHeight(28)
        tb_layout.addWidget(back_btn)

        self._title_label = QLabel("仪表盘")
        self._title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #333;")
        tb_layout.addWidget(self._title_label)

        tb_layout.addStretch()

        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setToolTip("重新查询数据")
        refresh_btn.setFixedHeight(28)
        refresh_btn.clicked.connect(lambda: self.dataRefreshRequested.emit(
            self._dashboard.id if self._dashboard else ""))
        tb_layout.addWidget(refresh_btn)

        # 导出下拉菜单
        export_btn = QPushButton("📤 导出 ▼")
        export_btn.setFixedHeight(28)
        export_menu = QMenu(export_btn)
        export_menu.addAction("🖼 导出 PNG 图片", self._export_png)
        export_menu.addAction("📄 导出 PDF 文件", self._export_pdf)
        export_menu.addAction("📊 导出 Excel 数据", self._export_excel)
        export_menu.addAction("🌐 导出 HTML 文件", self._export_html)
        export_btn.setMenu(export_menu)
        tb_layout.addWidget(export_btn)

        edit_btn = QPushButton("✏️ 编辑")
        edit_btn.setFixedHeight(28)
        edit_btn.clicked.connect(lambda: self.editRequested.emit(
            self._dashboard.id if self._dashboard else ""))
        tb_layout.addWidget(edit_btn)

        self._fullscreen_btn = QPushButton("⛶ 全屏")
        self._fullscreen_btn.setFixedHeight(28)
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        tb_layout.addWidget(self._fullscreen_btn)

        layout.addWidget(toolbar)

        # ===== WebView =====
        self._webview = QWebEngineView()
        self._webview.setStyleSheet("background: #F0F2F5;")
        self._webview.page().setBackgroundColor(QColor("#F0F2F5"))
        self._webview.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        layout.addWidget(self._webview, 1)

        # 设置 QWebChannel
        self._channel = QWebChannel(self._webview.page())
        self._channel.registerObject("bridge", self._bridge)
        self._webview.page().setWebChannel(self._channel)
        self._bridge.set_page(self._webview.page())
        self._bridge.actionReceived.connect(self._on_js_action)

    def load_dashboard(self, dashboard, data_map: dict[str, list] = None):
        """
        加载仪表盘进行渲染

        Args:
            dashboard: DashboardDefinition 对象
            data_map: {chart_id: [{col: val}, ...]} 聚合数据
        """
        self._dashboard = dashboard
        self._data_map = data_map or {}
        self._title_label.setText(dashboard.name)

        # 构建 HTML
        echarts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'echarts')
        html = self._build_html_with_data(dashboard, self._data_map, echarts_dir)

        # 加载
        base_url = QUrl.fromLocalFile(echarts_dir)
        self._webview.setHtml(html, base_url)

    def _build_html_with_data(self, dashboard, data_map: dict, echarts_dir: str = '') -> str:
        """构建包含内嵌数据的 HTML"""
        html = build_dashboard_html(dashboard.to_dict(), use_cdn=False, embed_data=True, echarts_dir=echarts_dir)

        # 嵌入中国地图 GeoJSON + 数据
        inject_parts = []
        china_path = os.path.join(echarts_dir, 'china.json') if echarts_dir else ''
        if china_path and os.path.exists(china_path):
            with open(china_path, 'r', encoding='utf-8') as f:
                china_json = f.read()
            inject_parts.append(f'<script>window._CHINA_GEO = {china_json};</script>')
        data_json = json_dumps_safe(data_map, ensure_ascii=False)
        inject_parts.append(f"<script>window._INITIAL_DATA = {data_json};</script>")
        html = html.replace('</body>', '\n'.join(inject_parts) + '\n</body>')

        return html

    def refresh_data(self, data_map: dict[str, list]):
        """刷新数据（不重载整个页面）"""
        self._data_map = data_map
        self._bridge.inject_all_data(data_map)

    def _on_js_action(self, action: str, payload_json: str):
        payload = parse_action_payload(payload_json)

        if action == "page_ready":
            # 数据已通过 _INITIAL_DATA 嵌入 HTML，无需重复注入
            pass
        elif action == "chart_clicked":
            pass  # 交叉筛选在 JS 端完成
        elif action == "change_query":
            # 筛选条件变更，需要重查数据库
            if self._dashboard:
                self.dataRefreshRequested.emit(self._dashboard.id)
        elif action == "export_ready":
            self._save_export_data(payload)

    def _save_export_data(self, payload: dict):
        """保存导出的数据"""
        if payload.get('format') == 'png':
            data = payload.get('data', '')
            if data:
                self._save_png_data(data)

    _pending_export_data = None       # 保存待导出的 base64 数据
    _pending_export_file = None       # 保存待导出的文件路径

    # ===== 导出功能 =====

    def _export_png(self):
        """请求 JS 端合成 PNG"""
        if self._dashboard:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "导出 PNG 图片",
                f"{self._dashboard.name}.png",
                "PNG 图片 (*.png)"
            )
            if file_path:
                self._pending_export_file = file_path
                self._bridge.export_png()

    def _save_png_data(self, base64_data: str):
        """保存 PNG base64 数据到文件"""
        file_path = getattr(self, '_pending_export_file', None)
        if not file_path:
            return
        try:
            # 去掉可能的 data:image/png;base64, 前缀
            if ',' in base64_data:
                base64_data = base64_data.split(',', 1)[1]
            data = base64.b64decode(base64_data)
            with open(file_path, 'wb') as f:
                f.write(data)
            print(f"[BI 报表] PNG 导出成功: {file_path}")
        except Exception as e:
            print(f"[BI 报表] 导出失败: {e}")
        finally:
            self._pending_export_file = None

    def _export_pdf(self):
        """导出 PDF（QWebEnginePage 原生支持）"""
        if not self._dashboard:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出 PDF 文件",
            f"{self._dashboard.name}.pdf",
            "PDF 文件 (*.pdf)"
        )
        if file_path:
            self._webview.page().printToPdf(file_path)
            print(f"[BI 报表] PDF 导出成功: {file_path}")

    def _export_excel(self):
        """导出 Excel（每图表一个 Sheet）"""
        if not self._dashboard or not self._data_map:
            print("[BI 报表] 导出失败: 没有可导出的数据")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出 Excel 数据",
            f"{self._dashboard.name}.xlsx",
            "Excel 文件 (*.xlsx)"
        )
        if not file_path:
            return
        try:
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                # 汇总 Sheet
                summary_rows = []
                for chart in self._dashboard.charts:
                    rows = self._data_map.get(chart.id, [])
                    summary_rows.append({
                        '图表名称': chart.title,
                        '图表类型': chart.chart_type,
                        '数据源': chart.data_source_name,
                        '数据行数': len(rows),
                    })
                pd.DataFrame(summary_rows).to_excel(writer, sheet_name='图表汇总', index=False)

                # 每个图表数据 Sheet
                for chart in self._dashboard.charts:
                    data = self._data_map.get(chart.id, [])
                    if data:
                        df = pd.DataFrame(data)
                        sheet_name = chart.title[:31]  # Excel sheet 名最长 31 字符
                        df.to_excel(writer, sheet_name=sheet_name, index=False)

            print(f"[BI 报表] Excel 导出成功: {file_path}")
        except Exception as e:
            print(f"[BI 报表] 导出失败: {e}")

    def _export_html(self):
        """导出独立 HTML 文件"""
        if not self._dashboard:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出 HTML 文件",
            f"{self._dashboard.name}.html",
            "HTML 文件 (*.html)"
        )
        if not file_path:
            return
        try:
            # 生成使用 CDN 的独立 HTML
            data_json = json_dumps_safe(self._data_map, ensure_ascii=False)
            html = build_dashboard_html(
                self._dashboard.to_dict(),
                use_cdn=True,
                embed_data=True,
            )
            html = html.replace(
                "</body>",
                f"<script>window._INITIAL_DATA = {data_json};</script>\n</body>"
            )
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"[BI 报表] HTML 导出成功: {file_path}")
        except Exception as e:
            print(f"[BI 报表] 导出失败: {e}")

    # ===== 全屏 =====

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self.window().showFullScreen()
            self._fullscreen_btn.setText("⛶ 退出全屏")
        else:
            self.window().showNormal()
            self._fullscreen_btn.setText("⛶ 全屏")

    def keyPressEvent(self, event):
        """ESC 退出全屏"""
        if event.key() == Qt.Key.Key_Escape and self._fullscreen:
            self._toggle_fullscreen()
        super().keyPressEvent(event)
