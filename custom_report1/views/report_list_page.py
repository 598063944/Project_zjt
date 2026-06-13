"""
报表列表页

显示所有已保存的报表，支持:
- 搜索、分页
- 新建 / 编辑 / 复制 / 删除
- 双击打开编辑器
- 文件夹分类管理（左侧文件夹树 + 右侧报表表格）
- 拖拽报表到文件夹
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QComboBox, QHeaderView,
    QAbstractItemView, QMenu, QInputDialog, QMessageBox, QGroupBox,
    QDialog, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QSplitter, QFrame, QApplication, QStyledItemDelegate, QStyle,
    QStyleOptionViewItem, QToolButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMimeData, QRect, QPoint, QSize
from PyQt6.QtGui import QAction, QDrag, QPainter, QColor, QFont, QPen

from ..repository import ReportRepository
from ..models import ReportDefinition

# 浅色弹窗样式（覆盖系统深色主题）
_LIGHT_DIALOG_STYLE = """
    QMessageBox, QInputDialog, QDialog {
        background-color: #FAFAFA; color: #333333;
    }
    QLabel { color: #333333; font-size: 13px; }
    QLineEdit {
        border: 1px solid #D9D9D9; border-radius: 4px;
        padding: 6px 10px; font-size: 13px; background: #FFFFFF; color: #333333;
    }
    QLineEdit:focus { border-color: #FF8C00; }
    QPushButton {
        background-color: #FFFFFF; color: #333333;
        border: 1px solid #D9D9D9; border-radius: 4px;
        padding: 6px 20px; font-size: 13px; min-width: 80px;
    }
    QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
"""

# 操作按钮样式
_ACTION_BTN_STYLE = """
    QPushButton {
        border: 1px solid #D9D9D9; border-radius: 3px;
        padding: 2px 0px; font-size: 12px; background: #FFFFFF; color: #333;
    }
    QPushButton:hover { border-color: #FF8C00; color: #FF8C00; background-color: #FFF7E6; }
"""

_ACTION_DELETE_STYLE = """
    QPushButton {
        border: 1px solid #FFCCC7; border-radius: 3px;
        padding: 2px 0px; font-size: 12px; background: #FFFFFF; color: #FF4D4F;
    }
    QPushButton:hover { background-color: #FFF1F0; border-color: #FF4D4F; }
"""


def _light_msgbox(parent, icon, title, text):
    """显示浅色背景的消息弹窗。"""
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(icon)
    msg.setStyleSheet(_LIGHT_DIALOG_STYLE)
    return msg.exec()


def _light_confirm(parent, title, text):
    """显示浅色背景的是/否确认弹窗。"""
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg.setStyleSheet(_LIGHT_DIALOG_STYLE)
    return msg.exec()


def _light_input(parent, title, label, text=''):
    """显示浅色背景的输入弹窗。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(360)
    dlg.setStyleSheet(_LIGHT_DIALOG_STYLE)
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel(label))
    edit = QLineEdit(text)
    layout.addWidget(edit)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return edit.text().strip(), True
    return '', False


class ActionButtonDelegate(QStyledItemDelegate):
    """在表格单元格内绘制操作按钮（编辑/复制/移动/删除），保证不溢出。"""

    BTN_W, BTN_H, GAP, MARGIN = 42, 24, 3, 4
    BTN_TEXTS = ["编辑", "复制", "移动", "删除"]
    BTN_COLORS = [
        (QColor("#333333"), QColor("#FFFFFF"), QColor("#D9D9D9")),       # 编辑: 灰色边框
        (QColor("#333333"), QColor("#FFFFFF"), QColor("#D9D9D9")),       # 复制: 灰色边框
        (QColor("#333333"), QColor("#FFFFFF"), QColor("#D9D9D9")),       # 移动: 灰色边框
        (QColor("#FF4D4F"), QColor("#FFFFFF"), QColor("#FFCCC7")),       # 删除: 红色
    ]
    BTN_HOVER_BG = QColor("#FFF7E6")
    BTN_HOVER_BORDER = QColor("#FF8C00")
    DELETE_HOVER_BG = QColor("#FFF1F0")

    # 信号：按钮被点击 → (action_index, report_id)
    buttonClicked = pyqtSignal(int, str)  # action: 0=编辑, 1=复制, 2=移动, 3=删除

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """绘制按钮"""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cell_rect = option.rect
        # 计算总宽度和起始 x（水平居中）
        total_w = self.MARGIN * 2 + self.BTN_W * 4 + self.GAP * 3
        start_x = cell_rect.x() + max(0, (cell_rect.width() - total_w) // 2)

        # 如果单元格太窄，按钮靠左
        if start_x < cell_rect.x():
            start_x = cell_rect.x()

        y = cell_rect.y() + (cell_rect.height() - self.BTN_H) // 2

        for i in range(4):
            bx = start_x + self.MARGIN + i * (self.BTN_W + self.GAP)
            btn_rect = QRect(bx, y, self.BTN_W, self.BTN_H)

            # 检查是否在可见区域内
            if btn_rect.right() > cell_rect.right():
                btn_rect.setRight(cell_rect.right() - 1)
            if btn_rect.width() < 10:
                break

            text_color, bg_color, border_color = self.BTN_COLORS[i]

            # 背景
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg_color)
            painter.drawRoundedRect(btn_rect, 3, 3)

            # 边框
            pen = QPen(border_color, 1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(btn_rect.adjusted(0, 0, -1, -1), 3, 3)

            # 文字
            painter.setPen(text_color)
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, self.BTN_TEXTS[i])

        painter.restore()

    def editorEvent(self, event, model, option, index):
        """处理鼠标点击"""
        if event.type() not in (event.Type.MouseButtonPress,):
            return False

        cell_rect = option.rect
        total_w = self.MARGIN * 2 + self.BTN_W * 4 + self.GAP * 3
        start_x = cell_rect.x() + max(0, (cell_rect.width() - total_w) // 2)
        if start_x < cell_rect.x():
            start_x = cell_rect.x()

        pos = event.pos()
        click_x = pos.x()
        click_y = pos.y()
        y = cell_rect.y() + (cell_rect.height() - self.BTN_H) // 2

        for i in range(4):
            bx = start_x + self.MARGIN + i * (self.BTN_W + self.GAP)
            if bx + self.BTN_W > cell_rect.right():
                bx = cell_rect.right() - self.BTN_W
            btn_rect = QRect(bx, y, self.BTN_W, self.BTN_H)

            if btn_rect.contains(click_x, click_y):
                rid = index.data(Qt.ItemDataRole.UserRole) or ""
                self.buttonClicked.emit(i, rid)
                return True

        return False

    def sizeHint(self, option, index):
        """建议尺寸"""
        total_w = self.MARGIN * 2 + self.BTN_W * 4 + self.GAP * 3
        return QSize(total_w + 6, 34)


class _FolderTree(QTreeWidget):
    """支持拖放报表的文件夹树"""

    dropRequested = pyqtSignal(str, str)  # report_id, folder_path

    def __init__(self, parent=None):
        super().__init__(parent)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            # 高亮悬停的文件夹节点
            item = self.itemAt(event.position().toPoint())
            if item:
                self.setCurrentItem(item)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasText():
            event.ignore()
            return
        report_id = event.mimeData().text()
        item = self.itemAt(event.position().toPoint())
        if item:
            folder_path = item.data(0, Qt.ItemDataRole.UserRole) or ""
            if folder_path == "__root__":
                folder_path = ""
            self.dropRequested.emit(report_id, folder_path)
        event.acceptProposedAction()


class ReportListPage(QWidget):
    """报表列表页面"""

    # 信号
    reportSelected = pyqtSignal(str)         # report_id
    reportEdit = pyqtSignal(str)             # report_id
    newReport = pyqtSignal()                 # 新建空白报表
    newReportWithMain = pyqtSignal(str)      # 新建并指定主表 (api_name)
    newReportInFolder = pyqtSignal(str)      # 新建报表到指定文件夹 (folder_path)

    def __init__(self, repo: ReportRepository = None, parent=None,
                 save_config_fn=None, load_config_fn=None):
        super().__init__(parent)
        self._repo = repo or ReportRepository()
        self._all_reports: list[ReportDefinition] = []
        self._current_page = 1
        self._page_size = 20
        self._save_config_fn = save_config_fn
        self._load_config_fn = load_config_fn
        self._col_widths_loaded = False
        self._object_name_map: dict[str, str] = {}  # {api_name: chinese_name}
        self._current_folder = "__root__"  # 当前选中的文件夹路径
        self._folder_data: list[dict] = []  # 文件夹树缓存

        self._setup_ui()

    def set_object_name_map(self, name_map: dict[str, str]):
        """设置对象 API 名 → 中文名的映射（用于主表列显示）。"""
        self._object_name_map = name_map or {}

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题组
        group = QGroupBox("自定义报表")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(15, 10, 15, 10)
        group_layout.setSpacing(8)

        # === 操作行 ===
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索报表名称...")
        self._search_input.setFixedHeight(30)
        self._search_input.setStyleSheet("""
            QLineEdit { border: 1px solid #8a8a8a; border-radius: 4px;
                        padding: 4px 12px; background: #FFFFFF; }
            QLineEdit:hover { border-color: #5f5f5f; }
        """)
        self._search_input.textChanged.connect(self._on_search)
        action_row.addWidget(self._search_input)

        refresh_btn = QPushButton("⟳ 刷新")
        refresh_btn.setFixedSize(80, 30)
        refresh_btn.clicked.connect(self.refresh)
        action_row.addWidget(refresh_btn)

        import_btn = QPushButton("📥 导入报表")
        import_btn.setFixedHeight(30)
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.setStyleSheet("""
            QPushButton { background-color: #FFFFFF; color: #333; border: 1px solid #D9D9D9;
                          border-radius: 4px; padding: 4px 14px; font-size: 13px; }
            QPushButton:hover { border-color: #52C41A; color: #52C41A; }
        """)
        import_btn.clicked.connect(self._import_report)
        action_row.addWidget(import_btn)

        action_row.addStretch()

        new_btn = QPushButton("+ 新建报表")
        new_btn.setFixedHeight(30)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet("""
            QPushButton { background-color: #FF8C00; color: #FFFFFF; border: none;
                          border-radius: 4px; padding: 4px 16px;
                          font-size: 14px; font-weight: bold; }
            QPushButton:hover { background-color: #E67E00; }
        """)
        new_btn.clicked.connect(self._on_new_report)
        action_row.addWidget(new_btn)

        group_layout.addLayout(action_row)

        # === 左右分栏：文件夹树 + 报表表格 ===
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background-color: #E0E0E0; }")

        # ---- 左侧：文件夹树 ----
        folder_panel = QFrame()
        folder_panel.setMinimumWidth(160)
        folder_panel.setStyleSheet("""
            QFrame { background-color: #FAFAFA; border-right: 1px solid #E0E0E0; }
        """)
        folder_layout = QVBoxLayout(folder_panel)
        folder_layout.setContentsMargins(8, 6, 4, 6)
        folder_layout.setSpacing(4)

        folder_header = QLabel("📁 文件夹")
        folder_header.setStyleSheet("font-weight: 600; font-size: 13px; color: #333; padding: 4px 0;")
        folder_layout.addWidget(folder_header)

        self._folder_tree = _FolderTree()
        self._folder_tree.setHeaderHidden(True)
        self._folder_tree.setIndentation(16)
        self._folder_tree.setAnimated(True)
        self._folder_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._folder_tree.customContextMenuRequested.connect(self._on_folder_context_menu)
        self._folder_tree.currentItemChanged.connect(self._on_folder_selected)
        self._folder_tree.dropRequested.connect(self._on_tree_drop)
        self._folder_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #FFFFFF; border: 1px solid #E0E0E0;
                border-radius: 4px; font-size: 13px; color: #333;
            }
            QTreeWidget::item { padding: 6px 4px; }
            QTreeWidget::item:hover { background-color: #FFF7E6; }
            QTreeWidget::item:selected { background-color: #FFF7E6; color: #FF8C00; }
        """)
        folder_layout.addWidget(self._folder_tree, 1)

        # 新建文件夹按钮
        new_folder_btn = QPushButton("+ 新建文件夹")
        new_folder_btn.setFixedHeight(28)
        new_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_folder_btn.setStyleSheet("""
            QPushButton { background-color: #FFFFFF; color: #555; border: 1px dashed #D9D9D9;
                          border-radius: 4px; padding: 4px 12px; font-size: 12px; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        new_folder_btn.clicked.connect(self._on_new_folder)
        folder_layout.addWidget(new_folder_btn)

        splitter.addWidget(folder_panel)

        # ---- 右侧：报表表格 + 分页 ----
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # 当前文件夹标题
        self._current_folder_label = QLabel("全部报表")
        self._current_folder_label.setStyleSheet("""
            font-size: 14px; font-weight: 600; color: #FF8C00; padding: 4px 0;
        """)
        right_layout.addWidget(self._current_folder_label)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "报表名称", "主表", "报表说明", "字段数", "结果记录数", "修改时间", "状态", "操作"
        ])
        for c in range(8):
            hdr = self._table.horizontalHeaderItem(c)
            if hdr:
                hdr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        self._table.cellClicked.connect(self._on_cell_click)
        self._table.setStyleSheet("""
            QTableWidget {
                gridline-color: #F0F0F0; background-color: #FFFFFF;
                border: 1px solid #E0E0E0; border-radius: 4px; font-size: 13px;
            }
            QTableWidget::item { padding: 10px 12px; border-bottom: 1px solid #F0F0F0; }
            QTableWidget::item:selected { background-color: #FFF7E6; color: #333; }
            QHeaderView::section {
                background-color: #FAFAFA; color: #333; padding: 10px 12px;
                border: none; border-bottom: 2px solid #E0E0E0; font-weight: 500;
            }
            QToolTip {
                background-color: #FFF7E6; color: #333; border: 1px solid #FF8C00;
                border-radius: 3px; padding: 4px 8px; font-size: 12px;
            }
        """)

        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(20)
        header.sectionResized.connect(self._on_column_resized)
        for c in range(8):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(0, 200)
        self._table.setColumnWidth(1, 100)
        self._table.setColumnWidth(2, 200)
        self._table.setColumnWidth(3, 60)
        self._table.setColumnWidth(4, 85)
        self._table.setColumnWidth(5, 140)
        self._table.setColumnWidth(6, 65)
        self._table.setColumnWidth(7, 25)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._col_resize_timer = QTimer()
        self._col_resize_timer.setSingleShot(True)
        self._col_resize_timer.setInterval(400)
        self._col_resize_timer.timeout.connect(self._save_column_widths)

        right_layout.addWidget(self._table, 1)

        # 分页
        page_row = QHBoxLayout()
        self._record_label = QLabel("共 0 条记录")
        self._record_label.setStyleSheet("font-weight: bold; color: #555;")
        page_row.addWidget(self._record_label)

        page_row.addStretch()

        page_row.addWidget(QLabel("每页:"))
        self._page_combo = QComboBox()
        self._page_combo.addItems(["20", "50", "80", "100"])
        self._page_combo.setCurrentText("20")
        self._page_combo.currentTextChanged.connect(self._on_page_size_changed)
        page_row.addWidget(self._page_combo)

        self._prev_btn = QPushButton("<")
        self._prev_btn.setFixedWidth(30)
        self._prev_btn.clicked.connect(self._prev_page)
        page_row.addWidget(self._prev_btn)

        self._page_label = QLabel("1/1")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setStyleSheet("font-weight: bold; color: #333;")
        page_row.addWidget(self._page_label)

        self._next_btn = QPushButton(">")
        self._next_btn.setFixedWidth(30)
        self._next_btn.clicked.connect(self._next_page)
        page_row.addWidget(self._next_btn)

        right_layout.addLayout(page_row)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)  # 文件夹面板不拉伸
        splitter.setStretchFactor(1, 1)  # 右侧表格拉伸
        splitter.setSizes([200, 600])     # 初始宽度：文件夹 200px，表格 600px
        group_layout.addWidget(splitter, 1)

        layout.addWidget(group, 1)

        # 初始化
        self.refresh()

    # ==================== 数据 ====================

    def refresh(self):
        """刷新列表和文件夹树"""
        # 刷新文件夹树
        self._folder_data = self._repo.list_folders()
        self._rebuild_folder_tree()

        # 刷新表格
        search = self._search_input.text().strip() or None
        if self._current_folder and self._current_folder != "__root__":
            self._all_reports = self._repo.list_by_folder(self._current_folder, search=search)
        else:
            self._all_reports = self._repo.list_all(search=search)
        self._current_page = 1
        self._populate()
        if not self._col_widths_loaded:
            self._load_column_widths()
            self._col_widths_loaded = True

    def _rebuild_folder_tree(self):
        """根据 _folder_data 重建文件夹树"""
        self._folder_tree.blockSignals(True)
        self._folder_tree.clear()

        def _add_nodes(parent, children):
            for item_data in children:
                node = QTreeWidgetItem(parent)
                node.setText(0, f"📁 {item_data['name']} ({item_data['count']})")
                node.setData(0, Qt.ItemDataRole.UserRole, item_data['path'])
                node.setToolTip(0, item_data['path'])
                if item_data.get('children'):
                    _add_nodes(node, item_data['children'])
                node.setExpanded(True)

        if self._folder_data:
            for root_item in self._folder_data:
                root_node = QTreeWidgetItem(self._folder_tree)
                root_node.setText(0, f"📂 {root_item['name']} ({root_item['count']})")
                root_node.setData(0, Qt.ItemDataRole.UserRole, root_item['path'])
                root_node.setToolTip(0, root_item['path'])
                root_node.setExpanded(True)
                if root_item.get('children'):
                    _add_nodes(root_node, root_item['children'])
                # 默认选中第一个（全部报表）
                if root_item['path'] == "__root__":
                    self._folder_tree.setCurrentItem(root_node)

        self._folder_tree.blockSignals(False)

    def _populate(self):
        """填充表格"""
        total = len(self._all_reports)
        page_count = max(1, (total + self._page_size - 1) // self._page_size)
        self._current_page = max(1, min(self._current_page, page_count))

        start = (self._current_page - 1) * self._page_size
        page_data = self._all_reports[start:start + self._page_size]

        def _item(text):
            it = QTableWidgetItem(str(text) if text else "")
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            return it

        self._table.setRowCount(len(page_data))
        for row, rpt in enumerate(page_data):
            self._table.setItem(row, 0, _item(rpt.name))

            # 主表中文名（优先映射名，其次 API 名）
            main_name = self._object_name_map.get(rpt.main_object_api, rpt.main_object_api)
            self._table.setItem(row, 1, _item(main_name))

            # 报表说明：由主表 + JOIN 表拼接而成
            obj_apis = rpt.get_object_apis() if hasattr(rpt, 'get_object_apis') else ([rpt.main_object_api] if rpt.main_object_api else [])
            obj_names = [self._object_name_map.get(api, api) for api in obj_apis if api]
            description = " + ".join(obj_names) if obj_names else main_name
            self._table.setItem(row, 2, _item(description))

            # 字段数
            col_count = len(rpt.columns)
            self._table.setItem(row, 3, _item(str(col_count)))

            # 结果记录数
            row_count_str = str(rpt.result_row_count) if rpt.result_row_count else "-"
            self._table.setItem(row, 4, _item(row_count_str))

            # 修改时间
            self._table.setItem(row, 5, _item(rpt.modified_at or rpt.created_at or ""))

            # 状态
            status = "已生成" if rpt.result_row_count > 0 else "未生成"
            self._table.setItem(row, 6, _item(status))

            # === 操作列：纯文本标记，点击触发菜单 ===
            action_item = QTableWidgetItem("⋮")
            action_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            action_item.setData(Qt.ItemDataRole.UserRole, rpt.id)
            action_item.setToolTip("点击查看操作")
            # 操作列文字样式
            font = action_item.font()
            font.setPointSize(14)
            font.setBold(True)
            action_item.setFont(font)
            action_item.setForeground(QColor("#FF8C00"))
            self._table.setItem(row, 7, action_item)
            self._table.setRowHeight(row, 34)

            # 存储 report_id 到首列 UserRole
            name_item = self._table.item(row, 0)
            if name_item:
                name_item.setData(Qt.ItemDataRole.UserRole, rpt.id)

        self._record_label.setText(f"共 {total} 条记录")
        self._page_label.setText(f"{self._current_page}/{page_count}")
        self._prev_btn.setEnabled(self._current_page > 1)
        self._next_btn.setEnabled(self._current_page < page_count)

    def _get_selected_report_id(self) -> str:
        """获取当前选中行的 report id"""
        row = self._table.currentRow()
        if row < 0:
            return ""
        item = self._table.item(row, 0)
        if item:
            rid = item.data(Qt.ItemDataRole.UserRole)
            if rid:
                return rid
        start = (self._current_page - 1) * self._page_size
        idx = start + row
        if idx < len(self._all_reports):
            return self._all_reports[idx].id
        return ""

    # ==================== 文件夹交互 ====================

    def _on_folder_selected(self, current, previous):
        """点击文件夹节点，筛选右侧表格"""
        if not current:
            return
        folder_path = current.data(0, Qt.ItemDataRole.UserRole)
        self._current_folder = folder_path or "__root__"

        # 更新标题
        if folder_path == "__root__":
            self._current_folder_label.setText("全部报表")
        else:
            self._current_folder_label.setText(f"📁 {folder_path.replace('/', ' › ')}")

        # 刷新表格
        search = self._search_input.text().strip() or None
        if self._current_folder and self._current_folder != "__root__":
            self._all_reports = self._repo.list_by_folder(self._current_folder, search=search)
        else:
            self._all_reports = self._repo.list_all(search=search)
        self._current_page = 1
        self._populate()

    def _on_folder_context_menu(self, pos):
        """文件夹右键菜单"""
        item = self._folder_tree.itemAt(pos)
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #FFFFFF; color: #333333; border: 1px solid #D9D9D9; border-radius: 4px; padding: 4px 0; }
            QMenu::item { padding: 8px 24px; font-size: 13px; background-color: #FFFFFF; color: #333333; }
            QMenu::item:selected { background-color: #FFF7E6; color: #FF8C00; }
            QMenu::separator { height: 1px; background: #F0F0F0; margin: 4px 12px; }
        """)

        new_sub_action = menu.addAction("📁 新建子文件夹")
        new_sub_action.triggered.connect(lambda: self._on_new_folder(item))

        if item:
            folder_path = item.data(0, Qt.ItemDataRole.UserRole)

            new_report_action = menu.addAction("📊 在此新建报表")
            new_report_action.triggered.connect(lambda: self._on_new_report_in_folder(folder_path))

            menu.addSeparator()

            if folder_path != "__root__":
                rename_action = menu.addAction("✏ 重命名文件夹")
                rename_action.triggered.connect(lambda: self._on_rename_folder(folder_path))

                menu.addSeparator()
                delete_action = menu.addAction("🗑 删除文件夹")
                delete_action.triggered.connect(lambda: self._on_delete_folder(folder_path))

        menu.exec(self._folder_tree.mapToGlobal(pos))

    def _on_new_folder(self, parent_item=None):
        """新建文件夹"""
        parent_path = ""
        if parent_item:
            parent_path = parent_item.data(0, Qt.ItemDataRole.UserRole) or ""
            if parent_path == "__root__":
                parent_path = ""

        name, ok = _light_input(self, "新建文件夹", "请输入文件夹名称:")
        if not ok or not name.strip():
            return

        folder_path = (parent_path + "/" + name.strip()) if parent_path else name.strip()

        # 检查是否已存在
        existing = self._repo.list_folders()

        def _path_exists(tree, target):
            for node in tree:
                if node.get('path') == target:
                    return True
                if node.get('children') and _path_exists(node['children'], target):
                    return True
            return False

        if _path_exists(existing, folder_path):
            _light_msgbox(self, QMessageBox.Icon.Warning, "提示", f"文件夹 \"{folder_path}\" 已存在。")
            return

        # 持久化创建空文件夹
        success = self._repo.create_folder(folder_path)
        if success:
            self.refresh()
        else:
            _light_msgbox(self, QMessageBox.Icon.Warning, "提示", f"文件夹 \"{name.strip()}\" 已存在。")

    def _on_new_report_in_folder(self, folder_path: str):
        """在指定文件夹中新建报表"""
        self.newReportInFolder.emit(folder_path if folder_path != "__root__" else "")

    def _on_rename_folder(self, old_path: str):
        """重命名文件夹"""
        if not old_path or old_path == "__root__":
            return
        current_name = old_path.split("/")[-1]
        new_name, ok = _light_input(self, "重命名文件夹", "请输入新名称:", text=current_name)
        if not ok or not new_name.strip() or new_name.strip() == current_name:
            return

        # 构建新路径
        parts = old_path.split("/")
        parts[-1] = new_name.strip()
        new_path = "/".join(parts)

        count = self._repo.rename_folder(old_path, new_path)
        if count >= 0:
            self.refresh()
            _light_msgbox(self, QMessageBox.Icon.Information, "重命名成功",
                                    f"已更新 {count} 个报表的文件夹路径。")

    def _on_delete_folder(self, folder_path: str):
        """删除文件夹"""
        if not folder_path or folder_path == "__root__":
            return

        reply = _light_confirm(self, "确认删除",
            f"确定要删除文件夹 \"{folder_path}\" 吗？\n\n"
            f"选择「是」：文件夹下的报表将移到根目录。\n"
            f"选择「否」：取消操作。")
        if reply != QMessageBox.StandardButton.Yes:
            return

        count = self._repo.delete_folder(folder_path, delete_reports=False)
        self._current_folder = "__root__"
        self.refresh()
        _light_msgbox(self, QMessageBox.Icon.Information, "删除成功",
                                f"文件夹已删除，{count} 个报表已移至根目录。")

    # ==================== 交互 ====================

    def _on_search(self, text):
        self.refresh()

    def _on_page_size_changed(self, text):
        try:
            self._page_size = int(text)
        except ValueError:
            self._page_size = 20
        self._current_page = 1
        self._populate()

    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._populate()

    def _next_page(self):
        total = len(self._all_reports)
        page_count = max(1, (total + self._page_size - 1) // self._page_size)
        if self._current_page < page_count:
            self._current_page += 1
            self._populate()

    def _on_double_click(self, row, col):
        """双击打开编辑（操作列不触发）"""
        if col == 7:
            return
        start = (self._current_page - 1) * self._page_size
        idx = start + row
        if 0 <= idx < len(self._all_reports):
            self.reportEdit.emit(self._all_reports[idx].id)

    def _on_cell_click(self, row, col):
        """单击操作列弹出菜单"""
        if col != 7:
            return
        item = self._table.item(row, 7)
        if not item:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return
        # 在单元格位置弹出操作菜单
        menu = QMenu(self._table)
        menu.setStyleSheet("""
            QMenu { background-color: #FFFFFF; color: #333; border: 1px solid #D9D9D9; border-radius: 4px; padding: 4px 0; }
            QMenu::item { padding: 8px 24px; font-size: 13px; background-color: #FFFFFF; color: #333; }
            QMenu::item:selected { background-color: #FFF7E6; color: #FF8C00; }
            QMenu::separator { height: 1px; background: #F0F0F0; margin: 4px 12px; }
        """)
        menu.addAction("编辑", lambda r=rid: self.reportEdit.emit(r))
        menu.addAction("复制", lambda r=rid: self._copy_report(r))
        menu.addSeparator()
        move_menu = menu.addMenu("移动到文件夹")
        move_menu.setStyleSheet(menu.styleSheet())
        move_menu.addAction("📂 根目录", lambda r=rid: self._move_report_to_folder(r, ""))
        # 填充文件夹
        folders = self._repo.list_folders()
        def _add_dirs(parent_menu, children):
            for node in children:
                np = node['path']
                if np == "__root__":
                    if node.get('children'):
                        _add_dirs(parent_menu, node['children'])
                    continue
                parent_menu.addAction(f"📁 {node['name']}", lambda r=rid, p=np: self._move_report_to_folder(r, p))
                if node.get('children'):
                    sub = parent_menu.addMenu(node['name'])
                    sub.setStyleSheet(parent_menu.styleSheet())
                    _add_dirs(sub, node['children'])
        if folders:
            for root_node in folders:
                if root_node.get('children'):
                    _add_dirs(move_menu, root_node['children'])
        menu.addSeparator()
        menu.addAction("删除", lambda r=rid: self._delete_report(r))
        # 在点击位置弹出
        cell_rect = self._table.visualRect(self._table.model().index(row, 7))
        menu.exec(self._table.viewport().mapToGlobal(cell_rect.center()))

    def _on_new_report(self):
        """新建报表 → 直接进入编辑器"""
        self.newReport.emit()

    def _import_report(self):
        """从 .crpt 文件导入报表"""
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "导入报表定义", "",
            "报表定义文件 (*.crpt *.json);;所有文件 (*)"
        )
        if not path:
            return

        try:
            import json
            import uuid
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not data.get('name'):
                _light_msgbox(self, QMessageBox.Icon.Warning, "导入失败", "无效的报表定义文件：缺少名称。")
                return

            data['id'] = uuid.uuid4().hex[:12]
            orig_name = data['name']
            data['name'] = orig_name + " (导入)"
            data.pop('result_table_name', None)
            data.pop('result_row_count', None)
            data.pop('last_refresh_time', None)
            data.pop('created_at', None)
            data.pop('modified_at', None)

            report = ReportDefinition.from_dict(data)
            self._repo.save(report)
            self.refresh()
            _light_msgbox(self, QMessageBox.Icon.Information, "导入成功",
                                    f"报表 \"{report.name}\" 已导入。\n请打开编辑页面配置数据源。")
        except Exception as e:
            _light_msgbox(self, QMessageBox.Icon.Warning, "导入失败", str(e))

    def _on_context_menu(self, pos):
        """右键菜单"""
        rid = self._get_selected_report_id()
        if not rid:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #FFFFFF; color: #333333; border: 1px solid #D9D9D9; border-radius: 4px; padding: 4px 0; }
            QMenu::item { padding: 8px 24px; font-size: 13px; background-color: #FFFFFF; color: #333333; }
            QMenu::item:selected { background-color: #FFF7E6; color: #FF8C00; }
            QMenu::separator { height: 1px; background: #F0F0F0; margin: 4px 12px; }
        """)
        edit_action = menu.addAction("编辑")
        edit_action.triggered.connect(lambda: self.reportEdit.emit(rid))

        copy_action = menu.addAction("复制")
        copy_action.triggered.connect(lambda: self._copy_report(rid))

        export_action = menu.addAction("导出")
        export_action.triggered.connect(lambda: self._export_report(rid))

        rename_action = menu.addAction("重命名")
        rename_action.triggered.connect(lambda: self._rename_report(rid))

        # 移动到文件夹子菜单
        menu.addSeparator()
        move_menu = menu.addMenu("移动到文件夹")
        move_menu.setStyleSheet(menu.styleSheet())

        root_action = move_menu.addAction("📂 根目录")
        root_action.triggered.connect(lambda checked, r=rid: self._move_report_to_folder(r, ""))

        # 列出文件夹
        folders = self._repo.list_folders()

        def _add_folder_actions(parent_menu, children, indent=0):
            for node in children:
                node_path = node['path']
                if node_path == "__root__":
                    if node.get('children'):
                        _add_folder_actions(parent_menu, node['children'], indent)
                    continue
                prefix = "  " * indent + "📁 "
                action = parent_menu.addAction(f"{prefix}{node['name']} ({node['count']})")
                action.triggered.connect(lambda checked, r=rid, p=node_path: self._move_report_to_folder(r, p))
                if node.get('children'):
                    _add_folder_actions(parent_menu, node['children'], indent + 1)

        if folders:
            for root_node in folders:
                if root_node.get('children'):
                    _add_folder_actions(move_menu, root_node['children'])

        menu.addSeparator()
        delete_action = menu.addAction("删除")
        delete_action.triggered.connect(lambda: self._delete_report(rid))

        menu.exec(self._table.mapToGlobal(pos))

    def _on_action_clicked(self, action: int, rid: str):
        """操作列按钮点击分发。action: 0=编辑, 1=复制, 2=移动, 3=删除"""
        if not rid:
            return
        if action == 0:
            self.reportEdit.emit(rid)
        elif action == 1:
            self._copy_report(rid)
        elif action == 2:
            self._show_move_menu_at_cell(rid)
        elif action == 3:
            self._delete_report(rid)

    def _show_move_menu_at_cell(self, rid: str):
        """在操作列位置弹出移动菜单"""
        # 尝试定位到当前选中的行
        row = self._table.currentRow()
        col_rect = self._table.visualRect(self._table.model().index(row, 7)) if row >= 0 else QRect()
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #FFFFFF; color: #333333; border: 1px solid #D9D9D9; border-radius: 4px; padding: 4px 0; }
            QMenu::item { padding: 8px 24px; font-size: 13px; background-color: #FFFFFF; color: #333333; }
            QMenu::item:selected { background-color: #FFF7E6; color: #FF8C00; }
            QMenu::separator { height: 1px; background: #F0F0F0; margin: 4px 12px; }
        """)
        self._build_move_menu(menu, rid)
        pos = self._table.viewport().mapToGlobal(col_rect.bottomLeft()) if col_rect.isValid() else self._table.viewport().mapToGlobal(QPoint(10, 10))
        menu.exec(pos)

    def _show_move_menu(self, rid: str, anchor_btn):
        """弹出移动菜单（由外部按钮调用，保留兼容）"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #FFFFFF; color: #333333; border: 1px solid #D9D9D9; border-radius: 4px; padding: 4px 0; }
            QMenu::item { padding: 8px 24px; font-size: 13px; background-color: #FFFFFF; color: #333333; }
            QMenu::item:selected { background-color: #FFF7E6; color: #FF8C00; }
            QMenu::separator { height: 1px; background: #F0F0F0; margin: 4px 12px; }
        """)
        self._build_move_menu(menu, rid)
        if anchor_btn:
            menu.exec(anchor_btn.mapToGlobal(anchor_btn.rect().bottomLeft()))
        else:
            menu.exec(self._table.viewport().mapToGlobal(QPoint(10, 10)))

    def _build_move_menu(self, menu: QMenu, rid: str):
        """构建移动菜单的文件夹选项"""
        root_action = menu.addAction("📂 根目录")
        root_action.triggered.connect(lambda checked, r=rid: self._move_report_to_folder(r, ""))

        folders = self._repo.list_folders()

        def _add_folder_actions(parent_menu, children):
            for node in children:
                node_path = node['path']
                if node_path == "__root__":
                    if node.get('children'):
                        _add_folder_actions(parent_menu, node['children'])
                    continue
                action = parent_menu.addAction(f"📁 {node['name']} ({node['count']})")
                # 使用默认参数捕获当前值，避免闭包延迟绑定
                action.triggered.connect(lambda checked, r=rid, p=node_path: self._move_report_to_folder(r, p))
                if node.get('children'):
                    sub = parent_menu.addMenu(f"  {node['name']} ▸")
                    sub.setStyleSheet(parent_menu.styleSheet())
                    _add_folder_actions(sub, node['children'])

        if folders:
            menu.addSeparator()
            for root_node in folders:
                if root_node.get('children'):
                    _add_folder_actions(menu, root_node['children'])

    def _on_tree_drop(self, report_id: str, folder_path: str):
        """拖放报表到文件夹树"""
        self._move_report_to_folder(report_id, folder_path)

    def _move_report_to_folder(self, rid: str, folder_path: str):
        """移动报表到指定文件夹"""
        if self._repo.move_to_folder(rid, folder_path):
            self.refresh()
            target = folder_path if folder_path else "根目录"
            self._current_folder_label.setText(f"📁 {target.replace('/', ' › ')}" if folder_path else "全部报表")

    def _copy_report(self, rid: str):
        name, ok = _light_input(self, "复制报表", "请输入新报表名称:")
        if ok and name.strip():
            new_rpt = self._repo.duplicate(rid, name.strip())
            if new_rpt:
                self.refresh()

    def _export_report(self, rid: str):
        """导出报表定义为 .crpt 文件"""
        report = self._repo.get(rid)
        if not report:
            return
        from PyQt6.QtWidgets import QFileDialog
        import json
        path, _ = QFileDialog.getSaveFileName(
            self, "导出报表定义", f"{report.name}.crpt",
            "报表定义文件 (*.crpt);;JSON 文件 (*.json)"
        )
        if not path:
            return
        try:
            data = report.to_dict()
            data.pop('result_table_name', None)
            data.pop('result_row_count', None)
            data.pop('last_refresh_time', None)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _light_msgbox(self, QMessageBox.Icon.Information, "导出成功", f"报表定义已导出到:\n{path}")
        except Exception as e:
            _light_msgbox(self, QMessageBox.Icon.Warning, "导出失败", str(e))

    def _rename_report(self, rid: str):
        rpt = self._repo.get(rid)
        if not rpt:
            return
        name, ok = _light_input(self, "重命名", "请输入新名称:", text=rpt.name)
        if ok and name.strip():
            rpt.name = name.strip()
            self._repo.save(rpt)
            self.refresh()

    def _delete_report(self, rid: str):
        rpt = self._repo.get(rid)
        if not rpt:
            return
        reply = _light_confirm(self, "确认删除",
            f"确定要删除报表 \"{rpt.name}\" 吗？\n此操作不可恢复。")
        if reply == QMessageBox.StandardButton.Yes:
            self._repo.delete(rid)
            self.refresh()

    # ==================== 列宽持久化 ====================

    def _on_column_resized(self, col_idx: int, old_width: int, new_width: int):
        """用户拖拽列宽后防抖保存到个人配置文件"""
        if not self._save_config_fn:
            return
        if hasattr(self, '_col_resize_timer') and self._col_resize_timer is not None:
            self._col_resize_timer.start()

    def _save_column_widths(self):
        """将当前列宽写入个人配置文件"""
        if not self._save_config_fn:
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
            cr['list_column_widths'] = widths
            self._save_config_fn(cfg)
        except Exception:
            pass

    def _load_column_widths(self):
        """从个人配置文件恢复已保存的列宽"""
        if not self._load_config_fn:
            return
        try:
            cfg = self._load_config_fn()
            if not isinstance(cfg, dict):
                return
            cr = cfg.get('custom_reports', {})
            if not isinstance(cr, dict):
                return
            widths = cr.get('list_column_widths', {})
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
