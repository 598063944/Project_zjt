# -*- coding: utf-8 -*-
from core import *
from common import *

"""
file_mover.py — 文件整理移动 Mixin
──────────────────────────────────
负责：MainFrame 中文件整理页面相关方法
  - create_file_organize_page()  文件整理页面
  - on_organize_* / load_organize_*  文件扫描 / 移动 / 日期过滤
  - move_files_to_new_folders()  文件按名称分组移动
依赖：core.py / common.py
被导入：主程序（作为 MainFrame 的 Mixin 父类）
"""
"""file_mover Mixin"""

# 导入所需模块
import os

# QtWebEngine 必须在 QApplication 创建前导入
try:
    import PyQt6.QtWebEngineWidgets  # noqa: F401
except ImportError:
    pass  # 精简版打包时可能不包含 WebEngine

from pathlib import Path  # 路径处理
import copy
import builtins
from functools import lru_cache
from io import BytesIO
import logging  # 日志记录
import platform  # 操作系统平台信息
import shutil  # 文件操作
import json  # JSON处理
import subprocess  # 子进程管理
from contextlib import contextmanager
from datetime import datetime, timedelta  # 日期时间处理
from decimal import Decimal, ROUND_HALF_UP

import sys  # 系统相关
import sqlite3  # SQLite 本地缓存
import os  # 操作系统接口
import ssl
import time  # 时间
import threading  # 线程管理
import urllib.request
import email.utils
import pkgutil
import tempfile
import psutil  # 进程管理
import re  # 正则表达式
import uuid  # UUID 生成（API 配置等）
import hashlib  # 哈希算法
import certifi
import requests  # HTTP请求
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager


from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QComboBox, QLineEdit, QHeaderView, QAbstractItemView, QSpinBox,
    QMessageBox, QDialog, QTreeWidget, QFileDialog, QCheckBox, QFrame, QScrollArea,
    QGroupBox, QStackedWidget, QRadioButton, QCalendarWidget, QDateEdit, QListWidget,
    QListWidgetItem, QMenu, QSizePolicy, QInputDialog, QSplitter, QToolButton, QProgressBar,
)
from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal, QDate, QSize, QPoint
from PyQt6.QtGui import QFont, QColor, QPalette, QAction, QIcon

class file_moverMixin:
    """file_mover functionality."""

    def create_file_organize_page(self):
        """创建文件整理功能页面（页面 1）- 所有控件在一个大框内"""
        page = QFrame()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(15, 10, 20, 10)  # 增加右侧边距
        page_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # 顶部对齐，下方留白

        # 大外框：文件整理
        main_group = QGroupBox("文件移动")
        main_group.setStyleSheet(get_glass_groupbox_style())
        main_layout = QVBoxLayout(main_group)
        main_layout.setContentsMargins(10, 12, 12, 10)
        main_layout.setSpacing(8)

        directory_config = self.config.get('directory_config', {})

        top_filter_frame = QFrame()
        top_filter_layout = QVBoxLayout(top_filter_frame)
        top_filter_layout.setContentsMargins(2, 2, 2, 2)
        top_filter_layout.setSpacing(6)

        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(10)
        row1_layout.addWidget(QLabel("预设选择："))
        self.preset_combo = QComboBox()
        self.preset_combo.setFixedWidth(180)
        organize_presets = directory_config.get('presets', [])
        self.preset_combo.addItem("自定义")
        for preset in organize_presets:
            self.preset_combo.addItem(preset.get("name", ""))
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        row1_layout.addWidget(self.preset_combo)
        row1_layout.addWidget(QLabel("时间筛选："))
        self.organize_start_date = None
        self.organize_end_date = None
        self.organize_date_filter_button = QPushButton("请选择日期范围")
        self.organize_date_filter_button.setMinimumWidth(150)
        self.organize_date_filter_button.clicked.connect(self.open_organize_date_filter_dialog)
        row1_layout.addWidget(self.organize_date_filter_button)
        row1_layout.addStretch()
        self.organize_btn = QPushButton("执行文件整理")
        self.organize_btn.setMinimumHeight(28)
        self.organize_btn.setMinimumWidth(130)
        self.organize_btn.clicked.connect(self.on_organize_files)
        row1_layout.addWidget(self.organize_btn)
        top_filter_layout.addLayout(row1_layout)

        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(10)
        row2_layout.addWidget(QLabel("源文件夹："))
        self.source_dir_text = QLineEdit()
        row2_layout.addWidget(self.source_dir_text, 1)
        self.source_dir_btn = QPushButton("浏览")
        self.source_dir_btn.setMinimumWidth(60)
        self.source_dir_btn.clicked.connect(self.on_browse_source_dir)
        row2_layout.addWidget(self.source_dir_btn)
        row2_layout.addWidget(QLabel("目标文件夹："))
        self.target_dir_text = QLineEdit()
        row2_layout.addWidget(self.target_dir_text, 1)
        self.target_dir_btn = QPushButton("浏览")
        self.target_dir_btn.setMinimumWidth(60)
        self.target_dir_btn.clicked.connect(self.on_browse_target_dir)
        row2_layout.addWidget(self.target_dir_btn)
        top_filter_layout.addLayout(row2_layout)

        row3_layout = QHBoxLayout()
        row3_layout.setSpacing(10)
        self.file_type_label = QLabel("文件后缀：")
        row3_layout.addWidget(self.file_type_label)
        self.file_type_text = QLineEdit()
        self.file_type_text.setPlaceholderText("例如：.pdf,.docx,.xlsx")
        file_extensions = directory_config.get('file_extensions', '')
        self.file_type_text.setText(file_extensions)
        self.file_type_text.textChanged.connect(self.on_file_extensions_changed)
        row3_layout.addWidget(self.file_type_text, 1)
        self.filename_label = QLabel("包含字段：")
        row3_layout.addWidget(self.filename_label)
        self.filename_text = QLineEdit()
        self.filename_text.setPlaceholderText("例如：合同")
        self.filename_text.setText(directory_config.get('filename_contains', ''))
        self.filename_text.textChanged.connect(self.on_filename_contains_changed)
        row3_layout.addWidget(self.filename_text, 1)
        top_filter_layout.addLayout(row3_layout)

        main_layout.addWidget(top_filter_frame)

        self.organize_list_group = QGroupBox("文件列表")
        self.organize_list_group.setStyleSheet(get_glass_groupbox_style(compact=True))
        organize_list_layout = QVBoxLayout(self.organize_list_group)
        organize_list_layout.setContentsMargins(8, 10, 8, 8)
        organize_list_layout.setSpacing(6)

        organize_list_header_layout = QHBoxLayout()
        self.organize_list_hint = QLabel("文件列表，根据筛选条件加载文件，可单选全选，选中的文件执行文件移动")
        organize_list_header_layout.addWidget(self.organize_list_hint)
        organize_list_header_layout.addStretch()
        self.organize_refresh_btn = QPushButton("刷新列表")
        self.organize_refresh_btn.setMinimumWidth(90)
        self.organize_refresh_btn.clicked.connect(self.load_organize_file_list)
        organize_list_header_layout.addWidget(self.organize_refresh_btn)
        organize_list_layout.addLayout(organize_list_header_layout)

        self.organize_file_table = QTableWidget()
        install_table_edit_context_menu(self.organize_file_table)
        self.organize_table_header = CheckBoxAutoFilterHeader(self.organize_file_table)
        self.organize_table_header.toggled.connect(self.on_organize_table_select_all_toggled)
        self.organize_file_table.setHorizontalHeader(self.organize_table_header)
        self.organize_file_table.setColumnCount(6)
        self.organize_file_table.setHorizontalHeaderLabels(["", "文件名", "修改时间", "文件类型", "文件大小", "当前路径"])
        self.organize_file_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.organize_file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.organize_file_table.itemChanged.connect(self.on_organize_file_table_item_changed)
        self.organize_file_table.verticalHeader().setVisible(False)
        self.organize_file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.organize_file_table.setColumnWidth(0, 28)
        self.organize_file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.organize_file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.organize_file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.organize_file_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.organize_file_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        organize_list_layout.addWidget(self.organize_file_table, 1)
        main_layout.addWidget(self.organize_list_group, 1)
        page_layout.addWidget(main_group)

        self.content_stack.addWidget(page)

        self.source_dir_text.setText(directory_config.get('default_source_dir', ''))
        self.target_dir_text.setText(directory_config.get('default_dest_dir', ''))
        self.source_dir_text.setReadOnly(False)
        self.source_dir_btn.setEnabled(True)
        self.target_dir_text.setReadOnly(False)
        self.target_dir_btn.setEnabled(True)
        self.file_type_text.setReadOnly(False)
        self.filename_text.setReadOnly(False)
        self.organize_file_entries = []


    def on_browse_source_dir(self):
        """浏览源文件夹"""
        from PyQt6.QtWidgets import QFileDialog

        # 获取输入框中的当前路径作为初始路径
        current_path = self.source_dir_text.text().strip()
        if not current_path or not os.path.exists(current_path):
            current_path = ""

        dir_path = QFileDialog.getExistingDirectory(self, "选择源文件夹", current_path)
        if dir_path:
            self.source_dir_text.setText(dir_path)
            # 保存到配置
            config = load_config()
            if 'directory_config' not in config:
                config['directory_config'] = {}
            config['directory_config']['default_source_dir'] = dir_path
            save_config_with_delay(config)
            self.load_organize_file_list()


    def on_browse_target_dir(self):
        """浏览目标文件夹"""
        from PyQt6.QtWidgets import QFileDialog

        # 获取输入框中的当前路径作为初始路径
        current_path = self.target_dir_text.text().strip()
        if not current_path or not os.path.exists(current_path):
            current_path = ""

        dir_path = QFileDialog.getExistingDirectory(self, "选择目标文件夹", current_path)
        if dir_path:
            self.target_dir_text.setText(dir_path)
            # 保存到配置
            config = load_config()
            if 'directory_config' not in config:
                config['directory_config'] = {}
            config['directory_config']['default_dest_dir'] = dir_path
            save_config_with_delay(config)


    def open_organize_date_filter_dialog(self):
        """打开文件整理修改时间筛选弹窗"""
        dialog = QuickDatePickerDialog(
            self.organize_start_date,
            self.organize_end_date,
            self
        )
        dialog.position_below_widget(self.organize_date_filter_button)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.organize_start_date = dialog.start_date
            self.organize_end_date = dialog.end_date
            if (
                self.organize_start_date and self.organize_end_date
                and self.organize_start_date.isValid() and self.organize_end_date.isValid()
            ):
                self.organize_date_filter_button.setText(
                    f"{self.organize_start_date.toString('yyyy-MM-dd')} ~ "
                    f"{self.organize_end_date.toString('yyyy-MM-dd')}"
                )
            else:
                self.organize_date_filter_button.setText("请选择日期范围")
            self.load_organize_file_list()


    def _parse_organize_extensions(self):
        """解析文件整理后缀条件"""
        file_extensions = self.file_type_text.text().strip()
        extensions = []
        if file_extensions:
            parts = re.split(r'[;,.\s]+', file_extensions)
            for part in parts:
                part = part.strip()
                if part:
                    if not part.startswith('.'):
                        part = '.' + part
                    extensions.append(part.lower())
        return extensions


    def _match_organize_date_filter(self, file_path):
        """按文件修改日期筛选"""
        start_date = getattr(self, 'organize_start_date', None)
        end_date = getattr(self, 'organize_end_date', None)
        if not (start_date and end_date and start_date.isValid() and end_date.isValid()):
            return True

        modified_dt = datetime.fromtimestamp(file_path.stat().st_mtime)
        modified_date = QDate(modified_dt.year, modified_dt.month, modified_dt.day)
        return start_date <= modified_date <= end_date


    def load_organize_file_list(self):
        """根据当前筛选条件加载文件整理列表"""
        source_dir = self.source_dir_text.text().strip()
        filename_contains = self.filename_text.text().strip()
        extensions = self._parse_organize_extensions()

        self.organize_file_entries = []
        self.organize_file_table.setRowCount(0)
        self.organize_table_header.set_check_state(Qt.CheckState.Unchecked)

        if not source_dir or not os.path.isdir(source_dir):
            self.organize_list_hint.setText("请先选择有效的源文件夹")
            return

        try:
            for file_path in sorted(Path(source_dir).iterdir(), key=lambda p: p.name.lower()):
                if not file_path.is_file():
                    continue
                if extensions and file_path.suffix.lower() not in extensions:
                    continue
                if filename_contains and filename_contains not in file_path.name:
                    continue
                if not self._match_organize_date_filter(file_path):
                    continue
                if "-" not in file_path.stem:
                    continue

                self.organize_file_entries.append({
                    "path": str(file_path),
                    "name": file_path.name,
                    "mtime": datetime.fromtimestamp(file_path.stat().st_mtime),
                    "suffix": file_path.suffix.lower(),
                    "size": file_path.stat().st_size,
                    "selected": True,
                })
        except Exception as e:
            self.organize_list_hint.setText(f"加载文件失败：{str(e)}")
            return

        self.organize_file_table.setRowCount(len(self.organize_file_entries))
        for row, entry in enumerate(self.organize_file_entries):
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            checkbox_item.setCheckState(Qt.CheckState.Checked)
            self.organize_file_table.setItem(row, 0, checkbox_item)
            self.organize_file_table.setItem(row, 1, QTableWidgetItem(entry["name"]))
            self.organize_file_table.setItem(row, 2, QTableWidgetItem(entry["mtime"].strftime("%Y-%m-%d %H:%M:%S")))
            self.organize_file_table.setItem(row, 3, QTableWidgetItem(entry["suffix"] or "-"))
            self.organize_file_table.setItem(row, 4, QTableWidgetItem(self._format_file_size(entry["size"])))
            self.organize_file_table.setItem(row, 5, QTableWidgetItem(entry["path"]))

        self.organize_list_hint.setText(f"共加载 {len(self.organize_file_entries)} 个文件，可勾选后执行文件整理")
        self.update_organize_table_header_state()


    def _format_file_size(self, size_bytes):
        """格式化文件大小"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


    def on_organize_table_select_all_toggled(self, checked):
        """文件整理列表全选/取消全选"""
        for row in range(self.organize_file_table.rowCount()):
            item = self.organize_file_table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.update_organize_table_header_state()


    def update_organize_table_header_state(self):
        """更新文件整理列表表头全选状态"""
        row_count = self.organize_file_table.rowCount()
        if row_count == 0:
            self.organize_table_header.set_check_state(Qt.CheckState.Unchecked)
            return

        checked_count = 0
        for row in range(row_count):
            item = self.organize_file_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                checked_count += 1

        if checked_count == 0:
            state = Qt.CheckState.Unchecked
        elif checked_count == row_count:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        self.organize_table_header.set_check_state(state)


    def on_organize_file_table_item_changed(self, item):
        """行勾选变化时同步表头状态"""
        if not item or item.column() != 0:
            return
        self.update_organize_table_header_state()


    def on_preset_changed(self, index):
        """预设选择变化事件"""
        try:
            if index == 0:  # 自定义
                # 加载默认值
                directory_config = self.config.get('directory_config', {})
                self.source_dir_text.setText(directory_config.get('default_source_dir', ''))
                self.target_dir_text.setText(directory_config.get('default_dest_dir', ''))
                file_extensions = directory_config.get('file_extensions', '')
                self.file_type_text.setText(file_extensions)
                self.filename_text.setText(directory_config.get('filename_contains', ''))
            else:
                # 加载预设值
                organize_presets = self.config.get('directory_config', {}).get('presets', [])
                if 0 <= index - 1 < len(organize_presets):
                    preset = organize_presets[index - 1]
                    self.source_dir_text.setText(preset.get('source_dir', ''))
                    self.target_dir_text.setText(preset.get('target_dir', ''))
                    file_extensions = preset.get('file_type', '')
                    self.file_type_text.setText(file_extensions)
                    self.filename_text.setText(preset.get('contains', ''))
                else:
                    # 索引越界，设置为自定义
                    self.preset_combo.setCurrentIndex(0)

            # 始终设置为可编辑，无论是否选择预设
            self.source_dir_text.setReadOnly(False)
            self.source_dir_btn.setEnabled(True)
            self.target_dir_text.setReadOnly(False)
            self.target_dir_btn.setEnabled(True)
            self.file_type_text.setReadOnly(False)
            self.filename_text.setReadOnly(False)
            self.load_organize_file_list()
        except Exception as e:
            # 发生任何错误，都设置为自定义
            self.preset_combo.setCurrentIndex(0)
            # 确保设置为可编辑
            self.source_dir_text.setReadOnly(False)
            self.source_dir_btn.setEnabled(True)
            self.target_dir_text.setReadOnly(False)
            self.target_dir_btn.setEnabled(True)
            self.file_type_text.setReadOnly(False)
            self.filename_text.setReadOnly(False)
            self.load_organize_file_list()


    def update_presets(self):
        """更新预设列表"""
        if hasattr(self, 'preset_combo'):
            # 保存当前选择
            current_index = self.preset_combo.currentIndex()
            current_text = self.preset_combo.currentText()

            # 清空现有选项
            self.preset_combo.clear()

            # 重新加载配置
            self.config = load_config()
            directory_config = self.config.get('directory_config', {})
            organize_presets = directory_config.get('presets', [])

            # 添加自定义选项
            self.preset_combo.addItem("自定义")

            # 添加所有预设
            for preset in organize_presets:
                self.preset_combo.addItem(preset.get("name", ""))

            # 恢复之前的选择
            if current_text == "自定义":
                self.preset_combo.setCurrentIndex(0)
            else:
                # 查找之前的预设
                found = False
                for i in range(1, self.preset_combo.count()):
                    if self.preset_combo.itemText(i) == current_text:
                        self.preset_combo.setCurrentIndex(i)
                        found = True
                        break
                # 如果没有找到匹配的预设，设置为自定义
                if not found:
                    self.preset_combo.setCurrentIndex(0)


    def on_filename_contains_changed(self, text):
        """实时保存文件名包含字段"""
        config = load_config()
        if 'directory_config' not in config:
            config['directory_config'] = {}
        config['directory_config']['filename_contains'] = text
        save_config(config)
        self.load_organize_file_list()


    def on_file_extensions_changed(self, text):
        """实时保存文件后缀设置"""
        config = load_config()
        if 'directory_config' not in config:
            config['directory_config'] = {}
        config['directory_config']['file_extensions'] = text
        save_config(config)
        self.load_organize_file_list()


    def on_organize_files(self):
        """执行文件整理操作"""
        try:
            source_dir = self.source_dir_text.text().strip()
            target_dir = self.target_dir_text.text().strip()
            file_extensions = self.file_type_text.text().strip()
            filename_contains = self.filename_text.text().strip()

            if not source_dir:
                show_error("错误", "请选择源文件夹")
                return

            if not target_dir:
                show_error("错误", "请选择目标文件夹")
                return

            if self.organize_file_table.rowCount() == 0:
                self.load_organize_file_list()

            selected_files = []
            for row in range(self.organize_file_table.rowCount()):
                item = self.organize_file_table.item(row, 0)
                path_item = self.organize_file_table.item(row, 5)
                if item and path_item and item.checkState() == Qt.CheckState.Checked:
                    selected_files.append(path_item.text())

            if not selected_files:
                show_error("提示", "请至少勾选一个文件")
                return

            # 执行文件整理
            self.append_output(f"\n=== 开始文件整理 ===")
            self.append_output(f"源文件夹: {source_dir}")
            self.append_output(f"目标文件夹: {target_dir}")
            self.append_output(f"文件后缀: {file_extensions if file_extensions else '所有文件'}")
            self.append_output(f"文件名包含: {filename_contains if filename_contains else '无'}")
            if self.organize_start_date and self.organize_end_date:
                self.append_output(
                    f"修改时间筛选: {self.organize_start_date.toString('yyyy-MM-dd')} ~ "
                    f"{self.organize_end_date.toString('yyyy-MM-dd')}"
                )
            self.append_output(f"勾选文件数: {len(selected_files)}")

            # 调用文件整理函数
            moved_count = self.move_files_to_new_folders(selected_files, target_dir)

            self.append_output(f"\n=== 文件整理完成 ===")
            self.append_output(f"成功移动 {moved_count} 个文件")
            self.append_output("====================")

            self.load_organize_file_list()

            # 打开目标文件夹（受通用设置控制）
            if self.config.get('app_settings', {}).get('open_output_folder', True):
                open_folder(target_dir)

            # 提交到SVN
            self.commit_to_svn(target_dir)

        except Exception as e:
            show_error("错误", f"文件整理失败: {str(e)}")
            self.append_output(f"\n=== 文件整理失败 ===")
            self.append_output(f"错误信息: {str(e)}")
            self.append_output("====================")


    def move_files_to_new_folders(self, selected_files, target_root):
        """将勾选文件移动到按文件名命名的新文件夹中"""
        moved_count = 0

        for file_name in selected_files:
            file_path = Path(file_name)
            if not file_path.exists() or not file_path.is_file():
                continue
            # 获取文件名（不含扩展名）
            base_name = file_path.stem
            # 在目标根目录下创建与文件名相同的新文件夹
            target_folder_path = os.path.join(target_root, base_name)
            os.makedirs(target_folder_path, exist_ok=True)  # 如果文件夹已存在，则不会抛出错误

            # 构建目标文件路径
            dst_file_path = os.path.join(target_folder_path, file_path.name)
            # 将文件从源路径移动到目标路径
            shutil.move(file_path, dst_file_path)
            # 打印移动信息
            self.append_output(f"移动文件: {file_path.name} → {base_name}")
            moved_count += 1

        return moved_count

