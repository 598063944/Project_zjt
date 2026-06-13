"""
图表配置面板

在仪表盘设计器右侧，选中图表后显示其配置项。
配置项根据图表类型动态显示/隐藏。
"""

# from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QCheckBox, QPushButton, QScrollArea, QFrame,
    QMenu, QListWidget, QListWidgetItem, QAbstractItemView, QWidgetAction,
    QSpinBox, QGroupBox, QGridLayout, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from .models import ChartType, ChartWidget, _new_id, chart_display_name

# 聚合函数选项
_AGG_FUNCS = ["SUM", "AVG", "COUNT", "MAX", "MIN", "无"]

# 需要维度/分类/名称字段的图表（X 轴、地区、分类、标签、节点名等）
_HAS_X_AXIS = {
    "bar", "line", "area", "scatter", "combo", "stacked_bar", "stacked_area",
    "pictorial_bar", "effect_scatter", "waterfall", "boxplot", "heatmap",
    "radar", "parallel", "candlestick",
    "map_china", "map_scatter", "map_lines",    # 地图：X = 地区
    "funnel", "treemap", "sunburst",            # 比例：X = 名称
    "sankey", "graph", "tree",                  # 关系：X = 源节点/节点名
    "theme_river",                              # 河流：X = 时间/类别
    "calendar", "word_cloud",                   # 日历：X = 日期；词云：X = 词语
    "pie",                                      # 饼图：X = 分类名称
}

# 可以多 Y 轴的图表
_MULTI_Y = {
    "bar", "line", "area", "combo", "stacked_bar", "stacked_area",
    "pictorial_bar", "radar", "parallel", "theme_river",
}

# 需要颜色分组的图表
_HAS_COLOR = {
    "bar", "line", "area", "pie", "combo", "stacked_bar", "stacked_area",
    "funnel", "treemap", "sunburst", "sankey", "graph", "tree",
    "theme_river", "scatter",
}

# 支持散点大小的图表
_HAS_SIZE = {"scatter", "effect_scatter", "map_scatter"}

# 支持下钻的图表
_HAS_DRILL = {
    "bar", "line", "area", "pie", "treemap", "sunburst",
    "heatmap", "calendar",
}

# 配色方案
_COLOR_PALETTES = ["默认", "复古", "深色", "清新", "暖色", "冷色", "马卡龙"]


class ChartConfigPanel(QWidget):
    """图表配置面板"""

    chartConfigChanged = pyqtSignal(dict)  # chart_id → 更新后的 ChartWidget 数据
    chartRemoved = pyqtSignal(str)         # chart_id
    chartTypeChanged = pyqtSignal(str, str)  # chart_id, new_type

    def __init__(self, parent=None, report_manager=None):
        super().__init__(parent)
        self._report_manager = report_manager  # ReportManager 引用（用于查询筛选选项）
        self._current_chart_id = None
        self._current_chart_data = {}  # 当前图表的完整数据 dict
        self._available_fields = []    # 可用字段列表
        self._filter_rows = []         # 筛选条件行 [{field, op, value, widget, delete_btn}]
        self._current_source_type = '' # 当前图表的数据源类型
        self._current_source_id = ''   # 当前图表的数据源 ID
        self._chart_data_rows = []     # 当前图表的数据行
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        container.setMinimumWidth(260)
        container.setStyleSheet(
            "font-size: 12px;"
            "QComboBox::drop-down { width: 12px; }"
            "QComboBox::down-arrow { width: 8px; height: 8px; }"
        )
        outer = QVBoxLayout(container)
        outer.setSpacing(4)
        outer.setContentsMargins(10, 6, 10, 6)

        # 标题栏
        header = QLabel("📊 图表配置")
        header.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        outer.addWidget(header)

        # 数据源选择
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("📁 数据源:"))
        self._source_combo = QComboBox()
        self._source_combo.setMinimumWidth(160)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        src_row.addWidget(self._source_combo, 1)
        outer.addLayout(src_row)

        # 提前初始化，防止 _update_visibility 在 UI 构建期间访问失败
        self._dim_row_widgets = []

        # === 主网格：2 列（标签-控件）× N 行 ===
        grid = QGridLayout()
        grid.setSpacing(4)

        # Row 0: 标题 | 类型
        grid.addWidget(QLabel("标题:"), 0, 0)
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("输入图表标题...")
        self._title_edit.textChanged.connect(self._on_config_changed)
        grid.addWidget(self._title_edit, 0, 1)

        grid.addWidget(QLabel("类型:"), 0, 2)
        self._type_combo = QComboBox()
        grid.addWidget(self._type_combo, 0, 3)

        # Row 1: X 轴/分类（地图类型自动切换为"地区字段"）
        self._x_label = QLabel("X 轴/分类:")
        grid.addWidget(self._x_label, 1, 0)
        self._x_field_combo = QComboBox()
        self._x_field_combo.setEditable(True)
        self._x_field_combo.currentTextChanged.connect(self._on_config_changed)
        grid.addWidget(self._x_field_combo, 1, 1)

        _s_label = QLabel("大小:")
        grid.addWidget(_s_label, 1, 2)
        self._size_combo = QComboBox()
        self._size_combo.setEditable(True)
        self._size_combo.addItem("— (无)", "")
        self._size_combo.currentTextChanged.connect(self._on_config_changed)
        grid.addWidget(self._size_combo, 1, 3)

        # Row 2: 颜色分组 | 配色方式
        _c_label = QLabel("颜色分组:")
        grid.addWidget(_c_label, 2, 0)
        self._color_combo = QComboBox()
        self._color_combo.setEditable(True)
        self._color_combo.addItem("— (无)", "")
        self._color_combo.currentTextChanged.connect(self._on_config_changed)
        grid.addWidget(self._color_combo, 2, 1)

        grid.addWidget(QLabel("配色:"), 2, 2)
        self._palette_combo = QComboBox()
        self._palette_combo.addItems(_COLOR_PALETTES)
        self._palette_combo.currentTextChanged.connect(self._on_config_changed)
        grid.addWidget(self._palette_combo, 2, 3)

        self._dim_row_widgets = [self._x_label, self._x_field_combo,
                                  _s_label, self._size_combo,
                                  _c_label, self._color_combo]

        # Row 3: 交互与筛选 (跨整行)
        self._interact_group = QGroupBox("交互与筛选")
        self._interact_group.setStyleSheet("QGroupBox { font-size: 12px; font-weight: bold; }")
        self._interact_grid = QGridLayout(self._interact_group)
        inter_grid = self._interact_grid
        inter_grid.setSpacing(3)
        self._cross_filter_cb = QCheckBox("交叉筛选")
        self._cross_filter_cb.setChecked(True)
        self._cross_filter_cb.toggled.connect(self._on_config_changed)
        inter_grid.addWidget(self._cross_filter_cb, 0, 0)

        self._drill_cb = QCheckBox("下钻")
        self._drill_cb.toggled.connect(self._on_config_changed)
        inter_grid.addWidget(self._drill_cb, 0, 1)
        self._drill_combo = QComboBox()
        self._drill_combo.addItems(["年→季→月→日", "年→季→月", "年→月", "季→月"])
        self._drill_combo.setEnabled(False)
        self._drill_cb.toggled.connect(self._drill_combo.setEnabled)
        self._drill_combo.currentTextChanged.connect(self._on_config_changed)
        inter_grid.addWidget(self._drill_combo, 0, 2)

        self._legend_cb = QCheckBox("图例")
        self._legend_cb.setChecked(True)
        self._legend_cb.toggled.connect(self._on_config_changed)
        inter_grid.addWidget(self._legend_cb, 1, 0)
        self._label_cb = QCheckBox("标签")
        self._label_cb.toggled.connect(self._on_config_changed)
        inter_grid.addWidget(self._label_cb, 1, 1)

        self._filter_add_btn = QPushButton("+ 筛选条件")
        self._filter_add_btn.clicked.connect(self._on_add_filter)
        self._filter_add_btn.setFixedHeight(26)
        inter_grid.addWidget(self._filter_add_btn, 2, 0, 1, 4)
        grid.addWidget(self._interact_group, 3, 0, 1, 4)

        # Row 4: 度量 (跨整行)
        self._measure_group = QGroupBox("度量")
        self._measure_group.setStyleSheet("QGroupBox { font-size: 12px; font-weight: bold; }")
        self._measure_layout = QVBoxLayout(self._measure_group)
        self._measure_layout.setSpacing(3)
        self._y_field_rows = []
        self._add_y_field_row()
        add_btn = QPushButton("+ 添加度量字段")
        add_btn.clicked.connect(self._add_y_field_row)
        add_btn.setFixedHeight(26)
        self._measure_layout.addWidget(add_btn)
        self._measure_layout.addStretch()
        grid.addWidget(self._measure_group, 4, 0, 1, 4)

        # Row 5: 图表样式 (跨整行)
        self._style_group = QGroupBox("图表样式")
        self._style_group.setStyleSheet("QGroupBox { font-size: 12px; font-weight: bold; }")
        style_grid = QGridLayout(self._style_group)
        style_grid.setSpacing(4)

        # 主题
        style_grid.addWidget(QLabel("主题:"), 0, 0)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems([
            "white", "dark", "chalk", "essos", "infographic",
            "macarons", "purple-passion", "roma", "romantic",
            "shine", "vintage", "walden", "westeros", "wonderland",
        ])
        self._theme_combo.setToolTip("ECharts 内置主题")
        self._theme_combo.currentTextChanged.connect(self._on_config_changed)
        style_grid.addWidget(self._theme_combo, 0, 1)

        # 背景色
        style_grid.addWidget(QLabel("背景:"), 0, 2)
        self._bg_combo = QComboBox()
        self._bg_combo.addItems(["", "#FFFFFF", "#1A1A2E", "#0D1117", "#F5F5F5", "#FFF8E1", "#E8F5E9"])
        self._bg_combo.setToolTip("图表背景色（空=跟随主题）")
        self._bg_combo.currentTextChanged.connect(self._on_config_changed)
        style_grid.addWidget(self._bg_combo, 0, 3)

        # 柱圆角
        style_grid.addWidget(QLabel("柱圆角:"), 1, 0)
        self._radius_spin = QSpinBox()
        self._radius_spin.setRange(0, 20)
        self._radius_spin.setValue(4)
        self._radius_spin.setSuffix(" px")
        self._radius_spin.setToolTip("柱状图边框圆角")
        self._radius_spin.valueChanged.connect(self._on_config_changed)
        style_grid.addWidget(self._radius_spin, 1, 1)

        # 不透明度
        style_grid.addWidget(QLabel("透明:"), 1, 2)
        self._opacity_spin = QSpinBox()
        self._opacity_spin.setRange(10, 100)
        self._opacity_spin.setValue(90)
        self._opacity_spin.setSuffix(" %")
        self._opacity_spin.setSingleStep(5)
        self._opacity_spin.setToolTip("图形不透明度")
        self._opacity_spin.valueChanged.connect(self._on_config_changed)
        style_grid.addWidget(self._opacity_spin, 1, 3)

        # 均值线
        self._markline_avg_cb = QCheckBox("显示均值线")
        self._markline_avg_cb.toggled.connect(self._on_config_changed)
        style_grid.addWidget(self._markline_avg_cb, 2, 0)

        # 坐标轴颜色
        style_grid.addWidget(QLabel("轴线:"), 2, 2)
        self._axis_color_combo = QComboBox()
        self._axis_color_combo.addItems(["#999", "#333", "#1890FF", "#52C41A", "#FA541C", "#FF4D4F", "none"])
        self._axis_color_combo.setToolTip("坐标轴线颜色 (none=隐藏)")
        self._axis_color_combo.currentTextChanged.connect(self._on_config_changed)
        style_grid.addWidget(self._axis_color_combo, 2, 3)

        grid.addWidget(self._style_group, 5, 0, 1, 4)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 1)
        outer.addLayout(grid)

        # 删除按钮
        delete_btn = QPushButton("🗑️ 删除此图表")
        delete_btn.setStyleSheet("QPushButton { color: #FF4D4F; font-size: 12px; padding: 6px; }")
        delete_btn.setFixedHeight(28)
        delete_btn.clicked.connect(self._on_delete)
        outer.addWidget(delete_btn)

        outer.addStretch()

        # 所有控件创建完毕后，连接类型切换信号并填充选项
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._populate_type_combo()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _populate_type_combo(self):
        self._type_combo.clear()
        categories = ChartType.category_map()
        for cat_name, types in categories.items():
            for t in types:
                icon = _chart_icon(t.value)
                self._type_combo.addItem(f"{icon}  {chart_display_name(t.value)}", t.value)

    # 数据源切换
    sourceChanged = pyqtSignal(str, str, str)  # (source_type, source_id, source_name)

    def set_available_sources(self, sources: dict):
        """设置可选数据源列表"""
        self._available_sources = sources
        self._source_combo.clear()
        self._source_combo.addItem("— 选择数据源 —", "")
        for r in sources.get('reports', []):
            self._source_combo.addItem(f"📊 {r['name']}", f"report:{r['id']}")
        for ds in sources.get('excel_datasets', []):
            self._source_combo.addItem(f"📄 {ds['name']}", f"excel:{ds['id']}")
        for t in sources.get('mysql_tables', []):
            self._source_combo.addItem(f"🗄️ {t['name']}", f"mysql:{t['name']}")

    def _on_source_changed(self):
        """用户切换数据源"""
        data = self._source_combo.currentData()
        if not data or not self._current_chart_id:
            return
        parts = data.split(':', 1)
        if len(parts) != 2:
            return
        src_type, src_id = parts
        self.sourceChanged.emit(src_type, src_id, self._source_combo.currentText().replace('📊 ','').replace('📄 ','').replace('🗄️ ',''))

    def set_available_fields(self, fields: list):
        """设置可用字段（从数据源获取）"""
        self._available_fields = fields
        self._update_field_combos()

    def _update_field_combos(self):
        """更新所有字段下拉列表"""
        field_names = []
        for f in self._available_fields:
            if isinstance(f, dict):
                name = f.get('key') or f.get('name', '')
                label = f.get('label', name)
                field_names.append((name, label))
            elif isinstance(f, (tuple, list)) and len(f) >= 2:
                field_names.append((f[0], f[1]))
            else:
                field_names.append((str(f), str(f)))

        # X 轴 + Y 度量字段：直接填充字段列表
        direct_combos = [self._x_field_combo]
        for row in self._y_field_rows:
            direct_combos.append(row["combo"])

        for combo in direct_combos:
            current = combo.currentText()
            combo.clear()
            for name, label in field_names:
                combo.addItem(f"{label}", name)
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        # 颜色分组 + 大小：保留"— (无)"选项在顶部
        opt_combos = [self._color_combo, self._size_combo]
        for combo in opt_combos:
            current_data = combo.currentData()
            combo.clear()
            combo.addItem("— (无)", "")
            for name, label in field_names:
                combo.addItem(f"{label}", name)
            # 恢复之前选中的值
            idx = combo.findData(current_data)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def load_chart(self, chart_data: dict):
        """
        加载图表配置到面板

        Args:
            chart_data: ChartWidget.to_dict()
        """
        self._current_chart_id = chart_data.get('id', '')
        self._current_chart_data = chart_data

        # 阻止信号 + 标记加载中
        self._loading = True
        self._block_signals(True)

        self._title_edit.setText(chart_data.get('title', ''))

        # 记录数据源信息（供查询筛选选项使用）
        self._current_source_type = chart_data.get('data_source_type', '')
        self._current_source_id = chart_data.get('data_source_id', '')

        chart_type = chart_data.get('chart_type', 'bar')
        idx = self._type_combo.findData(chart_type)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)

        self._x_field_combo.setCurrentText(chart_data.get('x_field', ''))
        self._color_combo.setCurrentText(chart_data.get('color_field', ''))
        self._size_combo.setCurrentText(chart_data.get('size_field', ''))

        # 预选数据源
        src_key = f"{chart_data.get('data_source_type', '')}:{chart_data.get('data_source_id', '')}"
        for i in range(self._source_combo.count()):
            if self._source_combo.itemData(i) == src_key:
                self._source_combo.setCurrentIndex(i)
                break

        # Y 字段：先清多余行（保留 1 行兜底），再按数量补齐
        y_fields = chart_data.get('y_fields', [])
        agg_funcs = chart_data.get('aggregate_funcs', {})
        # 删除多余行（保留第一行）
        while len(self._y_field_rows) > 1:
            self._remove_y_field_row(self._y_field_rows[-1])
        # 确保至少有 1 行
        if not self._y_field_rows:
            self._add_y_field_row()
        # 按 Y 字段数量补齐行
        need_rows = max(len(y_fields or []), 1)
        while len(self._y_field_rows) < need_rows:
            self._add_y_field_row()
        # 删除多余行
        while len(self._y_field_rows) > need_rows:
            self._remove_y_field_row(self._y_field_rows[-1])
        # 设置值
        for i, yf in enumerate(y_fields or ['']):
            row = self._y_field_rows[i]
            row["combo"].setCurrentText(yf)
            agg = agg_funcs.get(yf, "SUM")
            row["agg"].setCurrentText(agg)

        # 交互
        self._cross_filter_cb.setChecked(chart_data.get('enable_cross_filter', True))
        drill_path = chart_data.get('drill_path', [])
        self._drill_cb.setChecked(bool(drill_path))
        self._drill_combo.setEnabled(bool(drill_path))

        # 样式 — 加载所有字段
        style = chart_data.get('style_config', {})
        palette = style.get('color_palette', '默认')
        idx = self._palette_combo.findText(palette)
        if idx >= 0:
            self._palette_combo.setCurrentIndex(idx)
        self._legend_cb.setChecked(style.get('show_legend', True))
        self._label_cb.setChecked(style.get('show_label', False))

        # 扩展样式控件
        theme = style.get('theme', 'white')
        idx = self._theme_combo.findText(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._bg_combo.setCurrentText(style.get('bg_color', ''))
        self._radius_spin.setValue(int(style.get('bar_border_radius', 4)))
        self._opacity_spin.setValue(int((style.get('item_opacity', 0.9)) * 100))
        self._axis_color_combo.setCurrentText(style.get('axis_line_color', '#999'))
        self._markline_avg_cb.setChecked(chart_data.get('show_markline_avg', False))

        # 恢复筛选条件
        self._clear_filter_rows()
        for f in chart_data.get('filters', []) or []:
            self._on_add_filter()
            if self._filter_rows:
                row = self._filter_rows[-1]
                idx = row["field"].findText(f.get('field', ''))
                if idx >= 0:
                    row["field"].setCurrentIndex(idx)
                op_text = f.get('op', '等于')
                op_idx = row["op"].findText(op_text)
                if op_idx >= 0:
                    row["op"].setCurrentIndex(op_idx)
                row["value"].setText(f.get('value', ''))
                # 显示/隐藏多选按钮
                if row.get("multi_btn"):
                    row["multi_btn"].setVisible(op_text in ("属于", "不属于"))

        self._block_signals(False)
        self._loading = False

        # 更新控件可见性
        self._update_visibility(chart_type)

    def _block_signals(self, block: bool):
        self._title_edit.blockSignals(block)
        self._type_combo.blockSignals(block)
        self._x_field_combo.blockSignals(block)
        self._color_combo.blockSignals(block)
        self._size_combo.blockSignals(block)
        self._cross_filter_cb.blockSignals(block)
        self._drill_cb.blockSignals(block)
        self._drill_combo.blockSignals(block)
        self._palette_combo.blockSignals(block)
        self._legend_cb.blockSignals(block)
        self._label_cb.blockSignals(block)
        self._theme_combo.blockSignals(block)
        self._bg_combo.blockSignals(block)
        self._radius_spin.blockSignals(block)
        self._opacity_spin.blockSignals(block)
        self._axis_color_combo.blockSignals(block)
        self._markline_avg_cb.blockSignals(block)

    def _update_visibility(self, chart_type: str):
        if not hasattr(self, '_interact_group'):
            return  # UI 尚未构建完成
        has_x = chart_type in _HAS_X_AXIS
        has_color = chart_type in _HAS_COLOR
        has_size = chart_type in _HAS_SIZE
        has_drill = chart_type in _HAS_DRILL
        is_table = chart_type == 'table'
        is_pie = chart_type == 'pie'

        # X 轴/颜色分组/大小整行可见性
        show_dim = (has_x or is_pie)
        for w in self._dim_row_widgets:
            w.setVisible(show_dim)

        # 根据图表类型动态切换 X 轴标签
        x_labels = {
            ('map_china', 'map_scatter', 'map_lines'): "地区字段:",
            ('pie',): "分类名称:",
            ('funnel', 'treemap', 'sunburst'): "名称字段:",
            ('sankey', 'graph', 'tree'): "节点/源字段:",
            ('word_cloud',): "词语字段:",
            ('calendar',): "日期字段:",
        }
        matched = False
        for types, label in x_labels.items():
            if chart_type in types:
                self._x_label.setText(label)
                matched = True
                break
        if not matched:
            self._x_label.setText("X 轴/维度:")

        # 表格：显示度量组以选择显示列（隐藏聚合下拉）
        if is_table:
            self._measure_group.setVisible(True)
            self._measure_group.setTitle("显示列")
            for row in self._y_field_rows:
                row["agg"].setVisible(False)
        else:
            self._measure_group.setTitle("度量")
            for row in self._y_field_rows:
                row["agg"].setVisible(True)
        # 表格也支持筛选，不隐藏交互组
        self._drill_cb.setVisible(has_drill)
        self._drill_combo.setVisible(has_drill)
        self._color_combo.setEnabled(has_color)
        self._size_combo.setEnabled(has_size)

    def _on_type_changed(self):
        chart_type = self._type_combo.currentData()
        self._update_visibility(chart_type)
        if self._current_chart_id:
            self.chartTypeChanged.emit(self._current_chart_id, chart_type)
        self._on_config_changed()

    def _on_config_changed(self):
        if not self._current_chart_id or getattr(self, '_loading', False):
            return
        data = self._collect_config()
        self.chartConfigChanged.emit(data)

    def _collect_config(self) -> dict:
        """收集当前面板的配置为字典"""
        chart_type = self._type_combo.currentData() or "bar"
        y_fields = []
        agg_funcs = {}
        for row in self._y_field_rows:
            field = row["combo"].currentText().strip()
            agg = row["agg"].currentText()
            if field:
                y_fields.append(field)
                agg_funcs[field] = "SUM" if agg == "无" else agg

        # 收集筛选条件
        filters = []
        for row in self._filter_rows:
            field = row["field"].currentData() or row["field"].currentText()
            op = row["op"].currentText()
            value = row["value"].text().strip()
            if field:
                filters.append({"field": field, "op": op, "value": value})

        drill_path_raw = self._drill_combo.currentText()
        drill_map = {
            "年→季→月→日": ["year", "quarter", "month", "day"],
            "年→季→月": ["year", "quarter", "month"],
            "年→月": ["year", "month"],
            "季→月": ["quarter", "month"],
        }

        return {
            "id": self._current_chart_id,
            "chart_type": chart_type,
            "title": self._title_edit.text(),
            "data_source_type": self._current_source_type,
            "data_source_id": self._current_source_id,
            "data_source_name": self._source_combo.currentText().replace('📊 ','').replace('📄 ','').replace('🗄️ ',''),
            "x_field": self._x_field_combo.currentText(),
            "y_fields": y_fields,
            "aggregate_funcs": agg_funcs,
            "color_field": self._color_combo.currentData() or "",
            "size_field": self._size_combo.currentData() or "",
            "filters": filters,
            "enable_cross_filter": self._cross_filter_cb.isChecked(),
            "enable_drill": self._drill_cb.isChecked(),
            "drill_path": drill_map.get(drill_path_raw, []) if self._drill_cb.isChecked() else [],
            "style_config": {
                "color_palette": self._palette_combo.currentText(),
                "show_legend": self._legend_cb.isChecked(),
                "show_label": self._label_cb.isChecked(),
                "theme": self._theme_combo.currentText(),
                "bg_color": self._bg_combo.currentText(),
                "bar_border_radius": self._radius_spin.value(),
                "item_opacity": self._opacity_spin.value() / 100.0,
                "axis_line_color": self._axis_color_combo.currentText(),
            },
            "show_markline_avg": self._markline_avg_cb.isChecked(),
        }

    def _add_y_field_row(self):
        row_widget = QWidget()
        layout = QHBoxLayout(row_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        combo = QComboBox()
        combo.setEditable(True)
        combo.setMinimumWidth(80)
        combo.currentTextChanged.connect(self._on_config_changed)
        layout.addWidget(combo, 1)

        agg = QComboBox()
        agg.addItems(_AGG_FUNCS)
        agg.setMinimumWidth(80)
        agg.currentTextChanged.connect(self._on_config_changed)
        layout.addWidget(agg, 1)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(24, 24)
        remove_btn.setStyleSheet("QPushButton { color: #FF4D4F; border: none; font-size: 14px; }")
        remove_btn.clicked.connect(lambda: self._remove_y_field_row(row_data))
        layout.addWidget(remove_btn)

        row_data = {"widget": row_widget, "combo": combo, "agg": agg, "btn": remove_btn}
        self._y_field_rows.append(row_data)

        # 插入到"添加"按钮之前（布局: [...rows, add_btn, stretch]，按钮在 stretch 前一位）
        add_btn_index = self._measure_layout.count() - 2
        self._measure_layout.insertWidget(max(0, add_btn_index), row_widget)

        # 更新字段下拉
        if self._available_fields:
            field_names = []
            for f in self._available_fields:
                if isinstance(f, dict):
                    name = f.get('key') or f.get('name', '')
                    label = f.get('label', name)
                elif isinstance(f, (tuple, list)) and len(f) >= 2:
                    name = f[0]
                    label = f[1]
                else:
                    name = str(f)
                    label = name
                field_names.append((name, label))
            combo.clear()
            for name, label in field_names:
                combo.addItem(f"{label}", name)

        return row_data

    def _remove_y_field_row(self, row_data: dict):
        if len(self._y_field_rows) <= 1:
            return  # 至少保留一行
        self._y_field_rows.remove(row_data)
        row_data["widget"].deleteLater()
        self._on_config_changed()

    def _on_add_filter(self):
        """添加一行筛选条件 — "属于"支持手动输入 + 多选辅助"""
        row_widget = QWidget()
        row_widget.setStyleSheet("font-size: 12px;")
        layout = QHBoxLayout(row_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        # 字段下拉
        field_combo = QComboBox()
        field_combo.setMinimumWidth(80)
        for name, label in self._field_names():
            field_combo.addItem(label, name)
        layout.addWidget(field_combo, 1)

        # 操作符
        op_combo = QComboBox()
        op_combo.addItems(["等于", "不等于", "大于", "小于", "大于等于", "小于等于",
                          "包含", "不包含", "属于", "不属于", "为空", "不为空"])
        layout.addWidget(op_combo, 1)

        # 值输入（始终可见，支持手动输入逗号分隔的多值）
        value_edit = QLineEdit()
        value_edit.setPlaceholderText("输入值；多个值用逗号分隔")
        layout.addWidget(value_edit, 2)

        # 多选辅助按钮（"属于"/"不属于"时显示）
        multi_btn = QPushButton("☰")
        multi_btn.setFixedSize(26, 26)
        multi_btn.setToolTip("从数据中选择")
        multi_btn.setVisible(False)
        multi_btn.setStyleSheet(
            "QPushButton { border: 1px solid #D9D9D9; border-radius: 3px; background: #FFF; font-size: 14px; }"
            "QPushButton:hover { border-color: #1890FF; background: #E6F7FF; }"
        )

        # 创建多选弹出菜单（懒加载，点击时刷新选项）
        def show_multi_popup():
            menu = QMenu(row_widget)
            # 搜索框
            search_edit = QLineEdit()
            search_edit.setPlaceholderText("搜索...")
            search_edit.setStyleSheet("QLineEdit { margin: 4px; padding: 2px 6px; border: 1px solid #E8E8E8; border-radius: 2px; }")
            search_act = QWidgetAction(menu)
            search_act.setDefaultWidget(search_edit)
            menu.addAction(search_act)

            # 可勾选列表
            list_widget = QListWidget()
            list_widget.setMaximumHeight(200)
            list_widget.setStyleSheet("QListWidget { border: none; font-size: 12px; }")
            field_name = field_combo.currentData() or field_combo.currentText()
            values = self._fetch_distinct_values(field_name)
            # 已选值
            current_vals = set(v.strip() for v in value_edit.text().split(',') if v.strip())
            items = []
            for v in values:
                item = QListWidgetItem(str(v))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if str(v) in current_vals else Qt.CheckState.Unchecked)
                list_widget.addItem(item)
                items.append(item)
            search_edit.textChanged.connect(
                lambda t: [list_widget.setRowHidden(i, t.lower() not in list_widget.item(i).text().lower())
                           for i in range(list_widget.count())]
            )
            list_act = QWidgetAction(menu)
            list_act.setDefaultWidget(list_widget)
            menu.addAction(list_act)

            # 按钮行
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 4)
            clear_btn = QPushButton("清除")
            clear_btn.setFixedHeight(22)
            clear_btn.clicked.connect(lambda: [it.setCheckState(Qt.CheckState.Unchecked) for it in items])
            btn_layout.addWidget(clear_btn)
            sel_all_btn = QPushButton("全选")
            sel_all_btn.setFixedHeight(22)
            sel_all_btn.clicked.connect(lambda: [it.setCheckState(Qt.CheckState.Checked) for it in items])
            btn_layout.addWidget(sel_all_btn)
            ok_btn = QPushButton("填入")
            ok_btn.setFixedHeight(22)
            ok_btn.setStyleSheet("QPushButton { background: #1890FF; color: #FFF; border-radius: 3px; }")
            def on_ok():
                selected = [it.text() for it in items if it.checkState() == Qt.CheckState.Checked]
                value_edit.setText(", ".join(selected))
                menu.close()
                self._on_config_changed()
            ok_btn.clicked.connect(on_ok)
            btn_layout.addWidget(ok_btn)
            btn_act_w = QWidgetAction(menu)
            btn_act_w.setDefaultWidget(btn_widget)
            menu.addAction(btn_act_w)

            menu.popup(multi_btn.mapToGlobal(multi_btn.rect().bottomLeft()))
        multi_btn.clicked.connect(show_multi_popup)
        layout.addWidget(multi_btn)

        # 操作符切换 → 显示/隐藏多选按钮 + 修改 placeholder
        def on_op_changed(op_text):
            is_multi = op_text in ("属于", "不属于")
            multi_btn.setVisible(is_multi)
            value_edit.setPlaceholderText(
                "输入值；多个值用逗号分隔" if is_multi else "筛选值..."
            )
            self._on_config_changed()
        op_combo.currentTextChanged.connect(on_op_changed)

        # 删除按钮
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet("QPushButton { border: none; color: #FF4D4F; font-weight: bold; font-size: 11px; } QPushButton:hover { background: #FFF1F0; }")
        del_btn.clicked.connect(lambda: self._remove_filter_row(row_data))
        layout.addWidget(del_btn)

        row_data = {
            "widget": row_widget, "field": field_combo, "op": op_combo,
            "value": value_edit, "multi_btn": multi_btn, "delete_btn": del_btn
        }
        self._filter_rows.append(row_data)

        # 信号
        value_edit.textChanged.connect(self._on_config_changed)
        field_combo.currentTextChanged.connect(self._on_config_changed)

        filter_row = len(self._filter_rows) + 1
        self._interact_grid.addWidget(row_widget, filter_row, 0, 1, 4)
        self._interact_grid.addWidget(self._filter_add_btn, filter_row + 1, 0, 1, 4)

        self._on_config_changed()

    def _remove_filter_row(self, row_data: dict):
        """删除一行筛选条件"""
        if row_data not in self._filter_rows:
            return
        idx = self._filter_rows.index(row_data)
        self._filter_rows.remove(row_data)
        row_data["widget"].deleteLater()

        # 重新排列剩余行和添加按钮（从 row2 开始）
        for i, row in enumerate(self._filter_rows):
            self._interact_grid.addWidget(row["widget"], i + 2, 0, 1, 4)
        self._interact_grid.addWidget(self._filter_add_btn, len(self._filter_rows) + 2, 0, 1, 4)

        self._on_config_changed()

    def _field_names(self):
        """获取可用字段名列表（供筛选下拉使用）"""
        names = []
        for f in self._available_fields:
            if isinstance(f, dict):
                name = f.get('key') or f.get('name', '')
                label = f.get('label', name)
            elif isinstance(f, (tuple, list)) and len(f) >= 2:
                name = f[0]
                label = f[1]
            else:
                name = str(f)
                label = name
            names.append((name, label))
        return names

    def _on_delete(self):
        if self._current_chart_id:
            self.chartRemoved.emit(self._current_chart_id)
            self.clear()
            print(f"[BI 报表] 图表已删除: {self._current_chart_id}")

    def clear(self):
        """清空面板"""
        self._current_chart_id = None
        self._current_chart_data = {}
        self._block_signals(True)
        self._title_edit.clear()
        self._type_combo.setCurrentIndex(0)
        self._x_field_combo.clear()
        self._color_combo.clear()
        self._size_combo.clear()
        self._clear_filter_rows()
        self._block_signals(False)

    def _load_filter_values(self, field_name: str, multi_select: MultiSelectCombo):
        """为多选控件加载指定字段的去重值"""
        if not field_name or not multi_select:
            return
        # 从设计器/管理器获取该字段的实际数据值
        values = self._fetch_distinct_values(field_name)
        if values:
            multi_select.set_items(values)

    def _fetch_distinct_values(self, field_name: str) -> list:
        """获取字段的去重值列表 — 优先查数据库，回退到内存数据"""
        # 优先：通过 ReportManager 直接查数据库 DISTINCT
        if self._report_manager and self._current_source_type and self._current_source_id:
            vals = self._report_manager.query_distinct_values(
                self._current_source_type, self._current_source_id, field_name
            )
            if vals:
                return vals
        # 回退：从内存数据行提取
        data = self._chart_data_rows or []
        if data:
            seen = set()
            result = []
            for row in data:
                v = str(row.get(field_name, '')) if isinstance(row, dict) else ''
                if v and v not in seen:
                    seen.add(v)
                    result.append(v)
            return sorted(result)
        return []

    def set_chart_data_rows(self, rows: list):
        """外部调用：设置当前图表的数据行（用于填充多选选项）"""
        self._chart_data_rows = rows or []

    def _clear_filter_rows(self):
        """清除所有筛选行"""
        for row in self._filter_rows[:]:
            row["widget"].deleteLater()
        self._filter_rows.clear()
        self._interact_grid.addWidget(self._filter_add_btn, 2, 0, 1, 4)

    @property
    def current_chart_id(self) -> str:
        return self._current_chart_id


def _h_line() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    line.setStyleSheet("QFrame { color: #E8E8E8; }")
    return line


# ==================== 多选下拉控件 ====================

class MultiSelectCombo(QPushButton):
    """多选下拉按钮 — 用于筛选条件的"属于"操作符"""

    def __init__(self, placeholder="选择值...", parent=None):
        super().__init__(placeholder, parent)
        self._menu = QMenu(self)
        self._menu.aboutToHide.connect(self._update_text)
        self.setMenu(self._menu)
        self.setStyleSheet(
            "QPushButton { text-align: left; padding: 2px 8px; border: 1px solid #D9D9D9; "
            "border-radius: 3px; background: #FFF; font-size: 12px; } "
            "QPushButton:hover { border-color: #1890FF; }"
        )
        self._placeholder = placeholder
        self._items = {}  # {value: QListWidgetItem}

    def set_items(self, values: list):
        """设置可选项列表"""
        self._menu.clear()
        self._items.clear()
        # 添加搜索框
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("搜索...")
        search_edit.setStyleSheet("QLineEdit { margin: 4px; padding: 2px 6px; border: 1px solid #E8E8E8; border-radius: 2px; }")
        search_act = QWidgetAction(self._menu)
        search_act.setDefaultWidget(search_edit)
        self._menu.addAction(search_act)

        # 列表
        list_widget = QListWidget()
        list_widget.setMaximumHeight(200)
        list_widget.setStyleSheet("QListWidget { border: none; font-size: 12px; }")
        for v in values:
            item = QListWidgetItem(str(v))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            list_widget.addItem(item)
            self._items[str(v)] = item

        search_edit.textChanged.connect(
            lambda t: [list_widget.setRowHidden(i, t.lower() not in list_widget.item(i).text().lower())
                       for i in range(list_widget.count())]
        )

        list_act = QWidgetAction(self._menu)
        list_act.setDefaultWidget(list_widget)
        self._menu.addAction(list_act)

        # 确定/清除按钮
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(4, 2, 4, 4)
        clear_btn = QPushButton("清除")
        clear_btn.setFixedHeight(22)
        clear_btn.clicked.connect(lambda: self._clear_all(list_widget))
        btn_layout.addWidget(clear_btn)
        ok_btn = QPushButton("确定")
        ok_btn.setFixedHeight(22)
        ok_btn.setStyleSheet("QPushButton { background: #1890FF; color: #FFF; border-radius: 3px; }")
        ok_btn.clicked.connect(self._menu.hide)
        btn_layout.addWidget(ok_btn)
        btn_act = QWidgetAction(self._menu)
        btn_act.setDefaultWidget(btn_widget)
        self._menu.addAction(btn_act)

        self._update_text()

    def _clear_all(self, list_widget):
        for i in range(list_widget.count()):
            list_widget.item(i).setCheckState(Qt.CheckState.Unchecked)
        self._update_text()

    def _update_text(self):
        selected = self.selected_values()
        if selected:
            text = ", ".join(selected)
            if len(text) > 30:
                text = text[:30] + f"... (+{len(selected) - 1})"
            self.setText(text)
        else:
            self.setText(self._placeholder)

    def selected_values(self) -> list:
        return sorted([v for v, item in self._items.items()
                       if item.checkState() == Qt.CheckState.Checked])

    def set_selected_values(self, values: list):
        vals = set(str(v) for v in (values or []))
        for v, item in self._items.items():
            item.setCheckState(Qt.CheckState.Checked if v in vals else Qt.CheckState.Unchecked)
        self._update_text()


def _chart_icon(chart_type: str) -> str:
    """图表类型 → emoji 图标"""
    icons = {
        'bar': '📊', 'line': '📈', 'pie': '🥧', 'scatter': '🎯',
        'area': '📉', 'table': '📋', 'card': '💳', 'gauge': '⏱️',
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
    return line
