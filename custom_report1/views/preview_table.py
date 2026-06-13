"""
数据预览面板

从 MySQL 结果表查询并分页展示拼表结果。
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QComboBox, QLineEdit, QHeaderView,
    QAbstractItemView, QSpinBox, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor

from ..db_manager import ReportDatabase

# 浅色 QMessageBox 样式（覆盖系统深色主题）
_MSGBOX_STYLE = """
    QMessageBox { background-color: #FAFAFA; color: #333333; }
    QLabel { color: #333333; font-size: 13px; }
    QPushButton {
        background-color: #FFFFFF; color: #333333;
        border: 1px solid #D9D9D9; border-radius: 4px;
        padding: 6px 20px; font-size: 13px; min-width: 80px;
    }
    QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
"""

def _light_msgbox(parent, icon, title, text):
    """显示浅色背景的消息弹窗。"""
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(icon)
    msg.setStyleSheet(_MSGBOX_STYLE)
    return msg.exec()

def _light_question(parent, title, text):
    """显示浅色背景的是/否确认弹窗。"""
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg.setStyleSheet(_MSGBOX_STYLE)
    return msg.exec()


class PreviewTable(QWidget):
    """数据预览面板"""

    pageInfoChanged = pyqtSignal()  # 分页信息变更
    columnOrderChanged = pyqtSignal(list)  # 用户拖拽列顺序变更，参数为列名列表
    filterToggleRequested = pyqtSignal()  # 筛选按钮点击

    def __init__(self, db: ReportDatabase = None, parent=None,
                 show_search=True, show_pagination=True):
        super().__init__(parent)
        self._db = db
        self._report_id = ""
        self._current_page = 1
        self._page_size = 50
        self._total_rows = 0
        self._search_text = ""
        self._search_columns: list[str] = None  # None=搜全部列
        self._visible_fields: set = None
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._do_search)
        self._save_config_fn = None
        self._load_config_fn = None
        self._col_widths_loaded = False
        self._filter_conditions: list[dict] = []
        self._show_search = show_search
        self._show_pagination = show_pagination
        self._report_def = None  # ReportDefinition，用于公式列和汇总行

        self._setup_ui()

    def set_database(self, db: ReportDatabase):
        self._db = db

    def set_config_callbacks(self, save_fn, load_fn):
        """设置个人配置文件读写回调，用于持久化列宽。"""
        self._save_config_fn = save_fn
        self._load_config_fn = load_fn

    def set_report(self, report_id: str):
        self._report_id = report_id
        self._current_page = 1
        self._col_widths_loaded = False
        self.refresh()

    def set_report_definition(self, report_def):
        """设置报表定义，用于启用公式列计算和汇总行显示。"""
        self._report_def = report_def

    def update_filter_badge(self, count: int):
        """更新筛选按钮的 badge 计数"""
        if hasattr(self, '_filter_toggle_btn') and self._filter_toggle_btn:
            self._filter_toggle_btn.setText(f"筛选({count})" if count > 0 else "筛选")

    def get_filter_toggle_button(self):
        """返回筛选切换按钮引用（供 FilterBar 设置外部按钮）。"""
        return getattr(self, '_filter_toggle_btn', None)

    def set_visible_fields(self, fields: set):
        """设置可见字段集合（None=显示全部，set=仅显示指定字段名）。
        调用后自动刷新表格列显示。"""
        self._visible_fields = fields
        self.refresh()

    def set_filter_conditions(self, conditions: list[dict]):
        """设置筛选条件并刷新显示"""
        self._filter_conditions = list(conditions or [])
        self._current_page = 1
        self.refresh()

    def get_result_columns(self) -> list[str]:
        """获取当前结果表的列名列表"""
        if not self._db or not self._report_id:
            return []
        try:
            table = ReportDatabase.result_table_name(self._report_id)
            cols = self._db.execute(f"SHOW COLUMNS FROM `{table}`")
            if cols:
                return [r['Field'] for r in cols if r['Field'] not in ('_row_id', '_id', '_hash')]
        except Exception:
            pass
        return []

    def get_column_order(self) -> list[str]:
        """获取当前表格显示的列名顺序（用户拖拽调整后的顺序）"""
        order = []
        header = self._table.horizontalHeader()
        for visual in range(self._table.columnCount()):
            logical = header.logicalIndex(visual)
            item = self._table.horizontalHeaderItem(logical)
            if item:
                name = item.text().strip()
                if name:
                    order.append(name)
        return order

    def show_status(self, message: str):
        """显示状态消息（清空表格并显示提示文字）。"""
        self._clear()
        self._record_label.setText(message)

    # ---- 外部翻页 API ----

    def set_page(self, page: int):
        self._current_page = max(1, page)
        self.refresh()

    def set_page_size(self, size: int):
        self._page_size = size
        self._current_page = 1
        self.refresh()

    def get_page_info(self) -> dict:
        page_count = max(1, (self._total_rows + self._page_size - 1) // self._page_size)
        return {
            'current': self._current_page,
            'page_size': self._page_size,
            'total': self._total_rows,
            'page_count': page_count,
        }

    # ---- 外部搜索 API ----

    def set_search_text(self, text: str):
        self._search_text = text
        self._current_page = 1
        self.refresh()

    def set_search_columns(self, columns: list[str]):
        self._search_columns = columns

    def search(self):
        self._current_page = 1
        self.refresh()

    # ==================== UI ====================

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 筛选 + 搜索 + 工具行
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self._filter_toggle_btn = QPushButton("筛选")
        self._filter_toggle_btn.setMinimumWidth(56)
        self._filter_toggle_btn.setFixedHeight(26)
        self._filter_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_toggle_btn.setStyleSheet("""
            QPushButton { background: #FFFFFF; border: 1px solid #D9D9D9; border-radius: 3px;
                          font-size: 12px; padding: 2px 10px; color: #333; }
            QPushButton:hover { border-color: #1890FF; color: #1890FF; }
        """)
        self._filter_toggle_btn.clicked.connect(self.filterToggleRequested.emit)
        top_row.addWidget(self._filter_toggle_btn)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索...")
        self._search_input.setFixedWidth(200)
        self._search_input.setFixedHeight(28)
        self._search_input.setStyleSheet("""
            QLineEdit { border: 1px solid #D9D9D9; border-radius: 4px;
                        padding: 4px 10px; font-size: 12px; }
        """)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        top_row.addWidget(self._search_input)

        top_row.addStretch()

        top_row.addWidget(QLabel("每页:"))
        self._page_size_combo = QComboBox()
        self._page_size_combo.setEditable(True)
        self._page_size_combo.addItems(["20", "50", "80", "100", "200"])
        self._page_size_combo.setCurrentText("50")
        self._page_size_combo.setFixedWidth(70)
        self._page_size_combo.currentTextChanged.connect(self._on_page_size_changed)
        top_row.addWidget(self._page_size_combo)

        export_btn = QPushButton("导出")
        export_btn.setFixedSize(50, 26)
        export_btn.setStyleSheet("""
            QPushButton { border: 1px solid #D9D9D9; border-radius: 3px;
                          font-size: 11px; background: #FFFFFF; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        export_btn.clicked.connect(self._export)
        top_row.addWidget(export_btn)

        # 搜索工具栏 — 包装为 QWidget 以支持隐藏
        search_widget = QWidget()
        search_widget.setLayout(top_row)
        search_widget.setVisible(self._show_search)
        layout.addWidget(search_widget)

        # 表格
        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet("""
            QTableWidget {
                gridline-color: #F0F0F0; background-color: #FFFFFF;
                border: 1px solid #E0E0E0; border-radius: 4px; font-size: 13px;
            }
            QTableWidget::item:selected { background-color: #FFF7E6; color: #333; }
            QHeaderView::section {
                background-color: #FAFAFA; border-bottom: 2px solid #E0E0E0;
                font-weight: 500; padding: 8px; font-size: 12px;
            }
        """)
        # 支持用户拖拽调整列宽和列顺序
        header = self._table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setStretchLastSection(False)
        header.sectionResized.connect(self._on_column_resized)
        header.sectionMoved.connect(self._on_column_moved)
        layout.addWidget(self._table, 1)

        # 分页行
        page_row = QHBoxLayout()
        page_row.setSpacing(8)

        self._record_label = QLabel("共 0 条记录")
        self._record_label.setStyleSheet("font-size: 12px; color: #666;")
        page_row.addWidget(self._record_label)

        page_row.addStretch()

        self._prev_btn = QPushButton("← 上一页")
        self._prev_btn.setFixedSize(70, 26)
        self._prev_btn.setStyleSheet("""
            QPushButton { border: 1px solid #D9D9D9; border-radius: 3px;
                          font-size: 11px; background: #FFFFFF; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        self._prev_btn.clicked.connect(self._prev_page)
        page_row.addWidget(self._prev_btn)

        self._page_label = QLabel("第 1 页 / 共 1 页")
        self._page_label.setStyleSheet("font-size: 12px; color: #333; font-weight: 500;")
        page_row.addWidget(self._page_label)

        self._next_btn = QPushButton("下一页 →")
        self._next_btn.setFixedSize(70, 26)
        self._next_btn.setStyleSheet("""
            QPushButton { border: 1px solid #D9D9D9; border-radius: 3px;
                          font-size: 11px; background: #FFFFFF; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        self._next_btn.clicked.connect(self._next_page)
        page_row.addWidget(self._next_btn)

        # 分页栏 — 包装为 QWidget 以支持隐藏
        page_widget = QWidget()
        page_widget.setLayout(page_row)
        page_widget.setVisible(self._show_pagination)
        layout.addWidget(page_widget)

    # ==================== 数据 ====================

    def refresh(self):
        """重新加载数据"""
        if not self._db or not self._report_id:
            self._clear()
            return
        try:
            rows, total = self._db.query_result(
                self._report_id,
                page=self._current_page,
                page_size=self._page_size,
                search=self._search_text or None,
                search_columns=self._search_columns or None,
                filters=self._filter_conditions or None,
            )
            self._total_rows = total
            self._populate_table(rows)
            self._update_pager()
        except Exception as e:
            self._clear()
            self._record_label.setText(f"查询失败: {str(e)[:80]}")

    def _populate_table(self, rows: list[dict]):
        if not rows:
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            return

        # 转为 DataFrame 用于公式计算
        import pandas as pd
        df = pd.DataFrame(rows)

        # 应用公式列
        if self._report_def:
            try:
                from ..formula_engine import eval_formula_columns
                df = eval_formula_columns(df, self._report_def.columns)
            except Exception:
                pass

        # 获取列名（跳过 _row_id，排除公式列产生的内部列名），按可见字段过滤
        skip_cols = {'_row_id'}
        all_cols = [k for k in df.columns if k not in skip_cols]

        if self._visible_fields is not None:
            cols = [c for c in all_cols if c in self._visible_fields]
            if not cols:
                cols = all_cols
        else:
            cols = all_cols

        # 保存 cols 供 _add_summary_row 使用
        self._display_cols = cols

        self._table.setColumnCount(len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        for c in range(len(cols)):
            header_item = self._table.horizontalHeaderItem(c)
            if header_item:
                header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        # 转为 dict 列表以便填充
        row_dicts = df.to_dict('records')
        self._table.setRowCount(len(row_dicts))

        for r, row in enumerate(row_dicts):
            for c, col_name in enumerate(cols):
                val = row.get(col_name, '')
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    val = ''
                item = QTableWidgetItem(str(val) if val != '' else '')
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(r, c, item)

        # 追加汇总行
        if self._report_def and getattr(self._report_def, 'show_summary_row', False):
            self._add_summary_row(df, cols)

        # 自适应列宽（首次加载）或恢复已保存的列宽和列顺序
        self._table.resizeColumnsToContents()
        if not self._col_widths_loaded:
            self._load_column_widths()
            self._load_column_order()
            # 用 report_def.columns 的 sort_order 覆盖，确保详情页列顺序与编辑界面一致
            self._apply_definition_column_order()
            self._col_widths_loaded = True

    def _add_summary_row(self, df, cols: list[str]):
        """在表格底部追加汇总行（粗体、浅灰背景）。"""
        from ..formula_engine import compute_summary_row
        try:
            summary = compute_summary_row(df, self._report_def.columns)
        except Exception:
            return

        row_idx = self._table.rowCount()
        self._table.insertRow(row_idx)

        for c, col_name in enumerate(cols):
            val = summary.get(col_name, '')
            if val is None:
                val = ''
            # 第一列显示"合计"，其他显示数值
            display = str(val) if val != '' else ('合计' if c == 0 else '')
            item = QTableWidgetItem(display)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setBackground(QColor("#F5F5F5"))
            self._table.setItem(row_idx, c, item)

    def _clear(self):
        self._table.setRowCount(0)
        self._table.setColumnCount(0)
        self._total_rows = 0

    def _update_pager(self):
        self._record_label.setText(f"共 {self._total_rows} 条记录")
        page_count = max(1, (self._total_rows + self._page_size - 1) // self._page_size)
        self._page_label.setText(f"第 {self._current_page} 页 / 共 {page_count} 页")
        self._prev_btn.setEnabled(self._current_page > 1)
        self._next_btn.setEnabled(self._current_page < page_count)
        self.pageInfoChanged.emit()

    # ==================== 列宽持久化 ====================

    def _on_column_resized(self, col_idx: int, old_width: int, new_width: int):
        """用户拖拽列宽后保存到个人配置文件"""
        if not self._save_config_fn or not self._report_id:
            return
        QTimer.singleShot(300, self._save_column_widths)

    def _save_column_widths(self):
        """将当前列宽写入个人配置文件"""
        if not self._save_config_fn or not self._report_id:
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
            all_widths = cr.get('column_widths', {})
            if not isinstance(all_widths, dict):
                all_widths = {}
            all_widths[self._report_id] = widths
            cr['column_widths'] = all_widths
            self._save_config_fn(cfg)
        except Exception:
            pass

    def _load_column_widths(self):
        """从个人配置文件恢复已保存的列宽"""
        if not self._load_config_fn or not self._report_id:
            return
        try:
            cfg = self._load_config_fn()
            if not isinstance(cfg, dict):
                return
            cr = cfg.get('custom_reports', {})
            if not isinstance(cr, dict):
                return
            all_widths = cr.get('column_widths', {})
            if not isinstance(all_widths, dict):
                return
            widths = all_widths.get(self._report_id, {})
            if not widths:
                return
            header = self._table.horizontalHeader()
            for c in range(self._table.columnCount()):
                header_item = self._table.horizontalHeaderItem(c)
                if header_item:
                    col_name = header_item.text().strip()
                    if col_name in widths:
                        saved_w = widths[col_name]
                        if saved_w > 20:  # 最小列宽保护
                            header.resizeSection(c, saved_w)
        except Exception:
            pass

    # ==================== 列顺序持久化 ====================

    def _on_column_moved(self, logical_index, old_visual_index, new_visual_index):
        """用户拖拽列顺序后保存到个人配置文件"""
        if getattr(self, '_setting_column_order', False):
            return
        if not self._save_config_fn or not self._report_id:
            return
        QTimer.singleShot(300, self._save_column_order)

    def _save_column_order(self):
        """将当前列顺序写入个人配置文件"""
        order = []
        header = self._table.horizontalHeader()
        for visual in range(self._table.columnCount()):
            logical = header.logicalIndex(visual)
            item = self._table.horizontalHeaderItem(logical)
            if item:
                name = item.text().strip()
                if name:
                    order.append(name)
        if not order:
            return
        if self._save_config_fn and self._report_id:
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
                all_orders = cr.get('column_order', {})
                if not isinstance(all_orders, dict):
                    all_orders = {}
                all_orders[self._report_id] = order
                cr['column_order'] = all_orders
                self._save_config_fn(cfg)
            except Exception:
                pass
        self.columnOrderChanged.emit(order)

    def set_column_order(self, order: list[str]):
        """按给定的列名顺序重排列（从字段面板同步），不会触发保存或反向信号。"""
        if not order:
            return
        self._setting_column_order = True
        try:
            header = self._table.horizontalHeader()
            name_to_logical = {}
            for c in range(self._table.columnCount()):
                item = self._table.horizontalHeaderItem(c)
                if item:
                    name_to_logical[item.text().strip()] = c
            target_visual = 0
            for name in order:
                logical = name_to_logical.get(name)
                if logical is not None:
                    current_visual = header.visualIndex(logical)
                    if current_visual != target_visual:
                        header.moveSection(current_visual, target_visual)
                    target_visual += 1
        finally:
            self._setting_column_order = False

    def _apply_definition_column_order(self):
        """用 report_def.columns 的 sort_order 覆盖列顺序，
        确保详情页字段顺序始终与编辑界面调整的一致。"""
        if not self._report_def:
            return
        cols = getattr(self._report_def, 'columns', None)
        if not cols:
            return
        # 收集可见列的 (sort_order, display_name) 并按 sort_order 排序
        ordered = []
        for col in cols:
            if isinstance(col, dict):
                if not col.get('visible', True):
                    continue
                sort_order = col.get('sort_order', 0)
                display_name = col.get('display_name', '')
            else:
                if not getattr(col, 'visible', True):
                    continue
                sort_order = getattr(col, 'sort_order', 0)
                display_name = getattr(col, 'display_name', '')
            if display_name:
                ordered.append((sort_order, display_name))
        if not ordered:
            return
        ordered.sort(key=lambda x: x[0])
        order = [name for _, name in ordered]

        # 应用列顺序（只移动实际存在于表格中的列）
        header = self._table.horizontalHeader()
        name_to_logical = {}
        for c in range(self._table.columnCount()):
            item = self._table.horizontalHeaderItem(c)
            if item:
                name_to_logical[item.text().strip()] = c
        target_visual = 0
        for name in order:
            logical = name_to_logical.get(name)
            if logical is not None:
                current_visual = header.visualIndex(logical)
                if current_visual != target_visual:
                    header.moveSection(current_visual, target_visual)
                target_visual += 1

    def _load_column_order(self):
        """从个人配置文件恢复已保存的列顺序"""
        if not self._load_config_fn or not self._report_id:
            return
        try:
            cfg = self._load_config_fn()
            if not isinstance(cfg, dict):
                return
            cr = cfg.get('custom_reports', {})
            if not isinstance(cr, dict):
                return
            all_orders = cr.get('column_order', {})
            if not isinstance(all_orders, dict):
                return
            saved_order = all_orders.get(self._report_id, [])
            if not saved_order:
                return
            header = self._table.horizontalHeader()
            # 构建当前列名 → 逻辑索引映射
            name_to_logical = {}
            for c in range(self._table.columnCount()):
                item = self._table.horizontalHeaderItem(c)
                if item:
                    name_to_logical[item.text().strip()] = c
            # 按保存的顺序移动列
            target_visual = 0
            for name in saved_order:
                logical = name_to_logical.get(name)
                if logical is not None:
                    current_visual = header.visualIndex(logical)
                    if current_visual != target_visual:
                        header.moveSection(current_visual, target_visual)
                    target_visual += 1
        except Exception:
            pass

    # ==================== 交互 ====================

    def _on_search_text_changed(self, text):
        self._search_text = text
        self._search_timer.start()

    def _do_search(self):
        self._current_page = 1
        self.refresh()

    def _on_page_size_changed(self, text):
        try:
            self._page_size = int(text)
        except ValueError:
            self._page_size = 50
        self._current_page = 1
        self.refresh()

    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self.refresh()

    def _next_page(self):
        page_count = max(1, (self._total_rows + self._page_size - 1) // self._page_size)
        if self._current_page < page_count:
            self._current_page += 1
            self.refresh()

    def _export(self):
        from PyQt6.QtWidgets import QFileDialog
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            if self._total_rows > 10000:
                reply = _light_question(self, "确认导出",
                    f"共 {self._total_rows} 条记录，导出可能需要较长时间。是否继续？")
                if reply != QMessageBox.StandardButton.Yes:
                    return

            rows, _ = self._db.query_result(
                self._report_id, page=1,
                page_size=max(self._total_rows, 1),
                search=self._search_text or None,
                search_columns=self._search_columns or None,
            )
            if not rows:
                return

            # 转为 DataFrame 应用公式列
            import pandas as pd
            df = pd.DataFrame(rows)
            if self._report_def:
                try:
                    from ..formula_engine import eval_formula_columns, compute_summary_row
                    df = eval_formula_columns(df, self._report_def.columns)
                except Exception:
                    pass

            skip_cols = {'_row_id'}
            cols = [k for k in df.columns if k not in skip_cols]
            row_dicts = df.to_dict('records')

            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()
                writer.writerows(row_dicts)

                # 追加汇总行
                if self._report_def and getattr(self._report_def, 'show_summary_row', False):
                    try:
                        from ..formula_engine import compute_summary_row
                        summary = compute_summary_row(df, self._report_def.columns)
                        writer.writerow(summary)
                    except Exception:
                        pass

            _light_msgbox(self, QMessageBox.Icon.Information, "导出完成", f"已导出到: {path}")
        except Exception as e:
            _light_msgbox(self, QMessageBox.Icon.Warning, "导出失败", str(e))
