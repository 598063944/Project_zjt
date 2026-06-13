"""
左侧待选表面板

显示 MySQL 中的数据表，支持:
- CRM 对象清洗表（对象-{Name} / sr_{api}）
- Excel 导入表（ex_{id}）
- 其他 MySQL 表（排除系统表）

支持搜索过滤，双击将表添加到画布。
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QFrame,
    QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class _MySQLTableDialog(QDialog):
    """MySQL 表选择对话框：列出当前库中未被管理的表，支持搜索和多选。"""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加 MySQL 表")
        self.setMinimumSize(500, 420)
        self._db = db
        self._selected_table: str = ""
        self.setStyleSheet("""
            QDialog { background-color: #FAFAFA; }
            QLabel { color: #333333; font-size: 13px; }
            QLineEdit {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 6px 10px; font-size: 13px;
            }
            QLineEdit:focus { border-color: #FF8C00; }
            QTableWidget {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #E0E0E0; font-size: 13px;
                gridline-color: #F0F0F0;
            }
            QTableWidget::item { padding: 6px 10px; }
            QTableWidget::item:selected { background-color: #FFF7E6; color: #333333; }
            QHeaderView::section {
                background-color: #FAFAFA; color: #333333;
                border: none; border-bottom: 2px solid #E0E0E0;
                padding: 6px; font-weight: 500;
            }
            QPushButton {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 6px 20px; font-size: 13px; min-width: 80px;
            }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        self._setup_ui()
        self._load_tables()

    def _setup_ui(self):
        from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
        layout = QVBoxLayout(self)

        # 搜索
        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索表名...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        search_row.addWidget(self._search)
        layout.addLayout(search_row)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["表名", "行数", "列数"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 80)
        self._table.setColumnWidth(2, 60)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.itemDoubleClicked.connect(self._on_accept)
        layout.addWidget(self._table)

        # 提示
        hint = QLabel("💡 双击表名或选中后点确定，将表添加为报表数据源")
        hint.setStyleSheet("font-size: 11px; color: #999; padding: 4px 0;")
        layout.addWidget(hint)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_tables(self):
        try:
            all_tables = self._db.execute("SHOW TABLES") or []
        except Exception:
            return

        self._all_data = []
        for row in all_tables:
            table_name = list(row.values())[0] if row else ""
            if not table_name:
                continue
            try:
                cnt = self._db.execute(f"SELECT COUNT(*) AS cnt FROM `{table_name}`")
                row_count = cnt[0].get('cnt', 0) if cnt else 0
                cols = self._db.execute(f"SHOW COLUMNS FROM `{table_name}`")
                col_count = len(cols) if cols else 0
            except Exception:
                row_count = 0
                col_count = 0
            self._all_data.append((table_name, row_count, col_count))

        self._all_data.sort(key=lambda x: x[0].lower())
        self._populate_table(self._all_data)

    def _populate_table(self, data):
        self._table.setRowCount(len(data))
        for i, (name, rows, cols) in enumerate(data):
            self._table.setItem(i, 0, QTableWidgetItem(name))
            self._table.setItem(i, 1, QTableWidgetItem(str(rows)))
            self._table.setItem(i, 2, QTableWidgetItem(str(cols)))

    def _on_search(self, text):
        if not text:
            self._populate_table(self._all_data)
            return
        filtered = [(n, r, c) for n, r, c in self._all_data if text.lower() in n.lower()]
        self._populate_table(filtered)

    def _on_accept(self):
        row = self._table.currentRow()
        if row >= 0:
            item = self._table.item(row, 0)
            if item:
                self._selected_table = item.text()
        self.accept()

    @property
    def selected_table(self) -> str:
        return self._selected_table


class TableSelectorPanel(QWidget):
    """左侧待选表面板 —— 列出 MySQL 中的可用表"""

    tableSelected = pyqtSignal(str, str, list, str)  # table_name, display_name, fields, source_type
    importExcelRequested = pyqtSignal()       # 请求导入 Excel
    addMySQLRequested = pyqtSignal()          # 请求添加 MySQL 表
    refreshExcelRequested = pyqtSignal(str)   # 请求刷新 Excel 表数据 (table_name)

    def __init__(self, db=None, excel_repo=None, parent=None):
        """
        Args:
            db: ReportDatabase 实例（可为 None）
            excel_repo: ExcelDatasetRepository 实例（可为 None）
        """
        super().__init__(parent)
        self._db = db
        self._excel_repo = excel_repo
        self._table_data: dict[str, dict] = {}  # {table_name: {display_name, fields, source_type, ...}}
        self._name_map: dict[str, str] = {}  # {raw_name: mapped_name}
        self._setup_ui()

    def set_name_mapping(self, mapping: dict[str, str]):
        """设置表名映射 {api_name: chinese_display_name} 用于显示。"""
        self._name_map = mapping

    # ==================== UI ====================

    def _setup_ui(self):
        self.setMinimumWidth(190)
        self.setMaximumWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        title = QLabel("可用数据表")
        title.setObjectName("panel_title")
        layout.addWidget(title)

        # 搜索框
        search_frame = QFrame()
        search_frame.setStyleSheet("QFrame { background-color: #FFFFFF; padding: 6px 8px; }")
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(8, 6, 8, 6)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索表名...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search)
        search_layout.addWidget(self._search_input)
        layout.addWidget(search_frame)

        # 导入按钮行
        import_row = QHBoxLayout()
        import_row.setContentsMargins(8, 4, 8, 4)
        import_row.setSpacing(4)

        excel_btn = QPushButton("📥 导入Excel")
        excel_btn.setFixedHeight(28)
        excel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        excel_btn.setStyleSheet("""
            QPushButton { background-color: #52C41A; color: #FFFFFF; border: none;
                          border-radius: 3px; padding: 2px 10px; font-size: 12px; font-weight: 500; }
            QPushButton:hover { background-color: #45A818; }
        """)
        excel_btn.clicked.connect(self.importExcelRequested.emit)
        import_row.addWidget(excel_btn, 1)

        mysql_btn = QPushButton("🔗 添加MySQL表")
        mysql_btn.setFixedHeight(28)
        mysql_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mysql_btn.setStyleSheet("""
            QPushButton { background-color: #1890FF; color: #FFFFFF; border: none;
                          border-radius: 3px; padding: 2px 10px; font-size: 12px; font-weight: 500; }
            QPushButton:hover { background-color: #157FDF; }
        """)
        mysql_btn.clicked.connect(self.addMySQLRequested.emit)
        import_row.addWidget(mysql_btn, 1)

        layout.addLayout(import_row)

        # 列表
        self._list_widget = QListWidget()
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list_widget, 1)

        # 底部信息栏
        bottom = QFrame()
        bottom.setStyleSheet("QFrame { background-color: #F5F5F5; border-top: 1px solid #E0E0E0; padding: 6px 10px; }")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(10, 6, 10, 6)
        self._count_label = QLabel("共 0 张表")
        self._count_label.setStyleSheet("font-size: 11px; color: #999;")
        bottom_layout.addWidget(self._count_label)
        bottom_layout.addStretch()

        refresh_btn = QPushButton("刷新")
        refresh_btn.setFixedSize(52, 24)
        refresh_btn.clicked.connect(self.refresh)
        bottom_layout.addWidget(refresh_btn)

        layout.addWidget(bottom)

        # 样式
        self.setStyleSheet("""
            QWidget { background-color: #FAFAFA; }
            QLabel#panel_title {
                font-size: 13px; font-weight: 600; color: #333;
                padding: 10px 12px;
                background-color: #F5F5F5;
                border-bottom: 1px solid #E0E0E0;
            }
            QListWidget {
                border: none; background-color: #FFFFFF; font-size: 13px;
                outline: none; font-family: "Microsoft YaHei";
            }
            QListWidget::item {
                padding: 9px 12px; border-bottom: 1px solid #F0F0F0;
                color: #333333; background-color: #FFFFFF;
            }
            QListWidget::item:hover { background-color: #FFF7E6; }
            QListWidget::item:selected { background-color: #FFE7BA; color: #333; }
            QPushButton {
                background-color: #FFFFFF; border: 1px solid #D9D9D9;
                border-radius: 3px; padding: 2px 8px; font-size: 11px;
            }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)

    # ==================== 数据 ====================

    def refresh(self, include_mysql_tables: bool = False):
        """从 MySQL 查询可用表。

        Args:
            include_mysql_tables: 是否包含非管理的直连 MySQL 表。
                                  默认 False，只显示 CRM 对象表 + Excel 导入表。
        """
        self._list_widget.clear()
        self._table_data.clear()

        if not self._db or not self._db.available:
            self._show_placeholder("MySQL 未连接", "请在设置中配置并启用 MySQL 连接")
            return

        try:
            crm_tables = self._db.execute("SHOW TABLES LIKE '对象-%'") or []
        except Exception as e:
            self._show_placeholder("查询失败", str(e)[:80])
            return

        # 1. 对象表（仅显示 对象-XXX）
        for row in crm_tables:
            table_name = list(row.values())[0] if row else ""
            if not table_name:
                continue
            self._add_table_item(table_name, 'crm')

        # 2. (sr_% / ex_% / 普通MySQL表等不再显示)

        # 3. (已根据用户要求隐藏，不显示其他MySQL表)
        if include_mysql_tables:
            # (已根据用户要求隐藏，不再显示普通MySQL表)
            pass

        # 4. 始终追加「部门员工」等内置直连表（如果存在）
        for known_table in ('部门员工',):
            if known_table not in self._table_data and self._db.table_exists(known_table):
                self._add_table_item(known_table, 'mysql')

        if not self._table_data:
            self._show_placeholder("暂无数据表", "请先在对象查询中同步数据到 MySQL\n或通过上方按钮导入 Excel")
        else:
            self._count_label.setText(f"共 {len(self._table_data)} 张表")

    def add_mysql_table(self, table_name: str) -> bool:
        """按需添加一个直连 MySQL 表到列表。

        Returns:
            True 如果成功添加，False 如果表不存在或已在列表中。
        """
        if table_name in self._table_data:
            return False
        if not self._db or not self._db.table_exists(table_name):
            return False
        self._add_table_item(table_name, 'mysql')
        self._count_label.setText(f"共 {len(self._table_data)} 张表")
        return True

    def _add_table_item(self, table_name: str, source_type: str):
        """添加单个表到列表（通用方法）。"""
        # 解析显示名
        if source_type == 'crm':
            raw_name = table_name[3:] if table_name.startswith('对象-') else (
                table_name[3:] if table_name.startswith('sr_') else table_name)
            display_name = self._name_map.get(table_name) or self._name_map.get(raw_name) or raw_name
            icon = "📦"
        elif source_type == 'excel':
            display_name = table_name
            icon = "📊"
            if self._excel_repo:
                for ds in self._excel_repo.list_all():
                    if ds.mysql_table == table_name:
                        display_name = ds.name
                        break
        else:
            display_name = table_name
            icon = "🗄️"

        # 查询字段列表（排除系统列）
        fields = []
        row_count = 0
        last_sync = ""
        try:
            cols = self._db.execute(f"SHOW COLUMNS FROM `{table_name}`")
            if cols:
                fields = [r['Field'] for r in cols
                          if r['Field'] not in ('_id', '_hash', '_sync_time', '_row_id')]
            cnt = self._db.execute(f"SELECT COUNT(*) AS cnt FROM `{table_name}`")
            if cnt:
                row_count = cnt[0].get('cnt', 0)
            col_names = {r['Field'] for r in cols} if cols else set()
            if '_sync_time' in col_names:
                try:
                    sync = self._db.execute(
                        f"SELECT MAX(`_sync_time`) AS last_sync FROM `{table_name}`")
                    if sync and sync[0].get('last_sync'):
                        last_sync = str(sync[0]['last_sync'])[:19]
                except Exception:
                    pass
        except Exception:
            pass

        self._table_data[table_name] = {
            'display_name': display_name,
            'fields': fields,
            'row_count': row_count,
            'last_sync': last_sync,
            'source_type': source_type,
        }

        item = QListWidgetItem(f"  {icon} {display_name}  [{row_count}条]")
        item.setData(Qt.ItemDataRole.UserRole, table_name)
        tip = f"类型: {source_type}\n表: {table_name}\n字段数: {len(fields)}\n记录数: {row_count}"
        if last_sync:
            tip += f"\n最近同步: {last_sync}"
        item.setToolTip(tip)
        self._list_widget.addItem(item)

    def get_cached_fields(self, table_name: str) -> list:
        """获取已缓存的表字段列表"""
        data = self._table_data.get(table_name, {})
        return data.get('fields', [])

    # ==================== 交互 ====================

    def _on_context_menu(self, pos):
        """右键菜单：支持删除 Excel 导入表"""
        item = self._list_widget.itemAt(pos)
        if not item:
            return
        table_name = item.data(Qt.ItemDataRole.UserRole)
        if not table_name:
            return
        data = self._table_data.get(table_name, {})
        source_type = data.get('source_type', '')

        menu = QWidget(self).createContextMenu if False else None  # placeholder
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #FFFFFF; border: 1px solid #E0E0E0; padding: 4px; }
            QMenu::item { padding: 6px 30px 6px 20px; color: #333333; }
            QMenu::item:selected { background-color: #FFF7E6; }
            QMenu::separator { height: 1px; background: #F0F0F0; margin: 4px 8px; }
        """)

        if source_type == 'excel':
            refresh_action = menu.addAction("🔄 刷新数据")
            refresh_action.triggered.connect(lambda: self.refreshExcelRequested.emit(table_name))
            menu.addSeparator()
            delete_action = menu.addAction("🗑 删除")
            delete_action.triggered.connect(lambda: self._delete_direct_table(table_name, source_type))
        elif source_type == 'mysql':
            delete_action = menu.addAction("🗑 删除")
            delete_action.triggered.connect(lambda: self._delete_direct_table(table_name, source_type))
        else:
            info_action = menu.addAction(f"📋 表名: {table_name}")
            info_action.setEnabled(False)

        if not menu.isEmpty():
            menu.exec(self._list_widget.mapToGlobal(pos))

    def _delete_direct_table(self, table_name: str, source_type: str):
        """删除直连表（Excel 导入 / MySQL 表）：从 MySQL 删表 + 从仓库移除记录"""
        from PyQt6.QtWidgets import QMessageBox
        data = self._table_data.get(table_name, {})
        display_name = data.get('display_name', table_name)

        reply = QMessageBox.question(
            self, '确认删除',
            f'确定要删除「{display_name}」吗？\n\n'
            f'MySQL 表 {table_name} 将被删除，此操作不可撤销。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        errors = []
        # 1. 删除 MySQL 表
        if self._db and self._db.available:
            try:
                self._db.execute(f"DROP TABLE IF EXISTS `{table_name}`")
            except Exception as e:
                errors.append(f"MySQL: {e}")

        # 2. 从 ExcelDatasetRepository 移除
        if source_type == 'excel' and self._excel_repo:
            try:
                for ds in self._excel_repo.list_all():
                    if ds.mysql_table == table_name:
                        self._excel_repo.delete(ds.id)
                        break
            except Exception as e:
                errors.append(f"仓库: {e}")

        if errors:
            QMessageBox.warning(self, '删除失败', '；'.join(errors))
        else:
            # 刷新列表
            self.refresh()

    def _on_item_double_clicked(self, item):
        table_name = item.data(Qt.ItemDataRole.UserRole)
        if not table_name:
            return
        data = self._table_data.get(table_name, {})
        self.tableSelected.emit(
            table_name,
            data.get('display_name', table_name),
            data.get('fields', []),
            data.get('source_type', 'mysql'),
        )

    def _on_search(self, text):
        """搜索过滤"""
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            table_name = item.data(Qt.ItemDataRole.UserRole) or ""
            display_name = self._table_data.get(table_name, {}).get('display_name', '')
            match = (text.lower() in table_name.lower() or
                     text.lower() in display_name.lower())
            item.setHidden(not match)

    def _show_placeholder(self, title: str, detail: str):
        """显示占位提示"""
        self._list_widget.clear()
        self._table_data.clear()
        item = QListWidgetItem(f"  {title}\n  {detail}")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(Qt.GlobalColor.gray)
        self._list_widget.addItem(item)
        self._count_label.setText("共 0 张表")
