"""
筛选栏

提供日期范围 + CRM 风格多条件筛选配置，支持筛选方案保存/加载。
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QComboBox,
    QLineEdit, QLabel, QDateEdit,
    QCheckBox, QFrame, QStackedWidget, QSpinBox,
    QApplication, QCompleter, QScrollArea,
)
from PyQt6.QtCore import Qt, QDate, pyqtSignal, QPoint, QTimer, QObject

from .preview_table import PreviewTable, _light_msgbox


# ---- 操作符定义 ----

def _text_operators():
    """非日期字段的筛选操作符"""
    return [
        ("等于", "eq"), ("不等于", "ne"),
        ("包含", "contains"), ("不包含", "not_contains"),
        ("属于", "in"), ("不属于", "not_in"),
        ("为空（未填写）", "empty"), ("不为空", "not_empty"),
        ("开头是", "starts_with"), ("结尾是", "ends_with"),
        ("大于", "gt"), ("小于", "lt"),
        ("大于等于", "gte"), ("小于等于", "lte"),
    ]


def _date_operators():
    """日期字段的筛选操作符"""
    return [
        ("等于", "eq"), ("不等于", "ne"),
        ("早于", "date_before"), ("晚于", "date_after"),
        ("早于等于", "date_before_eq"), ("晚于等于", "date_after_eq"),
        ("为空（未填写）", "empty"), ("不为空", "not_empty"),
        ("时间段", "date_range"),
        ("过去N天内(不含当天)", "past_n_days_exclusive"),
        ("未来N天内(不含当天)", "future_n_days_exclusive"),
        ("过去N月内(不含当月)", "past_n_months_exclusive"),
        ("未来N月内(不含当月)", "future_n_months_exclusive"),
        ("过去N周内(不含当周)", "past_n_weeks_exclusive"),
        ("未来N周内(不含当周)", "future_n_weeks_exclusive"),
        ("过去N天内(含当天)", "past_n_days_inclusive"),
        ("未来N天内(含当天)", "future_n_days_inclusive"),
        ("过去N周内(含当周)", "past_n_weeks_inclusive"),
        ("未来N周内(含当周)", "future_n_weeks_inclusive"),
        ("过去N月内(含当月)", "past_n_months_inclusive"),
        ("未来N月内(含当月)", "future_n_months_inclusive"),
        ("N天前", "n_days_ago"),
        ("N天后", "n_days_later"),
        ("N周前", "n_weeks_ago"),
        ("N周后", "n_weeks_later"),
        ("过去N季度内(含当季度)", "past_n_quarters_inclusive"),
    ]


# 需要数字输入的相对日期操作符
_N_TYPE_OPS = frozenset({
    'past_n_days_exclusive', 'future_n_days_exclusive',
    'past_n_months_exclusive', 'future_n_months_exclusive',
    'past_n_weeks_exclusive', 'future_n_weeks_exclusive',
    'past_n_days_inclusive', 'future_n_days_inclusive',
    'past_n_weeks_inclusive', 'future_n_weeks_inclusive',
    'past_n_months_inclusive', 'future_n_months_inclusive',
    'n_days_ago', 'n_days_later',
    'n_weeks_ago', 'n_weeks_later',
    'past_n_quarters_inclusive',
})

# 数字比较操作符（需要数字输入框）
_NUMERIC_COMPARE_OPS = frozenset({'gt', 'lt', 'gte', 'lte'})


# 操作符中文 → API 码映射（用于筛选结果输出）
_OP_CN_TO_API = {
    '等于': 'EQ', '不等于': 'NEQ',
    '包含': 'CONTAINS', '不包含': 'NOT_CONTAINS',
    '属于': 'IN', '不属于': 'NOT_IN',
    '为空（未填写）': 'EMPTY', '不为空': 'NOT_EMPTY',
    '开头是': 'STARTS_WITH', '结尾是': 'ENDS_WITH',
    '大于': 'GT', '小于': 'LT',
    '大于等于': 'GTE', '小于等于': 'LTE',
    '早于': 'DATE_BEFORE', '晚于': 'DATE_AFTER',
    '早于等于': 'DATE_BEFORE_EQ', '晚于等于': 'DATE_AFTER_EQ',
    '时间段': 'DATE_RANGE',
    '过去N天内(不含当天)': 'PAST_N_DAYS_EXCLUSIVE',
    '未来N天内(不含当天)': 'FUTURE_N_DAYS_EXCLUSIVE',
    '过去N月内(不含当月)': 'PAST_N_MONTHS_EXCLUSIVE',
    '未来N月内(不含当月)': 'FUTURE_N_MONTHS_EXCLUSIVE',
    '过去N周内(不含当周)': 'PAST_N_WEEKS_EXCLUSIVE',
    '未来N周内(不含当周)': 'FUTURE_N_WEEKS_EXCLUSIVE',
    '过去N天内(含当天)': 'PAST_N_DAYS_INCLUSIVE',
    '未来N天内(含当天)': 'FUTURE_N_DAYS_INCLUSIVE',
    '过去N周内(含当周)': 'PAST_N_WEEKS_INCLUSIVE',
    '未来N周内(含当周)': 'FUTURE_N_WEEKS_INCLUSIVE',
    '过去N月内(含当月)': 'PAST_N_MONTHS_INCLUSIVE',
    '未来N月内(含当月)': 'FUTURE_N_MONTHS_INCLUSIVE',
    'N天前': 'N_DAYS_AGO', 'N天后': 'N_DAYS_LATER',
    'N周前': 'N_WEEKS_AGO', 'N周后': 'N_WEEKS_LATER',
    '过去N季度内(含当季度)': 'PAST_N_QUARTERS_INCLUSIVE',
}


# ---- 点击外部关闭过滤器 ----

class _ClickOutsideFilter(QObject):
    """监听全局鼠标点击，如果点击在筛选面板和切换按钮之外则关闭面板。"""

    def __init__(self, bar: 'FilterBar'):
        super().__init__(bar)
        self._bar = bar

    def eventFilter(self, watched, event):
        from PyQt6.QtCore import QEvent
        try:
            bar = self._bar
            panel = bar._filter_panel
            if panel is None or not panel.isVisible():
                return False
        except RuntimeError:
            return False
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        gp = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
        # 检查是否在面板内（frameGeometry 是父控件坐标，需转全局）
        panel_geo = panel.frameGeometry()
        panel_top_left_global = panel.parentWidget().mapToGlobal(panel_geo.topLeft()) if panel.parentWidget() else panel.mapToGlobal(panel_geo.topLeft())
        panel_global_rect = panel_top_left_global.x(), panel_top_left_global.y(), panel_geo.width(), panel_geo.height()
        if panel_global_rect[0] <= gp.x() <= panel_global_rect[0] + panel_global_rect[2] and \
           panel_global_rect[1] <= gp.y() <= panel_global_rect[1] + panel_global_rect[3]:
            return False
        # 检查是否在切换按钮内
        btn = getattr(bar, '_filter_toggle_btn', None)
        if btn is not None:
            btn_top_left = btn.mapToGlobal(QPoint(0, 0))
            btn_size = btn.size()
            if btn_top_left.x() <= gp.x() <= btn_top_left.x() + btn_size.width() and \
               btn_top_left.y() <= gp.y() <= btn_top_left.y() + btn_size.height():
                return False
        # 检查是否在追踪的子弹窗内
        if bar._outside_dialog_contains(gp):
            return False
        # 检查点击目标是否为弹窗类控件（QComboBox 下拉/QCompleter 弹窗/QDialog 等）
        target = None
        try:
            target = QApplication.widgetAt(gp)
        except Exception:
            pass
        if target is not None:
            from PyQt6.QtWidgets import QDialog, QAbstractItemView
            w = target
            while w is not None:
                # QComboBox 下拉列表 / QCompleter 弹窗 / QMenu 等
                if isinstance(w, (QDialog, QAbstractItemView)) and w.isVisible():
                    return False
                # 检查是否为 Popup 窗口（Qt.WindowType.Popup）
                if w.isVisible() and w.windowFlags() & Qt.WindowType.Popup:
                    return False
                w = w.parentWidget()
        # 点击外部 → 关闭
        panel.hide()
        bar._remove_outside_filter()
        return False


# ==================== FilterBar ====================


class FilterBar(QWidget):
    """筛选条件栏 —— 对齐 CRM 订单筛选逻辑"""

    filtersChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._conditions: list[dict] = []
        self._condition_rows: list[dict] = []   # widget row info
        self._available_fields: list[tuple] = []   # [(label, key, is_date, target_object_api), ...]
        self._all_field_labels: list[str] = []
        self._db = None            # ReportDatabase，用于查询去重值
        self._result_table = None  # 当前结果表名

        self._filter_panel = None
        self._panel_parented = False   # 面板是否已挂载到顶层窗口
        self._outside_filter = None    # 点击外部关闭的事件过滤器
        self._filter_active_dialogs: list = []  # 子弹窗追踪

        self._setup_ui()

    def set_database(self, db):
        """设置数据库连接，用于「属于」/「不属于」无配置字段时查询去重值。"""
        self._db = db

    def set_result_table(self, table_name: str):
        """设置当前结果表名，用于查询字段去重值。"""
        self._result_table = table_name

    def _outside_dialog_contains(self, gp) -> bool:
        """检查全局坐标是否在任一活跃的子弹窗内（日期选择/多选等）。"""
        for dlg in self._filter_active_dialogs:
            try:
                if dlg.isVisible():
                    dlg_geo = dlg.frameGeometry()
                    dlg_top = dlg.mapToGlobal(dlg_geo.topLeft()) if dlg.parentWidget() is None else dlg.parentWidget().mapToGlobal(dlg_geo.topLeft())
                    if dlg_top.x() <= gp.x() <= dlg_top.x() + dlg_geo.width() and \
                       dlg_top.y() <= gp.y() <= dlg_top.y() + dlg_geo.height():
                        return True
            except RuntimeError:
                pass
        return False

    def _track_child_dialog(self, dlg):
        """将子弹窗加入追踪列表，关闭时自动移除。"""
        if dlg not in self._filter_active_dialogs:
            self._filter_active_dialogs.append(dlg)
        try:
            dlg.destroyed.connect(lambda obj=None, d=dlg: self._untrack_child_dialog(d))
            dlg.finished.connect(lambda result, d=dlg: self._untrack_child_dialog(d))
        except Exception:
            pass

    def _untrack_child_dialog(self, dlg):
        if dlg in self._filter_active_dialogs:
            self._filter_active_dialogs.remove(dlg)

    def hideEvent(self, event):
        """FilterBar 被隐藏时自动关闭筛选面板（切换页面等场景）。"""
        if self._filter_panel and self._filter_panel.isVisible():
            self._filter_panel.hide()
            self._remove_outside_filter()
        super().hideEvent(event)

    # ==================== public API ====================

    def set_available_fields(self, fields: list):
        """设置可选字段列表 [(label, key, is_date, target_object_api), ...]，兼容 2/3-tuple"""
        self._available_fields = []
        self._all_field_labels = []
        seen = set()
        for item in fields:
            if len(item) >= 3:
                label, key, is_date = item[0], item[1], item[2]
            else:
                label, key = item[0], item[1]
                is_date = False
            target_object_api = item[3] if len(item) >= 4 else ""
            entry = (str(label), str(key), bool(is_date), str(target_object_api or ""))
            if entry in seen:
                continue
            seen.add(entry)
            self._available_fields.append(entry)
            self._all_field_labels.append(entry[0])
        self._refresh_condition_field_combos()

    @staticmethod
    def _strip_object_prefix(label: str) -> str:
        """去掉形如 [对象名] 字段名 的对象前缀。"""
        label = str(label or '').strip()
        if label.startswith('[') and ']' in label:
            end = label.index(']')
            return label[end + 1:].strip()
        return label

    def _find_available_field(self, field_label='', field_key='', target_object_api=''):
        """在当前可选字段中按 label/key/对象 API 查找字段元信息。"""
        field_label = str(field_label or '').strip()
        field_key = str(field_key or '').strip()
        target_object_api = str(target_object_api or '').strip()
        bare_label = self._strip_object_prefix(field_label)

        def score(entry):
            label, key, _is_date, target = entry
            if target_object_api and target and target != target_object_api:
                return None
            label_matches = label == field_label or self._strip_object_prefix(label) == bare_label
            key_matches = bool(field_key) and key == field_key
            if target_object_api and target == target_object_api and (key_matches or label_matches):
                return 0
            if label == field_label:
                return 1
            if key_matches and label_matches:
                return 2
            if key_matches:
                return 3
            if label_matches:
                return 4
            return None

        best = None
        best_score = None
        for entry in self._available_fields:
            s = score(entry)
            if s is None:
                continue
            if best_score is None or s < best_score:
                best = entry
                best_score = s
        return best

    def _find_available_field_index(self, field_label='', field_key='', target_object_api='') -> int:
        target = self._find_available_field(field_label, field_key, target_object_api)
        if not target:
            return -1
        for i, entry in enumerate(self._available_fields):
            if entry == target:
                return i
        return -1

    def _install_field_completer(self, field_combo):
        completer = QCompleter([str(l) for l in self._all_field_labels], self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        field_combo.setCompleter(completer)

    def _populate_field_combo_options(self, field_combo):
        field_combo.clear()
        for label, key, _is_date, _target_api in self._available_fields:
            field_combo.addItem(str(label), key)
        self._install_field_completer(field_combo)

    def _refresh_condition_field_combos(self):
        """报表列变化后，同步已存在条件行的字段下拉选项。"""
        for row_info in getattr(self, '_condition_rows', []):
            field_combo = row_info.get('field_combo')
            if not field_combo:
                continue
            current_label = field_combo.currentText().strip()
            current_key = field_combo.currentData()
            current_target = row_info.get('target_object_api', '')
            matched = self._find_available_field(current_label, current_key, current_target)

            field_combo.blockSignals(True)
            self._populate_field_combo_options(field_combo)
            if matched:
                idx = self._find_available_field_index(matched[0], matched[1], matched[3])
                if idx >= 0:
                    field_combo.setCurrentIndex(idx)
                row_info['target_object_api'] = matched[3]
            else:
                field_combo.setCurrentIndex(-1)
                if field_combo.lineEdit():
                    field_combo.setEditText('')
                row_info['target_object_api'] = ''
            field_combo.blockSignals(False)
            self._update_condition_input_mode(row_info)

    def get_conditions(self) -> list[dict]:
        """获取当前筛选条件列表 [{field, field_label, target_object_api, operator, value, expose, is_date}]"""
        return self._collect_conditions()

    def set_conditions(self, conditions: list[dict]):
        """设置筛选条件（从报表恢复，不触发 filtersChanged 避免覆盖性自动保存）"""
        self._clear_all_condition_rows(emit=False)
        for cond in (conditions or []):
            self._add_condition_row(cond, emit=False)
        self._refresh_exposed_tags()
        self._update_filter_toggle_badge()

    def clear_all(self):
        self._clear_all_condition_rows()
        self._refresh_exposed_tags()
        self._update_filter_toggle_badge()

    # ==================== UI setup ====================

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ---- 外露标签栏 ----
        self._tags_frame = QFrame()
        self._tags_frame.setStyleSheet("QFrame { background: transparent; }")
        self._tags_layout = QHBoxLayout(self._tags_frame)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(4)
        self._tags_layout.addStretch()
        self._tags_frame.setVisible(False)
        layout.addWidget(self._tags_frame)

        # ---- 筛选面板（内联子控件，不使用 Popup 窗口，确保输入法 IME 正常工作） ----
        panel = QFrame(self)
        panel.setVisible(False)
        panel.setStyleSheet("QFrame#filterPanel { border: 1px solid #D9D9D9; border-radius: 6px; background: #FAFAFA; }")
        panel.setObjectName("filterPanel")
        panel.setMinimumWidth(520)
        panel.setMinimumHeight(120)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.setSpacing(6)

        # 标题行
        title_row = QHBoxLayout()
        title = QLabel("设置筛选")
        title.setStyleSheet("font-size: 14px; font-weight: 600; color: #333; border: none; background: transparent;")
        title_row.addWidget(title)
        title_row.addStretch()
        clear_all_btn = QPushButton("清除全部")
        clear_all_btn.setMinimumWidth(56)
        clear_all_btn.setFixedHeight(24)
        clear_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_all_btn.setStyleSheet("""
            QPushButton { border: 1px solid #FF4D4F; color: #FF4D4F; border-radius: 3px;
                          font-size: 11px; padding: 2px 8px; background: #FFFFFF; }
            QPushButton:hover { background: #FFF1F0; }
        """)
        clear_all_btn.clicked.connect(lambda: self._clear_all_conditions())
        title_row.addWidget(clear_all_btn)
        panel_layout.addLayout(title_row)

        # 条件行容器（包在 QScrollArea 中，支持多条件滚动）
        self._conditions_scroll = QScrollArea()
        self._conditions_scroll.setWidgetResizable(True)
        self._conditions_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._conditions_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._conditions_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._conditions_scroll.setMinimumHeight(36)
        self._conditions_scroll.setMaximumHeight(320)
        conditions_widget = QWidget()
        self._conditions_container = QVBoxLayout(conditions_widget)
        self._conditions_container.setContentsMargins(0, 0, 0, 0)
        self._conditions_container.setSpacing(4)
        self._conditions_scroll.setWidget(conditions_widget)
        panel_layout.addWidget(self._conditions_scroll, 1)

        # 底部按钮
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)

        add_btn = QPushButton("+ 添加条件")
        add_btn.setMinimumWidth(72)
        add_btn.setFixedHeight(28)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet("""
            QPushButton { border: 1px solid #1890FF; color: #1890FF; border-radius: 4px;
                          font-size: 12px; padding: 2px 12px; background: #FFFFFF; }
            QPushButton:hover { background: #E6F7FF; }
        """)
        add_btn.clicked.connect(lambda: self._add_condition_row())
        bottom_row.addWidget(add_btn)

        bottom_row.addStretch()

        apply_btn = QPushButton("筛选")
        apply_btn.setMinimumWidth(48)
        apply_btn.setFixedHeight(28)
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet("""
            QPushButton { background-color: #FF8C00; color: #FFFFFF; border: none;
                          border-radius: 4px; font-size: 13px; font-weight: 600; padding: 2px 16px; }
            QPushButton:hover { background-color: #E67A00; }
        """)
        apply_btn.clicked.connect(lambda: [self._apply_filters(), panel.hide()])
        bottom_row.addWidget(apply_btn)

        panel_layout.addLayout(bottom_row)

        self._filter_panel = panel

    # ==================== 条件行管理 ====================

    def _add_condition_row(self, condition=None, emit=True):
        """添加一条筛选条件行"""
        condition = condition or {}
        panel = self._filter_panel

        row_frame = QFrame()
        row_frame.setFixedHeight(32)
        row_frame.setStyleSheet("QFrame { background: #F8F8F8; border: none; border-radius: 4px; }")
        row_layout = QHBoxLayout(row_frame)
        row_layout.setContentsMargins(6, 0, 6, 0)
        row_layout.setSpacing(5)

        # 删除按钮
        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(20, 20)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setToolTip("删除此条件")
        remove_btn.setStyleSheet("""
            QPushButton { font-weight: bold; color: #FF4D4F; border: 1px solid #FFCCC7;
                          border-radius: 10px; font-size: 10px; background: #FFF2F0; }
            QPushButton:hover { background: #FF4D4F; color: #FFF; border-color: #FF4D4F; }
        """)
        row_layout.addWidget(remove_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        # 字段选择
        field_combo = QComboBox()
        field_combo.setEditable(True)
        field_combo.setFixedWidth(140)
        field_combo.setFixedHeight(26)
        field_combo.setPlaceholderText("选择字段")
        field_combo.setStyleSheet("""
            QComboBox { font-size: 12px; border: 1px solid #D9D9D9; border-radius: 3px;
                        padding: 2px 4px; background: #FFF; }
            QComboBox QAbstractItemView { font-size: 12px; }
        """)
        self._populate_field_combo_options(field_combo)

        field_key = str(condition.get('field', '')).strip()
        field_label = str(condition.get('field_label', '')).strip()
        target_object_api = str(condition.get('target_object_api', '')).strip()
        if field_key or field_label:
            # 优先按 对象API + 字段API 精确匹配，避免不同表的同名字段串台
            idx = self._find_available_field_index(field_label, field_key, target_object_api)
            if idx >= 0:
                field_combo.setCurrentIndex(idx)
            else:
                # 回退：用 API key 匹配 item data（兼容旧报表）
                idx = field_combo.findData(field_key) if field_key else -1
            if idx >= 0:
                field_combo.setCurrentIndex(idx)
            else:
                # 回退：用 label 匹配显示文本
                if field_label:
                    idx = field_combo.findText(field_label)
                if idx >= 0:
                    field_combo.setCurrentIndex(idx)
                else:
                    # 最终回退：显示 label（可读），保留原始 key 在 data 中
                    field_combo.setEditText(field_label or field_key)
        row_layout.addWidget(field_combo, alignment=Qt.AlignmentFlag.AlignVCenter)

        # 操作符选择
        op_combo = QComboBox()
        op_combo.setFixedWidth(120)
        op_combo.setFixedHeight(26)
        op_combo.setStyleSheet("""
            QComboBox { font-size: 12px; border: 1px solid #D9D9D9; border-radius: 3px;
                        padding: 2px 2px; background: #FFF; }
            QComboBox QAbstractItemView { font-size: 12px; }
        """)
        sel_op = str(condition.get('operator', 'contains')).strip()

        # 判断字段类型，选择操作符
        field_label = field_combo.currentText().strip()
        is_date = self._is_date_field(field_label)
        import sys
        print(f"[FilterDebug] _add_condition_row: field_label={field_label!r}, is_date={is_date}, "
              f"available_fields sample={self._available_fields[:3] if self._available_fields else 'EMPTY'}",
              file=sys.stderr, flush=True)
        if sel_op in _N_TYPE_OPS:
            is_date = True
        operators = _date_operators() if is_date else _text_operators()
        for label, key in operators:
            op_combo.addItem(label, key)

        # 尝试匹配操作符
        op_idx = op_combo.findData(sel_op)
        if op_idx < 0:
            # 反向查找：API码 → 中文标签
            for label, key in operators:
                api_key = _OP_CN_TO_API.get(label, '')
                if api_key.upper() == sel_op.upper() or key == sel_op:
                    op_idx = op_combo.findData(key)
                    break
        if op_idx >= 0:
            op_combo.setCurrentIndex(op_idx)
        row_layout.addWidget(op_combo, alignment=Qt.AlignmentFlag.AlignVCenter)

        # 值输入区 (QStackedWidget: 0=text, 1=date, 2=date_range, 3=spinbox)
        value_stack = QStackedWidget()
        value_stack.setFixedWidth(150)
        value_stack.setFixedHeight(26)

        # Page 0: 文本
        value_input = QLineEdit()
        value_input.setPlaceholderText("值")
        value_input.setFixedHeight(26)
        value_input.setStyleSheet("font-size: 12px; border: 1px solid #D9D9D9; border-radius: 3px; padding: 2px 4px;")
        value_input.setText(str(condition.get('value', '')))
        # 防抖：避免每次按键都触发 filtersChanged → 编辑器刷新预览 → DB 查询打断 IME 输入
        _value_change_timer = QTimer()
        _value_change_timer.setSingleShot(True)
        _value_change_timer.setInterval(300)
        _value_change_timer.timeout.connect(lambda: self.filtersChanged.emit())
        value_input.textChanged.connect(lambda: _value_change_timer.start())
        value_stack.addWidget(value_input)

        # Page 1: 日期
        date_input = QDateEdit()
        date_input.setCalendarPopup(True)
        date_input.setDisplayFormat("yyyy-MM-dd")
        date_input.setDate(QDate.currentDate())
        date_input.setFixedHeight(26)
        date_input.setStyleSheet("font-size: 12px; border: 1px solid #D9D9D9; border-radius: 3px; padding: 2px 2px;")
        raw_val = str(condition.get('value', '')).strip()
        if raw_val:
            parsed = QDate.fromString(raw_val[:10], "yyyy-MM-dd")
            if parsed.isValid():
                date_input.setDate(parsed)
        date_input.dateChanged.connect(lambda: self.filtersChanged.emit())
        value_stack.addWidget(date_input)

        # Page 2: 日期范围按钮
        date_range_btn = QPushButton("选择日期范围")
        date_range_btn.setFixedHeight(26)
        date_range_btn.setStyleSheet("""
            QPushButton { border: 1px solid #D9D9D9; border-radius: 3px;
                          padding: 2px 6px; font-size: 12px; background: #FFF; }
            QPushButton:hover { border-color: #1890FF; }
        """)
        range_data = {'start': None, 'end': None}
        if condition.get('operator', '') in ('date_range', 'DATE_RANGE') and '~' in str(condition.get('value', '')):
            parts = str(condition['value']).split('~')
            if len(parts) == 2:
                s = QDate.fromString(parts[0].strip(), "yyyy-MM-dd")
                e = QDate.fromString(parts[1].strip(), "yyyy-MM-dd")
                if s.isValid() and e.isValid():
                    range_data = {'start': s, 'end': e}
                    date_range_btn.setText(f"{s.toString('yyyy-MM-dd')} ~ {e.toString('yyyy-MM-dd')}")
        date_range_btn.setProperty('cr_date_range', range_data)
        date_range_btn.clicked.connect(lambda checked, b=date_range_btn: self._open_condition_date_range(b))
        value_stack.addWidget(date_range_btn)

        # Page 3: 数字
        n_input = QSpinBox()
        n_input.setFixedHeight(26)
        n_input.setStyleSheet("font-size: 12px;")
        n_input.setRange(1, 999)
        raw_n = str(condition.get('value', '1'))
        n_input.setValue(int(raw_n) if raw_n.isdigit() else 1)
        n_input.valueChanged.connect(lambda: self.filtersChanged.emit())
        value_stack.addWidget(n_input)

        # Page 4: 多选（"属于"/"不属于"运算符，对齐 CRM 对象管理筛选逻辑）
        picker_widget = QWidget()
        picker_layout = QHBoxLayout(picker_widget)
        picker_layout.setContentsMargins(0, 0, 0, 0)
        picker_layout.setSpacing(2)
        multi_select_input = QLineEdit()
        multi_select_input.setPlaceholderText("输入或点击📋选择（多个值用；，; 隔开）")
        multi_select_input.setFixedHeight(26)
        multi_select_input.setStyleSheet("font-size: 12px; border: 1px solid #D9D9D9; border-radius: 3px; padding: 2px 4px;")
        multi_select_input.setText(str(condition.get('value', '')))
        # 手动输入时也触发筛选刷新（带防抖）
        _ms_change_timer = QTimer()
        _ms_change_timer.setSingleShot(True)
        _ms_change_timer.setInterval(300)
        _ms_change_timer.timeout.connect(lambda: self.filtersChanged.emit())
        multi_select_input.textChanged.connect(lambda: _ms_change_timer.start())
        picker_layout.addWidget(multi_select_input, 1)
        picker_btn = QPushButton("📋")
        picker_btn.setFixedSize(24, 24)
        picker_btn.setToolTip("从选项中选择多个值")
        picker_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        picker_btn.setStyleSheet("QPushButton { font-size: 11px; border: 1px solid #D9D9D9; border-radius: 3px; background: #FFF; } QPushButton:hover { border-color: #1890FF; background: #E6F7FF; }")
        picker_layout.addWidget(picker_btn)
        value_stack.addWidget(picker_widget)

        value_stack.setCurrentIndex(0)
        row_layout.addWidget(value_stack, alignment=Qt.AlignmentFlag.AlignVCenter)

        # 外露
        expose_check = QCheckBox("外露")
        expose_check.setChecked(bool(condition.get('expose', False)))
        expose_check.setToolTip("勾选后在筛选栏下方显示该条件标签")
        expose_check.setStyleSheet("QCheckBox { font-size: 12px; color: #666; spacing: 2px; }")
        expose_check.toggled.connect(lambda checked: self._refresh_exposed_tags())
        row_layout.addWidget(expose_check, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._conditions_container.addWidget(row_frame)

        row_info = {
            'frame': row_frame,
            'field_combo': field_combo,
            'op_combo': op_combo,
            'target_object_api': target_object_api,
            'value_stack': value_stack,
            'value_input': value_input,
            'date_input': date_input,
            'date_range_btn': date_range_btn,
            'n_input': n_input,
            'multi_select_input': multi_select_input,
            'picker_btn': picker_btn,
            'expose_check': expose_check,
        }
        self._condition_rows.append(row_info)

        # 连接信号
        remove_btn.clicked.connect(lambda: self._remove_condition_row(row_info))

        def _on_field_changed(info):
            matched = self._find_available_field(
                info['field_combo'].currentText().strip(),
                info['field_combo'].currentData(),
            )
            info['target_object_api'] = matched[3] if matched else ''
            info['value_input'].clear()
            info['date_input'].setDate(QDate.currentDate())
            info['date_range_btn'].setText("选择日期范围")
            info['date_range_btn'].setProperty('cr_date_range', {'start': None, 'end': None})
            info['n_input'].setValue(1)
            self._update_condition_input_mode(info)
            self.filtersChanged.emit()

        # editTextChanged 使用防抖延迟，避免在 IME 组合输入过程中频繁触发
        _field_change_timer = QTimer()
        _field_change_timer.setSingleShot(True)
        _field_change_timer.setInterval(200)

        def _on_edit_text_changed(text, info=row_info, timer=_field_change_timer):
            timer.start()

        _field_change_timer.timeout.connect(lambda info=row_info: _on_field_changed(info))

        field_combo.currentIndexChanged.connect(lambda idx, info=row_info: _on_field_changed(info))
        field_combo.editTextChanged.connect(_on_edit_text_changed)
        if field_combo.lineEdit():
            field_combo.lineEdit().editingFinished.connect(
                lambda info=row_info: self._update_condition_input_mode(info))
        op_combo.currentIndexChanged.connect(
            lambda idx, info=row_info: (self._update_condition_input_mode(info), self.filtersChanged.emit()))
        # 多选按钮 → 弹出选项列表
        picker_btn.clicked.connect(lambda checked, ri=row_info: self._open_multi_select_picker(ri))

        self._update_condition_input_mode(row_info)
        self._refresh_exposed_tags()
        self._update_filter_toggle_badge()
        self._adjust_filter_panel_size()

        if emit:
            self.filtersChanged.emit()

    def _remove_condition_row(self, row_info):
        if row_info in self._condition_rows:
            self._condition_rows.remove(row_info)
        frame = row_info.get('frame')
        if frame:
            frame.setParent(None)
            frame.deleteLater()
        self._refresh_exposed_tags()
        self._update_filter_toggle_badge()
        self._adjust_filter_panel_size()
        self.filtersChanged.emit()

    def _clear_all_condition_rows(self, emit=True):
        for row_info in list(self._condition_rows):
            frame = row_info.get('frame')
            if frame:
                frame.setParent(None)
                frame.deleteLater()
        self._condition_rows.clear()
        self._refresh_exposed_tags()
        self._update_filter_toggle_badge()
        self._adjust_filter_panel_size()
        if emit:
            self.filtersChanged.emit()

    def _clear_all_conditions(self):
        """清除所有条件（按钮回调）"""
        self._clear_all_condition_rows(emit=True)

    # ==================== 输入模式切换 ====================

    def _update_condition_input_mode(self, row_info):
        """根据字段类型和操作符切换 value_stack"""
        field_label = row_info['field_combo'].currentText().strip()
        is_date = self._is_date_field(field_label)

        op_combo = row_info['op_combo']
        # 重建操作符列表
        current_op = op_combo.currentData() or ''
        op_combo.blockSignals(True)
        op_combo.clear()
        operators = _date_operators() if is_date else _text_operators()
        for label, key in operators:
            op_combo.addItem(label, key)
        idx = op_combo.findData(current_op)
        if idx < 0 and is_date:
            idx = op_combo.findData('date_range')
        op_combo.setCurrentIndex(idx if idx >= 0 else 0)
        op_combo.blockSignals(False)

        operator = op_combo.currentData() or ''
        requires_value = operator not in ('empty', 'not_empty')
        row_info['value_stack'].setVisible(requires_value)
        if not requires_value:
            return

        if operator in ('in', 'not_in'):
            # "属于"/"不属于" → 多选组件（对齐 CRM 对象管理筛选逻辑）
            row_info['value_stack'].setCurrentIndex(4)
        elif is_date and operator == 'date_range':
            row_info['value_stack'].setCurrentIndex(2)
        elif (is_date and operator in _N_TYPE_OPS) or operator in _NUMERIC_COMPARE_OPS:
            row_info['value_stack'].setCurrentIndex(3)
        elif is_date:
            row_info['value_stack'].setCurrentIndex(1)
        else:
            row_info['value_stack'].setCurrentIndex(0)

    # ==================== 日期范围选择 ====================

    def _open_condition_date_range(self, btn):
        """打开日期范围选择弹窗 —— 对齐 CRM 合同转订单 QuickDatePickerDialog"""
        import sys
        main_mod = sys.modules.get('__main__')
        if not main_mod or not hasattr(main_mod, 'QuickDatePickerDialog'):
            # 回退：主模块未加载或无 QuickDatePickerDialog 时用简易弹窗
            self._open_simple_date_range(btn)
            return
        QuickDatePickerDialog = main_mod.QuickDatePickerDialog
        dr = btn.property('cr_date_range') or {'start': None, 'end': None}
        dlg = QuickDatePickerDialog(
            start_date=dr.get('start'),
            end_date=dr.get('end'),
            parent=self.window() or self,
        )
        dlg.set_popup_anchor_widget(btn)
        self._track_child_dialog(dlg)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.start_date and dlg.end_date:
            new_range = {'start': dlg.start_date, 'end': dlg.end_date}
            btn.setProperty('cr_date_range', new_range)
            btn.setText(f"{dlg.start_date.toString('yyyy-MM-dd')} ~ {dlg.end_date.toString('yyyy-MM-dd')}")
            self.filtersChanged.emit()

    def _open_simple_date_range(self, btn):
        """简易日期范围弹窗（主模块不可用时的回退方案）"""
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self.window() or self)
        dlg.setWindowTitle("选择日期范围")
        dlg.resize(360, 160)
        dlg.setStyleSheet("QDialog { background: #FAFAFA; }")

        layout = QVBoxLayout(dlg)
        row = QHBoxLayout()
        row.addWidget(QLabel("开始:"))
        start_edit = QDateEdit(QDate.currentDate())
        start_edit.setCalendarPopup(True)
        start_edit.setDisplayFormat("yyyy-MM-dd")
        row.addWidget(start_edit)
        row.addWidget(QLabel("结束:"))
        end_edit = QDateEdit(QDate.currentDate())
        end_edit.setCalendarPopup(True)
        end_edit.setDisplayFormat("yyyy-MM-dd")
        row.addWidget(end_edit)
        layout.addLayout(row)

        rd = btn.property('cr_date_range')
        if rd:
            if rd.get('start'):
                start_edit.setDate(rd['start'])
            if rd.get('end'):
                end_edit.setDate(rd['end'])

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        self._track_child_dialog(dlg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            s = start_edit.date()
            e = end_edit.date()
            if s <= e:
                btn.setProperty('cr_date_range', {'start': s, 'end': e})
                btn.setText(f"{s.toString('yyyy-MM-dd')} ~ {e.toString('yyyy-MM-dd')}")
            else:
                btn.setProperty('cr_date_range', {'start': e, 'end': s})
                btn.setText(f"{e.toString('yyyy-MM-dd')} ~ {s.toString('yyyy-MM-dd')}")
            self.filtersChanged.emit()

    # ==================== 多选（"属于"/"不属于"） ====================

    def _get_field_option_mappings(self, row_info) -> dict:
        """获取筛选条件行的字段选项映射 {option_id: display_text}。

        查找链路（对齐 CRM 对象管理 _get_default_condition_field_mappings）：
        1. 优先用 _available_fields 回查完整 label（含 [对象名] 前缀）
        2. 解析 [对象名] 前缀 → api_name
        3. 候选 key → 在 crm_object_fields 中反查 field_api_key
        4. 读取 crm_option_mappings[api_name][field_api_key]
        """
        import sys
        main_mod = sys.modules.get('__main__')
        if not main_mod or not hasattr(main_mod, 'load_config'):
            return {}
        try:
            cfg = main_mod.load_config()
        except Exception:
            return {}

        field_data = row_info['field_combo'].currentData()  # API key 或中文列名
        field_text = row_info['field_combo'].currentText().strip()
        if not field_text:
            return {}

        # 通过 _available_fields 回查完整 label（含 [对象名] 前缀）
        # 当数据源是结果表列名时，field_text 无前缀，但 _available_fields 可能有带前缀的条目
        full_label = field_text
        full_key = field_data
        target_object_api = ''
        matched_field = self._find_available_field(field_text, field_data)
        if matched_field:
            full_label, full_key, _is_date, target_object_api = matched_field

        # 解析 [对象名] 前缀
        object_label = ''
        field_label = full_label
        if full_label.startswith('[') and ']' in full_label:
            end = full_label.index(']')
            object_label = full_label[1:end]
            field_label = full_label[end + 1:].strip()

        # 候选 key
        candidate_keys = []
        if full_key:
            candidate_keys.append(full_key)
        if field_label and field_label not in candidate_keys:
            candidate_keys.append(field_label)
        # 也加入原始 field_data 和 field_text
        if field_data and str(field_data).strip() not in candidate_keys:
            candidate_keys.append(str(field_data).strip())
        if field_text not in candidate_keys:
            candidate_keys.append(field_text)

        fx_fields = cfg.get('fxiaoke', {}).get('crm_object_fields', {})
        fx_mappings = cfg.get('fxiaoke', {}).get('crm_option_mappings', {})
        br_mappings = cfg.get('business_rules', {}).get('crm_option_mappings', {})

        # 确定 API 列表。若字段来自报表列，必须只查该列所属对象，避免同名字段串表加载选项。
        api_names = []
        exact_api_locked = False
        if target_object_api:
            api_names.append(target_object_api)
            exact_api_locked = True
        elif object_label:
            crm_objects = cfg.get('fxiaoke', {}).get('crm_objects', []) or []
            for obj in crm_objects:
                if isinstance(obj, dict) and obj.get('name', '') == object_label:
                    api_names.append(obj.get('api_name', ''))
                    exact_api_locked = True
        if not exact_api_locked:
            for api in fx_fields:
                if api not in api_names:
                    api_names.append(api)
            for api in fx_mappings:
                if api not in api_names:
                    api_names.append(api)
            # 也加入 crm_objects 中的所有 API
            for obj in (cfg.get('fxiaoke', {}).get('crm_objects', []) or []):
                if isinstance(obj, dict) and obj.get('api_name'):
                    a = obj['api_name']
                    if a not in api_names:
                        api_names.append(a)

        for api_name in api_names:
            obj_fields = fx_fields.get(api_name, {})
            api_mappings = fx_mappings.get(api_name, {})
            if not isinstance(obj_fields, dict):
                obj_fields = {}
            if not isinstance(api_mappings, dict):
                api_mappings = {}

            resolved_keys = set()
            for ck in candidate_keys:
                if not ck:
                    continue
                if ck in obj_fields:
                    resolved_keys.add(ck)
                if ck in api_mappings:
                    resolved_keys.add(ck)
                for fk, fi in obj_fields.items():
                    label = (fi.get('label', fk) if isinstance(fi, dict) else str(fi)) if fi else fk
                    if str(label).strip() == ck:
                        resolved_keys.add(fk)

            for rk in resolved_keys:
                if rk in api_mappings:
                    return api_mappings[rk]
                if not exact_api_locked and isinstance(br_mappings, dict) and rk in br_mappings:
                    return br_mappings[rk]

        # 最终回退：直接在 br_mappings 中按候选 key 查找
        if not exact_api_locked and isinstance(br_mappings, dict):
            for ck in candidate_keys:
                if ck and ck in br_mappings:
                    return br_mappings[ck]

        return {}

    def _query_distinct_values(self, field_label: str) -> dict:
        """从结果表查询某字段的去重值，返回 {value: value} 映射（值与显示文本相同）。"""
        if not self._db or not self._result_table or not field_label:
            return {}
        try:
            safe_label = field_label.replace('`', '``')
            sql = (f"SELECT DISTINCT `{safe_label}` FROM `{self._result_table}` "
                   f"WHERE `{safe_label}` IS NOT NULL AND `{safe_label}` != '' "
                   f"ORDER BY `{safe_label}` LIMIT 500")
            rows = self._db.execute(sql)
            if rows:
                result = {}
                for r in rows:
                    v = str(r.get(field_label, '')).strip()
                    if v:
                        result[v] = v
                return result
        except Exception:
            pass
        return {}

    def _open_multi_select_picker(self, row_info):
        """打开多选下拉框，从选项映射中选择多个值（下拉框风格，对齐业务类型选择）。"""
        mappings = self._get_field_option_mappings(row_info)
        field_label = self._strip_object_prefix(
            row_info['field_combo'].currentText().strip())
        if not mappings:
            # 没有配置字段映射 → 从数据库结果表查询该字段的去重值
            mappings = self._query_distinct_values(field_label)
        if not mappings:
            from PyQt6.QtWidgets import QMessageBox
            _light_msgbox(self, QMessageBox.Icon.Information, '提示',
                          f'字段「{field_label}」暂无候选值。\n请先刷新数据，或手动输入筛选值。')
            return
        current = row_info['multi_select_input'].text().strip()

        import sys
        main_mod = sys.modules.get('__main__')
        anchor = row_info.get('picker_btn') or row_info.get('multi_select_input')
        target_input = row_info['multi_select_input']

        if main_mod and hasattr(main_mod, 'show_multi_select_dropdown'):
            main_mod.show_multi_select_dropdown(
                self.window() or self, mappings, current,
                anchor=anchor, target_input=target_input,
                on_change=lambda: self.filtersChanged.emit())
        else:
            self._simple_multi_select(mappings, current, anchor=anchor, target_input=target_input)

    def _simple_multi_select(self, mappings: dict, current: str, anchor=None, target_input=None):
        """简易多选下拉框（主模块 show_multi_select_dropdown 不可用时的回退方案）。"""
        import sys
        main_mod = sys.modules.get('__main__')
        # 优先尝试获取主模块的 CheckableOptionPopup
        CheckablePopup = getattr(main_mod, 'CheckableOptionPopup', None) if main_mod else None
        if CheckablePopup is not None:
            popup = CheckablePopup(self.window() or self)
            # ---- 关键：把 Popup 改为 Dialog，避免 Popup 的鼠标 grab 拦截外部点击 ----
            popup.setWindowFlags(
                Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            )
            popup.hide()  # 销毁 Popup 标志创建的原生句柄
            # 保持引用防止 GC，但不走 _track_child_dialog（popup 是 QFrame 非 QDialog，无 finished 信号）
            if popup not in self._filter_active_dialogs:
                self._filter_active_dialogs.append(popup)
            popup.destroyed.connect(lambda obj=None, p=popup: self._untrack_child_dialog(p))
            options = sorted(mappings.items(), key=lambda x: x[1])
            display_labels = [display for _id, display in options]
            label_to_id = {display: option_id for option_id, display in options}
            selected_set = set(v.strip() for v in current.replace(',', '；').split('；') if v.strip())
            popup.set_options(display_labels, selected_options=list(selected_set))
            def _on_selection_changed():
                if target_input is not None:
                    selected_labels = popup.get_selected_options()
                    values = [label_to_id.get(l, l) for l in selected_labels]
                    target_input.setText('；'.join(values) if values else '')
                self.filtersChanged.emit()
            popup.selection_changed.connect(_on_selection_changed)

            # ---- 点击外部关闭（_DialogOutsideCloseFilter） ----
            import sys
            main_mod = sys.modules.get('__main__')
            OutsideFilter = getattr(main_mod, '_DialogOutsideCloseFilter', None)
            if OutsideFilter is not None:
                popup.reject = lambda: popup.hide()
                pf = OutsideFilter(popup)
                popup._outside_filter = pf
                popup._outside_close_armed = False
                from PyQt6.QtWidgets import QApplication as QA2
                QA2.instance().installEventFilter(pf)
                QTimer.singleShot(0, lambda p=popup: setattr(p, '_outside_close_armed', True))
                # 销毁时移除过滤器
                _pf_ref = pf
                def _cleanup_filter(obj=None, f=_pf_ref):
                    try:
                        QA2.instance().removeEventFilter(f)
                    except Exception:
                        pass
                popup.destroyed.connect(_cleanup_filter)

            popup.show_below(anchor)
            popup.raise_()
            return

        # 最终回退：QDialog 弹窗
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QDialogButtonBox, QHBoxLayout
        dlg = QDialog(self.window() or self)
        dlg.setWindowTitle("选择值")
        dlg.setMinimumSize(260, 320)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        list_widget = QListWidget()
        list_widget.setStyleSheet("QListWidget { font-size: 12px; border: 1px solid #D9D9D9; border-radius: 3px; }")
        selected = set(v.strip() for v in current.split('；') if v.strip()) if current else set()
        items = sorted(mappings.items(), key=lambda x: x[1])
        for option_id, display_text in items:
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, option_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if display_text in selected else Qt.CheckState.Unchecked)
            list_widget.addItem(item)
        layout.addWidget(list_widget)
        sel_row = QHBoxLayout()
        from PyQt6.QtWidgets import QPushButton as QPB
        all_btn = QPB("全选")
        none_btn = QPB("取消全选")
        all_btn.setStyleSheet("QPushButton { font-size: 11px; border: 1px solid #D9D9D9; border-radius: 3px; padding: 2px 8px; } QPushButton:hover { border-color: #1890FF; }")
        none_btn.setStyleSheet("QPushButton { font-size: 11px; border: 1px solid #D9D9D9; border-radius: 3px; padding: 2px 8px; } QPushButton:hover { border-color: #1890FF; }")
        all_btn.clicked.connect(lambda: [list_widget.item(i).setCheckState(Qt.CheckState.Checked) for i in range(list_widget.count())])
        none_btn.clicked.connect(lambda: [list_widget.item(i).setCheckState(Qt.CheckState.Unchecked) for i in range(list_widget.count())])
        sel_row.addWidget(all_btn)
        sel_row.addWidget(none_btn)
        sel_row.addStretch()
        layout.addLayout(sel_row)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        self._track_child_dialog(dlg)
        dlg.adjustSize()
        if anchor is not None:
            try:
                anchor_global = anchor.mapToGlobal(anchor.rect().bottomLeft())
                dlg.move(anchor_global.x(), anchor_global.y() + 2)
            except Exception:
                pass
        if dlg.exec() == QDialog.DialogCode.Accepted:
            checked = []
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    checked.append(item.text())
            result = '；'.join(checked) if checked else ''
            if target_input is not None:
                target_input.setText(result)
            self.filtersChanged.emit()

    # ==================== 条件收集 ====================

    def _collect_conditions(self) -> list[dict]:
        """收集所有条件行"""
        result = []
        for row_info in self._condition_rows:
            raw_field_label = row_info['field_combo'].currentText().strip()
            field_key = row_info['field_combo'].currentData()
            matched_field = self._find_available_field(raw_field_label, field_key)
            target_object_api = ''
            matched_is_date = None
            if matched_field:
                matched_label, matched_key, matched_is_date, target_object_api = matched_field
                raw_field_label = matched_label
                field_key = matched_key

            field_label = raw_field_label
            # 去掉 [对象名] 前缀（筛选字段标签可能带前缀如 "[销售订单]业务类型"）
            field_label = self._strip_object_prefix(field_label)
            if not field_key:
                field_key = field_label  # fallback to label
            if not field_key:
                continue
            operator = row_info['op_combo'].currentData() or ''
            is_date = bool(matched_is_date) if matched_is_date is not None else self._is_date_field(raw_field_label)
            expose = row_info['expose_check'].isChecked()

            if operator in ('empty', 'not_empty'):
                value = ''
            elif operator in ('in', 'not_in'):
                value = row_info['multi_select_input'].text().strip()
                if not value:
                    continue
            elif is_date and operator == 'date_range':
                dr = row_info['date_range_btn'].property('cr_date_range')
                if dr and dr.get('start') and dr.get('end'):
                    value = f"{dr['start'].toString('yyyy-MM-dd')}~{dr['end'].toString('yyyy-MM-dd')}"
                else:
                    continue
            elif (is_date and operator in _N_TYPE_OPS) or operator in _NUMERIC_COMPARE_OPS:
                value = str(row_info['n_input'].value())
            elif is_date:
                value = row_info['date_input'].date().toString('yyyy-MM-dd')
            else:
                value = row_info['value_input'].text().strip()
                if not value:
                    continue

            # 将中文操作符转换为 API 操作码
            op_cn = row_info['op_combo'].currentText()
            api_operator = _OP_CN_TO_API.get(op_cn, operator.upper())

            result.append({
                'field': field_key,
                'field_label': field_label,
                'target_object_api': target_object_api,
                'operator': api_operator,
                'value': value,
                'expose': expose,
                'is_date': is_date,
            })
        return result

    # ==================== 外露标签 ====================

    def _refresh_exposed_tags(self):
        """刷新外露标签栏"""
        # 清除旧标签
        while self._tags_layout.count() > 0:
            item = self._tags_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        exposed = [ri for ri in self._condition_rows if ri['expose_check'].isChecked()]
        if not exposed:
            self._tags_frame.setVisible(False)
            return

        self._tags_frame.setVisible(True)
        for ri in exposed:
            field_label = ri['field_combo'].currentText().strip()
            operator_str = ri['op_combo'].currentText()
            is_date = self._is_date_field(field_label)
            op_data = ri['op_combo'].currentData()
            if operator_str in ('empty', 'not_empty'):
                val = operator_str
            elif op_data in ('in', 'not_in'):
                val = ri['multi_select_input'].text().strip()
            elif is_date and op_data == 'date_range':
                dr = ri['date_range_btn'].property('cr_date_range')
                if dr and dr.get('start') and dr.get('end'):
                    val = f"{dr['start'].toString('MM-dd')}~{dr['end'].toString('MM-dd')}"
                else:
                    val = "..."
            elif is_date and op_data in _N_TYPE_OPS:
                val = f"N={ri['n_input'].value()}"
            elif is_date:
                val = ri['date_input'].date().toString('MM-dd')
            else:
                val = ri['value_input'].text().strip()

            field_short = field_label[:4] if len(field_label) > 4 else field_label
            val_short = str(val)[:8] if len(str(val)) > 8 else str(val)
            tag_text = f"{field_short}:{val_short}"

            tag_btn = QPushButton(tag_text + " ×")
            tag_btn.setFixedHeight(22)
            tag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            tag_btn.setToolTip(f"{field_label} {operator_str} {val}\n点击编辑，× 移除")
            tag_btn.setStyleSheet("""
                QPushButton { background: #FFF7E6; border: 1px solid #FFD591; border-radius: 10px;
                              font-size: 11px; padding: 2px 10px; color: #D46B08; }
                QPushButton:hover { background: #FFE7BA; border-color: #FF8C00; }
            """)

            # 点击标签 → 编辑对应条件
            def _make_edit_fn(ri_copy):
                def _edit():
                    self._toggle_filter_panel(show=True)
                    # 高亮对应行（模拟点击字段下拉框）
                    try:
                        ri_copy['field_combo'].setFocus()
                    except Exception:
                        pass
                return _edit
            tag_btn.clicked.connect(_make_edit_fn(ri))
            self._tags_layout.addWidget(tag_btn)

        self._tags_layout.addStretch()

    # ==================== 筛选面板 ====================

    def _adjust_filter_panel_size(self):
        """根据条件行数动态调整面板高度，避免多条件时挤在一起。"""
        row_count = len(self._condition_rows)
        # 每个条件行 32px + 间距 4px，加上标题 30px + 底部 44px + 边距 24px
        content_h = row_count * 36 + 98
        content_h = max(140, min(content_h, 500))
        if hasattr(self, '_filter_panel') and self._filter_panel:
            self._filter_panel.setMinimumHeight(content_h)
            self._filter_panel.adjustSize()
            # 滚动区域高度：最多显示 6 行，超出部分滚动
            visible_h = min(row_count * 36, 216)
            if hasattr(self, '_conditions_scroll'):
                self._conditions_scroll.setMinimumHeight(visible_h)

    def set_toggle_button(self, btn):
        """设置外部的筛选切换按钮（用于定位弹出面板位置和更新 badge 文本）。

        Args:
            btn: QPushButton 实例，由外部（如 PreviewTable）持有和布局。
        """
        self._filter_toggle_btn = btn

    def toggle_filter_panel(self):
        """公开的筛选面板切换方法（供外部按钮调用）。"""
        self._toggle_filter_panel()

    def _toggle_filter_panel(self, show=None):
        """显示/隐藏筛选面板（对齐对象查询筛选面板的 Dialog + _DialogOutsideCloseFilter 模式）"""
        panel = self._filter_panel
        if panel is None:
            return
        if show is None:
            show = not panel.isVisible()
        if show:
            # 首次显示时，将面板挂载到顶层窗口，避免被同一布局中的 PreviewTable 等遮挡
            if not self._panel_parented:
                win = self.window()
                if win and panel.parentWidget() is not win:
                    panel.setParent(win)
                self._panel_parented = True
            self._adjust_filter_panel_size()
            panel.adjustSize()

            # ---- 关键：设为 Dialog 顶层窗口 + 安装 _DialogOutsideCloseFilter ----
            # 对齐对象查询 _toggle_obj_query_filter_panel，不使用 Popup（会 grab 鼠标）
            panel.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
            panel.setVisible(True)
            panel.raise_()
            panel.activateWindow()

            # 使用全局坐标定位在 toggle 按钮下方
            # 使用外部按钮定位；回退到 self 定位
            toggle_btn = getattr(self, '_filter_toggle_btn', None)
            if toggle_btn is not None:
                global_pos = toggle_btn.mapToGlobal(QPoint(0, toggle_btn.height() + 2))
            else:
                global_pos = self.mapToGlobal(QPoint(0, self.height()))
            panel.move(global_pos)

            # 安装点击外部关闭过滤器（对齐对象查询的 _DialogOutsideCloseFilter 机制）
            import sys
            main_mod = sys.modules.get('__main__')
            OutsideCloseFilter = getattr(main_mod, '_DialogOutsideCloseFilter', None) if main_mod else None
            if OutsideCloseFilter is not None:
                panel.reject = lambda: panel.setVisible(False)
                panel._outside_close_armed = False
                pf = OutsideCloseFilter(panel)
                panel._outside_filter = pf
                QApplication.instance().installEventFilter(pf)
                QTimer.singleShot(0, lambda p=panel: setattr(p, '_outside_close_armed', True))
            else:
                # 回退：使用自带的 _ClickOutsideFilter
                if self._outside_filter is None:
                    self._outside_filter = _ClickOutsideFilter(self)
                QTimer.singleShot(200, self._install_outside_filter)
        else:
            panel.hide()
            self._remove_outside_filter()

    def _install_outside_filter(self):
        if self._outside_filter and self._filter_panel and self._filter_panel.isVisible():
            try:
                QApplication.instance().installEventFilter(self._outside_filter)
            except Exception:
                pass

    def _remove_outside_filter(self):
        panel = self._filter_panel
        # 优先清理 _DialogOutsideCloseFilter（存储在 panel 上）
        old_pf = getattr(panel, '_outside_filter', None) if panel else None
        if old_pf is not None:
            try:
                QApplication.instance().removeEventFilter(old_pf)
            except Exception:
                pass
            try:
                panel._outside_filter = None
            except Exception:
                pass
        # 兼容旧的 _ClickOutsideFilter（存储在 self 上）
        if self._outside_filter:
            try:
                QApplication.instance().removeEventFilter(self._outside_filter)
            except Exception:
                pass

    def _apply_filters(self):
        """应用筛选条件（触发刷新）"""
        self._refresh_exposed_tags()
        self._update_filter_toggle_badge()
        self.filtersChanged.emit()

    def _update_filter_toggle_badge(self):
        """更新筛选按钮 badge 计数"""
        n = len(self._condition_rows)
        if hasattr(self, '_filter_toggle_btn'):
            self._filter_toggle_btn.setText(f"筛选({n})" if n > 0 else "筛选")

    # ==================== 字段类型判断 ====================

    def _is_date_field(self, field_label: str) -> bool:
        """判断字段是否为日期字段"""
        if not field_label:
            return False
        for label, key, is_date, _target_api in self._available_fields:
            if label == field_label or key == field_label:
                return is_date
        # 关键字回退
        date_keywords = ('时间', '日期', '创建', '修改', '提交', 'date', 'time', 'birth', 'birthday')
        ll = field_label.lower()
        for kw in date_keywords:
            if kw in ll:
                return True
        return False
