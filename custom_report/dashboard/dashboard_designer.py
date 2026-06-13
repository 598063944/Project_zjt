"""
仪表盘设计器

组装数据源面板、图表配置面板、预览区为完整的设计器界面。
对标 ReportEditorPage 的 splitter 模式。
"""

import os
import json
import logging
from ..utils import json_dumps_safe

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QFrame,
    QPushButton, QLabel, QLineEdit, QComboBox, QMessageBox,
    QDialog, QVBoxLayout as QVBDialog, QDialogButtonBox, QGridLayout,
    QTextEdit, QScrollArea,
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtGui import QColor

from .bridge import DashboardBridge, parse_action_payload
from .html_template import build_dashboard_html
from .data_source_panel import DataSourcePanel
from .chart_config_panel import ChartConfigPanel
from .models import DashboardDefinition, ChartWidget, ChartType, _new_id
from .pyecharts_renderer import render_chart_html_safe, set_echarts_base_dir

logger = logging.getLogger(__name__)


def _ui_output(msg: str):
    """输出消息到主窗口运行时窗口"""
    try:
        import sys
        main_mod = sys.modules.get('__main__')
        if main_mod:
            mf = getattr(main_mod, 'MainFrame', None)
            if mf and hasattr(mf, 'instance') and mf.instance:
                mf.instance.append_output(msg)
                return
    except Exception:
        pass
    # 回退：打印到 stdout
    import builtins
    builtins.print(msg)


def _mysql_type_to_generic(mysql_type: str) -> str:
    """将 MySQL 数据类型映射为通用类型"""
    t = (mysql_type or '').lower()
    if any(x in t for x in ('int', 'decimal', 'float', 'double', 'numeric')):
        return 'number'
    elif any(x in t for x in ('date', 'time', 'timestamp')):
        return 'date'
    return 'text'


def _apply_filters(rows: list, filters: list) -> list:
    """对数据行应用筛选条件"""
    if not filters or not rows:
        return rows
    result = rows
    for f in filters:
        field = f.get('field', '')
        op = f.get('op', '')
        value = (f.get('value', '') or '').strip()
        if not field:
            continue
        if op in ('为空', '不为空'):
            if op == '为空':
                result = [r for r in result if not str(r.get(field, '')).strip()]
            else:
                result = [r for r in result if str(r.get(field, '')).strip()]
        elif op == '属于':
            vals = set(v.strip() for v in value.split(',') if v.strip())
            result = [r for r in result if str(r.get(field, '')).strip() in vals] if vals else result
        elif op == '不属于':
            vals = set(v.strip() for v in value.split(',') if v.strip())
            result = [r for r in result if str(r.get(field, '')).strip() not in vals] if vals else result
        elif op == '包含':
            result = [r for r in result if value.lower() in str(r.get(field, '')).lower()]
        elif op == '不包含':
            result = [r for r in result if value.lower() not in str(r.get(field, '')).lower()]
        elif op in ('等于', '不等于', '大于', '小于', '大于等于', '小于等于') and value:
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
                elif op == '大于':
                    ok = is_numeric and isinstance(rv, (int, float)) and rv > v_num
                elif op == '小于':
                    ok = is_numeric and isinstance(rv, (int, float)) and rv < v_num
                elif op == '大于等于':
                    ok = is_numeric and isinstance(rv, (int, float)) and rv >= v_num
                elif op == '小于等于':
                    ok = is_numeric and isinstance(rv, (int, float)) and rv <= v_num
                else:
                    ok = False
                if ok:
                    filtered.append(r)
            result = filtered
    return result


GRID_COLUMN_OPTIONS = list(range(1, 51))  # 1~50 列
THEME_OPTIONS = ["light", "dark"]
ROW_HEIGHT_OPTIONS = [20, 50, 80, 100, 120, 150, 180, 200, 220, 250, 280, 300, 320, 350, 380, 400, 450, 500]


class DashboardDesigner(QWidget):
    """仪表盘设计器"""

    backRequested = pyqtSignal()
    dashboardSaved = pyqtSignal(str)  # dashboard_id
    dataRefreshRequested = pyqtSignal(str)  # dashboard_id

    def __init__(self, bridge: DashboardBridge = None, parent=None, db=None, excel_repo=None, report_manager=None):
        super().__init__(parent)
        self._dashboard = DashboardDefinition()
        self._data_map = {}       # {chart_id: [rows]}
        self._selected_source = None  # 单击选中的数据源 {type, id, name, fields}
        self._db = db
        self._excel_repo = excel_repo
        self._report_manager = report_manager  # 用于单图表数据刷新
        self._bridge = bridge or DashboardBridge(self)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ===== 工具栏 =====
        toolbar = QFrame()
        toolbar.setFixedHeight(44)
        toolbar.setStyleSheet("QFrame { background: #FAFAFA; border-bottom: 1px solid #E8E8E8; }")
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(12, 6, 12, 6)

        back_btn = QPushButton("← 返回")
        back_btn.clicked.connect(self.backRequested.emit)
        back_btn.setFixedHeight(28)
        tb.addWidget(back_btn)

        tb.addWidget(QLabel("名称:"))
        self._name_edit = QLineEdit("未命名仪表盘")
        self._name_edit.setFixedWidth(220)
        self._name_edit.setFixedHeight(28)
        self._name_edit.textChanged.connect(lambda t: setattr(self._dashboard, 'name', t))
        tb.addWidget(self._name_edit)

        save_btn = QPushButton("💾 保存")
        save_btn.clicked.connect(self._on_save)
        save_btn.setFixedHeight(28)
        tb.addWidget(save_btn)

        refresh_data_btn = QPushButton("🔄 刷新数据")
        refresh_data_btn.setToolTip("重新查询所有图表数据")
        refresh_data_btn.clicked.connect(lambda: self.dataRefreshRequested.emit(self._dashboard.id))
        refresh_data_btn.setFixedHeight(28)
        tb.addWidget(refresh_data_btn)

        preview_btn = QPushButton("👁 预览")
        preview_btn.clicked.connect(self._on_preview)
        preview_btn.setFixedHeight(28)
        tb.addWidget(preview_btn)

        tb.addStretch()

        tb.addWidget(QLabel("列:"))
        self._grid_combo = QComboBox()
        self._grid_combo.addItems([str(n) for n in GRID_COLUMN_OPTIONS])
        self._grid_combo.setCurrentText("25")
        self._grid_combo.setFixedWidth(56)
        self._grid_combo.setStyleSheet("QComboBox { font-size: 12px; }")
        self._grid_combo.currentTextChanged.connect(lambda t: self._on_grid_changed(int(t)))
        tb.addWidget(self._grid_combo)

        tb.addWidget(QLabel("行高:"))
        self._row_height_combo = QComboBox()
        self._row_height_combo.addItems([str(n) for n in ROW_HEIGHT_OPTIONS])
        self._row_height_combo.setCurrentText("50")
        self._row_height_combo.setFixedWidth(70)
        self._row_height_combo.currentTextChanged.connect(lambda t: self._on_row_height_changed(int(t)))
        tb.addWidget(self._row_height_combo)

        tb.addWidget(QLabel("主题:"))
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(THEME_OPTIONS)
        self._theme_combo.currentTextChanged.connect(lambda t: self._on_theme_changed(t))
        tb.addWidget(self._theme_combo)

        # 网格线开关
        from PyQt6.QtWidgets import QCheckBox
        self._grid_lines_cb = QCheckBox("网格")
        self._grid_lines_cb.setChecked(True)
        self._grid_lines_cb.toggled.connect(self._on_grid_lines_toggled)
        tb.addWidget(self._grid_lines_cb)

        ai_btn = QPushButton("🤖 AI 助手")
        ai_btn.setFixedHeight(28)
        ai_btn.clicked.connect(self._on_ai_assistant)
        tb.addWidget(ai_btn)

        layout.addWidget(toolbar)

        # ===== 主区域：三栏布局（数据源 | 预览 | 模板+配置） =====
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setHandleWidth(3)

        # ---- 左侧：数据源 ----
        self._data_source_panel = DataSourcePanel()
        self._data_source_panel.sourceDoubleClicked.connect(self._on_source_selected)
        self._data_source_panel.importExcelRequested.connect(self._on_import_excel)
        self._data_source_panel.importMySQLRequested.connect(self._on_import_mysql)
        self._data_source_panel.tableClicked.connect(self._on_table_clicked)
        self._data_source_panel.refreshRequested.connect(self._refresh_data_sources)
        self._main_splitter.addWidget(self._data_source_panel)

        # ---- 中间：预览区 ----
        self._preview_webview = QWebEngineView()
        self._preview_webview.setStyleSheet("background: #F0F2F5;")
        self._preview_webview.page().setBackgroundColor(QColor("#F0F2F5"))
        self._preview_webview.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        # 设置 QWebChannel
        self._channel = QWebChannel(self._preview_webview.page())
        self._channel.registerObject("bridge", self._bridge)
        self._preview_webview.page().setWebChannel(self._channel)
        self._bridge.set_page(self._preview_webview.page())
        self._bridge.actionReceived.connect(self._on_js_action)
        self._main_splitter.addWidget(self._preview_webview)

        # ---- 右侧：图表模板（上 1/3）+ 图表配置（下 2/3） ----
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setHandleWidth(3)

        # 图表模板库
        from .models import ChartType
        template_scroll = QScrollArea()
        template_scroll.setWidgetResizable(True)
        template_scroll.setFrameShape(QFrame.Shape.NoFrame)
        template_frame = QFrame()
        template_layout = QVBoxLayout(template_frame)
        template_layout.setContentsMargins(6, 6, 6, 6)
        template_layout.setSpacing(2)
        template_header = QLabel("📈 图表模板（选中数据表 → 点击类型添加）")
        template_header.setStyleSheet("font-size: 11px; color: #666;")
        template_layout.addWidget(template_header)

        categories = ChartType.category_map()
        for cat_name, types in categories.items():
            cat_label = QLabel(f"  {cat_name}")
            cat_label.setStyleSheet(
                "font-size: 11px; color: #999; font-weight: bold;"
                "margin-top: 3px; margin-bottom: 1px;"
            )
            template_layout.addWidget(cat_label)

            n = len(types)
            if n <= 2:
                cols = n
            elif n <= 4:
                cols = n
            elif n == 6:
                cols = 3
            else:
                cols = min(n, 4)

            grid = QGridLayout()
            grid.setSpacing(3)
            for i, t in enumerate(types):
                name = _chart_display_name(t.value)
                btn = QPushButton(f"  {_chart_icon(t.value)}  {name}")
                btn.setToolTip(f"{t.value} — {name}")
                btn.setMinimumHeight(26)
                btn.setStyleSheet(
                    "QPushButton { font-size: 11px; border: 1px solid #D9D9D9;"
                    "border-radius: 3px; background: #FFF; padding: 2px 4px;"
                    "text-align: left; }"
                    "QPushButton:hover { border-color: #FF8C00; background: #FFF7E6; }"
                )
                btn.clicked.connect(lambda checked, ct=t.value: self._on_add_chart_template(ct))
                grid.addWidget(btn, i // cols, i % cols)
            template_layout.addLayout(grid)
        template_layout.addStretch()
        template_scroll.setWidget(template_frame)
        right_splitter.addWidget(template_scroll)

        # 配置面板
        self._chart_config = ChartConfigPanel(report_manager=self._report_manager)
        self._chart_config.chartConfigChanged.connect(self._on_chart_config_changed)
        self._chart_config.chartRemoved.connect(self._on_chart_removed)
        self._chart_config.chartTypeChanged.connect(self._on_chart_type_changed)
        self._chart_config.sourceChanged.connect(self._on_chart_source_changed)
        right_splitter.addWidget(self._chart_config)

        # _chart_config 创建后再连接 sourcesLoaded（避免 AttributeError）
        self._data_source_panel.sourcesLoaded.connect(self._chart_config.set_available_sources)

        right_splitter.setStretchFactor(0, 1)  # 模板 1/3
        right_splitter.setStretchFactor(1, 2)  # 配置 2/3
        right_splitter.setSizes([200, 450])

        self._main_splitter.addWidget(right_splitter)

        # 三栏初始比例：数据源 1 : 预览 3 : 右侧 1.5
        # 防止面板被收缩到消失
        self._main_splitter.setCollapsible(0, False)
        self._main_splitter.setCollapsible(1, False)
        self._main_splitter.setCollapsible(2, False)
        right_splitter.setCollapsible(0, False)
        right_splitter.setCollapsible(1, False)

        # 设置各面板最小宽度
        self._data_source_panel.setMinimumWidth(180)
        self._preview_webview.setMinimumWidth(300)
        template_scroll.setMinimumWidth(180)
        self._chart_config.setMinimumWidth(180)
        template_scroll.setMinimumHeight(100)
        self._chart_config.setMinimumHeight(150)

        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 3)
        self._main_splitter.setStretchFactor(2, 1)
        self._main_splitter.setSizes([220, 700, 380])

        # 连接 splitter 变化信号以持久化宽度
        self._main_splitter.splitterMoved.connect(self._on_splitter_moved)
        right_splitter.splitterMoved.connect(self._on_splitter_moved)
        self._right_splitter = right_splitter

        layout.addWidget(self._main_splitter, 1)

        # 延迟恢复用户上次调整的分隔宽度
        QTimer.singleShot(0, self._restore_splitter_state)

    def _save_splitter_state(self):
        """保存 splitter 宽度到运行状态"""
        sizes = {
            'main': [int(s) for s in self._main_splitter.sizes()],
            'right': [int(s) for s in self._right_splitter.sizes()],
        }
        import sys
        main_mod = sys.modules.get('__main__')
        if main_mod:
            mf = getattr(main_mod, 'MainFrame', None)
            if mf and hasattr(mf, 'instance') and mf.instance:
                mf.instance.save_user_runtime_state_patch(
                    {'bi_designer_splitter_sizes': sizes}, immediate=False
                )

    def _restore_splitter_state(self):
        """从运行状态恢复 splitter 宽度（确保不小于最小值）"""
        import sys
        main_mod = sys.modules.get('__main__')
        if main_mod:
            mf = getattr(main_mod, 'MainFrame', None)
            if mf and hasattr(mf, 'instance') and mf.instance:
                state = (mf.instance.runtime_state or {}).get('bi_designer_splitter_sizes')
                if isinstance(state, dict):
                    if 'main' in state and len(state['main']) == 3:
                        sizes = [max(int(s), 180) for s in state['main']]
                        sizes[1] = max(sizes[1], 300)  # 预览区最小 300
                        self._main_splitter.setSizes(sizes)
                    if 'right' in state and len(state['right']) == 2:
                        sizes = [max(int(s), 100) for s in state['right']]
                        sizes[1] = max(sizes[1], 150)  # 配置区最小 150
                        self._right_splitter.setSizes(sizes)

    def _on_splitter_moved(self, pos, index):
        """splitter 拖拽后延迟保存宽度（防抖 500ms）"""
        if hasattr(self, '_splitter_save_timer') and self._splitter_save_timer.isActive():
            self._splitter_save_timer.stop()
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.timeout.connect(self._save_splitter_state)
        self._splitter_save_timer.start(500)

    # ===== 网格配置持久化 =====

    def _save_grid_config(self):
        """保存网格配置（列数、行高、主题、网格线）到用户运行状态，跨会话持久化"""
        config = {
            'columns': self._dashboard.grid_columns,
            'row_height': self._dashboard.grid_row_height,
            'theme': self._dashboard.theme,
            'grid_lines': self._grid_lines_cb.isChecked() if hasattr(self, '_grid_lines_cb') else True,
        }
        import sys
        main_mod = sys.modules.get('__main__')
        if main_mod:
            mf = getattr(main_mod, 'MainFrame', None)
            if mf and hasattr(mf, 'instance') and mf.instance:
                mf.instance.save_user_runtime_state_patch(
                    {'bi_dashboard_grid_config': config}, immediate=True
                )

    @staticmethod
    def _restore_grid_config() -> dict:
        """从用户运行状态恢复网格配置，无保存记录时返回默认值"""
        import sys
        main_mod = sys.modules.get('__main__')
        if main_mod:
            mf = getattr(main_mod, 'MainFrame', None)
            if mf and hasattr(mf, 'instance') and mf.instance:
                state = (mf.instance.runtime_state or {}).get('bi_dashboard_grid_config')
                if isinstance(state, dict):
                    return {
                        'columns': max(1, min(40, int(state.get('columns', 25)))),
                        'row_height': max(20, min(500, int(state.get('row_height', 50)))),
                        'theme': state.get('theme', 'light'),
                        'grid_lines': state.get('grid_lines', True),
                    }
        return {'columns': 25, 'row_height': 50, 'theme': 'light', 'grid_lines': True}

    # ===== 仪表盘加载 =====

    def load_dashboard(self, dashboard: DashboardDefinition, data_map: dict = None):
        """加载已有仪表盘进行编辑 — 使用用户保存的网格偏好"""
        self._dashboard = dashboard
        self._data_map = data_map or {}
        self._name_edit.setText(dashboard.name)

        # 从持久化状态恢复网格配置（全局生效）
        saved_grid = self._restore_grid_config()
        self._dashboard.grid_columns = saved_grid['columns']
        self._dashboard.grid_row_height = saved_grid['row_height']
        self._dashboard.theme = saved_grid.get('theme', 'light')
        grid_lines = saved_grid.get('grid_lines', True)

        self._grid_combo.blockSignals(True)
        self._row_height_combo.blockSignals(True)
        self._theme_combo.blockSignals(True)
        self._grid_combo.setCurrentText(str(self._dashboard.grid_columns))
        self._row_height_combo.setCurrentText(str(self._dashboard.grid_row_height))
        self._theme_combo.setCurrentText(self._dashboard.theme)
        self._grid_combo.blockSignals(False)
        self._row_height_combo.blockSignals(False)
        self._theme_combo.blockSignals(False)
        if hasattr(self, '_grid_lines_cb'):
            self._grid_lines_cb.setChecked(grid_lines)
        self._refresh_html()

    def new_dashboard(self):
        """新建空白仪表盘 — 使用用户上次保存的网格偏好"""
        self._dashboard = DashboardDefinition()
        self._data_map = {}
        self._selected_source = None
        self._name_edit.setText("未命名仪表盘")

        # 从持久化状态恢复网格配置
        saved_grid = self._restore_grid_config()
        self._dashboard.grid_columns = saved_grid.get('columns', 3)
        self._dashboard.grid_row_height = saved_grid.get('row_height', 320)
        self._dashboard.theme = saved_grid.get('theme', 'light')
        grid_lines = saved_grid.get('grid_lines', True)

        self._grid_combo.blockSignals(True)
        self._row_height_combo.blockSignals(True)
        self._theme_combo.blockSignals(True)
        self._grid_combo.setCurrentText(str(self._dashboard.grid_columns))
        self._row_height_combo.setCurrentText(str(self._dashboard.grid_row_height))
        self._theme_combo.setCurrentText(self._dashboard.theme)
        self._grid_combo.blockSignals(False)
        self._row_height_combo.blockSignals(False)
        self._theme_combo.blockSignals(False)
        if hasattr(self, '_grid_lines_cb'):
            self._grid_lines_cb.setChecked(grid_lines)
        self._chart_config.clear()
        self._refresh_html()

    # ===== HTML 更新 =====

    def _refresh_html(self):
        """重新生成并加载 HTML — 使用 pyecharts 预渲染每个图表"""
        try:
            echarts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'echarts')
            # 配置 pyecharts 离线路径 (首次调用时)
            set_echarts_base_dir(echarts_dir)

            config = self._dashboard.to_dict()
            chart_count = len(config.get('charts', []))
            data_chart_ids = list(self._data_map.keys())
            data_total = sum(len(v) for v in self._data_map.values())
            _ui_output(f"[BI 报表] 刷新HTML: {chart_count} 个图表, 数据: {data_total} 行 ({','.join(data_chart_ids[:3])}...)")

            # ===== pyecharts 预渲染：为每个图表生成 ECharts option JSON =====
            for chart_cfg in config.get('charts', []):
                chart_id = chart_cfg.get('id', '')
                data = self._data_map.get(chart_id, [])
                # 调用 pyecharts 渲染器，它会将 _echarts_option 附着到 chart_widget 上
                for chart_widget in self._dashboard.charts:
                    if chart_widget.id == chart_id:
                        render_chart_html_safe(chart_widget, data)
                        opt = getattr(chart_widget, '_echarts_option', None)
                        if opt:
                            chart_cfg['_echarts_option'] = opt
                        # card/table 是纯 HTML，无 _echarts_option，需独立注入
                        if chart_widget.chart_type in ('card', 'table'):
                            chart_cfg['_prerendered_html'] = render_chart_html_safe(chart_widget, data)
                        break

            html = build_dashboard_html(config, use_cdn=False, embed_data=False, echarts_dir=echarts_dir)

            # 嵌入中国地图 GeoJSON（避免 fetch file:// 受限）
            china_path = os.path.join(echarts_dir, 'china.json')
            inject_parts = []
            if os.path.exists(china_path):
                with open(china_path, 'r', encoding='utf-8') as f:
                    china_json = f.read()
                inject_parts.append(f'<script>window._CHINA_GEO = {china_json};</script>')
            data_json = json_dumps_safe(self._data_map, ensure_ascii=False)
            inject_parts.append(f"<script>window._INITIAL_DATA = {data_json}; window.setEditMode(true);</script>")
            html = html.replace('</body>', '\n'.join(inject_parts) + '\n</body>')

            base_url = QUrl.fromLocalFile(echarts_dir)
            self._preview_webview.setHtml(html, base_url)
        except Exception as e:
            _ui_output(f"[BI 报表] 刷新HTML失败: {e}")
            import traceback
            traceback.print_exc()

    # ===== 事件处理 =====

    def _on_source_selected(self, source_type: str, source_id: str, name: str, fields: list):
        """双击数据源 → 弹出快速字段配置对话框"""
        dialog = _QuickChartDialog(source_type, source_id, name, fields, self)
        # 如果用户先点击了图表模板按钮，预选图表类型
        if self._pending_chart_type:
            idx = dialog._type_combo.findData(self._pending_chart_type)
            if idx >= 0:
                dialog._type_combo.setCurrentIndex(idx)
            self._pending_chart_type = None
        if dialog.exec() == QDialog.DialogCode.Accepted:
            chart_def = dialog.get_chart_definition()
            self._add_chart_from_dialog(chart_def)

    def _add_chart_from_dialog(self, chart_def: dict):
        """从快速配置对话框添加图表"""
        chart = ChartWidget(
            chart_type=chart_def.get('chart_type', 'bar'),
            title=chart_def.get('title', '未命名图表'),
            data_source_type=chart_def.get('data_source_type', 'report'),
            data_source_id=chart_def.get('data_source_id', ''),
            data_source_name=chart_def.get('data_source_name', ''),
            x_field=chart_def.get('x_field', ''),
            y_fields=chart_def.get('y_fields', []),
            aggregate_funcs=chart_def.get('aggregate_funcs', {}),
            position=self._next_grid_position(),
        )

        self._dashboard.charts.append(chart)
        # 选中新图表以在配置面板显示
        self._select_chart_in_panel(chart.id)
        _ui_output(f"[BI 报表] 已添加图表「{chart.title}」，正在查询数据...")

        self._refresh_html()
        self.dataRefreshRequested.emit(self._dashboard.id)

    def _on_table_clicked(self, source_type: str, source_id: str, name: str, fields: list):
        """单击数据源 → 记录选中状态"""
        self._selected_source = {'type': source_type, 'id': source_id, 'name': name, 'fields': fields}
        _ui_output(f"[BI 报表] 已选中数据表「{name}」({len(fields)} 个字段)，点击图表模板即可添加")

    def _on_add_chart_template(self, chart_type: str):
        """点击图表模板按钮 —— 有选中表时直接添加，否则提示"""
        _ui_output(f"[BI DEBUG] _on_add_chart_template 被调用 chart_type={chart_type} selected_source={self._selected_source is not None}")
        if not self._selected_source:
            _ui_output("[BI 报表] 请先在左侧单击选中一个数据表，再点击图表类型")
            return
        src = self._selected_source
        fields = src['fields']

        # 智能选取 X/Y 字段：第一个文本字段做 X，第一个数值字段做 Y
        x_field = ''
        y_field = ''
        for f in fields:
            if isinstance(f, dict):
                key = f.get('key', '')
                dtype = f.get('data_type', 'text')
            elif isinstance(f, (tuple, list)) and len(f) >= 2:
                key = f[0]
                dtype = 'text'
            else:
                key = str(f)
                dtype = 'text'
            if not x_field:
                x_field = key
            if dtype == 'number' and not y_field:
                y_field = key
        if not y_field:
            y_field = x_field  # 没有数值字段时用第一个字段兜底

        type_name = _chart_display_name(chart_type)
        chart = ChartWidget(
            chart_type=chart_type,
            title=f"{type_name} - {src['name']}",
            data_source_type=src['type'],
            data_source_id=src['id'],
            data_source_name=src['name'],
            x_field=x_field,
            y_fields=[y_field],
            aggregate_funcs={y_field: 'SUM'},
            position=self._next_grid_position(),
        )
        self._dashboard.charts.append(chart)
        self._select_chart_in_panel(chart.id)
        _ui_output(f"[BI 报表] 已添加「{chart.title}」")
        # 先渲染卡片，再请求数据（数据到达后增量注入）
        self._refresh_html()
        self.dataRefreshRequested.emit(self._dashboard.id)

    def _next_grid_position(self) -> tuple:
        """计算下一个可用网格位置（扫描网格，跳过已被占据的格子，不覆盖已有图表）"""
        charts = self._dashboard.charts
        cols = max(1, self._dashboard.grid_columns)
        if not charts:
            return (0, 0)

        # 构建占用表 (稀疏网格，只记录被占的格子)
        occupied = set()
        for c in charts:
            r0, c0 = int(c.position[0]), int(c.position[1])
            rs = max(1, int(c.size[0]))
            cs = max(1, int(c.size[1]))
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r0 + dr, c0 + dc))

        # 逐行扫描找第一个空位
        row = 0
        while True:
            for col in range(cols):
                if (row, col) not in occupied:
                    return (row, col)
            row += 1  # 当前行满了，下一行

    def _on_chart_config_changed(self, data: dict):
        """配置面板数据变更 → 即时重新生成 pyecharts option + 更新 JS"""
        chart_id = data.get('id', '')
        # 如果类型刚被 _on_chart_type_changed 处理过，跳过本次（避免双重刷新覆盖）
        if getattr(self, '_skip_next_config_change', None) == chart_id:
            del self._skip_next_config_change
            return
        changed_chart = None
        for chart in self._dashboard.charts:
            if chart.id == chart_id:
                chart.chart_type = data.get('chart_type', chart.chart_type)
                chart.title = data.get('title', chart.title)
                # 数据源字段：只在传入非空值时更新
                if data.get('data_source_type'):
                    chart.data_source_type = data['data_source_type']
                if data.get('data_source_id'):
                    chart.data_source_id = data['data_source_id']
                if data.get('data_source_name'):
                    chart.data_source_name = data['data_source_name']
                chart.x_field = data.get('x_field', chart.x_field)
                chart.y_fields = data.get('y_fields', chart.y_fields)
                chart.aggregate_funcs = data.get('aggregate_funcs', chart.aggregate_funcs)
                chart.color_field = data.get('color_field', chart.color_field)
                chart.size_field = data.get('size_field', chart.size_field)
                chart.enable_cross_filter = data.get('enable_cross_filter', chart.enable_cross_filter)
                chart.enable_drill = data.get('enable_drill', chart.enable_drill)
                chart.drill_path = data.get('drill_path', chart.drill_path)
                chart.filters = data.get('filters', chart.filters)
                chart.show_markline_avg = data.get('show_markline_avg', chart.show_markline_avg)
                # 样式合并（而非覆盖）：配置面板只传部分字段，需保留其余字段
                incoming_style = data.get('style_config', {}) or {}
                current_style = dict(chart.style_config) if chart.style_config else {}
                current_style.update(incoming_style)
                chart.style_config = current_style
                changed_chart = chart
                break
        if not changed_chart:
            return

        # 同步数据到配置面板（用于筛选多选选项）
        rows = self._data_map.get(chart_id, [])
        if hasattr(self, '_chart_config'):
            self._chart_config.set_chart_data_rows(rows)

        # 立即用当前数据重新生成 pyecharts option
        render_chart_html_safe(changed_chart, rows)
        opt = getattr(changed_chart, '_echarts_option', None)

        # 推送 config + option/HTML 到 JS
        cfg = json_dumps_safe(changed_chart.__dict__, ensure_ascii=False)
        ct = changed_chart.chart_type
        if ct in ('card', 'table'):
            # card/table 推送预渲染 HTML
            html = render_chart_html_safe(changed_chart, rows)
            html_escaped = json_dumps_safe(html, ensure_ascii=False)
            self._bridge.run_js(
                f"(function(){{"
                f"var c={cfg};"
                f"c._prerendered_html={html_escaped};"
                f"window.updateChartConfig('{chart_id}', c);"
                f"}})();"
            )
        elif opt:
            self._bridge.run_js(
                f"(function(){{"
                f"var c={cfg};"
                f"c._echarts_option={opt};"
                f"window.updateChartConfig('{chart_id}', c);"
                f"}})();"
            )
        else:
            self._bridge.run_js(f"window.updateChartConfig('{chart_id}', {cfg});")

        # 防抖仅刷新当前图表数据（不全量刷新）
        if hasattr(self, '_refresh_timer') and self._refresh_timer.isActive():
            self._refresh_timer.stop()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(
            lambda cid=chart_id, cc=changed_chart: self._refresh_single_chart(cid, cc))
        self._refresh_timer.start(800)

    def _refresh_single_chart(self, chart_id: str, chart=None):
        """仅刷新单个图表的数据 — 用 pyecharts 预渲染 option 后注入 JS"""
        try:
            if not self._report_manager or not self._db:
                return
            if chart is None:
                for c in self._dashboard.charts:
                    if c.id == chart_id:
                        chart = c
                        break
            if not chart:
                return
            rows = self._report_manager.query_chart_data(chart)
            if rows:
                self._data_map[chart_id] = rows
                # 用 pyecharts 重新生成 option JSON
                render_chart_html_safe(chart, rows)
                opt = getattr(chart, '_echarts_option', None)
                self._bridge.inject_chart_data(chart_id, rows)
                if opt:
                    # dump_options_with_quotes 输出是 JS 对象字面量，直接嵌入 f-string
                    self._bridge.run_js(
                        f"(function(){{"
                        f"var c=(CONFIG.charts||[]).find(function(x){{return x.id==='{chart_id}';}});"
                        f"if(c) c._echarts_option={opt};"
                        f"var inst=chartInstances['{chart_id}'];"
                        f"if(inst&&!inst.isDisposed()){{"
                        f"try{{inst.setOption({opt},{{notMerge:true}});}}catch(e){{}}"
                        f"}}"
                        f"}})();"
                    )
                _ui_output(f"[BI 报表] 图表「{chart.title}」数据已刷新 ({len(rows)} 行)")
        except Exception as e:
            _ui_output(f"[BI 报表] 单图表刷新失败: {e}")

    def _on_chart_removed(self, chart_id: str):
        """删除图表"""
        self._dashboard.charts = [c for c in self._dashboard.charts if c.id != chart_id]
        if chart_id in self._data_map:
            del self._data_map[chart_id]
        self._refresh_html()

    def _on_chart_type_changed(self, chart_id: str, new_type: str):
        """图表类型变更 → 即时重新生成 pyecharts option + 更新 JS"""
        changed_chart = None
        for chart in self._dashboard.charts:
            if chart.id == chart_id:
                chart.chart_type = new_type
                changed_chart = chart
                break
        if not changed_chart:
            return

        # 标记跳过紧随的 _on_chart_config_changed（避免双重刷新）
        self._skip_next_config_change = chart_id

        # 立即用当前数据重新生成 pyecharts option (新类型)
        rows = self._data_map.get(chart_id, [])
        render_chart_html_safe(changed_chart, rows)  # 有数据则生成 option，无数据产生空占位
        opt = getattr(changed_chart, '_echarts_option', None)

        # 推送 config + 新 option 到 JS（一次性原子更新）
        cfg = json_dumps_safe(changed_chart.__dict__, ensure_ascii=False)
        if opt:
            self._bridge.run_js(
                f"(function(){{"
                f"var c={cfg};"
                f"c._echarts_option={opt};"
                f"window.updateChartConfig('{chart_id}', c);"
                f"}})();"
            )
        else:
            self._bridge.run_js(f"window.updateChartConfig('{chart_id}', {cfg});")

    def _on_chart_source_changed(self, source_type: str, source_id: str, source_name: str):
        """图表数据源切换 — 更新字段 + 重新查数据 + 刷新 HTML"""
        if not self._current_chart_id or not source_type or not source_id:
            return
        chart_id = self._current_chart_id
        for chart in self._dashboard.charts:
            if chart.id == chart_id:
                chart.data_source_type = source_type
                chart.data_source_id = source_id
                chart.data_source_name = source_name
                # 更新可用字段
                fields = self._lookup_chart_fields(source_type, source_id)
                if fields:
                    self._chart_config.set_available_fields(fields)
                # 同步数据源信息到配置面板
                self._chart_config._current_source_type = source_type
                self._chart_config._current_source_id = source_id
                _ui_output(f"[BI 报表] 图表「{chart.title}」数据源已切换: {source_name}")
                # 立即刷新数据
                self.dataRefreshRequested.emit(self._dashboard.id)
                if hasattr(self, '_refresh_timer') and self._refresh_timer.isActive():
                    self._refresh_timer.stop()
                break

    def _on_js_action(self, action: str, payload_json: str):
        payload = parse_action_payload(payload_json)

        if action == "page_ready":
            # 恢复网格线状态
            if self._grid_lines_cb.isChecked():
                self._bridge.run_js("window.toggleGridLines(true);")
        elif action == "chart_selected":
            chart_id = payload.get('chartId', '')
            self._select_chart_in_panel(chart_id)
        elif action == "chart_remove":
            chart_id = payload.get('chartId', '')
            self._on_chart_removed(chart_id)
            self._chart_config.clear()
        elif action == "chart_resize":
            chart_id = payload.get('chartId', '')
            size = payload.get('size', [1, 1])
            for chart in self._dashboard.charts:
                if chart.id == chart_id:
                    chart.size = (int(size[0]), int(size[1]))
                    break
        elif action == "chart_move":
            chart_id = payload.get('chartId', '')
            position = payload.get('position', [0, 0])
            for chart in self._dashboard.charts:
                if chart.id == chart_id:
                    chart.position = (int(position[0]), int(position[1]))
                    break
        elif action == "change_query":
            self.dataRefreshRequested.emit(self._dashboard.id)
        elif action == "export_ready":
            pass  # 设计器不需要 PNG 导出

    def _select_chart_in_panel(self, chart_id: str):
        """在配置面板中显示选中的图表（先填充字段下拉框，再加载图表数据）"""
        self._current_chart_id = chart_id
        for chart in self._dashboard.charts:
            if chart.id == chart_id:
                sources = self._data_source_panel._data_sources
                self._chart_config.set_available_sources(sources)
                fields = self._lookup_chart_fields(chart.data_source_type, chart.data_source_id)
                if fields:
                    self._chart_config.set_available_fields(fields)
                # 传入当前数据行，供筛选条件多选加载选项
                rows = self._data_map.get(chart_id, [])
                self._chart_config.set_chart_data_rows(rows)
                self._chart_config.load_chart(chart.__dict__)
                return

    def _lookup_chart_fields(self, source_type: str, source_id: str) -> list:
        """从数据源面板查找指定数据源的字段列表"""
        sources = self._data_source_panel._data_sources
        if source_type == 'report':
            for r in sources.get('reports', []):
                if r.get('id') == source_id:
                    return r.get('fields', [])
        elif source_type == 'excel':
            for ds in sources.get('excel_datasets', []):
                if ds.get('id') == source_id:
                    return ds.get('columns', [])
        elif source_type == 'mysql':
            for t in sources.get('mysql_tables', []):
                if t.get('name') == source_id:
                    return t.get('columns', [])
        return []

    def _on_grid_changed(self, cols: int):
        self._dashboard.grid_columns = cols
        self._save_grid_config()
        self._refresh_html()

    def _on_row_height_changed(self, height: int):
        self._dashboard.grid_row_height = height
        self._save_grid_config()
        self._refresh_html()

    def _on_theme_changed(self, theme: str):
        self._dashboard.theme = theme
        self._save_grid_config()
        self._refresh_html()

    def _on_grid_lines_toggled(self, show: bool):
        self._bridge.run_js(f"window.toggleGridLines({str(show).lower()});")
        self._save_grid_config()

    def _on_save(self):
        self.dashboardSaved.emit(self._dashboard.id)

    def _on_preview(self):
        """切换到查看模式预览"""
        self._on_save()  # 先保存
        # 由外部处理页面切换

    def _on_import_excel(self, file_path: str):
        """导入 Excel/CSV 文件为数据集"""
        if not self._db or not self._db.available:
            QMessageBox.warning(self, "数据库未连接", "请先在设置中配置并启用 MySQL 连接。")
            return
        try:
            from .excel_importer import ExcelImporter
            importer = ExcelImporter(self._db)
            dataset = importer.import_file(file_path)
            if self._excel_repo:
                self._excel_repo.save(dataset)
            _ui_output(f"[BI 报表] 已导入 Excel 数据集「{dataset.name}」({dataset.row_count} 行)")
            self._refresh_data_sources()
        except Exception as e:
            _ui_output(f"[BI 报表] Excel 导入失败: {e}")
            QMessageBox.warning(self, "导入失败", str(e))

    def _on_import_mysql(self):
        """弹出 MySQL 表选择对话框，将选中的表添加为数据源"""
        if not self._db or not self._db.available:
            QMessageBox.warning(self, "数据库未连接", "请先在设置中配置并启用 MySQL 连接。")
            return
        from ..views.table_selector_panel import _MySQLTableDialog
        dlg = _MySQLTableDialog(self._db, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            table_name = dlg.selected_table
            if table_name:
                # 查询表信息
                try:
                    cols = self._db.execute(f"SHOW COLUMNS FROM `{table_name}`")
                    columns = []
                    if cols:
                        for c in cols:
                            col_name = c.get('Field', '')
                            col_type = c.get('Type', 'text')
                            col_comment = c.get('Comment', '') or col_name
                            columns.append({
                                'key': col_name,
                                'label': col_comment,
                                'data_type': _mysql_type_to_generic(col_type),
                            })
                    cnt = self._db.execute(f"SELECT COUNT(*) AS cnt FROM `{table_name}`")
                    row_count = cnt[0].get('cnt', 0) if cnt else 0
                except Exception as e:
                    QMessageBox.warning(self, "查询失败", f"无法查询表 {table_name}: {e}")
                    return

                # 添加到数据源面板
                self._data_source_panel.add_mysql_table(table_name, row_count, columns)
                _ui_output(f"[BI 报表] 已添加 MySQL 表「{table_name}」({row_count} 行)")

    def _refresh_data_sources(self):
        """导入后刷新数据源面板"""
        if not self._db or not self._db.available:
            return
        try:
            sources = {'reports': [], 'excel_datasets': [], 'mysql_tables': []}

            # 自定义报表：报表-直连表
            rpt_tables = self._db.execute(
                "SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE '报表-%'"
            )
            if rpt_tables:
                for t in rpt_tables:
                    name = t.get('TABLE_NAME', '')
                    row_count = t.get('TABLE_ROWS', 0) or 0
                    display_name = name[3:] if name.startswith('报表-') else name
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
                                # 过滤系统字段和 ID 字段
                                if col_name in ('_id', '_hash', '_sync_time', '_row_id', 'id'):
                                    continue
                                if col_name.endswith('_id'):
                                    continue
                                fields.append({
                                    'key': col_name,
                                    'label': c.get('COLUMN_COMMENT', '') or col_name,
                                    'data_type': _mysql_type_to_generic(c.get('DATA_TYPE', 'text')),
                                })
                    except Exception:
                        pass
                    sources['reports'].append({
                        'id': name,
                        'name': display_name,
                        'row_count': row_count,
                        'fields': fields,
                        'table_name': name,
                    })

            # Excel 数据集
            if self._excel_repo:
                for ds in self._excel_repo.list_all():
                    sources['excel_datasets'].append({
                        'id': ds.id,
                        'name': ds.name,
                        'row_count': ds.row_count,
                        'columns': ds.columns,
                        'table_name': ds.mysql_table,
                    })

            # MySQL 表：只显示已导入的表（保留之前的导入记录，刷新行数）
            imported_tables = self._data_source_panel._data_sources.get('mysql_tables', [])
            for t in imported_tables:
                name = t.get('name', '')
                row_count = t.get('row_count', 0)
                if name and self._db.table_exists(name):
                    # 刷新行数
                    try:
                        cnt = self._db.execute(f"SELECT COUNT(*) AS cnt FROM `{name}`")
                        row_count = cnt[0].get('cnt', 0) if cnt else 0
                    except Exception:
                        pass
                    sources['mysql_tables'].append({
                        'name': name,
                        'row_count': row_count,
                        'columns': t.get('columns', []),
                    })

            self._data_source_panel.set_data_sources(sources)
            _ui_output(f"[BI 报表] 数据源已刷新: {len(sources['reports'])} 个报表, {len(sources['excel_datasets'])} 个Excel, {len(sources['mysql_tables'])} 个MySQL表")
        except Exception as e:
            _ui_output(f"[BI 报表] 刷新数据源失败: {e}")

    def _on_ai_assistant(self):
        """打开 AI 助手对话框，通过自然语言创建图表"""
        # 检查是否配置了 API
        config = self._load_config()
        providers_cfg = config.get('llm_providers', {})

        # 兼容新旧两种格式
        enabled_providers = {}
        if 'providers' in providers_cfg:
            # 新格式：{"providers": [{id, api_key, enabled, ...}, ...], "active": "..."}
            for pdata in providers_cfg.get('providers', []):
                if isinstance(pdata, dict) and pdata.get('enabled') and pdata.get('api_key', '').strip():
                    enabled_providers[pdata.get('id', '')] = pdata
        else:
            # 旧格式：{"deepseek": {api_key, enabled, ...}, "active": "..."}
            enabled_providers = {pid: cfg for pid, cfg in providers_cfg.items()
                                if isinstance(cfg, dict) and cfg.get('enabled') and cfg.get('api_key') and pid != 'active'}

        if not enabled_providers:
            _ui_output("[BI 报表] AI 助手未配置，请先在 设置 → API 配置 中启用至少一个 LLM 提供商并填写 API Key")
            QMessageBox.information(self, "AI 助手未配置",
                                    "请先在 设置 → API 配置 中启用至少一个 LLM 提供商并填写 API Key。")
            return

        # 获取可用数据源信息
        sources_info = []
        for rinfo in self._data_source_panel._data_sources.get('reports', []):
            if isinstance(rinfo, dict):
                src = {
                    'id': rinfo.get('id', ''),
                    'name': rinfo.get('name', ''),
                    'row_count': rinfo.get('row_count', 0),
                    'fields': rinfo.get('fields', []),
                }
                sources_info.append(src)

        if not sources_info:
            _ui_output("[BI 报表] 没有可用的数据源，请先配置自定义报表或在设置中加载数据")
            QMessageBox.information(self, "无数据源", "没有可用的数据源，请先配置自定义报表。")
            return

        # 打开 AI 对话对话框
        from .ai_assistant import AIAssistant
        assistant = AIAssistant(providers_cfg)

        dialog = AIChartDialog(self, assistant, sources_info)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            chart_def = dialog.get_chart_definition()
            if chart_def:
                self._add_chart_from_ai(chart_def)

    def _add_chart_from_ai(self, chart_def: dict):
        """从 AI 返回的定义添加图表"""
        from .models import ChartWidget, _new_id
        chart = ChartWidget(
            id=_new_id(),
            chart_type=chart_def.get('chart_type', 'bar'),
            title=chart_def.get('title', 'AI 图表'),
            x_field=chart_def.get('x_field', ''),
            y_fields=chart_def.get('y_fields', []),
            aggregate_funcs=chart_def.get('aggregate_funcs', {}),
            color_field=chart_def.get('color_field', ''),
            position=self._next_grid_position(),
            data_source_type=chart_def.get('data_source_type', 'report'),
            data_source_id=chart_def.get('data_source_id', ''),
            data_source_name=chart_def.get('data_source_name', ''),
        )
        self._dashboard.charts.append(chart)
        self._select_chart_in_panel(chart.id)
        _ui_output(f"[BI 报表] AI 已创建图表「{chart.title}」，正在查询数据...")
        self._refresh_html()
        self.dataRefreshRequested.emit(self._dashboard.id)

    def _load_config(self) -> dict:
        """加载主配置（避免循环导入）"""
        import sys
        main_mod = sys.modules.get('__main__')
        if main_mod:
            load_config_fn = getattr(main_mod, 'load_config', None)
            if load_config_fn:
                return load_config_fn()
        return {}

    # ===== 数据刷新 =====

    def refresh_data(self, data_map: dict[str, list]):
        """刷新数据 —— 增量注入 pyecharts option + 数据，不重载页面"""
        self._data_map = data_map
        if self._dashboard.charts:
            # 为每个图表重新生成 pyecharts option
            option_map = {}
            for chart_widget in self._dashboard.charts:
                chart_id = chart_widget.id
                data = data_map.get(chart_id, [])
                if data:
                    render_chart_html_safe(chart_widget, data)
                    opt = getattr(chart_widget, '_echarts_option', None)
                    if opt:
                        option_map[chart_id] = opt
            # 注入最新 option + 数据
            self._bridge.inject_all_data(data_map, option_map if option_map else None)
            _ui_output(f"[BI 报表] 数据已刷新，共 {len(data_map)} 个图表")
        else:
            _ui_output(f"[BI 报表] 数据已刷新，仪表盘无图表")

    def add_chart_with_data(self, chart: ChartWidget, data: list):
        """直接添加图表（如 AI 助手创建）"""
        self._dashboard.charts.append(chart)
        self._data_map[chart.id] = data
        self._refresh_html()


# ===== 快速字段配置对话框 =====

class _QuickChartDialog(QDialog):
    """选择数据源后快速配置图表"""

    def __init__(self, source_type: str, source_id: str, name: str, fields: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快速配置图表")
        self.setMinimumSize(420, 350)
        self._source_type = source_type
        self._source_id = source_id
        self._source_name = name

        layout = QVBDialog(self)

        layout.addWidget(QLabel(f"<b>数据源:</b> {name} ({source_type})"))

        # 图表类型
        layout.addWidget(QLabel("图表类型:"))
        self._type_combo = QComboBox()
        categories = ChartType.category_map()
        for cat_name, types in categories.items():
            for t in types:
                self._type_combo.addItem(f"{_chart_icon(t.value)} {_chart_display_name(t.value)}", t.value)
        layout.addWidget(self._type_combo)

        # 标题
        layout.addWidget(QLabel("图表标题:"))
        self._title_edit = QLineEdit(name)
        layout.addWidget(self._title_edit)

        # X 轴
        layout.addWidget(QLabel("X 轴（维度）:"))
        self._x_combo = QComboBox()
        layout.addWidget(self._x_combo)

        # Y 轴
        layout.addWidget(QLabel("Y 轴（度量）:"))
        y_layout = QHBoxLayout()
        self._y_combo = QComboBox()
        y_layout.addWidget(self._y_combo, 1)
        self._agg_combo = QComboBox()
        self._agg_combo.addItems(["SUM", "AVG", "COUNT", "MAX", "MIN"])
        y_layout.addWidget(QLabel("聚合:"))
        y_layout.addWidget(self._agg_combo)
        layout.addLayout(y_layout)

        # 填充字段
        self._fields = fields
        for f in fields:
            if isinstance(f, dict):
                name = f.get('key') or f.get('name', '')
                label = f.get('label', name)
                dtype = f.get('data_type', 'text')
            elif isinstance(f, (tuple, list)) and len(f) >= 2:
                name = f[0]
                label = f[1]
                dtype = 'text'
            else:
                name = str(f)
                label = name
                dtype = 'text'
            display = f"{label}"
            self._x_combo.addItem(display, name)
            self._y_combo.addItem(display, name)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_chart_definition(self) -> dict:
        """获取图表配置字典"""
        y_field = self._y_combo.currentData() or self._y_combo.currentText()
        agg = self._agg_combo.currentText()
        return {
            'chart_type': self._type_combo.currentData() or 'bar',
            'title': self._title_edit.text(),
            'x_field': self._x_combo.currentData() or self._x_combo.currentText(),
            'y_fields': [y_field],
            'aggregate_funcs': {y_field: agg},
            'data_source_type': self._source_type,
            'data_source_id': self._source_id,
            'data_source_name': self._source_name,
        }


# ===== AI 助手对话框 =====

class AIChartDialog(QDialog):
    """AI 数据分析助手 — 支持问答、分析、总结、图表创建"""

    _CHART_TYPES_INFO = """可用图表类型:
bar(柱状图), line(折线图), pie(饼图), scatter(散点图), area(面积图),
table(表格), card(指标卡), gauge(仪表盘), funnel(漏斗图), treemap(树图),
sunburst(旭日图), heatmap(热力图), stacked_bar(堆叠柱状), stacked_area(堆叠面积),
radar(雷达图), sankey(桑基图), word_cloud(词云)"""

    def __init__(self, parent, assistant, sources_info: list):
        super().__init__(parent)
        model_name = assistant.current_model_name if hasattr(assistant, 'current_model_name') else 'AI'
        self.setWindowTitle(f"AI 数据分析助手 — {model_name}")
        self.setMinimumSize(700, 550)
        self._assistant = assistant
        self._sources_info = sources_info
        self._chart_def = None
        self._chat_history = []

        layout = QVBoxLayout(self)

        # ---- 数据源信息（可折叠） ----
        src_text = "📊 可用数据源:\n"
        for src in sources_info:
            fields_str = ", ".join(
                f.get('label', f.get('key', str(f))) if isinstance(f, dict) else str(f)
                for f in src.get('fields', [])[:8]
            )
            src_text += f"  • {src['name']} ({src['row_count']} 行): {fields_str}\n"
        info_label = QLabel(src_text)
        info_label.setStyleSheet("font-size: 11px; color: #666; background: #F5F5F5; padding: 8px; border-radius: 4px;")
        info_label.setWordWrap(True)
        info_label.setMaximumHeight(80)
        layout.addWidget(info_label)

        # ---- 对话历史 ----
        self._chat_view = QTextEdit()
        self._chat_view.setReadOnly(True)
        self._chat_view.setStyleSheet("QTextEdit { font-size: 13px; border: 1px solid #E8E8E8; border-radius: 4px; }")
        layout.addWidget(self._chat_view, 1)

        # ---- 输入区域 ----
        input_frame = QFrame()
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        self._input_edit = QTextEdit()
        self._input_edit.setPlaceholderText(
            "💬 问数据: 哪个大区的合同金额最高？\n"
            "📈 分析: 分析各产品类型的销售趋势\n"
            "📊 图表: 按月份统计合同数量的柱状图\n"
            "📋 总结: 总结本季度核心指标\n"
            "（Enter 发送，Shift+Enter 换行）"
        )
        self._input_edit.setMaximumHeight(72)
        self._input_edit.installEventFilter(self)
        input_layout.addWidget(self._input_edit, 1)

        send_btn = QPushButton("发送")
        send_btn.setFixedSize(60, 44)
        send_btn.setStyleSheet("QPushButton { background: #1890FF; color: #FFF; border: none; border-radius: 4px; font-weight: bold; } QPushButton:hover { background: #40A9FF; }")
        send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(send_btn)

        layout.addWidget(input_frame)

        # ---- 底部按钮 ----
        btn_layout = QHBoxLayout()
        self._add_btn = QPushButton("➕ 添加图表到仪表盘")
        self._add_btn.setEnabled(False)
        self._add_btn.setFixedHeight(30)
        self._add_btn.clicked.connect(self._on_add_chart)
        btn_layout.addWidget(self._add_btn)

        btn_layout.addStretch()

        clear_btn = QPushButton("清空对话")
        clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(clear_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def eventFilter(self, obj, event):
        """Enter 发送消息，Shift+Enter 换行"""
        from PyQt6.QtCore import QEvent
        if obj == self._input_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
                # Shift+Enter 换行
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False
                # Enter / Ctrl+Enter 发送
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def _on_send(self):
        user_input = self._input_edit.toPlainText().strip()
        if not user_input:
            return

        # 显示用户消息
        self._append_message("🙋 你", user_input)
        self._input_edit.clear()
        self._chat_view.append("⏳ AI 思考中...")

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self._do_chat(user_input))

    def _do_chat(self, user_input: str):
        response = self._assistant.chat(user_input, self._sources_info)
        # 移除"思考中"
        cursor = self._chat_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.select(cursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()
        cursor.deletePreviousChar()

        # 显示 AI 响应
        self._append_message("🤖 AI", response)

        # 尝试解析 JSON 图表定义
        self._chart_def = None
        try:
            import json
            text = response
            json_str = None
            if '```json' in text:
                json_str = text.split('```json')[1].split('```')[0].strip()
            elif '```' in text:
                json_str = text.split('```')[1].split('```')[0].strip()
            elif '{' in text and '}' in text:
                start = text.index('{')
                end = text.rindex('}') + 1
                json_str = text[start:end]

            if json_str:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict) and 'chart_type' in parsed:
                    self._chart_def = parsed
                    self._add_btn.setEnabled(True)
                    self._append_message("💡 提示", f"检测到图表定义「{parsed.get('title', '未命名')}」，点击下方按钮添加到仪表盘")
                    _ui_output(f"[BI 报表] AI 返回了图表定义: {parsed.get('title', '未命名')}")
        except Exception:
            self._add_btn.setEnabled(False)

    def _append_message(self, role: str, content: str):
        """追加一条消息到对话历史"""
        self._chat_history.append({"role": role, "content": content})
        html = f'<p><b style="color:#1890FF">{role}:</b></p><p style="margin:4px 0 12px 12px;white-space:pre-wrap;">{content}</p>'
        self._chat_view.append(html)

    def _on_clear(self):
        self._chat_view.clear()
        self._chat_history.clear()
        self._chart_def = None
        self._add_btn.setEnabled(False)
        self._append_message("💡 提示", "对话已清空，请提出新的问题。")

    def _on_add_chart(self):
        if self._chart_def:
            self.accept()

    def get_chart_definition(self) -> dict:
        return self._chart_def


# ===== 图标映射 =====

def _chart_icon(chart_type: str) -> str:
    icons = {
        'bar': '📊', 'line': '📈', 'pie': '🥧', 'scatter': '🎯',
        'area': '📉', 'table': '📋', 'card': '💳', 'gauge': '⚙️',
        'combo': '📊', 'stacked_bar': '📊', 'stacked_area': '📉',
        'pictorial_bar': '🏞️', 'effect_scatter': '💧', 'waterfall': '📉',
        'funnel': '🔽', 'treemap': '🗺️', 'sunburst': '🎨',
        'boxplot': '📦', 'heatmap': '🔥', 'calendar': '📅',
        'candlestick': '🕯️', 'sankey': '🌊', 'graph': '🕸️',
        'tree': '🌳', 'radar': '🕸️', 'parallel': '📊',
        'theme_river': '🌊', 'map_china': '🗺️',
        'map_scatter': '📍', 'map_lines': '✈️', 'word_cloud': '🏷️',
    }
    return icons.get(chart_type, '📊')


def _chart_display_name(chart_type: str) -> str:
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
