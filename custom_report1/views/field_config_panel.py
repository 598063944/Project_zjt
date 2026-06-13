"""
字段配置面板

显示报表中已选择的字段列，支持:
- 拖拽排序
- 编辑显示名
- 设置可见性
- 删除字段
- 聚合方式设置（SUM/AVG/COUNT/MAX/MIN）
- 添加计算字段（公式）
- 分组键与汇总行开关
"""

import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QAbstractItemView, QLabel, QCheckBox,
    QMessageBox, QComboBox, QDialog, QLineEdit, QFormLayout, QDialogButtonBox,
    QRadioButton, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QEvent, QTimer
from PyQt6.QtGui import QColor, QDrag, QDropEvent

logger = logging.getLogger(__name__)
import inspect

from ..formula_engine import _EXCEL_FUNC_REGISTRY


class NoWheelComboBox(QComboBox):
    """忽略鼠标滚轮事件的 QComboBox，防止滚动页面时意外修改下拉选项。"""

    def wheelEvent(self, event):
        event.ignore()


class _DragTable(QTableWidget):
    """支持手动拖拽排序的 QTableWidget，禁用 InternalMove 以避免 cellWidget 错位。"""

    dragFinished = pyqtSignal(int, int)  # from_row, to_row

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_from_row = -1
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def startDrag(self, supportedActions):
        self._drag_from_row = self.currentRow()
        super().startDrag(supportedActions)

    def dropEvent(self, event: QDropEvent):
        from_row = self._drag_from_row
        self._drag_from_row = -1
        if from_row < 0:
            event.ignore()
            return
        to_row = self.indexAt(event.position().toPoint()).row() if hasattr(event, 'position') else self.indexAt(event.pos()).row()
        if to_row < 0:
            to_row = self.rowCount() - 1
        if from_row == to_row:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.dragFinished.emit(from_row, to_row)


class FieldConfigPanel(QWidget):
    """字段配置面板"""

    columnsChanged = pyqtSignal()       # 列配置变更
    fieldRemoved = pyqtSignal(str)      # column_id
    fieldMoved = pyqtSignal(int, int)   # from_row, to_row

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[dict] = []  # [{id, display_name, source_object, source_field, visible, computation_type, aggregate_func, formula_expression}]
        self._building = False           # 防止循环信号
        self._show_summary_row = False
        self._group_by_fields: set = set()
        self._save_config_fn = None
        self._load_config_fn = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 标题行
        header_row = QHBoxLayout()
        title = QLabel("报表列")
        title.setStyleSheet("font-size: 14px; font-weight: 600; color: #333;")
        header_row.addWidget(title)
        header_row.addStretch()

        select_all = QPushButton("全选")
        select_all.setFixedSize(48, 24)
        select_all.setStyleSheet("font-size: 12px; padding: 2px 6px; border: 1px solid #D9D9D9; border-radius: 3px;")
        select_all.clicked.connect(self._select_all)
        header_row.addWidget(select_all)

        deselect_all = QPushButton("全不选")
        deselect_all.setFixedSize(60, 24)
        deselect_all.setStyleSheet("font-size: 12px; padding: 2px 6px; border: 1px solid #D9D9D9; border-radius: 3px;")
        deselect_all.clicked.connect(self._deselect_all)
        header_row.addWidget(deselect_all)

        remove_btn = QPushButton("- 移除")
        remove_btn.setMinimumWidth(60)
        remove_btn.setFixedHeight(24)
        remove_btn.setStyleSheet("""
            QPushButton { border: 1px solid #FF4D4F; color: #FF4D4F; border-radius: 3px;
                          padding: 2px 12px; font-size: 12px; background: #FFFFFF; }
            QPushButton:hover { background: #FFF1F0; }
        """)
        remove_btn.clicked.connect(self._remove_selected)
        header_row.addWidget(remove_btn)

        layout.addLayout(header_row)

        # 字段表格 (5列: 可见 | 显示名 | 来源 | 聚合方式 | 字段格式)
        self._table = _DragTable()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["显示", "列显示名", "来源", "聚合方式", "字段格式"])
        for c in range(5):
            hdr = self._table.horizontalHeaderItem(c)
            if hdr:
                hdr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #E0E0E0; border-radius: 4px;
                background-color: #FFFFFF; font-size: 12px; color: #333333;
            }
            QHeaderView::section {
                background-color: #FAFAFA; font-size: 11px; color: #333333;
                border: none; border-bottom: 1px solid #E0E0E0; padding: 4px;
            }
            QTableWidget::item { padding: 4px 6px; }
            QCheckBox { color: #333333; background: transparent; }
            QCheckBox::indicator { width: 14px; height: 14px; }
            QComboBox { font-size: 11px; color: #333333; background: #FFFFFF;
                        border: 1px solid #D9D9D9; border-radius: 3px; padding: 2px 4px; }
        """)
        hh = self._table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(20)
        hh.sectionResized.connect(self._on_field_col_resized)
        # 全部 Interactive：用户可自由拖拽调整每列宽度，不强制铺满
        for c in range(5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(0, 44)
        self._table.setColumnWidth(1, 140)
        self._table.setColumnWidth(2, 200)
        self._table.setColumnWidth(3, 72)
        self._table.setColumnWidth(4, 130)
        # 水平滚动条：列宽总和超出视口时出现，不强制挤压
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 列宽保存定时器（防抖）
        self._field_col_resize_timer = QTimer()
        self._field_col_resize_timer.setSingleShot(True)
        self._field_col_resize_timer.setInterval(400)
        self._field_col_resize_timer.timeout.connect(self._save_field_col_widths)
        self._table.cellChanged.connect(self._on_cell_changed)
        self._table.dragFinished.connect(self._on_drag_finished)

        layout.addWidget(self._table, 1)

        # 排序按钮 + 计算字段 + 汇总行设置
        compute_row = QHBoxLayout()
        compute_row.setSpacing(4)

        up_btn = QPushButton("↑ 上移")
        up_btn.setMinimumWidth(64)
        up_btn.setFixedHeight(26)
        up_btn.setStyleSheet(self._btn_style())
        up_btn.clicked.connect(self._move_up)
        compute_row.addWidget(up_btn)

        down_btn = QPushButton("↓ 下移")
        down_btn.setMinimumWidth(64)
        down_btn.setFixedHeight(26)
        down_btn.setStyleSheet(self._btn_style())
        down_btn.clicked.connect(self._move_down)
        compute_row.addWidget(down_btn)

        top_btn = QPushButton("⏫ 置顶")
        top_btn.setMinimumWidth(64)
        top_btn.setFixedHeight(26)
        top_btn.setStyleSheet(self._btn_style())
        top_btn.clicked.connect(self._move_top)
        compute_row.addWidget(top_btn)

        compute_row.addSpacing(8)

        add_formula_btn = QPushButton("+ 添加计算字段")
        add_formula_btn.setFixedHeight(26)
        add_formula_btn.setStyleSheet(self._btn_style())
        add_formula_btn.clicked.connect(self._add_computed_field)
        compute_row.addWidget(add_formula_btn)

        add_addr_btn = QPushButton("+ 添加地址提取列")
        add_addr_btn.setFixedHeight(26)
        add_addr_btn.setStyleSheet(self._btn_style())
        add_addr_btn.clicked.connect(self._add_address_extract_field)
        compute_row.addWidget(add_addr_btn)

        add_date_part_btn = QPushButton("+ 添加时间成分")
        add_date_part_btn.setFixedHeight(26)
        add_date_part_btn.setStyleSheet(self._btn_style())
        add_date_part_btn.clicked.connect(self._add_date_part_field)
        compute_row.addWidget(add_date_part_btn)

        compute_row.addStretch()

        self._summary_cb = QCheckBox("显示汇总行")
        self._summary_cb.setStyleSheet("font-size: 12px; color: #333333;")
        self._summary_cb.stateChanged.connect(self._on_summary_changed)
        compute_row.addWidget(self._summary_cb)

        layout.addLayout(compute_row)

    @staticmethod
    def _btn_style():
        return """
            QPushButton { border: 1px solid #D9D9D9; border-radius: 3px;
                          padding: 2px 10px; font-size: 12px; background: #FFFFFF; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """

    # ==================== 数据操作 ====================

    def set_columns(self, columns: list[dict]):
        """设置字段列表"""
        self._building = True
        self._columns = columns
        self._table.setRowCount(len(columns))

        for row, col in enumerate(columns):
            # 可见性 (列 0)
            check_widget = QWidget()
            check_layout = QHBoxLayout(check_widget)
            check_layout.setContentsMargins(0, 0, 0, 0)
            check_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb = QCheckBox()
            cb.blockSignals(True)
            cb.setChecked(col.get('visible', True))
            cb.blockSignals(False)
            cb.stateChanged.connect(lambda state, r=row: self._on_visible_changed(r, state))
            check_layout.addWidget(cb)
            self._table.setCellWidget(row, 0, check_widget)

            # 显示名 (列 1)
            display_item = QTableWidgetItem(col.get('display_name', ''))
            display_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 1, display_item)

            # 来源 (列 2)  — 聚合列为 "聚合(SUM, 金额)"，公式列为 "公式(=...)"
            comp_type = col.get('computation_type', 'direct')
            if comp_type == 'aggregate':
                agg = col.get('aggregate_func', 'SUM')
                sf = col.get('source_field', '')
                source_text = f"聚合({agg}, {sf})"
            elif comp_type == 'formula':
                expr = col.get('formula_expression', '')
                source_text = f"公式({expr[:30]}{'…' if len(expr) > 30 else ''})"
            elif comp_type == 'address_extract':
                level = col.get('address_target_level', 'city')
                level_labels = {'province': '省-全称', 'province_short': '省-简称', 'city': '市', 'area': '区'}
                level_label = level_labels.get(level, level)
                src_cols = col.get('address_source_fields', [])
                src_text = ', '.join([c for c in src_cols if c])
                source_text = f"地址提取({level_label}, [{src_text}])"
            elif comp_type == 'date_part':
                unit = col.get('date_part_unit', 'year')
                unit_labels = {'year': '年', 'month': '月', 'week': '周', 'quarter': '季度'}
                unit_label = unit_labels.get(unit, unit)
                src_field = col.get('date_part_source_field', '')
                source_text = f"时间成分({unit_label}, {src_field})"
            else:
                source_text = f"{col.get('source_object', '')}.{col.get('source_field', '')}"
            source_item = QTableWidgetItem(source_text)
            source_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if comp_type == 'formula':
                # 在 UserRole 中保存完整公式，避免从截断的显示文本恢复
                source_item.setData(Qt.ItemDataRole.UserRole, expr)
            elif comp_type == 'address_extract':
                # 在 UserRole 中保存完整配置（JSON），避免从显示文本恢复时丢失
                import json as _json
                addr_config = _json.dumps({
                    'address_source_fields': col.get('address_source_fields', []),
                    'address_target_level': col.get('address_target_level', 'city'),
                }, ensure_ascii=False)
                source_item.setData(Qt.ItemDataRole.UserRole, addr_config)
            elif comp_type == 'date_part':
                import json as _json
                dp_config = _json.dumps({
                    'date_part_source_field': col.get('date_part_source_field', ''),
                    'date_part_unit': col.get('date_part_unit', 'year'),
                }, ensure_ascii=False)
                source_item.setData(Qt.ItemDataRole.UserRole, dp_config)
            self._table.setItem(row, 2, source_item)

            # 聚合方式 (列 3) — QComboBox（禁用滚轮）
            agg_combo = NoWheelComboBox()
            agg_combo.addItems(["—", "SUM", "AVG", "COUNT", "MAX", "MIN"])
            agg_combo.setCurrentIndex(0)
            agg_func = col.get('aggregate_func', '')
            if comp_type == 'aggregate' and agg_func:
                idx = agg_combo.findText(agg_func.upper())
                if idx >= 0:
                    agg_combo.setCurrentIndex(idx)
            agg_combo.currentTextChanged.connect(
                lambda text, r=row: self._on_agg_changed(r, text)
            )
            self._table.setCellWidget(row, 3, agg_combo)

            # 字段格式 (列 4) — QComboBox（禁用滚轮）
            from ..constants import FIELD_FORMATS
            fmt_combo = NoWheelComboBox()
            for val, label in FIELD_FORMATS:
                fmt_combo.addItem(label, val)
            fmt_combo.setCurrentIndex(0)  # 默认 "文本"
            current_fmt = col.get('field_format', 'text')
            for idx in range(fmt_combo.count()):
                if fmt_combo.itemData(idx) == current_fmt:
                    fmt_combo.setCurrentIndex(idx)
                    break
            fmt_combo.currentTextChanged.connect(
                lambda text, r=row: self._on_format_changed(r)
            )
            self._table.setCellWidget(row, 4, fmt_combo)

        self._building = False

    def get_columns(self) -> list[dict]:
        """获取当前字段列表"""
        result = []
        for row in range(self._table.rowCount()):
            display_item = self._table.item(row, 1)
            source_item = self._table.item(row, 2)
            check_widget = self._table.cellWidget(row, 0)
            agg_combo = self._table.cellWidget(row, 3)

            display_name = display_item.text().strip() if display_item else ''
            source_text = source_item.text().strip() if source_item else ''

            # 解析来源：直接列为 "对象.字段"，聚合列为 "聚合(SUM,字段)"，公式列为 "公式(...)"
            source_object = ''
            source_field = ''
            computation_type = 'direct'
            aggregate_func = ''
            formula_expression = ''
            address_source_fields = []
            address_target_level = ''
            date_part_source_field = ''
            date_part_unit = ''

            if source_text.startswith('聚合('):
                computation_type = 'aggregate'
                inner = source_text[3:-1]  # 去掉 "聚合(" 和 ")"
                parts = inner.split(',', 1)
                aggregate_func = parts[0].strip() if parts else ''
                source_field = parts[1].strip() if len(parts) > 1 else ''
            elif source_text.startswith('地址提取('):
                computation_type = 'address_extract'
                # 从 UserRole 读取完整配置（显示文本仅做概要展示）
                addr_config_str = source_item.data(Qt.ItemDataRole.UserRole)
                if addr_config_str:
                    try:
                        import json as _json
                        addr_config = _json.loads(str(addr_config_str))
                        address_source_fields = addr_config.get('address_source_fields', [])
                        address_target_level = addr_config.get('address_target_level', 'city')
                    except Exception:
                        address_source_fields = []
                        address_target_level = 'city'
                else:
                    address_source_fields = []
                    address_target_level = 'city'
            elif source_text.startswith('时间成分('):
                computation_type = 'date_part'
                dp_config_str = source_item.data(Qt.ItemDataRole.UserRole)
                if dp_config_str:
                    try:
                        import json as _json
                        dp_config = _json.loads(str(dp_config_str))
                        date_part_source_field = dp_config.get('date_part_source_field', '')
                        date_part_unit = dp_config.get('date_part_unit', 'year')
                    except Exception:
                        date_part_source_field = ''
                        date_part_unit = 'year'
                else:
                    date_part_source_field = ''
                    date_part_unit = 'year'
            elif source_text.startswith('公式('):
                computation_type = 'formula'
                # 优先从 UserRole 读取完整公式（显示文本可能被截断）
                full_expr = source_item.data(Qt.ItemDataRole.UserRole)
                if full_expr:
                    formula_expression = str(full_expr)
                else:
                    inner = source_text[3:-1]
                    # 防止从截断的显示文本（含 …）读取损毁的公式
                    if '…' in inner:
                        formula_expression = self._find_original_formula(display_name, row)
                        if not formula_expression:
                            logger.warning(f"[FieldConfig] 公式列 '{display_name}' UserRole 丢失且显示文本已截断，公式可能损毁")
                            formula_expression = inner
                    else:
                        formula_expression = inner
            else:
                parts = source_text.rsplit('.', 1) if '.' in source_text else ('', source_text)
                source_object = parts[0] if len(parts) > 1 else ''
                source_field = parts[1] if len(parts) > 1 else source_text

            visible = True
            if check_widget:
                cb = check_widget.findChild(QCheckBox)
                if cb:
                    visible = cb.isChecked()

            # 如果 combo 选了聚合函数但来源没变，修正 computation_type
            if computation_type == 'direct' and isinstance(agg_combo, QComboBox):
                agg_text = agg_combo.currentText()
                if agg_text != '—':
                    computation_type = 'aggregate'
                    aggregate_func = agg_text
                else:
                    aggregate_func = ''

            # 字段格式 (列 4)
            field_format = 'text'
            fmt_combo = self._table.cellWidget(row, 4)
            if isinstance(fmt_combo, QComboBox):
                field_format = fmt_combo.currentData() or 'text'

            result.append({
                'display_name': display_name,
                'source_object': source_object,
                'source_field': source_field,
                'visible': visible,
                'computation_type': computation_type,
                'aggregate_func': aggregate_func,
                'formula_expression': formula_expression,
                'address_source_fields': address_source_fields if computation_type == 'address_extract' else [],
                'address_target_level': address_target_level if computation_type == 'address_extract' else '',
                'date_part_source_field': date_part_source_field if computation_type == 'date_part' else '',
                'date_part_unit': date_part_unit if computation_type == 'date_part' else '',
                'field_format': field_format,
            })
        return result

    def _sync_columns_from_table(self):
        """将表格当前行序同步到 _columns（拖拽排序后调用）。"""
        table_cols = []
        for row in range(self._table.rowCount()):
            display_item = self._table.item(row, 1)
            source_item = self._table.item(row, 2)
            check_widget = self._table.cellWidget(row, 0)
            agg_combo = self._table.cellWidget(row, 3)

            display_name = display_item.text().strip() if display_item else ''
            source_text = source_item.text().strip() if source_item else ''

            source_object = ''
            source_field = ''
            computation_type = 'direct'
            aggregate_func = ''
            formula_expression = ''
            address_source_fields = []
            address_target_level = ''
            date_part_source_field = ''
            date_part_unit = ''

            if source_text.startswith('聚合('):
                computation_type = 'aggregate'
                inner = source_text[3:-1]
                parts = inner.split(',', 1)
                aggregate_func = parts[0].strip() if parts else ''
                source_field = parts[1].strip() if len(parts) > 1 else ''
            elif source_text.startswith('地址提取('):
                computation_type = 'address_extract'
                addr_config_str = source_item.data(Qt.ItemDataRole.UserRole)
                if addr_config_str:
                    try:
                        import json as _json
                        addr_config = _json.loads(str(addr_config_str))
                        address_source_fields = addr_config.get('address_source_fields', [])
                        address_target_level = addr_config.get('address_target_level', 'city')
                    except Exception:
                        pass
            elif source_text.startswith('时间成分('):
                computation_type = 'date_part'
                dp_config_str = source_item.data(Qt.ItemDataRole.UserRole)
                if dp_config_str:
                    try:
                        import json as _json
                        dp_config = _json.loads(str(dp_config_str))
                        date_part_source_field = dp_config.get('date_part_source_field', '')
                        date_part_unit = dp_config.get('date_part_unit', 'year')
                    except Exception:
                        pass
            elif source_text.startswith('公式('):
                computation_type = 'formula'
                full_expr = source_item.data(Qt.ItemDataRole.UserRole)
                if full_expr:
                    formula_expression = str(full_expr)
                else:
                    inner = source_text[3:-1]
                    if '…' in inner:
                        formula_expression = self._find_original_formula(display_name, row)
                        if not formula_expression:
                            logger.warning(f"[FieldConfig] 公式列 '{display_name}' UserRole 丢失且显示文本已截断，公式可能损毁")
                            formula_expression = inner
                    else:
                        formula_expression = inner
            else:
                parts = source_text.rsplit('.', 1) if '.' in source_text else ('', source_text)
                source_object = parts[0] if len(parts) > 1 else ''
                source_field = parts[1] if len(parts) > 1 else source_text

            visible = True
            if check_widget:
                cb = check_widget.findChild(QCheckBox)
                if cb:
                    visible = cb.isChecked()

            if computation_type == 'direct' and isinstance(agg_combo, QComboBox):
                agg_text = agg_combo.currentText()
                if agg_text != '—':
                    computation_type = 'aggregate'
                    aggregate_func = agg_text

            # 字段格式 (列 4)
            field_format = 'text'
            fmt_combo = self._table.cellWidget(row, 4)
            if isinstance(fmt_combo, QComboBox):
                field_format = fmt_combo.currentData() or 'text'

            table_cols.append({
                'display_name': display_name,
                'source_object': source_object,
                'source_field': source_field,
                'visible': visible,
                'computation_type': computation_type,
                'aggregate_func': aggregate_func,
                'formula_expression': formula_expression,
                'address_source_fields': address_source_fields if computation_type == 'address_extract' else [],
                'address_target_level': address_target_level if computation_type == 'address_extract' else '',
                'date_part_source_field': date_part_source_field if computation_type == 'date_part' else '',
                'date_part_unit': date_part_unit if computation_type == 'date_part' else '',
                'field_format': field_format,
            })
        if table_cols:
            self._columns = table_cols

    def add_column(self, display_name: str, source_object: str, source_field: str):
        """添加一个字段列"""
        self._sync_columns_from_table()
        self._columns.append({
            'display_name': display_name,
            'source_object': source_object,
            'source_field': source_field,
            'visible': True,
            'computation_type': 'direct',
            'aggregate_func': '',
            'formula_expression': '',
            'field_format': 'text',
        })
        self.set_columns(self._columns)
        self.columnsChanged.emit()

    def remove_column_by_field(self, source_field: str, source_object: str = ""):
        """按字段名移除"""
        self._sync_columns_from_table()
        self._columns = [
            c for c in self._columns
            if not (c['source_field'] == source_field and
                    (not source_object or c['source_object'] == source_object))
        ]
        self.set_columns(self._columns)
        self.columnsChanged.emit()

    def reorder_by_display_names(self, names: list[str]):
        """按 display_name 列表重排 _columns 顺序（从预览列拖拽同步）。"""
        self._sync_columns_from_table()
        name_to_idx = {name: i for i, name in enumerate(names)}
        ordered = sorted(
            self._columns,
            key=lambda c: name_to_idx.get(c.get('display_name', ''), len(names))
        )
        if ordered == self._columns:
            return
        self._columns = ordered
        self.set_columns(self._columns)
        self.columnsChanged.emit()

    # ==================== 分组键 / 汇总行 ====================

    def get_group_by_fields(self) -> list:
        return list(self._group_by_fields)

    def set_group_by_fields(self, fields: list):
        self._group_by_fields = set(fields or [])

    def get_show_summary_row(self) -> bool:
        return self._show_summary_row

    def set_show_summary_row(self, show: bool):
        self._show_summary_row = show
        self._summary_cb.blockSignals(True)
        self._summary_cb.setChecked(show)
        self._summary_cb.blockSignals(False)

    # ==================== 内部回调 ====================

    def _on_cell_changed(self, row, col):
        if self._building:
            return
        if col == 1:  # 显示名
            item = self._table.item(row, 1)
            if item:
                new_name = item.text().strip()
                entry = self._find_column_by_table_row(row)
                if entry is not None:
                    self._columns[entry]['display_name'] = new_name
                    self.columnsChanged.emit()

    def _on_visible_changed(self, row, state):
        if self._building:
            return
        entry = self._find_column_by_table_row(row)
        if entry is not None:
            self._columns[entry]['visible'] = (state == Qt.CheckState.Checked.value)
            self.columnsChanged.emit()

    def _on_agg_changed(self, row, text):
        """聚合方式下拉变更 → 更新来源列显示并通知外部。"""
        if self._building:
            return
        entry = self._find_column_by_table_row(row)
        if entry is None:
            return
        source_item = self._table.item(row, 2)
        if source_item:
            src_text = source_item.text().strip()
            if text != '—':
                # 设置为聚合模式
                self._columns[entry]['computation_type'] = 'aggregate'
                self._columns[entry]['aggregate_func'] = text
                # 更新来源列显示为 "聚合(SUM, 字段)"
                sf = self._columns[entry].get('source_field', '')
                source_item.setText(f"聚合({text}, {sf})")
            else:
                # 改回直接引用
                self._columns[entry]['computation_type'] = 'direct'
                self._columns[entry]['aggregate_func'] = ''
                so = self._columns[entry].get('source_object', '')
                sf = self._columns[entry].get('source_field', '')
                source_item.setText(f"{so}.{sf}")
        self.columnsChanged.emit()

    def _on_format_changed(self, row):
        """字段格式下拉变更 → 更新 _columns 并通知外部。"""
        if self._building:
            return
        entry = self._find_column_by_table_row(row)
        if entry is None:
            return
        fmt_combo = self._table.cellWidget(row, 4)
        if isinstance(fmt_combo, QComboBox):
            self._columns[entry]['field_format'] = fmt_combo.currentData() or 'text'
        self.columnsChanged.emit()

    # ==================== 列宽持久化 ====================

    def set_config_callbacks(self, save_fn, load_fn):
        """设置配置文件读写回调（用于列宽持久化）。"""
        self._save_config_fn = save_fn
        self._load_config_fn = load_fn
        # 首次加载时恢复列宽
        QTimer.singleShot(100, self._load_field_col_widths)

    def _on_field_col_resized(self, col_idx: int, old_width: int, new_width: int):
        """用户拖拽列宽后防抖保存。"""
        if not hasattr(self, '_save_config_fn') or not self._save_config_fn:
            return
        if hasattr(self, '_field_col_resize_timer') and self._field_col_resize_timer is not None:
            self._field_col_resize_timer.start()

    def _save_field_col_widths(self):
        """保存当前列宽到个人配置文件。"""
        if not hasattr(self, '_save_config_fn') or not self._save_config_fn:
            return
        widths = {}
        header = self._table.horizontalHeader()
        for c in range(self._table.columnCount()):
            header_item = self._table.horizontalHeaderItem(c)
            if header_item:
                col_name = header_item.text().strip()
                if col_name:
                    widths[col_name] = header.sectionSize(c)
        if not widths:
            return
        try:
            cfg = None
            if self._load_config_fn:
                try:
                    cfg = self._load_config_fn()
                except Exception:
                    pass
            if not isinstance(cfg, dict):
                cfg = {}
            cr = cfg.setdefault('custom_reports', {})
            cr['field_panel_column_widths'] = widths
            self._save_config_fn(cfg)
        except Exception:
            pass

    def _load_field_col_widths(self):
        """从个人配置文件恢复列宽。"""
        if not hasattr(self, '_load_config_fn') or not self._load_config_fn:
            return
        try:
            cfg = self._load_config_fn()
            if not isinstance(cfg, dict):
                return
            cr = cfg.get('custom_reports', {})
            if not isinstance(cr, dict):
                return
            widths = cr.get('field_panel_column_widths', {})
            if not isinstance(widths, dict) or not widths:
                return
            header = self._table.horizontalHeader()
            for c in range(self._table.columnCount()):
                header_item = self._table.horizontalHeaderItem(c)
                if header_item:
                    col_name = header_item.text().strip()
                    if col_name in widths:
                        saved_w = widths[col_name]
                        if saved_w > 20:
                            header.resizeSection(c, saved_w)
        except Exception:
            pass

    def _on_summary_changed(self, state):
        self._show_summary_row = (state == Qt.CheckState.Checked.value)
        self.columnsChanged.emit()

    def _find_original_formula(self, display_name: str, row: int) -> str:
        """当 UserRole 丢失时，尝试从 self._columns 查找公式列的原始表达式。

        按行号匹配优先，其次按显示名匹配。
        返回找到的 formula_expression，未找到返回空字符串。
        """
        if 0 <= row < len(self._columns):
            col = self._columns[row]
            if col.get('display_name') == display_name:
                expr = col.get('formula_expression', '')
                if expr and '…' not in expr:
                    return expr
        # 按显示名搜索
        for col in self._columns:
            if col.get('display_name') == display_name:
                expr = col.get('formula_expression', '')
                if expr and '…' not in expr:
                    return expr
        return ''

    def _add_computed_field(self):
        """弹出添加计算字段对话框。"""
        dlg = _ComputedFieldDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            field_data = dlg.get_field_data()
            self._sync_columns_from_table()
            self._columns.append(field_data)
            self.set_columns(self._columns)
            self.columnsChanged.emit()

    def _add_address_extract_field(self):
        """弹出添加地址提取列对话框。"""
        # 先同步表状态，确保 _columns 是最新的
        self._sync_columns_from_table()
        # 收集当前所有直接列作为候选
        candidate_cols = [
            c.get('display_name', '')
            for c in self._columns
            if c.get('computation_type', 'direct') == 'direct' and c.get('display_name')
        ]
        dlg = _AddressExtractDialog(self, candidate_cols)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            field_data_list = dlg.get_field_data_list()
            self._sync_columns_from_table()
            for field_data in field_data_list:
                self._columns.append(field_data)
            self.set_columns(self._columns)
            self.columnsChanged.emit()

    def _add_date_part_field(self):
        """弹出添加时间成分列对话框。"""
        try:
            self._sync_columns_from_table()
            # 收集当前所有直接列为候选源字段
            candidate_cols = [
                c.get('display_name', '')
                for c in self._columns
                if c.get('computation_type', 'direct') == 'direct' and c.get('display_name')
            ]
            dlg = _DatePartExtractDialog(self, candidate_cols)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                field_data_list = dlg.get_field_data_list()
                self._sync_columns_from_table()
                for field_data in field_data_list:
                    self._columns.append(field_data)
                self.set_columns(self._columns)
                self.columnsChanged.emit()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "错误", f"添加时间成分失败:\n{str(e)}")

    def _find_column_by_table_row(self, table_row: int) -> int | None:
        """根据表格行号查找 _columns 中的索引（按 source 字段匹配）。"""
        source_item = self._table.item(table_row, 2)
        if not source_item:
            return table_row if table_row < len(self._columns) else None
        source_text = source_item.text().strip()
        parts = source_text.rsplit('.', 1) if '.' in source_text else ('', source_text)
        src_object = parts[0] if len(parts) > 1 else ''
        src_field = parts[1] if len(parts) > 1 else source_text
        for i, c in enumerate(self._columns):
            if c.get('source_field') == src_field and c.get('source_object', '') == src_object:
                return i
        return table_row if table_row < len(self._columns) else None

    def _select_all(self):
        for row in range(self._table.rowCount()):
            w = self._table.cellWidget(row, 0)
            if w:
                cb = w.findChild(QCheckBox)
                if cb:
                    cb.setChecked(True)
        self.columnsChanged.emit()

    def _deselect_all(self):
        for row in range(self._table.rowCount()):
            w = self._table.cellWidget(row, 0)
            if w:
                cb = w.findChild(QCheckBox)
                if cb:
                    cb.setChecked(False)
        self.columnsChanged.emit()

    def _on_drag_finished(self, from_row: int, to_row: int):
        """拖拽排序完成 → 交换 _columns 条目并完整重建表格。"""
        if from_row < 0 or to_row < 0 or from_row >= len(self._columns) or to_row >= len(self._columns):
            return
        self._sync_columns_from_table()
        moved = self._columns.pop(from_row)
        self._columns.insert(to_row, moved)
        self.set_columns(self._columns)
        self._table.setCurrentCell(to_row, 1)
        self.columnsChanged.emit()

    def _move_up(self):
        self._sync_columns_from_table()
        row = self._table.currentRow()
        if row > 0:
            self._columns.insert(row - 1, self._columns.pop(row))
            self.set_columns(self._columns)
            self._table.setCurrentCell(row - 1, 1)
            self.columnsChanged.emit()

    def _move_down(self):
        self._sync_columns_from_table()
        row = self._table.currentRow()
        if row < self._table.rowCount() - 1:
            self._columns.insert(row + 1, self._columns.pop(row))
            self.set_columns(self._columns)
            self._table.setCurrentCell(row + 1, 1)
            self.columnsChanged.emit()

    def _move_top(self):
        """将选中行移动到最顶部。"""
        self._sync_columns_from_table()
        row = self._table.currentRow()
        if row > 0:
            moved = self._columns.pop(row)
            self._columns.insert(0, moved)
            self.set_columns(self._columns)
            self._table.setCurrentCell(0, 1)
            self.columnsChanged.emit()

    def _remove_selected(self):
        self._sync_columns_from_table()
        rows = sorted(set(idx.row() for idx in self._table.selectedIndexes()), reverse=True)
        for row in rows:
            if 0 <= row < len(self._columns):
                col_id = self._columns[row].get('id', '')
                self._columns.pop(row)
                if col_id:
                    self.fieldRemoved.emit(col_id)
        self.set_columns(self._columns)
        self.columnsChanged.emit()


def _describe_func_params(func, min_args: int, max_args: int | None) -> str:
    """从函数签名提取可读的参数列表字符串。"""
    try:
        sig = inspect.signature(func)
        parts = []
        for name, param in sig.parameters.items():
            if name in ('self', 'cls'):
                continue
            if param.kind == param.VAR_POSITIONAL:
                parts.append('...')
            elif param.kind == param.VAR_KEYWORD:
                pass
            elif param.default is not param.empty:
                parts.append(f'[{name}]')
            else:
                parts.append(name)
        return ', '.join(parts)
    except Exception:
        if min_args == 0 and max_args == 0:
            return ''
        if max_args is None:
            return f'arg1, arg2, ...'
        return ', '.join(f'arg{i+1}' for i in range(max_args))


# 函数名 → 参数提示文本
_FUNC_PARAM_HINTS: dict[str, str] = {}
for _name, (_func, _min_a, _max_a) in _EXCEL_FUNC_REGISTRY.items():
    _FUNC_PARAM_HINTS[_name] = _describe_func_params(_func, _min_a, _max_a)


# 公式补全弹出列表的样式
_FUNC_POPUP_STYLE = """
    QListWidget {
        border: 1px solid #D9D9D9;
        border-radius: 4px;
        font-size: 13px;
        color: #333333;
        background: #FFFFFF;
        outline: none;
    }
    QListWidget::item {
        padding: 6px 10px;
    }
    QListWidget::item:selected {
        background: #E6F2FF;
        color: #1890FF;
    }
"""


class _FormulaEdit(QLineEdit):
    """支持函数名自动补全的公式输入框。

    输入时检测函数名上下文，弹出函数建议列表；
    选中后自动补全函数名并追加 '('。
    """

    suggestionSelected = pyqtSignal(str)  # 选中函数名时发出

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup: 'QListWidget | None' = None
        self._suggestion_items: list[str] = []
        self.textChanged.connect(self._on_text_changed)

    def _ensure_popup(self):
        if self._popup is None:
            from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QAbstractItemView
            self._popup = QListWidget()
            self._popup.setWindowFlags(
                Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
            )
            self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self._popup.setStyleSheet(_FUNC_POPUP_STYLE)
            self._popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._popup.itemClicked.connect(self._apply_suggestion)
            self._popup.installEventFilter(self)
            self.installEventFilter(self)

    def _on_text_changed(self, _text: str):
        """文本变化时检测是否处于函数名输入上下文。"""
        if not self._popup:
            return
        word, start_pos = self._current_word()
        if word and len(word) >= 2 and start_pos >= 0:
            matches = [n for n in _EXCEL_FUNC_REGISTRY if word.upper() in n.upper()]
            if matches:
                self._show_suggestions(matches, word)
                return
        self._popup.hide()

    def _current_word(self) -> tuple[str, int]:
        """获取光标前正在输入的单词及其起始位置。

        Returns:
            (word, start_pos): 单词文本及其在全文中的起始位置。
            没有单词时返回 ('', -1)。
        """
        text = self.text()
        pos = self.cursorPosition()
        before = text[:pos]
        import re as _re
        m = _re.search(r'[A-Za-z_]\w*$', before)
        if m:
            return m.group(), m.start()
        return '', -1

    def _show_suggestions(self, names: list[str], _current_word: str):
        """在光标下方弹出函数建议列表。"""
        popup = self._popup
        popup.clear()
        self._suggestion_items = sorted(names)
        from PyQt6.QtWidgets import QListWidgetItem
        for name in self._suggestion_items:
            params = _FUNC_PARAM_HINTS.get(name, '')
            text = f"{name}({params})" if params else name
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, name)
            popup.addItem(item)
        popup.setCurrentRow(0)

        # 定位到光标下方
        cursor_rect = self.cursorRect()
        pos = self.mapToGlobal(cursor_rect.bottomLeft())
        popup.move(pos)

        # 自适应尺寸
        popup.setMinimumWidth(max(260, self.width()))
        item_height = 28
        count = min(len(self._suggestion_items), 10)
        popup.setFixedHeight(count * item_height + 6)
        popup.show()

    def _apply_suggestion(self, item):
        """选中建议项：替换当前单词为函数名，追加 '('。"""
        name = item.data(Qt.ItemDataRole.UserRole) or item.text().split('(')[0]
        _, start = self._current_word()
        if start < 0:
            return
        text = self.text()
        pos = self.cursorPosition()
        # 替换当前单词为函数名
        new_text = text[:start] + name + '(' + text[pos:]
        self.setText(new_text)
        new_cursor = start + len(name) + 1
        self.setCursorPosition(new_cursor)
        self.setFocus()
        if self._popup:
            self._popup.hide()

    def eventFilter(self, obj, event):
        """拦截键盘事件：上下键导航弹出列表，Enter/Tab 确认，Esc 关闭。"""
        if obj is self and event.type() == QEvent.Type.KeyPress:
            if self._popup and self._popup.isVisible():
                key = event.key()
                if key == Qt.Key.Key_Down:
                    self._popup.setFocus()
                    self._popup.setCurrentRow(0)
                    return True
                elif key == Qt.Key.Key_Up:
                    self._popup.setFocus()
                    self._popup.setCurrentRow(self._popup.count() - 1)
                    return True
                elif key == Qt.Key.Key_Escape:
                    self._popup.hide()
                    return True
                elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                    current = self._popup.currentItem()
                    if current:
                        self._apply_suggestion(current)
                    else:
                        self._popup.hide()
                    return True
        elif obj is self._popup and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                current = self._popup.currentItem()
                if current:
                    self._apply_suggestion(current)
                return True
            elif key == Qt.Key.Key_Escape:
                self._popup.hide()
                self.setFocus()
                return True
            elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                # 让列表自己处理上下键
                return False
        return super().eventFilter(obj, event)


class _ComputedFieldDialog(QDialog):
    """添加计算字段对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加计算字段")
        self.setMinimumWidth(420)
        self.setStyleSheet("""
            QDialog { background-color: #FFFFFF; color: #333333; }
            QLabel { color: #333333; font-size: 13px; }
            QLineEdit {
                border: 1px solid #D9D9D9; border-radius: 3px;
                padding: 6px 8px; font-size: 13px; color: #333333; background: #FFFFFF;
            }
            QLineEdit:focus { border-color: #FF8C00; }
            QComboBox {
                border: 1px solid #D9D9D9; border-radius: 3px;
                padding: 4px 8px; font-size: 13px; color: #333333; background: #FFFFFF;
            }
            QPushButton {
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 6px 20px; font-size: 13px; background: #FFFFFF; color: #333333;
            }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
            QRadioButton { color: #333333; font-size: 13px; }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("如: 合计金额、计算结果")
        form.addRow("字段显示名:", self._name_edit)

        self._formula_edit = _FormulaEdit()
        self._formula_edit.setPlaceholderText("如: =YEAR(日期列), =IF(金额>1000, '大额', '小额'), =单价*数量")
        self._formula_edit.textChanged.connect(self._on_formula_text_changed)
        form.addRow("公式表达式:", self._formula_edit)

        # 参数提示标签（输入函数名时显示签名）
        self._param_hint_label = QLabel("")
        self._param_hint_label.setStyleSheet("font-size: 11px; color: #1890FF; padding-left: 4px; min-height: 16px;")
        form.addRow("", self._param_hint_label)

        hint = QLabel("日期: YEAR/MONTH/QUARTER/DAY/HOUR/MINUTE/SECOND/WEEKDAY/WEEKNUM/DATEDIF/DATE/TODAY/NOW/EDATE/EOMONTH/TIME/YEARFRAC/ISOWEEKNUM\n"
                      "逻辑: IF/IFS/AND/OR/NOT/IFERROR/TRUE/FALSE/XOR/SWITCH\n"
                      "数学: ROUND/ROUNDUP/ROUNDDOWN/INT/ABS/MOD/SQRT/POWER/SUM/AVERAGE/COUNT/MAX/MIN/CEILING/FLOOR/LN/LOG/EXP/EVEN/ODD/TRUNC/PI/RADIANS/DEGREES/SIGN/FACT/PRODUCT/QUOTIENT\n"
                      "文本: LEFT/RIGHT/MID/LEN/UPPER/LOWER/TRIM/CONCAT/CONCATENATE/TEXTJOIN/REPLACE/SUBSTITUTE/FIND/TEXT/PROPER/SEARCH/EXACT/REPT/VALUE/FIXED/CHAR/CODE/CLEAN\n"
                      "统计: COUNTIF/SUMIF/AVERAGEIF/MEDIAN/STDEV/STDEVP/VAR/VARP/LARGE/SMALL/RANK/MODE\n"
                      "判断: ISNUMBER/ISTEXT/ISBLANK/ISNA\n"
                      "公式以 = 开头，列名用 [列显示名] 引用，支持 +-*/ 运算")
        hint.setStyleSheet("font-size: 11px; color: #999999;")
        form.addRow("", hint)

        layout.addLayout(form)

        # 快捷公式按钮行
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)
        quick_label = QLabel("快捷公式:")
        quick_label.setStyleSheet("font-size: 12px; color: #666;")
        quick_row.addWidget(quick_label)

        self._quick_btns_data = [
            ("年", "YEAR("),
            ("月", "MONTH("),
            ("季度", "QUARTER("),
            ("周", "WEEKNUM("),
        ]
        for label, template in self._quick_btns_data:
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setStyleSheet("""
                QPushButton { border: 1px solid #B0D9FF; border-radius: 3px;
                              padding: 2px 8px; font-size: 11px; background: #F0F7FF; color: #1890FF; }
                QPushButton:hover { background: #E6F2FF; border-color: #1890FF; }
            """)
            btn.clicked.connect(lambda checked, t=template: self._insert_formula_template(t))
            quick_row.addWidget(btn)

        quick_row.addStretch()
        layout.addLayout(quick_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_formula_text_changed(self, text: str):
        """更新参数提示：当前正在输入函数名时显示签名，否则清空。"""
        if not hasattr(self, '_param_hint_label'):
            return
        edit = self._formula_edit
        word, _ = edit._current_word()
        if word and len(word) >= 2:
            upper = word.upper()
            # 精确匹配函数名：显示签名
            if upper in _FUNC_PARAM_HINTS:
                params = _FUNC_PARAM_HINTS[upper]
                if params:
                    self._param_hint_label.setText(f"{upper}({params})")
                else:
                    self._param_hint_label.setText(f"{upper}")
            else:
                # 部分匹配：显示候选数量
                matches = [n for n in _EXCEL_FUNC_REGISTRY if upper in n.upper()]
                if matches and len(matches) <= 3:
                    names = "/".join(matches[:3])
                    self._param_hint_label.setText(f"→ {names}")
                elif matches:
                    self._param_hint_label.setText(f"→ {len(matches)} 个匹配函数")
                else:
                    self._param_hint_label.setText("")
        else:
            self._param_hint_label.setText("")

    def _insert_formula_template(self, template: str):
        """将公式模板插入到公式编辑框中。"""
        current = self._formula_edit.text()
        if not current.startswith("="):
            current = "=" + current
        # 在当前位置插入模板，或追加到末尾
        self._formula_edit.setText(current + template)
        self._formula_edit.setFocus()

    def _on_accept(self):
        name = self._name_edit.text().strip()
        expr = self._formula_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入字段显示名")
            return
        if not expr:
            QMessageBox.warning(self, "提示", "请输入公式表达式")
            return
        self.accept()

    def get_field_data(self) -> dict:
        expr = self._formula_edit.text().strip()
        return {
            'display_name': self._name_edit.text().strip(),
            'source_object': '',
            'source_field': '',
            'visible': True,
            'computation_type': 'formula',
            'aggregate_func': '',
            'formula_expression': expr,
            'field_format': 'text',
        }


class _AddressExtractDialog(QDialog):
    """添加地址提取列对话框（多选层级，对齐时间成分交互）"""

    _LEVEL_LABELS = [
        ('province', '省（全称）'),
        ('province_short', '省（简称）'),
        ('city', '市'),
        ('area', '区/县'),
    ]

    def __init__(self, parent=None, candidate_cols: list[str] = None):
        super().__init__(parent)
        self.setWindowTitle("添加地址提取列")
        self.setMinimumWidth(440)
        self._candidate_cols = candidate_cols or []
        self._checkboxes: dict[str, QCheckBox] = {}
        self._preview_labels: dict[str, QLabel] = {}
        self.setStyleSheet("""
            QDialog { background-color: #FFFFFF; color: #333333; }
            QLabel { color: #333333; font-size: 13px; }
            QLineEdit {
                border: 1px solid #D9D9D9; border-radius: 3px;
                padding: 6px 8px; font-size: 13px; color: #333333; background: #FFFFFF;
            }
            QLineEdit:focus { border-color: #FF8C00; }
            QComboBox {
                border: 1px solid #D9D9D9; border-radius: 3px;
                padding: 4px 8px; font-size: 13px; color: #333333; background: #FFFFFF;
            }
            QPushButton {
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 6px 20px; font-size: 13px; background: #FFFFFF; color: #333333;
            }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
            QCheckBox { color: #333333; font-size: 13px; }
            QCheckBox::indicator { width: 16px; height: 16px; }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 显示名称前缀
        form = QFormLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText('输入前缀，如"客户" → "客户省"、"客户市"')
        self._name_edit.textChanged.connect(self._update_previews)
        form.addRow("显示名称前缀:", self._name_edit)
        layout.addLayout(form)

        # 选择提取层级（多选）
        level_label = QLabel("选择提取层级:")
        level_label.setStyleSheet("font-size: 13px; color: #333333; font-weight: 500; margin-top: 4px;")
        layout.addWidget(level_label)

        levels_frame = QFrame()
        levels_frame.setStyleSheet("QFrame { border: 1px solid #E0E0E0; border-radius: 4px; background: #FAFAFA; padding: 6px; }")
        levels_layout = QVBoxLayout(levels_frame)
        levels_layout.setSpacing(4)

        for level_key, level_name in self._LEVEL_LABELS:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)

            cb = QCheckBox(level_name)
            cb.setChecked(True)
            cb.toggled.connect(lambda checked, lk=level_key: self._on_level_toggled(lk, checked))
            row_layout.addWidget(cb)
            self._checkboxes[level_key] = cb

            row_layout.addStretch()

            preview_label = QLabel(f"预览: {level_name}")
            preview_label.setStyleSheet("font-size: 12px; color: #999;")
            row_layout.addWidget(preview_label)
            self._preview_labels[level_key] = preview_label

            levels_layout.addLayout(row_layout)

        layout.addWidget(levels_frame)

        # 候选列选择（最多 5 个）
        cand_label = QLabel("候选列（按顺序尝试匹配，取第一个匹配成功的结果）:")
        cand_label.setStyleSheet("font-size: 13px; color: #333333; font-weight: 500; margin-top: 8px;")
        layout.addWidget(cand_label)

        self._combo_widgets = []
        for i in range(5):
            row_layout = QHBoxLayout()
            lbl = QLabel(f"  {i + 1}.")
            lbl.setFixedWidth(24)
            lbl.setStyleSheet("color: #999; font-size: 12px;")
            row_layout.addWidget(lbl)

            combo = QComboBox()
            combo.addItem("(无)", "")
            for cn in self._candidate_cols:
                combo.addItem(cn, cn)
            combo.setCurrentIndex(0)
            row_layout.addWidget(combo, 1)
            layout.addLayout(row_layout)
            self._combo_widgets.append(combo)

        hint = QLabel("💡 提示：从候选列的值中按顺序匹配省/市/区名称，取第一个匹配成功的结果。未匹配到则留空。")
        hint.setStyleSheet("font-size: 11px; color: #999; margin-top: 8px;")
        layout.addWidget(hint)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        ok_btn = QPushButton("确定")
        ok_btn.setStyleSheet("""
            QPushButton {
                border: none; border-radius: 4px;
                background: #FF8C00; color: #FFF; font-size: 13px; font-weight: 500;
            }
            QPushButton:hover { background: #E67A00; }
        """)
        ok_btn.clicked.connect(self._on_confirm)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        self._update_previews()

    def _update_previews(self):
        prefix = self._name_edit.text().strip()
        for level_key, level_name in self._LEVEL_LABELS:
            if level_key in self._preview_labels:
                display = f"{prefix}{level_name}" if prefix else level_name
                cb = self._checkboxes.get(level_key)
                if cb and cb.isChecked():
                    self._preview_labels[level_key].setText(f"预览: {display}")
                    self._preview_labels[level_key].setStyleSheet("font-size: 12px; color: #FF8C00; font-weight: 500;")
                else:
                    self._preview_labels[level_key].setText(f"预览: {display}")
                    self._preview_labels[level_key].setStyleSheet("font-size: 12px; color: #999;")

    def _on_level_toggled(self, level_key, checked):
        self._update_previews()

    def _on_confirm(self):
        # 检查是否至少选了一个候选列
        selected = [data for combo in self._combo_widgets if (data := combo.currentData())]
        if not selected:
            QMessageBox.warning(self, "提示", "请至少选择一个候选列")
            return

        has_checked = any(cb.isChecked() for cb in self._checkboxes.values())
        if not has_checked:
            QMessageBox.warning(self, "提示", "请至少勾选一个提取层级")
            return

        self.accept()

    def get_field_data_list(self) -> list[dict]:
        """返回勾选的地址提取列配置列表。"""
        prefix = self._name_edit.text().strip()
        # 获取候选列（去重、去空）
        source_cols = []
        seen = set()
        for combo in self._combo_widgets:
            data = combo.currentData()
            if data and data not in seen:
                source_cols.append(data)
                seen.add(data)

        result = []
        for level_key, level_name in self._LEVEL_LABELS:
            cb = self._checkboxes.get(level_key)
            if cb and cb.isChecked():
                display = f"{prefix}{level_name}" if prefix else level_name
                result.append({
                    'display_name': display,
                    'source_object': '',
                    'source_field': '',
                    'visible': True,
                    'computation_type': 'address_extract',
                    'aggregate_func': '',
                    'formula_expression': '',
                    'address_source_fields': list(source_cols),
                    'address_target_level': level_key,
                    'field_format': 'text',
                })
        return result


class _DatePartExtractDialog(QDialog):
    """添加时间成分列对话框（年/月/周/季度提取）"""

    TIME_UNITS = [
        ('year', '年'),
        ('month', '月'),
        ('week', '周'),
        ('quarter', '季度'),
    ]

    def __init__(self, parent=None, candidate_cols: list[str] = None):
        super().__init__(parent)
        self.setWindowTitle("添加时间成分")
        self.setMinimumWidth(440)
        self._candidate_cols = candidate_cols or []
        self._checkboxes = {}
        self._preview_labels = {}
        self.setStyleSheet("""
            QDialog { background-color: #FFFFFF; color: #333333; }
            QLabel { color: #333333; font-size: 13px; }
            QLineEdit {
                border: 1px solid #D9D9D9; border-radius: 3px;
                padding: 6px 8px; font-size: 13px; color: #333333; background: #FFFFFF;
            }
            QLineEdit:focus { border-color: #FF8C00; }
            QComboBox {
                border: 1px solid #D9D9D9; border-radius: 3px;
                padding: 4px 8px; font-size: 13px; color: #333333; background: #FFFFFF;
            }
            QPushButton {
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 6px 20px; font-size: 13px; background: #FFFFFF; color: #333333;
            }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
            QCheckBox { color: #333333; font-size: 13px; }
            QCheckBox::indicator { width: 16px; height: 16px; }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 提取源字段
        form = QFormLayout()
        self._source_combo = QComboBox()
        self._source_combo.addItem("(请选择)", "")
        for cn in self._candidate_cols:
            self._source_combo.addItem(cn, cn)
        form.addRow("提取源字段:", self._source_combo)

        # 显示名称前缀
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText('输入前缀，如"创建" → "创建年"')
        self._name_edit.textChanged.connect(self._update_previews)
        form.addRow("显示名称:", self._name_edit)

        layout.addLayout(form)

        # 选择时间单位
        unit_label = QLabel("选择时间单位:")
        unit_label.setStyleSheet("font-size: 13px; color: #333333; font-weight: 500; margin-top: 4px;")
        layout.addWidget(unit_label)

        units_frame = QFrame()
        units_frame.setStyleSheet("QFrame { border: 1px solid #E0E0E0; border-radius: 4px; background: #FAFAFA; padding: 6px; }")
        units_layout = QVBoxLayout(units_frame)
        units_layout.setSpacing(4)

        for unit_key, unit_name in self.TIME_UNITS:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)

            cb = QCheckBox(unit_name)
            cb.setChecked(True)
            cb.toggled.connect(lambda checked, uk=unit_key: self._on_unit_toggled(uk, checked))
            row_layout.addWidget(cb)
            self._checkboxes[unit_key] = cb

            row_layout.addStretch()

            preview_label = QLabel(f"预览: {unit_name}")
            preview_label.setStyleSheet("font-size: 12px; color: #999;")
            row_layout.addWidget(preview_label)
            self._preview_labels[unit_key] = preview_label

            units_layout.addLayout(row_layout)

        layout.addWidget(units_frame)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        ok_btn = QPushButton("确定")
        ok_btn.setStyleSheet("""
            QPushButton {
                border: none; border-radius: 4px;
                background: #FF8C00; color: #FFF; font-size: 13px; font-weight: 500;
            }
            QPushButton:hover { background: #E67A00; }
        """)
        ok_btn.clicked.connect(self._on_confirm)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        self._update_previews()

    def _update_previews(self):
        prefix = self._name_edit.text().strip()
        for unit_key, unit_name in self.TIME_UNITS:
            if unit_key in self._preview_labels:
                display = f"{prefix}{unit_name}" if prefix else unit_name
                cb = self._checkboxes.get(unit_key)
                if cb and cb.isChecked():
                    self._preview_labels[unit_key].setText(f"预览: {display}")
                    self._preview_labels[unit_key].setStyleSheet("font-size: 12px; color: #FF8C00; font-weight: 500;")
                else:
                    self._preview_labels[unit_key].setText(f"预览: {display}")
                    self._preview_labels[unit_key].setStyleSheet("font-size: 12px; color: #999;")

    def _on_unit_toggled(self, unit_key, checked):
        self._update_previews()

    def _on_confirm(self):
        source_field = self._source_combo.currentData() or ''
        if not source_field:
            QMessageBox.warning(self, "提示", "请选择提取源字段。")
            return

        has_checked = any(cb.isChecked() for cb in self._checkboxes.values())
        if not has_checked:
            QMessageBox.warning(self, "提示", "请至少勾选一个时间单位。")
            return

        self.accept()

    def get_field_data_list(self) -> list[dict]:
        """返回勾选的时间成分列配置列表。"""
        prefix = self._name_edit.text().strip()
        source_field = self._source_combo.currentData() or ''
        result = []
        for unit_key, unit_name in self.TIME_UNITS:
            cb = self._checkboxes.get(unit_key)
            if cb and cb.isChecked():
                display = f"{prefix}{unit_name}" if prefix else unit_name
                result.append({
                    'display_name': display,
                    'source_object': '',
                    'source_field': '',
                    'visible': True,
                    'computation_type': 'date_part',
                    'aggregate_func': '',
                    'formula_expression': '',
                    'date_part_source_field': source_field,
                    'date_part_unit': unit_key,
                    'field_format': 'text',
                })
        return result
