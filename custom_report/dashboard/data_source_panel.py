"""
数据源选择面板

在仪表盘设计器左侧显示可用数据源（自定义报表 / Excel 数据集 / MySQL 表），
双击数据源可查看字段详情，支持搜索过滤。
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTreeWidget, QTreeWidgetItem, QPushButton, QFileDialog,
    QDialog, QDialogButtonBox, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class DataSourcePanel(QWidget):
    """数据源选择面板"""

    # 信号
    sourceSelected = pyqtSignal(str, str, list)  # (source_type, source_id, fields)
    sourceDoubleClicked = pyqtSignal(str, str, str, list)  # (type, id, name, fields)
    tableClicked = pyqtSignal(str, str, str, list)  # 单击选中表 (type, id, name, fields)
    sourcesLoaded = pyqtSignal(dict)  # 数据源加载完成
    importExcelRequested = pyqtSignal(str)  # file_path
    importMySQLRequested = pyqtSignal()
    refreshRequested = pyqtSignal()  # 请求刷新数据源列表

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data_sources = {"reports": [], "excel_datasets": [], "mysql_tables": []}
        self._field_cache = {}  # {source_type:source_id: [fields]}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.setMinimumWidth(180)
        self.setStyleSheet(
            "font-size: 12px;"
            "QComboBox::drop-down { width: 12px; }"
            "QComboBox::down-arrow { width: 8px; height: 8px; }"
        )

        # 标题行：折叠按钮 + 标题
        header_row = QHBoxLayout()
        header_row.setSpacing(4)
        self._collapse_btn = QPushButton("◀")
        self._collapse_btn.setFixedSize(22, 22)
        self._collapse_btn.setToolTip("收起/展开数据源面板")
        self._collapse_btn.setStyleSheet(
            "QPushButton { border: 1px solid #D9D9D9; border-radius: 3px; background: #FFF; font-size: 10px; }"
            "QPushButton:hover { border-color: #1890FF; }"
        )
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        header_row.addWidget(self._collapse_btn)
        header = QLabel("📊 数据源")
        header.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        header_row.addWidget(header, 1)
        layout.addLayout(header_row)

        # 搜索 + 刷新 同行
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 搜索...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        search_row.addWidget(self._search, 1)
        refresh_btn = QPushButton("🔄")
        refresh_btn.setToolTip("刷新数据源列表（保留图表）")
        refresh_btn.clicked.connect(self.refresh_data)
        refresh_btn.setFixedHeight(26)
        refresh_btn.setFixedWidth(58)
        search_row.addWidget(refresh_btn)
        layout.addLayout(search_row)

        # 可折叠区域
        self._collapsible = QWidget()
        coll_layout = QVBoxLayout(self._collapsible)
        coll_layout.setContentsMargins(0, 0, 0, 0)
        coll_layout.setSpacing(4)

        # 树形列表
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(16)
        self._tree.setAnimated(True)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.setStyleSheet("""
            QTreeWidget { background: #FAFAFA; border: none; font-size: 13px; }
            QTreeWidget::item { padding: 6px 4px; }
            QTreeWidget::item:hover { background: #FFF7E6; }
            QTreeWidget::item:selected { background: #FFD591; color: #333; }
        """)
        coll_layout.addWidget(self._tree, 1)

        # 导入按钮：并排一行
        import_row = QHBoxLayout()
        import_row.setSpacing(4)
        self._import_excel_btn = QPushButton("📤 Excel")
        self._import_excel_btn.clicked.connect(self._on_import_excel)
        self._import_excel_btn.setFixedHeight(28)
        import_row.addWidget(self._import_excel_btn, 1)
        self._import_mysql_btn = QPushButton("🗄️ MySQL")
        self._import_mysql_btn.clicked.connect(lambda: self.importMySQLRequested.emit())
        self._import_mysql_btn.setFixedHeight(28)
        import_row.addWidget(self._import_mysql_btn, 1)
        coll_layout.addLayout(import_row)

        layout.addWidget(self._collapsible, 1)
        self._collapsed = False

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._collapsible.setVisible(not self._collapsed)
        self._collapse_btn.setText("▶" if self._collapsed else "◀")
        # 收缩时设置最小宽度，展开时恢复
        if self._collapsed:
            self.setFixedWidth(40)
        else:
            self.setMinimumWidth(180)
            self.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX

    def add_mysql_table(self, name: str, row_count: int, columns: list):
        """
        动态添加一个 MySQL 表到数据源列表

        Args:
            name: 表名
            row_count: 行数
            columns: [{key, label, data_type}, ...]
        """
        # 检查是否已存在
        for t in self._data_sources.get('mysql_tables', []):
            if t.get('name') == name:
                return  # 已存在，跳过
        entry = {'name': name, 'row_count': row_count, 'columns': columns}
        self._data_sources.setdefault('mysql_tables', []).append(entry)
        key = f"mysql:{name}"
        self._field_cache[key] = columns
        self._populate_tree()

    def set_data_sources(self, sources: dict):
        """
        设置数据源列表

        Args:
            sources: {
                'reports': [{id, name, row_count, fields, table_name}],
                'excel_datasets': [{id, name, row_count, columns, table_name}],
                'mysql_tables': [{name, row_count, columns}],
            }
        """
        self._data_sources = sources
        # 缓存字段信息
        for r in sources.get('reports', []):
            key = f"report:{r['id']}"
            self._field_cache[key] = r.get('fields', [])
        for ds in sources.get('excel_datasets', []):
            key = f"excel:{ds['id']}"
            self._field_cache[key] = ds.get('columns', [])
        for t in sources.get('mysql_tables', []):
            key = f"mysql:{t['name']}"
            self._field_cache[key] = t.get('columns', [])
        self._populate_tree()
        self.sourcesLoaded.emit(sources)

    def refresh_data(self):
        """刷新数据源列表（发出信号由设计器重新查询，不清理图表数据）"""
        self.refreshRequested.emit()

    def _populate_tree(self, search: str = None):
        self._tree.clear()
        search_lower = (search or '').lower()

        sources = self._data_sources

        # 自定义报表
        reports = sources.get('reports', [])
        if reports:
            report_root = QTreeWidgetItem(["▼ 自定义报表 (%d)" % len(reports)])
            report_root.setData(0, Qt.ItemDataRole.UserRole, "section")
            report_font = QFont()
            report_font.setBold(True)
            report_root.setFont(0, report_font)
            for r in reports:
                name = r.get('name', '')
                if search_lower and search_lower not in name.lower():
                    continue
                row_count = r.get('row_count', 0)
                item = QTreeWidgetItem([f"🗂️ {name}   {row_count}行"])
                item.setData(0, Qt.ItemDataRole.UserRole, f"report:{r['id']}")
                item.setToolTip(0, f"表: {r.get('table_name', '')}\n字段: {len(r.get('fields', []))}个")
                report_root.addChild(item)
            if report_root.childCount() > 0:
                self._tree.addTopLevelItem(report_root)
                report_root.setExpanded(True)

        # Excel 数据集
        datasets = sources.get('excel_datasets', [])
        excel_root = QTreeWidgetItem(["▼ Excel 数据集 (%d)" % len(datasets)])
        excel_root.setData(0, Qt.ItemDataRole.UserRole, "section")
        excel_root.setFont(0, QFont())
        excel_root.font(0).setBold(True)
        for ds in datasets:
            name = ds.get('name', '')
            if search_lower and search_lower not in name.lower():
                continue
            row_count = ds.get('row_count', 0)
            item = QTreeWidgetItem([f"📄 {name}   {row_count}行"])
            item.setData(0, Qt.ItemDataRole.UserRole, f"excel:{ds['id']}")
            item.setToolTip(0, f"源文件: {ds.get('source_file', '')}\n字段: {len(ds.get('columns', []))}个")
            excel_root.addChild(item)
        if excel_root.childCount() > 0:
            self._tree.addTopLevelItem(excel_root)
            excel_root.setExpanded(True)

        # MySQL 表
        tables = sources.get('mysql_tables', [])
        if tables:
            mysql_root = QTreeWidgetItem(["▼ MySQL 表 (%d)" % len(tables)])
            mysql_root.setData(0, Qt.ItemDataRole.UserRole, "section")
            mysql_root.setFont(0, QFont())
            mysql_root.font(0).setBold(True)
            for t in tables:
                name = t.get('name', '')
                if search_lower and search_lower not in name.lower():
                    continue
                row_count = t.get('row_count', 0)
                item = QTreeWidgetItem([f"🗄️ {name}   {row_count}行"])
                item.setData(0, Qt.ItemDataRole.UserRole, f"mysql:{name}")
                mysql_root.addChild(item)
            if mysql_root.childCount() > 0:
                self._tree.addTopLevelItem(mysql_root)
                mysql_root.setExpanded(True)

    def _on_search(self, text: str):
        self._populate_tree(text)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """单击选中数据表，通知设计器"""
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if not key or key == "section":
            return
        parts = key.split(':', 1)
        if len(parts) != 2:
            return
        source_type, source_id = parts
        fields = self._field_cache.get(key, [])
        name = item.text(0).replace('🗂️ ', '').replace('📄 ', '').replace('🗄️ ', '').rsplit('   ', 1)[0]
        self.tableClicked.emit(source_type, source_id, name, fields)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if not key or key == "section":
            return
        parts = key.split(':', 1)
        if len(parts) != 2:
            return
        source_type, source_id = parts
        fields = self._field_cache.get(key, [])

        # 显示字段预览对话框
        dialog = _FieldPreviewDialog(source_type, source_id, fields, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = item.text(0).replace('🗂️ ', '').replace('📄 ', '').replace('🗄️ ', '').rsplit('   ', 1)[0]
            self.sourceDoubleClicked.emit(source_type, source_id, name, fields)

    def _on_import_excel(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入数据文件", "",
            "数据文件 (*.xlsx *.xls *.csv *.json);;所有文件 (*.*)"
        )
        if file_path:
            self.importExcelRequested.emit(file_path)


class _FieldPreviewDialog(QDialog):
    """数据源字段预览对话框"""

    def __init__(self, source_type: str, source_id: str, fields: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("字段预览")
        self.setMinimumSize(400, 350)
        self.setStyleSheet("QDialog { background: #FAFAFA; }")

        layout = QVBoxLayout(self)

        # 标题
        type_names = {"report": "自定义报表", "excel": "Excel 数据集", "mysql": "MySQL 表"}
        type_name = type_names.get(source_type, source_type)
        layout.addWidget(QLabel(f"<b>{type_name}</b> — {source_id}"))
        layout.addWidget(QLabel(f"共 {len(fields)} 个字段:"))

        # 字段列表
        tree = QTreeWidget()
        tree.setHeaderLabels(["字段名", "类型", "建议用途"])
        for f in fields:
            if isinstance(f, dict):
                name = f.get('key') or f.get('name', '')
                dtype = f.get('data_type', 'text')
                # 推断建议用途
                if dtype in ('number', 'int64', 'float64', 'int', 'float', 'double'):
                    use = "度量（数值）"
                elif dtype in ('date', 'datetime', 'datetime64[ns]'):
                    use = "维度（时间）"
                else:
                    use = "维度（文本）"
            elif isinstance(f, (tuple, list)) and len(f) >= 2:
                name = f[0]
                dtype = 'text'
                use = "维度"
            else:
                name = str(f)
                dtype = 'text'
                use = "—"
            item = QTreeWidgetItem([name, dtype, use])
            tree.addTopLevelItem(item)
        tree.resizeColumnToContents(0)
        layout.addWidget(tree)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
