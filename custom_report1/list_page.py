# -*- coding: utf-8 -*-
"""报表列表页"""

import sys
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QComboBox, QAbstractItemView, QMenu, QMessageBox,
)
from PyQt6.QtGui import QFont, QColor, QAction

from .constants import DEFAULT_PAGE_SIZES


class ReportListPage(QWidget):
    """报表预设列表页。

    信号:
        reportEdit(str): 双击/编辑报表时发射，携带报表 ID
        newReport(): 点击"新建报表"时发射
    """

    reportEdit = pyqtSignal(str)
    newReport = pyqtSignal()

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self._store = store
        self._presets = []
        self._filtered_presets = []
        self._current_page = 1
        self._page_size = DEFAULT_PAGE_SIZES[0] if DEFAULT_PAGE_SIZES else 20

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 标题栏
        title_layout = QHBoxLayout()
        title_label = QLabel("📊 自定义报表")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索报表名称...")
        self._search_edit.setMinimumWidth(200)
        toolbar.addWidget(self._search_edit)

        toolbar.addStretch()

        self._new_btn = QPushButton("＋ 新建报表")
        self._new_btn.setStyleSheet(
            "QPushButton { background-color: #1890FF; color: white; padding: 6px 16px; "
            "border-radius: 4px; border: none; } "
            "QPushButton:hover { background-color: #40A9FF; }"
        )
        toolbar.addWidget(self._new_btn)

        self._delete_btn = QPushButton("删除")
        self._delete_btn.setStyleSheet(
            "QPushButton { padding: 6px 12px; border: 1px solid #D9D9D9; border-radius: 4px; } "
            "QPushButton:hover { border-color: #FF4D4F; color: #FF4D4F; }"
        )
        toolbar.addWidget(self._delete_btn)

        self._copy_btn = QPushButton("复制")
        self._copy_btn.setStyleSheet(
            "QPushButton { padding: 6px 12px; border: 1px solid #D9D9D9; border-radius: 4px; } "
            "QPushButton:hover { border-color: #1890FF; color: #1890FF; }"
        )
        toolbar.addWidget(self._copy_btn)

        layout.addLayout(toolbar)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["报表名称", "类型", "主数据源", "修改时间", "状态"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self._table)

        # 分页
        page_layout = QHBoxLayout()
        page_layout.addStretch()

        page_layout.addWidget(QLabel("每页:"))
        self._page_size_combo = QComboBox()
        for size in DEFAULT_PAGE_SIZES:
            self._page_size_combo.addItem(str(size), size)
        page_layout.addWidget(self._page_size_combo)

        page_layout.addSpacing(16)

        self._prev_btn = QPushButton("◀ 上一页")
        self._prev_btn.setStyleSheet(
            "QPushButton { padding: 4px 12px; border: 1px solid #D9D9D9; border-radius: 4px; } "
            "QPushButton:hover { border-color: #1890FF; } "
            "QPushButton:disabled { color: #CCCCCC; }"
        )
        page_layout.addWidget(self._prev_btn)

        self._page_label = QLabel("第 1 页 / 共 1 页")
        page_layout.addWidget(self._page_label)

        self._next_btn = QPushButton("下一页 ▶")
        self._next_btn.setStyleSheet(
            "QPushButton { padding: 4px 12px; border: 1px solid #D9D9D9; border-radius: 4px; } "
            "QPushButton:hover { border-color: #1890FF; } "
            "QPushButton:disabled { color: #CCCCCC; }"
        )
        page_layout.addWidget(self._next_btn)

        layout.addLayout(page_layout)

    def _connect_signals(self):
        self._new_btn.clicked.connect(self._on_new_report)
        self._delete_btn.clicked.connect(self._on_delete)
        self._copy_btn.clicked.connect(self._on_copy)
        self._search_edit.textChanged.connect(self._on_search)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)
        self._prev_btn.clicked.connect(self._on_prev_page)
        self._next_btn.clicked.connect(self._on_next_page)

    def refresh(self):
        """刷新列表数据。"""
        if self._store:
            filter_text = self._search_edit.text().strip() or None
            self._presets = self._store.list_presets(filter_text=filter_text)
        else:
            self._presets = []
        self._filtered_presets = list(self._presets)
        self._current_page = 1
        self._populate_table()

    def _populate_table(self):
        total = len(self._filtered_presets)
        page_count = max(1, (total + self._page_size - 1) // self._page_size)
        self._current_page = min(self._current_page, page_count)
        start = (self._current_page - 1) * self._page_size
        end = min(start + self._page_size, total)
        page_items = self._filtered_presets[start:end]

        self._table.setRowCount(len(page_items))
        for row_idx, preset in enumerate(page_items):
            name_item = QTableWidgetItem(preset.name)
            name_item.setData(Qt.ItemDataRole.UserRole, preset.key)
            self._table.setItem(row_idx, 0, name_item)

            type_display = {"report": "报表", "folder": "文件夹", "dashboard": "仪表盘"}.get(preset.type, preset.type)
            self._table.setItem(row_idx, 1, QTableWidgetItem(type_display))
            self._table.setItem(row_idx, 2, QTableWidgetItem(preset.main_source or '-'))
            self._table.setItem(row_idx, 3, QTableWidgetItem(preset.modified or '-'))
            status_display = "✓ 启用" if preset.status == 'enabled' else "✗ 禁用"
            self._table.setItem(row_idx, 4, QTableWidgetItem(status_display))

        self._update_pagination_ui(page_count)

    def _update_pagination_ui(self, page_count):
        self._page_label.setText(f"第 {self._current_page} 页 / 共 {page_count} 页")
        self._prev_btn.setEnabled(self._current_page > 1)
        self._next_btn.setEnabled(self._current_page < page_count)

    def _on_search(self, text):
        filter_text = text.strip().lower()
        if filter_text:
            self._filtered_presets = [p for p in self._presets if filter_text in p.name.lower()]
        else:
            self._filtered_presets = list(self._presets)
        self._current_page = 1
        self._populate_table()

    def _on_double_click(self, row, col):
        item = self._table.item(row, 0)
        if item:
            report_id = item.data(Qt.ItemDataRole.UserRole)
            if report_id:
                self.reportEdit.emit(report_id)

    def _on_new_report(self):
        self.newReport.emit()

    def _on_delete(self):
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        if not item:
            return
        name = item.text()
        report_id = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除报表「{name}」吗？\n此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._store:
                self._store.delete_preset(report_id or name)
            self.refresh()

    def _on_copy(self):
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        if not item:
            return
        name = item.text()
        report_id = item.data(Qt.ItemDataRole.UserRole)
        if self._store:
            config = self._store.load_preset(report_id or name)
            if config:
                new_name = f"{name} - 副本"
                self._store.save_preset(new_name, config)
                self.refresh()

    def _on_context_menu(self, pos):
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        item = self._table.item(row, 0)
        if not item:
            return
        name = item.text()
        report_id = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        edit_action = QAction("编辑", menu)
        edit_action.triggered.connect(lambda: self.reportEdit.emit(report_id or name))
        menu.addAction(edit_action)

        copy_action = QAction("复制", menu)
        copy_action.triggered.connect(self._on_copy)
        menu.addAction(copy_action)

        menu.addSeparator()

        delete_action = QAction("删除", menu)
        delete_action.triggered.connect(self._on_delete)
        menu.addAction(delete_action)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _on_page_size_changed(self):
        self._page_size = self._page_size_combo.currentData() or 20
        self._current_page = 1
        self._populate_table()

    def _on_prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._populate_table()

    def _on_next_page(self):
        total = len(self._filtered_presets)
        page_count = max(1, (total + self._page_size - 1) // self._page_size)
        if self._current_page < page_count:
            self._current_page += 1
            self._populate_table()
