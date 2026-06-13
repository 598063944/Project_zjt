"""
报表详情页（数据视图）

从 MySQL 结果表读取报表数据，全页展示。
布局对齐 CRM「订单转合同」页面：QGroupBox 包裹筛选栏 + 搜索框 + 数据区 + 分页栏。
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
    QGroupBox, QComboBox, QLineEdit, QCompleter,
)
from PyQt6.QtCore import Qt, pyqtSignal

from .preview_table import PreviewTable, _light_msgbox
from .filter_bar import FilterBar
from ..db_manager import ReportDatabase


class ReportDetailPage(QWidget):
    """报表详情页 —— 对齐 CRM 订单页布局"""

    backRequested = pyqtSignal()
    editRequested = pyqtSignal(str)
    refreshDataRequested = pyqtSignal(str)

    def __init__(self, db: ReportDatabase = None, parent=None,
                 save_config_fn=None, load_config_fn=None,
                 app_config: dict = None,
                 save_filters_fn=None):
        super().__init__(parent)
        self._db = db
        self._report_id = ""
        self._report_name = ""
        self._report_def = None  # 报表定义，用于读取 write_mode 等配置
        self._save_config_fn = save_config_fn
        self._load_config_fn = load_config_fn
        self._app_config = app_config or {}
        self._save_filters_fn = save_filters_fn

        self._setup_ui()

    def set_database(self, db: ReportDatabase):
        self._db = db
        self._preview.set_database(db)
        self._filter_bar.set_database(db)

    def load_report(self, report_id: str, report_name: str = "", filters: list = None,
                    id_column: str = None, report_def=None):
        self._report_id = report_id
        self._report_name = report_name or report_id
        self._id_column = id_column  # 主表 _id 对应的中文列名，用于同步 MySQL 时做 PK
        self._report_def = report_def  # 保存报表定义，用于同步 MySQL 时读取 write_mode
        self._title_label.setText(f"📊 {self._report_name}")
        self._preview.set_report(report_id)
        if report_def is not None:
            self._preview.set_report_definition(report_def)
        # 设置筛选栏的结果表，用于「属于」/「不属于」查询去重值
        if self._db:
            self._filter_bar.set_result_table(self._db.result_table_name(report_id))
        self._update_filter_fields()
        if filters:
            self._filter_bar.set_conditions(filters)
            # set_conditions 不触发 filtersChanged，需手动应用到表格
            self._preview.set_filter_conditions(self._filter_bar.get_conditions())

    # ==================== UI ====================

    def _setup_ui(self):
        from PyQt6.QtWidgets import QSizePolicy

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(8)

        # ========== 主 GroupBox ==========
        main_group = QGroupBox("报表数据")
        main_layout = QVBoxLayout(main_group)
        main_layout.setSpacing(8)

        # ---- 工具行（返回 + 标题 + stretch + 导出 + 编辑）----
        tool_row = QHBoxLayout()
        tool_row.setSpacing(12)

        back_btn = QPushButton("← 返回列表")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; color: #1890FF;
                          font-size: 14px; text-decoration: underline; padding: 4px 10px; }
            QPushButton:hover { color: #FF8C00; }
        """)
        back_btn.clicked.connect(self.backRequested.emit)
        tool_row.addWidget(back_btn)

        self._title_label = QLabel("📊 报表数据")
        self._title_label.setStyleSheet("font-size: 16px; font-weight: 600; color: #333;")
        tool_row.addWidget(self._title_label)

        tool_row.addSpacing(16)

        # ---- 筛选栏 ----
        self._filter_bar = FilterBar()
        if self._db:
            self._filter_bar.set_database(self._db)
        self._filter_bar.filtersChanged.connect(self._on_filter_changed)
        self._filter_bar.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._filter_bar.setMinimumHeight(34)
        tool_row.addWidget(self._filter_bar)

        tool_row.addSpacing(8)

        # ---- 搜索框 ----
        self._search_frame = QFrame()
        self._search_frame.setFixedHeight(32)
        self._search_frame.setMaximumWidth(280)
        self._search_frame.setStyleSheet("""
            QFrame { border: 1px solid #D9D9D9; border-radius: 4px;
                     background-color: #FFFFFF; }
            QFrame:focus-within { border-color: #1890FF; }
        """)
        search_layout = QHBoxLayout(self._search_frame)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)

        self._search_field_combo = QComboBox()
        self._search_field_combo.setEditable(True)
        self._search_field_combo.setFixedWidth(120)
        self._search_field_combo.setFixedHeight(30)
        self._search_field_combo.setPlaceholderText("搜索字段…")
        self._search_field_combo.setCurrentText("全字段")
        self._search_field_combo.setStyleSheet("""
            QComboBox { border: none; background: transparent;
                        padding: 2px 4px 2px 8px; font-size: 12px; color: #666; }
            QComboBox:hover { color: #333; }
            QComboBox::drop-down { border: none; width: 16px; }
            QComboBox QAbstractItemView { border: 1px solid #D9D9D9; border-radius: 4px;
                        background-color: #FFFFFF;
                        selection-background-color: #E6F7FF; selection-color: #1890FF; }
        """)
        search_layout.addWidget(self._search_field_combo)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("border: none; background-color: #E8E8E8; min-width: 1px; max-width: 1px;")
        search_layout.addWidget(sep)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索...")
        self._search_input.setStyleSheet("QLineEdit { border: none; padding: 2px 8px; font-size: 12px; }")
        self._search_input.returnPressed.connect(self._on_search)
        search_layout.addWidget(self._search_input, 1)

        tool_row.addWidget(self._search_frame)

        tool_row.addStretch()

        self._export_btn = QPushButton("导出")
        self._export_btn.setFixedSize(50, 26)
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.setStyleSheet("""
            QPushButton { border: 1px solid #D9D9D9; border-radius: 3px;
                          font-size: 11px; background: #FFFFFF; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        self._export_btn.clicked.connect(lambda: self._preview._export() if self._preview else None)
        tool_row.addWidget(self._export_btn)

        self._sync_btn = QPushButton("同步MySQL")
        self._sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_btn.setMinimumWidth(110)
        self._sync_btn.setStyleSheet("""
            QPushButton { background-color: #00A854; color: #FFFFFF; border: none;
                          border-radius: 4px; padding: 8px 18px; font-size: 14px; font-weight: 600; }
            QPushButton:hover { background-color: #008C44; }
            QPushButton:disabled { background-color: #B0B0B0; }
        """)
        self._sync_btn.clicked.connect(self._on_sync_mysql)
        tool_row.addWidget(self._sync_btn)

        refresh_btn = QPushButton("🔄 更新数据")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setMinimumWidth(110)
        refresh_btn.setStyleSheet("""
            QPushButton { background-color: #1890FF; color: #FFFFFF; border: none;
                          border-radius: 4px; padding: 8px 18px; font-size: 14px; font-weight: 600; }
            QPushButton:hover { background-color: #1472C8; }
            QPushButton:disabled { background-color: #B0B0B0; }
        """)
        refresh_btn.clicked.connect(lambda: self.refreshDataRequested.emit(self._report_id))
        tool_row.addWidget(refresh_btn)
        self._refresh_btn = refresh_btn

        edit_btn = QPushButton("⚙ 编辑报表")
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setMinimumWidth(110)
        edit_btn.setStyleSheet("""
            QPushButton { background-color: #FF8C00; color: #FFFFFF; border: none;
                          border-radius: 4px; padding: 8px 18px; font-size: 14px; font-weight: 600; }
            QPushButton:hover { background-color: #E67A00; }
        """)
        edit_btn.clicked.connect(lambda: self.editRequested.emit(self._report_id))
        tool_row.addWidget(edit_btn)

        main_layout.addLayout(tool_row)

        # ========== 数据明细 GroupBox ==========
        data_group = QGroupBox("数据明细")
        data_layout = QVBoxLayout(data_group)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(6)

        # --- 表格（隐藏内部搜索和分页）---
        self._preview = PreviewTable(self._db, show_search=False, show_pagination=False)
        self._preview.set_config_callbacks(self._save_config_fn, self._load_config_fn)
        self._preview.pageInfoChanged.connect(self._on_page_info_changed)
        data_layout.addWidget(self._preview, 1)

        # --- 分页栏（完全复制 CRM pag_bar）---
        pag_bar = QHBoxLayout()
        pag_bar.setSpacing(8)

        self._record_label = QLabel("共 0 条记录")
        self._record_label.setStyleSheet("font-weight: bold; color: #555;")
        pag_bar.addWidget(self._record_label)

        pag_bar.addStretch()

        pag_bar.addWidget(QLabel("每页："))
        self._page_size_combo = QComboBox()
        self._page_size_combo.setEditable(True)
        self._page_size_combo.addItem("自定义", -1)
        for sz in (20, 50, 80, 100, 200):
            self._page_size_combo.addItem(str(sz), sz)
        self._page_size_combo.setCurrentIndex(1)  # 默认 20
        self._page_size_combo.setStyleSheet("QComboBox { font-size: 11px; padding: 2px 4px; }")
        self._page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)
        pag_bar.addWidget(self._page_size_combo)

        pag_bar.addSpacing(12)
        self._prev_btn = QPushButton("<")
        self._prev_btn.setFixedWidth(30)
        self._prev_btn.setFixedHeight(26)
        self._prev_btn.clicked.connect(self._on_prev_page)
        pag_bar.addWidget(self._prev_btn)

        self._page_label = QLabel("1/1")
        self._page_label.setFixedWidth(50)
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setStyleSheet("font-weight: bold; color: #333;")
        pag_bar.addWidget(self._page_label)

        self._next_btn = QPushButton(">")
        self._next_btn.setFixedWidth(30)
        self._next_btn.setFixedHeight(26)
        self._next_btn.clicked.connect(self._on_next_page)
        pag_bar.addWidget(self._next_btn)

        data_layout.addLayout(pag_bar)

        main_layout.addWidget(data_group, 1)
        layout.addWidget(main_group, 1)

    # ==================== 搜索 ====================

    def _update_filter_fields(self):
        """更新筛选栏字段 + 搜索字段下拉框"""
        if not self._preview:
            return
        columns = self._preview.get_result_columns()
        if not columns:
            return
        # 更新搜索字段下拉框
        all_labels = ["全字段"] + columns
        self._search_field_combo.blockSignals(True)
        self._search_field_combo.clear()
        self._search_field_combo.addItem("全字段", "")
        for col in columns:
            self._search_field_combo.addItem(col, col)
        self._search_field_combo.setCurrentIndex(0)
        self._search_field_combo.blockSignals(False)
        completer = QCompleter(all_labels, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._search_field_combo.setCompleter(completer)
        # 更新筛选栏字段
        date_kw = ('时间', '日期', '创建', '修改', '提交', 'date', 'time')
        field_list = []
        for col in columns:
            is_date = any(kw in col.lower() for kw in date_kw)
            field_list.append((col, col, is_date))
        self._filter_bar.set_available_fields(field_list)

    def _on_search(self):
        """搜索框回车"""
        text = self._search_input.text().strip()
        field = self._search_field_combo.currentData() or ""
        if field:
            self._preview.set_search_columns([field])
        else:
            self._preview.set_search_columns(None)
        self._preview.set_search_text(text)

    # ==================== 分页 ====================

    def _on_page_size_changed(self):
        data = self._page_size_combo.currentData()
        if data and data > 0:
            self._preview.set_page_size(data)

    def _on_prev_page(self):
        info = self._preview.get_page_info()
        if info['current'] > 1:
            self._preview.set_page(info['current'] - 1)

    def _on_next_page(self):
        info = self._preview.get_page_info()
        if info['current'] < info['page_count']:
            self._preview.set_page(info['current'] + 1)

    def _on_page_info_changed(self):
        """分页信息变更 → 同步外部控件"""
        info = self._preview.get_page_info()
        self._record_label.setText(f"共 {info['total']} 条记录")
        self._page_label.setText(f"{info['current']}/{info['page_count']}")
        self._prev_btn.setEnabled(info['current'] > 1)
        self._next_btn.setEnabled(info['current'] < info['page_count'])
        # 同步每页条数下拉框
        ps = str(info['page_size'])
        if self._page_size_combo.currentText() != ps:
            self._page_size_combo.blockSignals(True)
            idx = self._page_size_combo.findText(ps)
            if idx >= 0:
                self._page_size_combo.setCurrentIndex(idx)
            self._page_size_combo.blockSignals(False)

    # ==================== 筛选 ====================

    def _on_filter_changed(self):
        if not self._preview or not self._report_id:
            return
        conditions = self._filter_bar.get_conditions()
        self._preview.set_filter_conditions(conditions)
        if self._save_filters_fn:
            self._save_filters_fn(self._report_id, conditions)

    def _on_sync_mysql(self):
        """将当前结果表数据同步到展示用的 MySQL 表（带中文表头）。

        写入方式与编辑界面保持一致：读取报表定义中保存的 write_mode，
        - 覆盖: DROP+CREATE 目标表，全量插入
        - 增量: INSERT ... ON DUPLICATE KEY UPDATE
        """
        from PyQt6.QtWidgets import QMessageBox

        if not self._db or not self._report_id:
            _light_msgbox(self, QMessageBox.Icon.Warning, "同步失败", "数据库未连接")
            return

        filters = self._filter_bar.get_conditions()
        # 排除「生命状态」筛选条件：作废数据也要写入 MySQL
        filters = [f for f in filters
                   if '生命状态' not in str(f.get('field_label', '') or f.get('field', ''))]
        search = self._search_input.text().strip() or None
        search_col = self._search_field_combo.currentData()
        search_columns = [search_col] if search_col else None

        table_name = f"报表-{self._report_name}"

        # 从报表定义读取 write_mode，与编辑界面保持一致
        write_mode = "incremental"
        if self._report_def is not None:
            wm = getattr(self._report_def, 'write_mode', None)
            if wm in ('overwrite', 'incremental'):
                write_mode = wm

        self._sync_btn.setEnabled(False)
        self._sync_btn.setText("⏳ 同步中...")

        # sync_id_fields 存的是字段中文标签 = 结果表列名，可直接使用
        sync_id_fields = getattr(self._report_def, 'sync_id_fields', None) or None

        try:
            # 从报表定义取列顺序（按 sort_order）
            cols = getattr(self._report_def, 'columns', None) or []
            column_order = [
                (c.display_name if hasattr(c, 'display_name') else c.get('display_name', ''))
                for c in sorted(cols, key=lambda x: x.sort_order if hasattr(x, 'sort_order') else x.get('sort_order', 0))
                if (c.display_name if hasattr(c, 'display_name') else c.get('display_name', ''))
            ]
            ok, msg, stats = self._db.sync_filtered_to_mysql(
                self._report_id, table_name,
                filters=filters, search=search, search_columns=search_columns,
                id_column='_id',
                column_order=column_order,
                write_mode=write_mode,
                sync_id_fields=sync_id_fields if sync_id_fields else None,
                sync_id_separator=getattr(self._report_def, 'sync_id_separator', '_') or '_',
            )
            if ok:
                _light_msgbox(self, QMessageBox.Icon.Information,
                              "同步完成", f"已同步到 MySQL 表: {table_name}\n{msg}")
            else:
                _light_msgbox(self, QMessageBox.Icon.Warning, "同步失败", msg)
        except Exception as e:
            _light_msgbox(self, QMessageBox.Icon.Warning, "同步异常", str(e))
        finally:
            self._sync_btn.setText("同步MySQL")
            self._sync_btn.setEnabled(True)
