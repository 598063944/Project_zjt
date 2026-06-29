# -*- coding: utf-8 -*-
from core import *
from common import *

"""
object_query.py — 对象查询 Mixin
────────────────────────────────
负责：MainFrame 中 CRM 对象通用查询相关方法
  - create_object_query_page()   对象查询页面（CRM 对象选择 / 字段配置 / 数据表格）
  - 所有 _obj_query_* / _on_obj_query_* 方法  数据加载 / 筛选 / 同步到 MySQL
  - _to_timestamp_ms / _parse_date_to_ts / _build_api_filters  数据转换与过滤
  - fetch_object_fields / _get_crm_object_fields_api  CRM 字段元数据获取
依赖：core.py / common.py / network.py
被导入：主程序（作为 MainFrame 的 Mixin 父类）
"""
"""object_query Mixin"""

# 导入所需模块
import os
import common  # 显式导入，用于访问模块级私有函数

# QtWebEngine 必须在 QApplication 创建前导入
import PyQt6.QtWebEngineWidgets  # noqa: F401

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

class object_queryMixin:
    """object_query functionality."""

    def create_object_query_page(self):
        """创建对象查询页面（页面6）—— 布局与 CRM 订单一致"""
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(8)

        # ===== 第一行：对象选择 + 筛选按钮 + 搜索框 + 字段显示 =====
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        top_row.addWidget(QLabel("对象选择："))
        self.obj_query_object_combo = QComboBox()
        self.obj_query_object_combo.setFixedWidth(150)
        self.obj_query_object_combo.setFixedHeight(30)
        self.obj_query_object_combo.setStyleSheet("QComboBox { border: 1px solid #D9D9D9; border-radius: 4px; padding: 2px 6px; font-size: 12px; background: #FFF; }")
        crm_objs = self.config.get('fxiaoke', {}).get('crm_objects', [])
        if not crm_objs:
            crm_objs = [
                {'name': '销售订单', 'api_name': 'SalesOrderObj'},
                {'name': '商机', 'api_name': 'NewOpportunityObj'},
                {'name': '发货单', 'api_name': 'DeliveryNoteObj'},
            ]
        self.obj_query_object_combo.addItem("请选择对象", "")
        for obj in crm_objs:
            self.obj_query_object_combo.addItem(obj.get('name', ''), obj.get('api_name', ''))

        # ✅【关键】先连接信号，再设置默认值（确保顺序正确）
        self.obj_query_object_combo.currentIndexChanged.connect(self._on_obj_query_object_changed)

        # ✅【新增】延迟加载默认选择（避免初始化时触发）
        fx_cfg = self.config.get('fxiaoke', {})
        default_obj_api = fx_cfg.get('default_obj_query_object', '')
        if default_obj_api:
            # 使用QTimer延迟设置，确保UI完全就绪
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(200, lambda: self._set_default_obj_query(default_obj_api))
        else:
            print(f"[DEBUG-对象查询] ℹ️ 未配置默认对象")

        top_row.addWidget(self.obj_query_object_combo)

        # 方案按钮
        self.obj_query_preset_btn = QPushButton("方案 ▼")
        self.obj_query_preset_btn.setFixedHeight(30)
        self.obj_query_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.obj_query_preset_btn.setToolTip("筛选方案管理")
        self.obj_query_preset_btn.setStyleSheet("QPushButton { border: 1px solid #D9D9D9; border-radius: 4px; padding: 2px 10px; font-size: 12px; color: #333; background: #FFF; } QPushButton:hover { border-color: #1890FF; color: #1890FF; }")
        self.obj_query_preset_btn.clicked.connect(self._show_obj_query_preset_popup)
        top_row.addWidget(self.obj_query_preset_btn)

        # 筛选按钮
        self.obj_query_filter_btn = QPushButton("筛选")
        self.obj_query_filter_btn.setFixedHeight(30)
        self.obj_query_filter_btn.setStyleSheet("QPushButton { border: 1px solid #D9D9D9; border-radius: 4px; padding: 4px 12px; font-size: 13px; background: #FFF; color: #333; } QPushButton:hover { border-color: #1890FF; color: #1890FF; }")
        self.obj_query_filter_btn.clicked.connect(self._toggle_obj_query_filter_panel)
        top_row.addWidget(self.obj_query_filter_btn)

        # 搜索框
        search_frame = QFrame()
        search_frame.setFixedHeight(30)
        search_frame.setMaximumWidth(260)
        search_frame.setStyleSheet("QFrame { border: 1px solid #D9D9D9; border-radius: 4px; background: #FFF; }")
        sf_layout = QHBoxLayout(search_frame)
        sf_layout.setContentsMargins(0, 0, 0, 0)
        sf_layout.setSpacing(0)

        self.obj_query_search_input = QLineEdit()
        self.obj_query_search_input.setPlaceholderText("搜索")
        self.obj_query_search_input.setFixedHeight(28)
        self.obj_query_search_input.setStyleSheet("QLineEdit { border: none; background: transparent; padding: 2px 8px; font-size: 12px; }")
        self.obj_query_search_input.textChanged.connect(self._on_obj_query_search)
        sf_layout.addWidget(self.obj_query_search_input, stretch=1)
        top_row.addWidget(search_frame)

        # 加载条数快捷设置
        load_count_label = QLabel("加载条数:")
        load_count_label.setFixedHeight(30)
        load_count_label.setStyleSheet("font-size: 12px; color: #666; padding-left: 8px;")
        top_row.addWidget(load_count_label)

        self.obj_query_load_count_spin = QSpinBox()
        self.obj_query_load_count_spin.setRange(1, 10000)
        self.obj_query_load_count_spin.setValue(20)
        self.obj_query_load_count_spin.setFixedWidth(100)
        self.obj_query_load_count_spin.setFixedHeight(30)
        self.obj_query_load_count_spin.setToolTip("从CRM获取的最大记录数（1~10000）\n切换对象时自动读取对应的设置值")
        self.obj_query_load_count_spin.setStyleSheet("QSpinBox { border: 1px solid #D9D9D9; border-radius: 4px; padding: 2px 4px; font-size: 12px; background: #FFF; }")
        self.obj_query_load_count_spin.valueChanged.connect(self._on_obj_query_load_count_changed)
        top_row.addWidget(self.obj_query_load_count_spin)

        # ✅【新增】快捷筛选条件内联显示区域（紧跟加载条数之后）
        self.obj_query_quick_filters_container = QFrame()
        self.obj_query_quick_filters_container.setFixedHeight(30)
        self.obj_query_quick_filters_container.setStyleSheet("QFrame { background: transparent; border: none; }")
        qf_layout = QHBoxLayout(self.obj_query_quick_filters_container)
        qf_layout.setContentsMargins(6, 0, 0, 0)
        qf_layout.setSpacing(4)

        self.obj_query_quick_label = QLabel("快捷:")
        self.obj_query_quick_label.setFixedHeight(28)
        self.obj_query_quick_label.setStyleSheet("font-size: 11px; color: #1890FF; font-weight: bold;")
        self.obj_query_quick_label.setVisible(False)
        qf_layout.addWidget(self.obj_query_quick_label)

        self.obj_query_quick_tags_layout = QHBoxLayout()
        self.obj_query_quick_tags_layout.setSpacing(4)
        qf_layout.addLayout(self.obj_query_quick_tags_layout)

        qf_layout.addStretch()
        top_row.addWidget(self.obj_query_quick_filters_container)

        top_row.addStretch()

        # ✅【新增】刷新按钮
        self.obj_query_refresh_btn = QPushButton("🔄 刷新")
        self.obj_query_refresh_btn.setFixedWidth(80)
        self.obj_query_refresh_btn.setFixedHeight(30)
        self.obj_query_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.obj_query_refresh_btn.setToolTip("手动刷新对象查询数据")
        self.obj_query_refresh_btn.setStyleSheet("QPushButton { border: 1px solid #D9D9D9; border-radius: 4px; padding: 4px 12px; font-size: 13px; background: #FFF; color: #333; } QPushButton:hover { border-color: #1890FF; color: #1890FF; }")
        self.obj_query_refresh_btn.clicked.connect(self._on_obj_query_manual_refresh)
        top_row.addWidget(self.obj_query_refresh_btn)

        # 字段显示按钮
        self.obj_query_column_btn = QPushButton("字段显示")
        self.obj_query_column_btn.setFixedWidth(80)
        self.obj_query_column_btn.clicked.connect(self._open_obj_query_column_settings)
        top_row.addWidget(self.obj_query_column_btn)

        # MySQL 同步模式下拉
        sync_mode_cfg = self.config.get('fxiaoke', {}).get('obj_query_sync_mode', 'auto')
        self.obj_query_sync_mode_combo = QComboBox()
        self.obj_query_sync_mode_combo.setFixedHeight(30)
        self.obj_query_sync_mode_combo.setFixedWidth(90)
        self.obj_query_sync_mode_combo.addItem("自动同步", "auto")
        self.obj_query_sync_mode_combo.addItem("手动同步", "manual")
        self.obj_query_sync_mode_combo.setCurrentIndex(0 if sync_mode_cfg == 'auto' else 1)
        self.obj_query_sync_mode_combo.setStyleSheet("QComboBox { border: 1px solid #D9D9D9; border-radius: 4px; padding: 2px 6px; font-size: 12px; background: #FFF; }")
        self.obj_query_sync_mode_combo.currentIndexChanged.connect(self._on_obj_query_sync_mode_changed)
        top_row.addWidget(self.obj_query_sync_mode_combo)

        # 同步到数据库按钮
        self.obj_query_sync_btn = QPushButton("同步")
        self.obj_query_sync_btn.setFixedWidth(50)
        self.obj_query_sync_btn.setFixedHeight(30)
        self.obj_query_sync_btn.setToolTip("将当前数据同步到 MySQL 数据库")
        self.obj_query_sync_btn.setStyleSheet("QPushButton { border: 1px solid #D9D9D9; border-radius: 4px; padding: 2px 8px; font-size: 12px; background: #FFF; color: #333; } QPushButton:hover { border-color: #1890FF; color: #1890FF; }")
        self.obj_query_sync_btn.clicked.connect(self._on_obj_query_sync_to_mysql)
        top_row.addWidget(self.obj_query_sync_btn)

        layout.addLayout(top_row)

        # ===== 筛选条件面板（使用公共 FilterPanel） =====
        # 字段选项从 _obj_query_display_headers 获取（数据加载后填充），初始化时为空列表
        headers = getattr(self, '_obj_query_display_headers', [])
        if not headers and hasattr(self, 'obj_query_search_field'):
            headers = [self.obj_query_search_field.itemText(i) for i in range(self.obj_query_search_field.count()) if self.obj_query_search_field.itemData(i)]
        field_options = [(h, h) for h in headers if h and h != "全字段"]

        self._obj_query_filter_panel = FilterPanel(
            self,
            mode="inline",
            title="设置筛选",
            show_title=True,
            show_add_btn=True,
            show_apply_btn=True,
            show_clear_btn=True,
            show_save_btn=True,
            show_exposed_tags=False,
            add_btn_text="+ 添加条件",
            apply_btn_text="筛选",
            clear_btn_text="清除",
            save_btn_text="另存为",
            toggle_btn=self.obj_query_filter_btn,
            toggle_badge=True,
            row_defaults={
                'field_options': field_options,
                'field_width': 140,
                'text_operators': self.obj_query_text_ops,
                'date_operators': self.obj_query_date_ops,
                'op_width': 95,
                'default_operator': 'contains',
                'value_pages': ('text', 'date', 'date_range', 'spin'),
                'show_expose': True,
                'show_picker': True,
                'show_remove': True,
                'debounce_ms': 250,
                'is_date_field_cb': self._obj_query_is_date_field,
                'picker_cb': self._obj_query_on_row_picker,
            },
            on_apply=lambda panel: self._apply_obj_query_filter_and_close(),
        )
        # 覆写 FilterPanel 的「保存」按钮行为
        self._obj_query_filter_panel._on_save_preset = lambda panel: self._save_obj_query_preset()

        # 兼容旧变量名
        self.obj_query_filter_panel = self._obj_query_filter_panel._panel_frame
        self.obj_query_condition_rows = self._obj_query_filter_panel._legacy_rows
        self.obj_query_conditions_layout = self._obj_query_filter_panel._rows_layout
        layout.addWidget(self._obj_query_filter_panel)

        # ===== 外露标签 =====
        self._obj_query_exposed_tags_bar = ExposedTagsBar(self)
        self._obj_query_exposed_tags_bar.tagRemoved.connect(self._on_obj_query_exposed_tag_removed)
        layout.addWidget(self._obj_query_exposed_tags_bar)

        # ===== 表格 =====
        self.obj_query_table = QTableWidget()
        install_table_edit_context_menu(self.obj_query_table)
        self.obj_query_table.setColumnCount(0)
        self.obj_query_table.setRowCount(0)
        self.obj_query_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.obj_query_table.cellClicked.connect(self._on_obj_query_table_cell_clicked)
        self.obj_query_table.setAlternatingRowColors(True)
        self.obj_query_table.horizontalHeader().setStretchLastSection(False)
        self.obj_query_table.horizontalHeader().sectionResized.connect(self._on_obj_query_column_resized)

        # ✅【新增】隐藏垂直表头（序号列）
        self.obj_query_table.verticalHeader().setVisible(False)

        # ✅【新增】让水平表头支持选中复制
        self.obj_query_table.horizontalHeader().setHighlightSections(True)
        self.obj_query_table.horizontalHeader().setSectionsClickable(True)

        # ✅【新增】为表头添加右键菜单（支持复制功能）
        self.obj_query_table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.obj_query_table.horizontalHeader().customContextMenuRequested.connect(self._on_obj_query_header_context_menu)

        layout.addWidget(self.obj_query_table, stretch=1)

        # ===== 分页栏 =====
        page_bar = QHBoxLayout()
        # ✅【修改】对象查询状态标签（左下角显示加载信息，左对齐）
        self.obj_query_status_label = QLabel("")
        self.obj_query_status_label.setFixedWidth(280)
        self.obj_query_status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # 左对齐
        self.obj_query_status_label.setStyleSheet("color: #1890FF; font-size: 11px;")  # 蓝色提示
        page_bar.addWidget(self.obj_query_status_label)

        # 数据来源标签
        self.obj_query_source_label = QLabel("")
        self.obj_query_source_label.setFixedWidth(160)
        self.obj_query_source_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.obj_query_source_label.setStyleSheet("color: #999; font-size: 10px;")
        page_bar.addWidget(self.obj_query_source_label)

        # 弹性空间，将页码控件推到右侧
        page_bar.addStretch()

        page_bar.addWidget(QLabel("每页显示："))
        self.obj_query_page_size = QComboBox()
        self.obj_query_page_size.setEditable(True)
        self.obj_query_page_size.addItem("自定义", -1)
        for ps in (20, 50, 80, 100, 200):
            self.obj_query_page_size.addItem(str(ps), ps)
        self.obj_query_page_size.setCurrentIndex(1)
        self.obj_query_page_size.setStyleSheet("QComboBox { font-size: 11px; padding: 2px 4px; }")
        self.obj_query_page_size.currentIndexChanged.connect(self._on_obj_query_page_size_changed)
        page_bar.addWidget(self.obj_query_page_size)
        page_bar.addSpacing(10)
        self.obj_query_current_page = 1
        self.obj_query_prev_btn = QPushButton("<")
        self.obj_query_prev_btn.setFixedWidth(34)
        self.obj_query_prev_btn.clicked.connect(lambda: [setattr(self, 'obj_query_current_page', self.obj_query_current_page - 1), self._obj_query_populate_table()])
        page_bar.addWidget(self.obj_query_prev_btn)
        self.obj_query_page_label = QLabel("0/0")
        self.obj_query_page_label.setFixedWidth(50)
        self.obj_query_page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_bar.addWidget(self.obj_query_page_label)

        self.obj_query_next_btn = QPushButton(">")
        self.obj_query_next_btn.setFixedWidth(34)
        self.obj_query_next_btn.clicked.connect(lambda: [setattr(self, 'obj_query_current_page', self.obj_query_current_page + 1), self._obj_query_populate_table()])
        page_bar.addWidget(self.obj_query_next_btn)

        layout.addLayout(page_bar)

        self.content_stack.addWidget(page)


    def _on_obj_query_header_context_menu(self, position):
        """
        处理对象查询表格表头的右键菜单事件

        【功能说明】：
        当用户在表头上点击右键时，显示上下文菜单，
        提供复制表头名称的功能。

        【菜单选项】：
        1. 复制此列标题 - 复制当前点击的表头文字
        2. 复制所有标题 - 复制所有表头文字（Tab分隔）
        3. 复制可见标题 - 复制当前显示的表头文字

        【使用方式】：
        - 右键点击任意表头
        - 选择要执行的复制操作
        - 粘贴到需要的地方

        参数：
        ------
        position : QPoint
            鼠标点击的位置坐标
        """

        # 获取点击的列索引
        column_index = self.obj_query_table.horizontalHeader().logicalIndexAt(position)

        if column_index < 0 or column_index >= self.obj_query_table.columnCount():
            return

        # 获取该列的表头文字
        header_text = self.obj_query_table.horizontalHeaderItem(column_index).text()

        if not header_text:
            return

        # 创建右键菜单
        menu = QMenu(self)

        # 菜单项1：复制此列标题
        copy_single_action = QAction(f"📋 复制: \"{header_text}\"", self)
        copy_single_action.triggered.connect(lambda: self._copy_text_to_clipboard(header_text))
        menu.addAction(copy_single_action)

        menu.addSeparator()

        # 菜单项2：复制所有表头标题
        all_headers = []
        for col in range(self.obj_query_table.columnCount()):
            h_item = self.obj_query_table.horizontalHeaderItem(col)
            if h_item and h_item.text():
                all_headers.append(h_item.text())

        all_headers_str = "\t".join(all_headers) if all_headers else ""

        copy_all_action = QAction(f"📋 复制所有表头 ({len(all_headers)} 列)", self)
        copy_all_action.triggered.connect(lambda: self._copy_text_to_clipboard(all_headers_str))
        copy_all_action.setEnabled(len(all_headers) > 0)
        menu.addAction(copy_all_action)

        # 菜单项3：复制可见表头标题（当前显示的）
        visible_headers = getattr(self, '_obj_query_visible_headers', None)
        if visible_headers:
            visible_headers_str = "\t".join(visible_headers)

            copy_visible_action = QAction(f"📋 复制可见表头 ({len(visible_headers)} 列)", self)
            copy_visible_action.triggered.connect(lambda: self._copy_text_to_clipboard(visible_headers_str))
            menu.addAction(copy_visible_action)

        # 显示菜单
        menu.exec(self.obj_query_table.mapToGlobal(position))


    def _copy_text_to_clipboard(self, text):
        """
        将文本复制到系统剪贴板

        【功能说明】：
        通用的剪贴板操作方法，支持复制任意文本到系统剪贴板。

        【参数】：
        ------
        text : str
            要复制的文本内容

        【使用场景】：
        - 复制表头名称
        - 复制单元格内容
        - 复制其他任意文本
        """

        if not text:
            return

        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(text)

        print(f"[DEBUG-对象查询] 📋 已复制到剪贴板 | 内容: \"{text[:50]}{'...' if len(text) > 50 else ''}\" | 长度: {len(text)}")


    def _set_default_obj_query(self, default_api):
        """
        安全设置对象查询的默认选择（延迟调用）

        【功能说明】：
        在UI完全初始化后，安全地设置默认选中的对象。

        【2026-05-10 优化】：
        移除首次加载标志，改为基于缓存的智能加载机制。
        设置默认对象后会自动触发数据加载（如果没有缓存的话）。
        """
        print(f"\n[DEBUG-对象查询] 🎯 设置默认对象 | 目标API: '{default_api}'")

        if not hasattr(self, 'obj_query_object_combo'):
            print(f"[ERROR-对象查询] ❌ obj_query_object_combo 不存在")
            return

        # 查找匹配的对象
        found_index = -1
        for i in range(self.obj_query_object_combo.count()):
            item_data = self.obj_query_object_combo.itemData(i)

            if item_data == default_api:
                found_index = i
                break

        if found_index >= 0:
            # 暂时断开信号，避免触发自动加载
            self.obj_query_object_combo.blockSignals(True)
            self.obj_query_object_combo.setCurrentIndex(found_index)
            self.obj_query_object_combo.blockSignals(False)

            print(f"   ✓ 已设置默认对象为: {self.obj_query_object_combo.currentText()} (数据将在进入页面时加载)")
        else:
            print(f"[WARNING-对象查询] ⚠️ 未找到匹配的默认对象: '{default_api}'")



    def _on_obj_query_object_changed(self, idx):
        """
        对象选择变化 → 智能加载数据（带缓存机制和防抖处理）

        【核心逻辑】：
        1️⃣ 首次切换到某个对象 → 自动从CRM加载 + 缓存
        2️⃣ 后续切换到已缓存的对象 → 直接显示缓存数据（不请求API）
        3️⃣ 切换到未缓存的新对象 → 自动从CRM加载 + 缓存
        4️⃣ 点击"🔄 刷新"按钮 → 强制重新加载当前对象

        【2026-05-11 性能优化】：
        - 添加防抖机制，避免快速切换时触发多次加载
        - 使用QTimer延迟执行，提升用户体验
        - 添加加载状态管理，防止重复请求

        【2026-05-10 修复】：
        移除全局首次加载标志，改为基于每个对象的缓存状态判断是否需要加载。
        """

        api_name = self.obj_query_object_combo.currentData()

        # 安全检查
        if not api_name or not str(api_name).strip():
            return

        # 中文检测和修正（保留原有逻辑）
        if any('\u4e00' <= char <= '\u9fff' for char in str(api_name)):
            corrected_api = None
            for i in range(self.obj_query_object_combo.count()):
                item_text = self.obj_query_object_combo.itemText(i)
                item_data = self.obj_query_object_combo.itemData(i)

                if item_text == str(api_name):
                    corrected_api = item_data
                    break

            if corrected_api and corrected_api != api_name:
                api_name = corrected_api
            else:
                return

        # 切换对象前：保存上一个对象的界面筛选条件（UI 筛选独立于设置筛选）
        old_api = getattr(self, '_pending_obj_query_api', None)
        old_conditions = self._collect_obj_query_conditions()
        if old_api and old_api != api_name and old_conditions:
            cfg = load_config()
            ui_cfg = cfg.setdefault('fxiaoke', {}).setdefault('obj_query_ui_filters', {})
            ui_cfg[old_api] = old_conditions
            save_config(cfg)

        # 切换对象时同步加载条数 SpinBox 的值
        self._sync_load_count_spin_from_config()

        # ✅【新增】切换对象时加载快捷筛选条件（从配置中 is_quick=True 的条件）
        self._load_quick_filters_for_object(api_name)

        # ✅【性能优化】防抖处理：取消之前的加载任务，断开旧连接
        if hasattr(self, '_obj_query_debounce_timer'):
            self._obj_query_debounce_timer.stop()
            try:
                self._obj_query_debounce_timer.timeout.disconnect()
            except TypeError:
                pass

        # 创建或重用防抖定时器（300ms延迟）
        from PyQt6.QtCore import QTimer
        if not hasattr(self, '_obj_query_debounce_timer'):
            self._obj_query_debounce_timer = QTimer()
            self._obj_query_debounce_timer.setSingleShot(True)

        # ✅ 每次重新连接（使用 _pending_obj_query_api 而非闭包捕获的 api_name，
        #    避免首次调用后 api_name 被凝固，导致后续所有切换静默失败）
        self._obj_query_debounce_timer.timeout.connect(
            lambda: self._do_obj_query_load(self._pending_obj_query_api)
        )

        # 设置当前要加载的对象API名称（必须在 connect 之后、start 之前设置）
        self._pending_obj_query_api = api_name

        # 显示加载状态
        if hasattr(self, 'obj_query_status_label'):
            self.obj_query_status_label.setText(f"⏳ 准备加载 {self.obj_query_object_combo.currentText()}...")

        # 启动防抖定时器（300ms后执行实际加载）
        self._obj_query_debounce_timer.start(300)


    def _to_timestamp_ms(self, date_str):
        """将日期字符串转为 Unix 毫秒时间戳（CRM API 要求）"""
        from datetime import datetime
        date_str = str(date_str).strip()
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return str(int(datetime.strptime(date_str, fmt).timestamp() * 1000))
            except ValueError:
                continue
        return date_str  # 无法解析则原样返回


    def _parse_date_to_ts(self, val):
        """将日期值（字符串/时间戳/整数）转为 Unix 毫秒时间戳（int），用于客户端日期比较。
        支持格式：Unix 毫秒字符串/整数、yyyy-MM-dd、yyyy-MM-dd HH:mm:ss。
        无法解析时返回 None。
        """
        if val is None:
            return None
        from datetime import datetime
        s = str(val).strip()
        if not s:
            return None
        # 纯数字 → 当作 Unix 毫秒时间戳
        if s.isdigit() or (s.startswith('-') and s[1:].isdigit()):
            try:
                return int(s)
            except (ValueError, TypeError):
                pass
        # 常见日期格式
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return int(datetime.strptime(s, fmt).timestamp() * 1000)
            except ValueError:
                continue
        return None


    def _build_api_filters_from_settings(self, api_name):
        """从设置区域的默认筛选条件构建 API filters（不经过筛选面板 UI）"""
        self._obj_query_filter_build_message = ''
        fx_cfg = load_config().get('fxiaoke', {})
        obj_settings = fx_cfg.get('obj_query_settings', {}).get(api_name, {})
        saved_filters = obj_settings.get('filters', [])
        logging.info(f"[DEBUG-API筛选-入口] api={api_name}, has_settings={bool(obj_settings)}, filters_count={len(saved_filters) if isinstance(saved_filters, list) else 'NOT_LIST'}")
        if not saved_filters or not isinstance(saved_filters, list):
            return None

        # 构建 display_name → api_name 映射
        field_config = fx_cfg.get('crm_object_fields', {}).get(api_name, {})
        display_to_api = {}
        for api_key, field_info in field_config.items():
            if isinstance(field_info, dict):
                label = field_info.get('label', api_key).strip()
            elif isinstance(field_info, str) and field_info.strip():
                label = field_info.strip()
            else:
                label = api_key
            if label:
                display_to_api[label] = api_key

        # 构建 display_value → option_id 反向映射（用于"属于"筛选值转换）
        # 优先从 fxiaoke.crm_option_mappings 读取（嵌套结构：{api_name: {field: {id: text}}}）
        option_mappings = fx_cfg.get('crm_option_mappings', {}).get(api_name, {})
        # 回退到 business_rules.crm_option_mappings（扁平结构：{field: {id: text}}）
        if not option_mappings:
            full_cfg = load_config()
            option_mappings = full_cfg.get('business_rules', {}).get('crm_option_mappings', {})
        display_to_option = {}  # {field_display_name: {value_display: option_id}}
        for fk, mappings in option_mappings.items():
            if isinstance(mappings, dict):
                # 找到这个 API key 对应的显示名
                fk_label = fk
                for api_k, fi in field_config.items():
                    if api_k == fk:
                        fk_label = (fi.get('label', fk) if isinstance(fi, dict) else str(fi)) if fi else fk
                        break
                rev = {}
                for opt_id, opt_text in mappings.items():
                    if isinstance(opt_text, str) and opt_text.strip():
                        rev[opt_text.strip()] = opt_id
                if rev:
                    display_to_option[fk_label] = rev
        # UI → CRM API 操作符映射
        op_map = {
            'eq': 'EQ', 'ne': 'N', 'contains': 'LIKE', 'not_contains': 'NLIKE',
            'gt': 'GT', 'lt': 'LT', 'gte': 'GTE', 'lte': 'LTE',
            'empty': 'IS', 'not_empty': 'ISN',
            'in': 'IN', 'not_in': 'NIN',
            'starts_with': 'STARTWITH', 'ends_with': 'ENDWITH',
            'has_any_of': 'HASANYOF', 'not_has_any_of': 'NHASANYOF',
            'date_before': 'LTE', 'date_after': 'GTE',
        }

        api_filters = []
        skipped_conditions = []
        for cond in saved_filters:
            field_name = cond.get('field', '')
            op = cond.get('operator', '')
            value = cond.get('value', '')
            if not field_name:
                continue

            api_field = cond.get('field_api') or display_to_api.get(field_name, field_name)

            if op in ('empty', 'not_empty'):
                crm_op = op_map.get(op)
                if crm_op:
                    api_filters.append({'field_name': api_field, 'operator': crm_op, 'field_values': []})
            elif op == 'date_range' and '~' in value:
                parts = str(value).split('~')
                if len(parts) == 2:
                    start_ts = self._to_timestamp_ms(parts[0].strip() + ' 00:00:00')
                    end_ts = self._to_timestamp_ms(parts[1].strip() + ' 23:59:59')
                    api_filters.append({'field_name': api_field, 'operator': 'BETWEEN', 'field_values': [start_ts, end_ts]})
                else:
                    skipped_conditions.append(field_name)
            elif op == 'date_range':
                skipped_conditions.append(field_name)
            elif op == 'past_n_days':
                from datetime import datetime, timedelta
                try:
                    n = int(value)
                    end_ts = self._to_timestamp_ms(datetime.now().strftime('%Y-%m-%d 23:59:59'))
                    start_ts = self._to_timestamp_ms((datetime.now() - timedelta(days=n)).strftime('%Y-%m-%d 00:00:00'))
                    api_filters.append({'field_name': api_field, 'operator': 'BETWEEN', 'field_values': [start_ts, end_ts]})
                except ValueError:
                    skipped_conditions.append(field_name)
            elif op in ('in', 'not_in', 'has_any_of', 'not_has_any_of') and re.search(r'[,，;；、]', str(value)):
                # "属于" + 多值 → IN（值转为 option ID）
                value_list = [v.strip() for v in re.split(r'[,，;；、]', str(value)) if v.strip()]
                value_map = display_to_option.get(field_name, {})
                api_values = [value_map.get(v, v) for v in value_list]
                if api_values:
                    api_filters.append({'field_name': api_field, 'operator': op_map.get(op, 'IN'), 'field_values': api_values})
                else:
                    skipped_conditions.append(field_name)
            elif op in ('in', 'not_in', 'has_any_of', 'not_has_any_of'):
                # "属于" + 单值 → IN（值转为 option ID）
                value_map = display_to_option.get(field_name, {})
                api_value = value_map.get(value, value)
                if api_value:
                    api_filters.append({'field_name': api_field, 'operator': op_map.get(op, 'IN'), 'field_values': [api_value]})
                else:
                    skipped_conditions.append(field_name)
            elif op == 'contains':
                api_filters.append({'field_name': api_field, 'operator': 'LIKE', 'field_values': [value]})
            elif op in op_map:
                crm_op = op_map[op]
                # 日期类操作符：尝试将值转为 Unix 毫秒时间戳
                if op in ('lt', 'gt', 'lte', 'gte', 'date_before', 'date_after', 'eq', 'ne'):
                    ts_value = self._to_timestamp_ms(value)
                    api_filters.append({'field_name': api_field, 'operator': crm_op, 'field_values': [ts_value]})
                else:
                    api_filters.append({'field_name': api_field, 'operator': crm_op, 'field_values': [value]})
            else:
                skipped_conditions.append(field_name)

        if skipped_conditions:
            self._obj_query_filter_build_message = f"⚠️ 筛选条件无法转换为CRM过滤条件：{', '.join(skipped_conditions)}，已返回空结果"
            logging.info(f"[DEBUG-API筛选] {self._obj_query_filter_build_message}")
            return None

        import json; logging.info(f"[DEBUG-API筛选] api={api_name}, filters={json.dumps(api_filters, ensure_ascii=False) if api_filters else 'None'}")
        return api_filters if api_filters else None


    def _do_obj_query_load(self, api_name):
        """
        执行对象查询的实际加载逻辑（由防抖定时器调用）

        【设计目的】：
        - 与_on_obj_query_object_changed分离，实现防抖
        - 避免快速切换对象时触发多次网络请求
        - 统一管理加载状态和错误处理
        """
        # ✅【安全检查】防止已取消的加载任务执行
        pending_api = getattr(self, '_pending_obj_query_api', None)
        if not api_name or api_name != pending_api:
            print(f"[DEBUG-对象查询] ⚠️ 加载任务已取消 | 请求: '{api_name}' | 当前: '{pending_api}'")
            return

        # 切换对象时同步加载该对象的筛选条件到界面筛选面板
        self._apply_default_filters_for_object(api_name)

        # ✅【内存缓存】同一次运行中，已加载过的对象直接复用内存数据
        #   但如果筛选条件在设置中被修改过，则跳过缓存重新从 API 获取
        if not hasattr(self, '_obj_query_mem_cache'):
            self._obj_query_mem_cache = {}
        filters_dirty = getattr(self, '_obj_query_filters_dirty', False)
        if not filters_dirty and api_name in self._obj_query_mem_cache and self._obj_query_mem_cache[api_name]:
            self.obj_query_all_data = self._obj_query_mem_cache[api_name]
            self.obj_query_current_page = 1
            self._reset_obj_query_field_mapping()
            self.obj_query_data_ready.emit(api_name)
            print(f"[DEBUG-对象查询] 💾 内存缓存命中 '{api_name}': {len(self.obj_query_all_data)} 条")
            return
        if filters_dirty:
            print(f"[DEBUG-对象查询] 🔄 筛选条件已变更，跳过内存缓存")
            self._obj_query_filters_dirty = False
            self._obj_query_mem_cache.pop(api_name, None)

        # 清空表格显示空白界面
        self.obj_query_all_data = []
        self.obj_query_current_page = 1
        self._reset_obj_query_field_mapping()
        self._show_empty_table()

        # 1. 尝试从 MySQL 缓存加载历史数据（快速展示，后续由 CRM 刷新为最新）
        cached_rows = None
        try:
            mc = MysqlCache()
            if mc.available:
                cached_rows = mc.get_all(api_name)
            mc.close()
        except Exception as e:
            logging.warning(f"[对象查询] MySQL 读取失败 '{api_name}': {e}")

        if cached_rows and len(cached_rows) > 0:
            print(f"[DEBUG-对象查询] 💾 MySQL缓存命中 '{api_name}': {len(cached_rows)} 条")
            self.obj_query_all_data = cached_rows
            self.obj_query_current_page = 1
            self._reset_obj_query_field_mapping()
            self._obj_query_client_filters = self.config.get('fxiaoke', {}).get('obj_query_settings', {}).get(api_name, {}).get('filters', [])
            self._obj_query_mem_cache[api_name] = self.obj_query_all_data
            self.obj_query_data_ready.emit(api_name)
            if hasattr(self, 'obj_query_source_label'):
                self.obj_query_source_label.setText(f"📦 MySQL 缓存 | {len(cached_rows)} 条（后台刷新中…）")
            # 不 return，继续从 CRM 获取最新数据并刷新表格

        # 2. 从 CRM 获取全量数据（不带 API 筛选，写入 MySQL + 更新表格）
        print(f"\n[DEBUG-对象查询] 🔍 从CRM获取数据(全量): '{api_name}'")
        if hasattr(self, 'obj_query_source_label'):
            self.obj_query_source_label.setText("☁️ CRM API 加载中...")
        api_filters = self._build_api_filters_from_settings(api_name)
        build_message = getattr(self, '_obj_query_filter_build_message', '')
        if build_message:
            self._show_obj_query_empty_filter_result(api_name, build_message)
            return
        logging.info(f"[DEBUG-对象查询-case2] api_filters={'有' if api_filters else '无'}")

        self._obj_query_fetch_data(api_name, filters=api_filters)


    def _obj_query_populate_table_safe(self, api_name):
        """在主线程中安全地填充对象查询表格（包含状态更新和组件就绪检查）"""
        # 恢复刷新按钮状态
        if hasattr(self, 'obj_query_refresh_btn'):
            self.obj_query_refresh_btn.setText("🔄 刷新")
            self.obj_query_refresh_btn.setEnabled(True)

        # 更新状态标签
        data = getattr(self, 'obj_query_all_data', [])
        cache_count = len(data) if data else 0
        if hasattr(self, 'obj_query_status_label'):
            status_text = f"✅ {self.obj_query_object_combo.currentText()} 已加载 {cache_count} 条记录"
            empty_messages = getattr(self, '_obj_query_filter_empty_messages', {})
            if cache_count == 0 and isinstance(empty_messages, dict) and empty_messages.get(api_name):
                status_text = empty_messages.get(api_name)
            self.obj_query_status_label.setText(status_text)

        # 安全检查：确保组件已完全初始化
        if not hasattr(self, 'obj_query_table'):
            print(f"[WARNING-对象查询] ⚠️ obj_query_table 不存在，跳过表格填充")
            return

        # 验证当前选中的对象是否与加载数据一致（防止旧数据覆盖新对象）
        current_api = self.obj_query_object_combo.currentData() or ''
        if current_api and current_api != api_name:
            print(f"[DEBUG-对象查询] ⚠️ 数据已过期 | 加载: '{api_name}' | 当前: '{current_api}' | 跳过填充")
            return

        # 填充表格（捕获所有异常，避免信号调度静默吞错导致空白表格）
        try:
            self._obj_query_populate_table()
        except Exception as e:
            print(f"[ERROR-对象查询] ❌ 表格填充失败: {e}")
            import traceback
            traceback.print_exc()
            # 降级：至少显示有多少条数据
            if hasattr(self, 'obj_query_page_label'):
                self.obj_query_page_label.setText(f"数据: {cache_count} 条 (渲染失败)")
            if hasattr(self, 'obj_query_status_label'):
                self.obj_query_status_label.setText(f"❌ 渲染失败: {e}")
            return

        # 自动同步到 MySQL（后台线程执行，不阻塞 UI）
        if data and self._get_obj_query_sync_mode() == 'auto':
            display_name = self.obj_query_object_combo.currentText().strip()
            self.update_output.emit(f"[对象查询] 自动同步 MySQL 开始: '{api_name}' {len(data)} 条")
            self.task_manager.start(
                f'mysql_sync_{api_name}',
                f'MySQL同步: {display_name}',
                self._do_obj_query_sync_to_mysql_bg,
                api_name, data, display_name
            )


    def _reset_obj_query_field_mapping(self):
        """重置对象查询的字段映射缓存（加载已保存的字段显示设置）"""
        api_name = self.obj_query_object_combo.currentData() or ''
        if api_name:
            vis, order = self._load_obj_query_field_settings(api_name)
            self._obj_query_visible_headers = vis
            self._obj_query_header_order = order
        else:
            self._obj_query_visible_headers = None
            self._obj_query_header_order = None
        self._obj_query_all_labels = None
        self._obj_query_all_api_fields = None
        self._obj_query_display_headers = None
        self._obj_query_display_to_api = None
        self._reverse_option_map_key = None
        self._reverse_option_map_cache = {}


    def _load_obj_query_field_settings(self, api_name):
        """加载指定对象的字段显示设置（visible_headers, header_order）"""
        settings = self.config.get('app_settings', {}).get('obj_query_field_settings', {}).get(api_name, {})
        visible = settings.get('visible_headers', None)
        order = settings.get('header_order', None)
        return visible if visible else None, order if order else None


    def _save_obj_query_field_settings(self, api_name, visible_headers, header_order):
        """保存指定对象的字段显示设置到配置文件"""
        config = load_config()
        config.setdefault('app_settings', {}).setdefault('obj_query_field_settings', {})
        config['app_settings']['obj_query_field_settings'][api_name] = {
            'visible_headers': list(visible_headers),
            'header_order': list(header_order),
        }
        save_config_with_delay(config)
        self.config = config


    def _show_empty_table(self):
        """显示空白表格（用于未加载的对象）"""
        table = self.obj_query_table
        table.setRowCount(0)
        table.setColumnCount(0)

        # 更新分页信息
        self.obj_query_page_label.setText("0/0")

        # 清空筛选器中的旧选项
        if hasattr(self, 'obj_query_filter_field'):
            self.obj_query_filter_field.clear()
            self.obj_query_filter_field.addItem("选择字段", "")

        # 清空搜索下拉框
        if hasattr(self, 'obj_query_search_field'):
            self.obj_query_search_field.clear()

        print(f"[DEBUG-对象查询] ✅ 已显示空白表格\n")

        # ✅ 重置所有字段映射相关缓存
        self._reset_obj_query_field_mapping()
        print(f"[DEBUG-对象查询] 🔄 所有字段映射缓存已重置")


    def _show_obj_query_empty_filter_result(self, api_name, message):
        """筛选条件有效但无结果，或条件无法转换时，显示空结果而不回退全量数据。"""
        self.obj_query_all_data = []
        self.obj_query_current_page = 1
        self._obj_query_client_filters = []
        if not hasattr(self, '_obj_query_filter_empty_messages'):
            self._obj_query_filter_empty_messages = {}
        self._obj_query_filter_empty_messages[api_name] = message
        self.update_output.emit(f"[对象查询] {api_name}: {message}")
        if hasattr(self, 'obj_query_status_label'):
            self.obj_query_status_label.setText(message)
        self._reset_obj_query_field_mapping()
        self.obj_query_data_ready.emit(api_name)


    def _obj_query_fetch_data(self, api_name, filters=None, client_filters=None, is_custom=None):
        """从 CRM API 获取对象数据（支持服务端筛选 + 客户端二次过滤）"""
        # 自动检测对象类型
        if is_custom is None:
            is_custom = self._lookup_crm_object_type(api_name) == 'custom'
        # 安全检查
        if not api_name or any('\u4e00' <= char <= '\u9fff' for char in str(api_name)):
            actual_api = self.obj_query_object_combo.currentData() or ''
            if actual_api and actual_api != api_name:
                api_name = actual_api
            else:
                error_msg = f"[对象查询] 加载失败: 无效的对象API名称 ('{api_name}')"
                self.update_output.emit(error_msg)
                # 更新状态标签显示错误
                if hasattr(self, 'obj_query_status_label'):
                    self.obj_query_status_label.setText("❌ 加载失败: 无效的对象API名称")
                return

        print(f"\n[DEBUG-对象查询] 🚀 开始加载数据 | 对象: '{api_name}' | filters: {filters}")
        # 存储客户端二次过滤条件
        self._obj_query_client_filters = client_filters or []
        filters_applied = bool(filters)

        # 更新状态标签显示正在加载
        if hasattr(self, 'obj_query_status_label'):
            from PyQt6.QtCore import QTimer
            filter_count = len(filters) if filters else 0
            self.obj_query_status_label.setText(f"⏳ 正在加载 {self.obj_query_object_combo.currentText()} 数据{f' (筛选条件: {filter_count}个)' if filter_count else ''}...")

        import threading
        cfg = load_config()
        fx_cfg = cfg.get('fxiaoke', {})
        crm = FXiaokeCRM(
            app_id=fx_cfg.get('app_id', 'FSAID_1323c1a'),
            app_secret=fx_cfg.get('app_secret', 'e7f4188d14704299b375c91ddda92cb0'),
            permanent_code=fx_cfg.get('permanent_code', 'E8B8D8536B0385D035657AC2528928F0'),
            admin_mobile=fx_cfg.get('admin_mobile', '15889740213')
        )

        # 读取字段管理配置
        crm_cfg_fields = cfg.get('fxiaoke', {}).get('crm_object_fields', {}).get(api_name, {})
        configured_fields = list(crm_cfg_fields.keys()) if crm_cfg_fields else []
        if not configured_fields:
            self.obj_query_all_data = []
            self._obj_query_client_filters = []
            if hasattr(self, 'obj_query_status_label'):
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self.obj_query_status_label.setText(
                    "⚠️ 未配置字段，请先在 设置→CRM设置→对象管理→字段配置 中添加字段"))
            # 清空表格
            if hasattr(self, 'obj_query_table'):
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self.obj_query_table.setRowCount(0))
            return
        field_projection = list(dict.fromkeys(configured_fields))
        # _id 为固定获取字段，所有对象始终请求
        if '_id' not in field_projection:
            field_projection.insert(0, '_id')
        for f in list(field_projection):
            if not f.endswith('__r') and f'{f}__r' not in field_projection:
                field_projection.append(f'{f}__r')

        # 从配置读取该对象的加载条数（默认使用全局 load_count，限制 1~10000）
        obj_settings = fx_cfg.get('obj_query_settings', {}).get(api_name, {})
        global_load_default = int(fx_cfg.get('load_count', 10000))
        max_records = int(obj_settings.get('max_records', global_load_default))
        max_records = max(1, min(max_records, 10000))

        def _fetch():
            data, total, err = crm.fetch_all_data_object(
                data_object_api_name=api_name,
                max_records=max_records,
                batch_size=min(100, max_records),
                filters=filters if filters else None,
                field_projection=field_projection,
                is_custom=is_custom
            )

            if err:
                self.obj_query_all_data = []  # 确保清空，不残留旧数据
                if hasattr(self, 'obj_query_source_label'):
                    self.obj_query_source_label.setText("❌ API 加载失败")
                self.update_output.emit(f"[对象查询] {api_name} 加载失败: {err}")
                if hasattr(self, 'obj_query_status_label'):
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda e=err: self.obj_query_status_label.setText(
                        f"❌ 加载失败: {e[:30]}"))
                self.obj_query_data_ready.emit(api_name)
                return

            # ✅【核心】保存数据到实例变量
            self.obj_query_all_data = data or []
            self._obj_query_mem_cache[api_name] = self.obj_query_all_data
            if hasattr(self, 'obj_query_source_label'):
                self.obj_query_source_label.setText(f"☁️ CRM API | {len(data) if data else 0} 条")
            if not hasattr(self, '_obj_query_filter_empty_messages'):
                self._obj_query_filter_empty_messages = {}
            if filters_applied and not self.obj_query_all_data:
                empty_msg = "⚠️ 筛选条件未匹配到数据，已返回空结果"
                self._obj_query_filter_empty_messages[api_name] = empty_msg
                self.update_output.emit(f"[对象查询] {api_name}: {empty_msg}")
                print(f"[对象查询] {api_name}: {empty_msg}")
            else:
                self._obj_query_filter_empty_messages.pop(api_name, None)

            count = len(self.obj_query_all_data)
            print(f"[DEBUG-对象查询] ✅ 数据加载完成 | 对象: '{api_name}' | 记录数: {count}")

            # ✅【关键修复】通过信号将表格填充调度到主线程（QTimer.singleShot 在守护线程中无事件循环，不会触发）
            self.obj_query_data_ready.emit(api_name)

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()


    def _debounced_obj_query_filter_populate(self):
        """防抖后执行筛选面板的表格重填充（避免每次输入都重建表格）"""
        self._obj_query_populate_table(rebuild_columns=False)


    def _obj_query_populate_table(self, rebuild_columns=True):
        """填充对象查询表格。rebuild_columns=False 时仅更新行数据，不重建列结构和搜索下拉框。"""
        data = getattr(self, 'obj_query_all_data', [])

        # ✅【关键调试】打印数据状态
        print(f"\n[DEBUG-表格填充] 🚀 _obj_query_populate_table() 开始执行")
        print(f"   数据行数: {len(data)}")
        print(f"   _obj_query_all_api_fields: {getattr(self, '_obj_query_all_api_fields', None) is not None}")
        print(f"   _obj_query_display_headers: {getattr(self, '_obj_query_display_headers', None) is not None}")
        print(f"   _obj_query_display_to_api: {getattr(self, '_obj_query_display_to_api', None) is not None}")
        print(f"   _obj_query_visible_headers: {getattr(self, '_obj_query_visible_headers', None)}")

        if not data:
            print(f"[DEBUG-表格填充] ⚠️ 数据为空，显示空白表格")
            self.obj_query_table.setColumnCount(0)
            self.obj_query_table.setRowCount(0)
            self.obj_query_page_label.setText("0/0")
            return

        # 首次加载时建立稳定的字段映射（之后不再重新计算）
        # ✅【关键】检查是否需要重建字段映射
        need_rebuild = getattr(self, '_obj_query_all_api_fields', None) is None

        if need_rebuild:
            api_name = self.obj_query_object_combo.currentData() or ''
            field_name_map = {}
            if api_name:
                cfg = load_config()
                saved_fields = cfg.get('fxiaoke', {}).get('crm_object_fields', {}).get(api_name, {})

                if saved_fields:
                    for api_key, field_info in saved_fields.items():
                        if isinstance(field_info, dict):
                            display = field_info.get('label', '') or field_info.get('display_name', '')
                        else:
                            display = str(field_info) if field_info else ''
                        if display:
                            field_name_map[api_key] = display

                field_type_map = {}
                user_ref_name_set = {'owner', 'created_by', 'last_modified_by', 'submit_by', 'belong_to'}
                crm_fields = self._get_crm_object_fields_cached(api_name)
                for f in crm_fields:
                    if isinstance(f, dict):
                        f_name = f.get('apiName', '') or f.get('name', '')
                        f_type = f.get('type', '') or f.get('dataType', '')
                        f_ref_to = f.get('referenceTo', '')
                        f_label = f.get('label', '')
                        if f_name:
                            f_type_lower = f_type.lower()
                            f_ref_to_lower = f_ref_to.lower() if f_ref_to else ''
                            is_user_ref = (
                                (f_type_lower in ('reference', 'lookup', 'masterdetail') and f_ref_to_lower in {'user', 'employee'})
                                or f_name.rstrip('_r').rstrip('_') in user_ref_name_set
                            )
                            if is_user_ref:
                                field_type_map[f_name] = 'user_ref'
                                if f_name.endswith('__r'):
                                    field_type_map[f_name[:-2]] = 'user_ref'
                            elif f_type_lower in ('datetime', 'timestamp', 'date_time'):
                                field_type_map[f_name] = 'datetime'
                            elif f_type_lower in ('date', 'dateonly'):
                                field_type_map[f_name] = 'date'
                            else:
                                field_type_map[f_name] = f_type
                            if f_name.endswith('__r'):
                                f_name_clean = f_name[:-2]
                                if f_name_clean not in field_type_map:
                                    field_type_map[f_name_clean] = f_type
                        if f_name and f_label and f_name not in field_name_map:
                            field_name_map[f_name] = f_label

                print(f"\n   📊 最终 field_name_map 统计: {len(field_name_map)} 个映射")
                type_dist = {}
                for v in field_type_map.values():
                    type_dist[v] = type_dist.get(v, 0) + 1
                print(f"   📊 field_type_map 统计: {len(field_type_map)} 个映射 | 类型分布: {type_dist}")

                # ✅ 存储字段类型映射，供单元格填充时使用
                self._obj_query_field_type_map = field_type_map

            # ✅【全新方案】保持原始字段键不变，在显示时智能匹配字段配置
            # CRM返回的关联对象字段键可能包含 __r（如 field_VS5oH__c__r）
            # 用户在字段管理中配置的是标准格式（如 field_VS5oH__c → "客户类型"）
            # 匹配逻辑：先直接匹配，再尝试去除 __r/_r 后匹配

            all_api_fields = []
            _meta_keys = {'_id', '_from_mapped_cache', 'mapped_at'}
            for row in data:
                for key in row.keys():
                    if key not in all_api_fields and key not in _meta_keys:
                        all_api_fields.append(key)
            # 过滤无意义的 __r 字段：仅当基字段值为 dict（引用类型）时才保留 __r 变体
            # 通过检查实际数据判断（非元数据），预设对象和自定义对象行为一致
            ref_base_fields = set()
            for row in data:
                for k, v in row.items():
                    if isinstance(v, dict) and not k.endswith('__r'):
                        ref_base_fields.add(k)
            _filtered_fields = []
            for f in all_api_fields:
                if f.endswith('__r'):
                    base = f[:-3]  # 去掉 '__r' 得到基字段名
                    if base not in ref_base_fields:
                        continue  # 非引用字段的 __r 变体，跳过
                _filtered_fields.append(f)
            all_api_fields = _filtered_fields

            # ✅【核心函数】智能查找字段显示名称（增强版）
            def get_field_display_name(api_key, name_map):
                """
                智能查找字段的显示名称，支持多种格式匹配：
                1. 直接用 api_key 查找
                2. 去除末尾 __r 或 _r 后查找
                3. 去除末尾多余下划线后查找（如 resource_ → resource）
                4. 组合尝试各种变体
                """
                # ✅【调试】对关键字段详细跟踪
                is_debug = any(kw in api_key.lower() for kw in ['resource', 'lock_status', 'payment', 'logistics', '__r', '_r'])

                if is_debug:
                    print(f"\n   🔍 [匹配跟踪] 处理字段: '{api_key}' (长度: {len(api_key)})")
                    print(f"      name_map 包含的键示例: {[k for k in list(name_map.keys())[:10]]}")

                # 方式1：直接匹配
                if api_key in name_map:
                    if is_debug:
                        print(f"      ✅ 方式1成功: 直接匹配到 '{name_map[api_key]}'")
                    return name_map[api_key]

                # ✅【增强】生成所有可能的变体进行匹配
                variants = []

                # 变体A：原始键
                variants.append(('原始', api_key))

                # 变体B：去除 __r 或 _r
                test_key = api_key
                if test_key.endswith('__r'):
                    test_key = test_key[:-2]
                    variants.append(('去__r', test_key))
                elif test_key.endswith('_r'):
                    test_key = test_key[:-2]
                    variants.append(('去_r', test_key))

                # 变体C：去除所有末尾下划线
                stripped = test_key.rstrip('_')
                if stripped != test_key:
                    variants.append(('去尾部_', stripped))

                # 变体D：组合 - 先去 __r 再去所有 _
                combined = api_key
                if combined.endswith('__r'):
                    combined = combined[:-2]
                elif combined.endswith('_r'):
                    combined = combined[:-2]
                combined = combined.rstrip('_')
                if combined not in [v[1] for v in variants]:
                    variants.append(('组合处理', combined))

                # ✅【调试】打印所有变体
                if is_debug:
                    print(f"      🔧 生成的匹配变体:")
                    for var_name, var_key in variants:
                        status = "✅ 在name_map中" if var_key in name_map else "❌ 不在"
                        print(f"         {var_name}: '{var_key}' → {status}")

                # 尝试每个变体
                for var_name, var_key in variants:
                    if var_key != api_key and var_key in name_map:
                        print(f"[DEBUG-对象查询] 🔧 字段匹配成功({var_name}) | 原始: '{api_key}' → 配置: '{var_key}' → 显示: '{name_map[var_key]}'")
                        return name_map[var_key]

                # 都没找到，返回原始键
                if is_debug:
                    print(f"      ⚠️ 最终结果: 所有变体均未匹配，使用原始键 '{api_key}'")
                return api_key

            # 使用智能匹配获取显示名称
            display_headers = [get_field_display_name(f, field_name_map) for f in all_api_fields]

            # ✅ 去重：同一显示名只保留第一条（基础字段优先于 __r 变体）
            seen = set()
            deduped = []
            for api_f, disp_h in zip(all_api_fields, display_headers):
                if disp_h not in seen:
                    seen.add(disp_h)
                    deduped.append((api_f, disp_h))
            all_api_fields = [d[0] for d in deduped]
            display_headers = [d[1] for d in deduped]

            # ✅【调试信息】打印字段映射详情
            print(f"\n[DEBUG-对象查询] 📊 字段映射详情 (共 {len(all_api_fields)} 个字段):")
            matched_count = 0
            for i, (api_f, disp_h) in enumerate(zip(all_api_fields, display_headers)):
                is_matched = (api_f != disp_h)
                if is_matched:
                    matched_count += 1
                # 只打印前10个 + 包含特殊字符的
                if i < 10 or '__r' in api_f or '_r' in api_f or 'resource' in api_f.lower() or 'payment' in api_f.lower() or 'logistics' in api_f.lower():
                    status = "✅ 已配置" if is_matched else "❌ 未配置"
                    print(f"   #{i:3d} | {api_f:<30s} → {disp_h:<20s} | {status}")
            if len(all_api_fields) > 10:
                print(f"   ... 还有 {len(all_api_fields) - 10} 个字段")
            print(f"[DEBUG-对象查询] 📈 统计: 总字段={len(all_api_fields)} | 已自定义={matched_count} | 未配置={len(all_api_fields)-matched_count}\n")

            self._obj_query_all_api_fields = all_api_fields
            self._obj_query_display_headers = display_headers
            # 注意：display_to_api 的值是原始API键，用于后续数据访问
            self._obj_query_display_to_api = dict(zip(display_headers, all_api_fields))

            print(f"[DEBUG-对象查询] ✅ 字段映射建立完成 | 总字段数: {len(all_api_fields)}")
        # 使用稳定的映射
        all_api_fields = self._obj_query_all_api_fields
        display_headers = self._obj_query_display_headers
        display_to_api = self._obj_query_display_to_api
        # 条件筛选
        filtered = data
        conditions = self._collect_obj_query_conditions()
        # 合并 API 请求时的客户端二次过滤条件
        client_filters = getattr(self, '_obj_query_client_filters', [])
        if client_filters:
            conditions = conditions + [c for c in client_filters if c not in conditions]
        if conditions:
            # 建立显示名 → API key 的反向映射（值是原始键）
            display_to_api = {display_headers[i]: all_api_fields[i] for i in range(len(all_api_fields))}
            # 建立反向选项映射：option_id → display_text（用于"属于"等客户端筛选，缓存避免每次重建）
            api_name = self.obj_query_object_combo.currentData() or ''
            reverse_option_cache_key = getattr(self, '_reverse_option_map_key', None)
            if reverse_option_cache_key != api_name:
                self._reverse_option_map_cache = {}
                self._reverse_option_map_key = api_name
                if api_name:
                    option_mappings = self.config.get('fxiaoke', {}).get('crm_option_mappings', {}).get(api_name, {})
                    if option_mappings:
                        field_config = self.config.get('fxiaoke', {}).get('crm_object_fields', {}).get(api_name, {})
                        for fk, mappings in option_mappings.items():
                            if not isinstance(mappings, dict):
                                continue
                            fk_label = fk
                            fi = field_config.get(fk)
                            if isinstance(fi, dict):
                                fk_label = fi.get('label', fk).strip() or fk
                            elif isinstance(fi, str) and fi.strip():
                                fk_label = fi.strip()
                            rev = {str(option_id): str(text).strip() for option_id, text in mappings.items() if str(text).strip()}
                            if rev:
                                self._reverse_option_map_cache[fk_label] = rev
            reverse_option_map = self._reverse_option_map_cache
            cond_filtered = []
            for row in filtered:
                match = True
                for cond in conditions:
                    f = cond['field']
                    op = cond['operator']
                    v = cond['value'].lower()
                    api_key = display_to_api.get(f, f)  # 直接使用原始键
                    # 引用字段优先使用 __r / _r 变体的显示名称，而非原始 ID
                    cell_val = str(row.get(api_key, '') or '').lower()
                    for suffix in ('__r', '_r'):
                        r_key = f'{api_key}{suffix}'
                        if r_key in row and row[r_key] is not None:
                            r_val = row[r_key]
                            if isinstance(r_val, dict):
                                cell_val = str(r_val.get('name', r_val)).lower()
                            elif r_val:
                                cell_val = str(r_val).lower()
                            break
                    # "属于"/"不属于"：尝试用反向选项映射把 cell 的 option_id 转为显示文本再比较
                    if op in ('in', 'not_in') and f in reverse_option_map:
                        id_to_text = reverse_option_map[f]
                        cell_raw = str(row.get(api_key, '') or '').strip()
                        if cell_raw in id_to_text:
                            cell_val = id_to_text[cell_raw].lower()
                    if op == 'contains' and v not in cell_val: match = False
                    elif op == 'not_contains' and v in cell_val: match = False
                    elif op == 'eq' and cell_val != v: match = False
                    elif op == 'ne' and cell_val == v: match = False
                    elif op == 'in':
                        in_values = {x.strip() for x in v.split(',') if x.strip()}
                        if cell_val not in in_values: match = False
                    elif op == 'starts_with' and not cell_val.startswith(v): match = False
                    elif op == 'ends_with' and not cell_val.endswith(v): match = False
                    elif op == 'empty' and cell_val: match = False
                    elif op == 'not_empty' and not cell_val: match = False
                    elif op in ('lt', 'gt', 'lte', 'gte', 'date_before', 'date_after'):
                        # 日期比较：尝试解析 cell 值和筛选值为时间戳/日期进行比较
                        cell_ts = self._parse_date_to_ts(cell_val)
                        filter_ts = self._parse_date_to_ts(v)
                        if cell_ts is not None and filter_ts is not None:
                            if op in ('lt', 'date_before') and not (cell_ts < filter_ts): match = False
                            elif op in ('gt', 'date_after') and not (cell_ts > filter_ts): match = False
                            elif op == 'lte' and not (cell_ts <= filter_ts): match = False
                            elif op == 'gte' and not (cell_ts >= filter_ts): match = False
                    elif op == 'date_range':
                        parts = v.split('~')
                        if len(parts) == 2:
                            cell_ts = self._parse_date_to_ts(cell_val)
                            start_ts = self._parse_date_to_ts(parts[0].strip() + ' 00:00:00')
                            end_ts = self._parse_date_to_ts(parts[1].strip() + ' 23:59:59')
                            if cell_ts is not None and start_ts is not None and end_ts is not None:
                                if not (start_ts <= cell_ts <= end_ts): match = False
                            else:
                                # 回退到字符串比较
                                if not (parts[0].strip() <= cell_val <= parts[1].strip()): match = False
                    elif op == 'past_n_days':
                        from datetime import datetime, timedelta
                        try:
                            n = int(v)
                            cell_ts = self._parse_date_to_ts(cell_val)
                            now_ts = int(datetime.now().timestamp() * 1000)
                            past_ts = int((datetime.now() - timedelta(days=n)).timestamp() * 1000)
                            if cell_ts is not None:
                                if not (past_ts <= cell_ts <= now_ts): match = False
                        except (ValueError, TypeError):
                            pass
                    if not match: break
                if match: cond_filtered.append(row)
            filtered = cond_filtered
        # 搜索过滤（在条件筛选结果上进一步过滤）
        search_text = self.obj_query_search_input.text().strip().lower() if hasattr(self, 'obj_query_search_input') else ''
        if search_text:
            filtered = [r for r in filtered if any(search_text in str(v or '').lower() for v in r.values())]
        # 分页
        page_size = self._get_combo_page_size(self.obj_query_page_size)
        total = len(filtered)
        max_page = max(1, (total + page_size - 1) // page_size)
        cur_page = getattr(self, 'obj_query_current_page', 1)
        if cur_page > max_page:
            cur_page = max_page
            self.obj_query_current_page = max_page
        start = (cur_page - 1) * page_size
        end = min(start + page_size, total)
        page_data = filtered[start:end]

        # ✅【关键调试】打印分页和过滤结果
        print(f"[DEBUG-表格填充] 📊 分页信息 | 总记录: {total} | 当前页: {self.obj_query_current_page} | 每页: {page_size} | 最大页: {max_page}")
        print(f"[DEBUG-表格填充] 📄 本页数据行数: {len(page_data)} (第{start+1}-{end}行)")

        # 确定可见列（与 CRM _get_crm_display_headers 一致）
        visible_labels = getattr(self, '_obj_query_visible_headers', None) or list(display_headers)
        print(f"[DEBUG-表格填充] 🔍 过滤前可见字段数: {len(visible_labels)}")
        if len(visible_labels) > 0:
            print(f"   前5个字段: {visible_labels[:5]}")

        visible_labels = [h for h in visible_labels if h in display_to_api]
        print(f"[DEBUG-表格填充] ✅ 过滤后可见字段数: {len(visible_labels)}")

        # ✅【关键修复】如果过滤后可见字段为空，使用完整字段列表作为备选
        if len(visible_labels) == 0:
            print(f"[WARNING-表格填充] ⚠️ 可见字段为空，使用完整字段列表作为备选")
            visible_labels = list(display_headers)
            print(f"[DEBUG-表格填充] 🔄 备选后可见字段数: {len(visible_labels)}")
            if len(visible_labels) > 0:
                print(f"   前5个字段: {visible_labels[:5]}")

        # 更新搜索字段下拉（仅在需要重建列结构时）
        if rebuild_columns and hasattr(self, 'obj_query_search_field'):
            self.obj_query_search_field.blockSignals(True)
            self.obj_query_search_field.clear()
            for h in visible_labels:
                self.obj_query_search_field.addItem(h, display_to_api.get(h, h))
            self.obj_query_search_field.setCurrentIndex(0)
            self.obj_query_search_field.blockSignals(False)
        # === 列重建 + 数据填充 ===
        table = self.obj_query_table
        old_cols = table.columnCount()
        new_cols = len(visible_labels)
        print(f"[DEBUG-表格填充] 📋 表格列数变化: {old_cols} → {new_cols}")
        # 如果列数变化（或强制重建），则重建列结构
        need_rebuild_cols = rebuild_columns or (old_cols != new_cols)
        if need_rebuild_cols and old_cols != new_cols:
            table.setColumnCount(new_cols)
        if need_rebuild_cols:
            table.setHorizontalHeaderLabels(visible_labels)
        table.setRowCount(len(page_data))
        print(f"[DEBUG-表格填充] ✅ 表格已设置 | 列数: {new_cols} | 行数: {len(page_data)}")

        field_type_map = getattr(self, '_obj_query_field_type_map', {})
        user_ref_name_set = {'owner', 'created_by', 'last_modified_by', 'submit_by', 'belong_to'}
        obj_api_name = self.obj_query_object_combo.currentData() or ''
        # 加载当前对象的选项映射
        option_mappings = {}
        if obj_api_name:
            option_mappings = self.config.get('fxiaoke', {}).get('crm_option_mappings', {}).get(obj_api_name, {})
        for row_idx, row in enumerate(page_data):
            for col_idx, label in enumerate(visible_labels):
                api = display_to_api.get(label, label)
                raw_value = row.get(api, '')
                # 0️⃣ 最优先：字段明细映射（用户自定义的选项值映射）
                field_mappings = option_mappings.get(api, {})
                if field_mappings:
                    raw_str = str(raw_value).strip() if raw_value else ''
                    if raw_str and raw_str in field_mappings:
                        display_value = field_mappings[raw_str]
                        table.setItem(row_idx, col_idx, QTableWidgetItem(display_value))
                        continue
                ftype = field_type_map.get(api, '')
                # 1️⃣ 最可靠的检测：数据行中是否存在 __r 关联数据
                if not api.endswith('__r') and f'{api}__r' in row:
                    ref_val = row.get(f'{api}__r')
                    if ref_val is not None and ref_val != '':
                        ftype = 'user_ref'
                # 2️⃣ 字段名兜底：已知的用户字段名
                api_clean = api.rstrip('_r').rstrip('_')
                if ftype != 'user_ref' and api_clean in user_ref_name_set:
                    ftype = 'user_ref'
                # 3️⃣ 标签/字段名兜底：时间/日期字段
                label_lower = label.lower()
                if ftype not in ('user_ref', 'datetime', 'date'):
                    if any(kw in label for kw in ('时间', '日期')) or any(kw in label_lower for kw in ('time', 'date')):
                        ftype = 'datetime'
                    elif any(kw in api_clean for kw in ('create_time', 'update_time', 'modify_time', 'submit_time')):
                        ftype = 'datetime'
                # 按类型格式化
                if ftype == 'user_ref':
                    ref_val = row.get(f'{api}__r')
                    if ref_val is not None and ref_val != '':
                        display_value = self._extract_display_value(ref_val)
                    else:
                        display_value = self._extract_display_value(raw_value)
                elif ftype in ('datetime', 'timestamp'):
                    display_value = self._format_timestamp(raw_value)
                elif ftype == 'date':
                    display_value = self._format_date(raw_value)
                else:
                    display_value = self._auto_format_value(raw_value)
                table.setItem(row_idx, col_idx, QTableWidgetItem(display_value))
        self.obj_query_page_label.setText(f"{self.obj_query_current_page}/{max_page}")


    def _format_timestamp(self, value):
        """将 Unix 毫秒时间戳转换为 yyyy-mm-dd HH:MM:SS 格式"""
        if value is None:
            return ''
        try:
            ts = float(value)
            if ts <= 0:
                return str(value)
            if ts > 1e14:
                ts = ts / 1000000
            elif ts > 1e11:
                ts = ts / 1000
            dt = datetime.fromtimestamp(ts)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OSError, OverflowError):
            return str(value)


    def _format_date(self, value):
        """将 Unix 毫秒时间戳转换为 yyyy-mm-dd 日期格式"""
        if value is None:
            return ''
        try:
            ts = float(value)
            if ts <= 0:
                return str(value)
            if ts > 1e14:
                ts = ts / 1000000
            elif ts > 1e11:
                ts = ts / 1000
            dt = datetime.fromtimestamp(ts)
            return dt.strftime('%Y-%m-%d')
        except (ValueError, OSError, OverflowError):
            return str(value)


    def _auto_format_value(self, value):
        """兜底检测：值本身是否像时间戳（13位毫秒级数字）"""
        if value is None:
            return ''
        try:
            if isinstance(value, (int, float)):
                s = str(int(value))
                if len(s) == 13 and s.startswith('1'):
                    return self._format_timestamp(value)
                if len(s) == 10 and s.startswith('1'):
                    return self._format_timestamp(value)
            if isinstance(value, str) and value.strip().isdigit():
                s = value.strip()
                if len(s) == 13 and s.startswith('1'):
                    return self._format_timestamp(int(s))
                if len(s) == 10 and s.startswith('1'):
                    return self._format_timestamp(int(s))
        except Exception:
            pass
        return self._extract_display_value(value)


    def _extract_display_value(self, value):
        """
        智能提取显示值：过滤非中文内容，只保留有意义的中文字段

        【功能说明】：
        CRM返回的数据中，很多字段包含复杂的JSON结构、ID、英文等，
        用户希望表格中只显示直观的中文名称。

        【处理规则】：
        1. 空值 → 返回空字符串
        2. 简单字符串 → 提取其中的中文部分
        3. JSON格式字符串（列表/字典）→ 解析后提取所有中文值
        4. 列表/字典类型 → 递归提取中文值

        【示例】：

        输入: "[{'id': '-10000', 'name': '系统'}]"
        输出: "系统"

        输入: "[{'id': '1408', 'name': '古俊峰', 'dept': '1032', ...}]"
        输出: "古俊峰"

        输入: "FS02087"
        输出: "FS02087" (无中文则保留原值)

        输入: "option1"
        输出: "option1" (无中文则保留原值)
        """
        if value is None:
            return ''

        # 转换为字符串处理
        str_value = str(value).strip()

        # 空值检查
        if not str_value or str_value.lower() in ['none', 'null', '']:
            return ''

        # 尝试解析JSON格式的字符串
        if (str_value.startswith('[') and str_value.endswith(']')) or \
           (str_value.startswith('{') and str_value.endswith('}')):
            try:
                import ast
                parsed = ast.literal_eval(str_value)
                result = self._extract_chinese_from_struct(parsed)
                if result:
                    return result
            except Exception as e:
                # ✅【调试】打印解析失败详情
                print(f"[DEBUG-数据过滤] ⚠️ JSON解析失败 | 错误: {str(e)}")
                print(f"   原始值(前100字符): {str_value[:100]}")
                pass  # 解析失败，继续其他处理

        # 检查是否包含中文
        chinese_text = self._extract_chinese_chars(str_value)
        if chinese_text:
            return chinese_text.replace('|', ', ')

        # 无中文，返回原值
        return str_value.replace('|', ', ')


    def _extract_chinese_from_struct(self, data):
        """
        从复杂的数据结构（列表/字典）中提取中文字段值

        【优先级】：
        1. name 字段（最可能是名称）
        2. nickname 字段（昵称）
        3. 其他包含中文的字段
        """
        # ✅【调试】打印数据类型和结构
        is_debug = True  # 调试时开启
        if is_debug:
            print(f"\n[DEBUG-结构提取] 📥 输入数据类型: {type(data)}")
            if isinstance(data, list):
                print(f"   列表长度: {len(data)}")
                if len(data) > 0:
                    print(f"   第一个元素类型: {type(data[0])}")
                    if isinstance(data[0], dict):
                        print(f"   第一个元素的keys: {list(data[0].keys())[:5]}")

        if isinstance(data, list):
            # 处理列表
            chinese_values = []
            for idx, item in enumerate(data):
                if isinstance(item, dict):
                    # ✅【调试】打印每个元素的处理过程
                    if is_debug and idx < 3:
                        print(f"\n   🔍 处理列表第{idx}项:")

                    # 优先查找 name 和 nickname
                    found = False
                    for key in ['name', 'nickname']:
                        if key in item:
                            val = str(item[key])
                            chinese = self._extract_chinese_chars(val)
                            if chinese:
                                chinese_values.append(chinese)
                                found = True
                                if is_debug:
                                    print(f"      ✅ 找到字段 '{key}': '{val}' → 提取为: '{chinese}'")
                                break

                    if not found:
                        # 如果没有 name/nickname，遍历所有字段找中文
                        for v in item.values():
                            chinese = self._extract_chinese_chars(str(v))
                            if chinese and chinese not in chinese_values:
                                chinese_values.append(chinese)
                                if is_debug:
                                    print(f"      🔄 其他字段提取: '{chinese}'")
                                break

            # ✅【调试】打印最终结果
            if is_debug and chinese_values:
                print(f"\n   📊 提取到的中文值列表 ({len(chinese_values)}个): {chinese_values}")

            # 返回用逗号分隔的中文值
            if chinese_values:
                result = ', '.join(chinese_values[:5])  # 逗号+空格分隔，最多显示5个
                if is_debug:
                    print(f"   ✅ 最终返回: '{result}'")
                return result
            return ''

        elif isinstance(data, dict):
            # 处理单个字典
            for key in ['name', 'nickname']:
                if key in data:
                    val = str(data[key])
                    chinese = self._extract_chinese_chars(val)
                    if chinese:
                        return chinese

            # 遍历所有字段
            for v in data.values():
                chinese = self._extract_chinese_chars(str(v))
                if chinese:
                    return chinese
            return ''

        return ''


    def _extract_chinese_chars(self, text):
        """
        智能文本提取：保留有意义的业务数据（中文+数字+符号）

        【核心原则】：
        保留对用户有价值的信息，过滤无意义的纯英文/代码。

        【保留的内容】：
        ✅ 中文汉字（一-龥）
        ✅ 数字（0-9） - 重要！如：<7天、7-15天、100%
        ✅ 常用符号 - 重要！如：< > - / . : （）等
        ✅ 中文标点（，。！？等）

        【过滤的内容】：
        ❌ 纯英文单词（option1, CRM, True, False等）
        ❌ 无意义的字母组合

        【示例】：
        输入: "<7天内跟进"          → 输出: "<7天内跟进"     ✅ 完整保留
        输入: "7-15天内跟进"         → 输出: "7-15天内跟进"    ✅ 完整保留
        输入: "正常销售(option1)"    → 输出: "正常销售"       ✅ 过滤英文
        输入: "张三(已停用)"         → 输出: "张三(已停用)"     ✅ 保留括号
        输入: "FS02087"             → 输出: "FS02087"         ✅ 保留编号
        输入: "option1"             → 输出: ""                ✅ 过滤纯英文
        """
        import re
        if not text:
            return ''

        # ✅【核心】智能提取模式：保留中文 + 数字 + 有意义的符号
        # 匹配规则：
        # 1. 中文字符
        # 2. 数字（0-9）
        # 3. 常用业务符号：< > - / . : ( ) [ ] { } % # @ & * + = ! ? 等
        # 4. 中文标点
        smart_pattern = re.compile(
            r'[\u4e00-\u9fff'      # 基本汉字
            r'\u3400-\u4dbf'       # 扩展A区
            r'\uf900-\ufaff'       # 兼容区
            r'\u3000-\u303f'       # 中文标点
            r'\uff00-\uffef'       # 全角字符
            r'0-9'                 # 数字
            r'A-Za-z'              # 英文字母（保留ERP订单号等含字母编码）
            r' <>\-\./\:\(\)\[\]\{\}\%\#\@\&\*\+\=\!\?\,\。\;\_\|\''  # 常用符号（含空格+下划线+管道符，保留多选字段分隔）
            r']+',
            re.UNICODE
        )

        matches = smart_pattern.findall(text)

        if matches:
            result = ''.join(matches).strip()

            # 清理多余空格（如果有的话）
            result = re.sub(r'\s+', ' ', result)

            if len(result) >= 1:
                # ✅【调试】特殊字段跟踪
                is_debug = any(kw in text.lower() for kw in ['跟进', '周期', '天', 'status', '时间'])
                if is_debug:
                    print(f"[DEBUG-智能提取] 📊 提取结果 | 原始: '{text}' → 输出: '{result}'")

                return result

        return ''


    def _clean_for_sync(self, api_name, data):
        """按指定 API 加载字段映射并清洗数据 → 中文列名 + 清洗值。
        与 _get_obj_query_cleaned_data_bg 逻辑一致，但不依赖缓存的实例属性，
        始终从 config 加载当前 API 的字段配置，避免多对象混淆。

        返回: (cleaned_rows, display_headers, display_type_map)
        """
        if not data:
            return [], [], {}

        cfg = load_config()
        saved_fields = cfg.get('fxiaoke', {}).get('crm_object_fields', {}).get(api_name, {})
        field_name_map = {}
        field_type_map = {}
        for api_key, field_info in (saved_fields or {}).items():
            if isinstance(field_info, dict):
                label = field_info.get('label', '') or field_info.get('display_name', '')
                ftype = field_info.get('dataType', '') or field_info.get('field_type', '')
            else:
                label = str(field_info) if field_info else ''
                ftype = ''
            if label:
                field_name_map[api_key] = label
                if ftype:
                    field_type_map[api_key] = ftype
        if not field_name_map:
            # 未配置字段映射时，使用 CRM 原始数据的第一行 key 作为字段列表
            # （兼容自定义对象未在「字段管理」中配置的情况）
            if data and isinstance(data[0], dict):
                sample = data[0]
                for k in sample:
                    if k != '_id' and (k.startswith('_') or k.endswith('__r')):
                        continue
                    if k not in field_name_map:
                        field_name_map[k] = k
            if not field_name_map:
                return [], [], {}

        all_api_fields = list(field_name_map.keys())
        display_headers = list(field_name_map.values())
        display_to_api = dict(zip(display_headers, all_api_fields))
        user_ref_name_set = {'owner', 'created_by', 'last_modified_by', 'submit_by', 'belong_to'}
        option_mappings = self.config.get('fxiaoke', {}).get('crm_option_mappings', {}).get(api_name, {})

        cleaned_rows = []
        for row in data:
            cleaned = {'_id': str(row.get('_id', '')).strip()}
            for label in display_headers:
                api_key = display_to_api.get(label, label)
                raw_value = row.get(api_key, '')

                field_mappings = option_mappings.get(api_key, {})
                if field_mappings:
                    raw_str = str(raw_value).strip() if raw_value else ''
                    if raw_str and raw_str in field_mappings:
                        cleaned[label] = field_mappings[raw_str]
                        continue

                ftype = field_type_map.get(api_key, '')
                if not api_key.endswith('__r') and f'{api_key}__r' in row:
                    ref_val = row.get(f'{api_key}__r')
                    if ref_val is not None and ref_val != '':
                        ftype = 'user_ref'
                api_clean = api_key.rstrip('_r').rstrip('_')
                if ftype != 'user_ref' and api_clean in user_ref_name_set:
                    ftype = 'user_ref'
                label_lower = label.lower()
                if ftype not in ('user_ref', 'datetime', 'date'):
                    if any(kw in label for kw in ('时间', '日期')) or any(kw in label_lower for kw in ('time', 'date')):
                        ftype = 'datetime'
                    elif any(kw in api_clean for kw in ('create_time', 'update_time', 'modify_time', 'submit_time')):
                        ftype = 'datetime'

                if ftype == 'user_ref':
                    ref_val = row.get(f'{api_key}__r')
                    if ref_val is not None and ref_val != '':
                        cleaned[label] = self._extract_display_value(ref_val)
                    else:
                        cleaned[label] = self._extract_display_value(raw_value)
                elif ftype in ('datetime', 'timestamp'):
                    cleaned[label] = self._format_timestamp(raw_value)
                elif ftype == 'date':
                    cleaned[label] = self._format_date(raw_value)
                else:
                    cleaned[label] = str(raw_value) if raw_value is not None else ''
            cleaned_rows.append(cleaned)

        # 构建显示名 → CRM 类型映射（供下游写入数值字段用）
        display_type_map = {}
        if field_type_map and display_headers:
            for label in display_headers:
                api = display_to_api.get(label, label)
                ftype = field_type_map.get(api, '')
                if ftype:
                    display_type_map[label] = ftype

        return cleaned_rows, display_headers, display_type_map


    def _get_obj_query_cleaned_data_bg(self, api_name, data):
        """线程安全版本：将数据清洗为与表格展示一致的格式（中文表头+清洗值）。
        所有需要的值均通过参数传入，不访问 Qt 控件。

        返回: (cleaned_rows, display_headers, api_name, display_name)
        """
        if not data:
            return [], [], api_name, ''

        # 尝试使用缓存的映射，否则从配置加载
        all_api_fields = getattr(self, '_obj_query_all_api_fields', None)
        display_headers = getattr(self, '_obj_query_display_headers', None)
        field_name_map = {}  # API key → display label
        if not all_api_fields or not display_headers:
            cfg = load_config()
            saved_fields = cfg.get('fxiaoke', {}).get('crm_object_fields', {}).get(api_name, {})
            for api_key, field_info in (saved_fields or {}).items():
                if isinstance(field_info, dict):
                    label = field_info.get('label', '') or field_info.get('display_name', '')
                else:
                    label = str(field_info) if field_info else ''
                if label:
                    field_name_map[api_key] = label
            if not field_name_map:
                # 未配置字段映射时，使用 CRM 原始数据的第一行 key 作为字段列表
                if data and isinstance(data[0], dict):
                    sample = data[0]
                    for k in sample:
                        if k != '_id' and (k.startswith('_') or k.endswith('__r')):
                            continue
                        if k not in field_name_map:
                            field_name_map[k] = k
            if not field_name_map:
                return [], [], api_name, ''
            all_api_fields = list(field_name_map.keys())
            display_headers = list(field_name_map.values())
        else:
            # 缓存存在时，也构建 field_name_map 用于后续补充数据中的字段
            field_name_map = dict(zip(all_api_fields, display_headers))

        # ✅【关键修复】从实际数据中补全缓存/配置中缺失的字段
        # 确保 CRM 返回的所有有效字段都被同步到 MySQL，不依赖缓存是否完整
        existing_api_set = set(all_api_fields)
        _meta_keys = {'_id', '_from_mapped_cache', 'mapped_at'}
        added_from_data = 0
        for row in data:
            for key in row.keys():
                if key in _meta_keys or key in existing_api_set:
                    continue
                if key.endswith('__r'):
                    continue  # __r 变体由引用字段逻辑处理，不单独建列
                # 检查是否有对应的 __r 变体（引用字段），有则基字段可能是引用类型
                has_r_variant = f'{key}__r' in row or f'{key}_r' in row
                if has_r_variant and isinstance(row.get(f'{key}__r') or row.get(f'{key}_r'), dict):
                    continue  # 引用字段的基字段，由 user_ref 逻辑处理
                # 新字段：用 API key 自身作为显示名（后续可从 CRM 元数据补充）
                existing_api_set.add(key)
                all_api_fields.append(key)
                display_headers.append(key)
                field_name_map[key] = key
                added_from_data += 1
        if added_from_data:
            logging.info(f"[对象查询] MySQL 同步: 从数据中补全了 {added_from_data} 个字段 (缓存/配置中缺失)")

        visible_labels = getattr(self, '_obj_query_visible_headers', None) or list(display_headers)
        visible_labels = [h for h in visible_labels if h in dict(zip(display_headers, all_api_fields))]
        if not visible_labels:
            visible_labels = list(display_headers)

        # MySQL 清洗表始终写入全部已配置字段，而非仅可见字段
        # 否则 replace_cleaned_all 的 DROP COLUMN 逻辑会误删 JOIN 所需的列
        cleaned_headers = list(display_headers)

        display_to_api = dict(zip(display_headers, all_api_fields))
        field_type_map = getattr(self, '_obj_query_field_type_map', {})
        user_ref_name_set = {'owner', 'created_by', 'last_modified_by', 'submit_by', 'belong_to'}
        option_mappings = {}
        if api_name:
            option_mappings = self.config.get('fxiaoke', {}).get('crm_option_mappings', {}).get(api_name, {})

        cleaned_rows = []
        for row in data:
            cleaned = {'_id': str(row.get('_id', '')).strip()}
            for label in cleaned_headers:
                api = display_to_api.get(label, label)
                raw_value = row.get(api, '')

                field_mappings = option_mappings.get(api, {})
                if field_mappings:
                    raw_str = str(raw_value).strip() if raw_value else ''
                    if raw_str and raw_str in field_mappings:
                        cleaned[label] = field_mappings[raw_str]
                        continue

                ftype = field_type_map.get(api, '')
                if not api.endswith('__r') and f'{api}__r' in row:
                    ref_val = row.get(f'{api}__r')
                    if ref_val is not None and ref_val != '':
                        ftype = 'user_ref'
                api_clean = api.rstrip('_r').rstrip('_')
                if ftype != 'user_ref' and api_clean in user_ref_name_set:
                    ftype = 'user_ref'
                label_lower = label.lower()
                if ftype not in ('user_ref', 'datetime', 'date'):
                    if any(kw in label for kw in ('时间', '日期')) or any(kw in label_lower for kw in ('time', 'date')):
                        ftype = 'datetime'
                    elif any(kw in api_clean for kw in ('create_time', 'update_time', 'modify_time', 'submit_time')):
                        ftype = 'datetime'

                if ftype == 'user_ref':
                    ref_val = row.get(f'{api}__r')
                    if ref_val is not None and ref_val != '':
                        cleaned[label] = self._extract_display_value(ref_val)
                    else:
                        cleaned[label] = self._extract_display_value(raw_value)
                elif ftype in ('datetime', 'timestamp'):
                    cleaned[label] = self._format_timestamp(raw_value)
                elif ftype == 'date':
                    cleaned[label] = self._format_date(raw_value)
                else:
                    cleaned[label] = self._auto_format_value(raw_value)

            cleaned_rows.append(cleaned)

        return cleaned_rows, cleaned_headers, api_name, ''


    def _get_obj_query_cleaned_data(self):
        """将当前对象查询数据清洗为与表格展示一致的格式（中文表头+清洗值）。
        委托给 _get_obj_query_cleaned_data_bg，自身负责从 Qt 控件读取当前选中的对象名。
        """
        data = getattr(self, 'obj_query_all_data', [])
        if not data:
            return [], [], '', ''

        api_name = self.obj_query_object_combo.currentData() or ''
        display_name = self.obj_query_object_combo.currentText().strip()

        cleaned_rows, visible_labels, _api, _display = self._get_obj_query_cleaned_data_bg(api_name, data)
        return cleaned_rows, visible_labels, api_name, display_name


    def _get_obj_query_sync_mode(self):
        """获取当前同步模式：auto / manual"""
        if hasattr(self, 'obj_query_sync_mode_combo'):
            return self.obj_query_sync_mode_combo.currentData() or 'auto'
        return self.config.get('fxiaoke', {}).get('obj_query_sync_mode', 'auto')


    def _on_obj_query_sync_mode_changed(self):
        """同步模式切换时保存到配置"""
        mode = self._get_obj_query_sync_mode()
        cfg = load_config()
        cfg.setdefault('fxiaoke', {})['obj_query_sync_mode'] = mode
        save_config_with_delay(cfg)
        print(f"[对象查询] 同步模式切换为: {'自动同步' if mode == 'auto' else '手动同步'}")


    def _on_obj_query_load_count_changed(self, value):
        """加载条数变更 → 保存到当前对象的配置 + 实时同步到设置界面"""
        api_name = self.obj_query_object_combo.currentData()
        if not api_name:
            return
        cfg = load_config()
        obj_settings = cfg.setdefault('fxiaoke', {}).setdefault('obj_query_settings', {}).setdefault(api_name, {})
        obj_settings['max_records'] = value
        save_config_with_delay(cfg)
        print(f"[对象查询] 加载条数更新: '{api_name}' → {value} 条")
        # 实时同步到设置界面（同一对象时）
        self._sync_load_count_to_settings(api_name, value)


    def _do_obj_query_sync_to_mysql(self, api_name, data):
        """执行 MySQL 同步（JSON缓存表 + 清洗表），供手动同步和自动同步共用"""
        display_name = self.obj_query_object_combo.currentText().strip()
        self._do_obj_query_sync_to_mysql_bg(api_name, data, display_name)


    def _do_obj_query_sync_to_mysql_bg(self, api_name, data, display_name):
        """线程安全版本：在后台线程中执行 MySQL 同步。
        display_name 由主线程预先读取并传入，避免在后台线程访问 Qt 控件。
        返回 (success: bool, message: str) 供 task_completed 信号使用。
        """
        try:
            mc = MysqlCache()
            if not mc.available:
                self.update_output.emit(f"[对象查询] MySQL 未启用/无法连接，跳过同步")
                mc.close()
                return False, "MySQL 未启用"
            mc.upsert_all(api_name, data)
            self.update_output.emit(f"[对象查询] MySQL 原始缓存(JSON)已同步: {len(data)} 条")

            cleaned_rows, cleaned_headers, _obj_api, _display = self._get_obj_query_cleaned_data_bg(api_name, data)

            # 构建显示名 → CRM 类型映射，用于数值字段写入
            api_type_map = getattr(self, '_obj_query_field_type_map', {})
            display_type_map = {}
            if api_type_map and cleaned_headers:
                # 从配置获取 API→显示名映射
                cfg = load_config()
                saved_fields = cfg.get('fxiaoke', {}).get('crm_object_fields', {}).get(api_name, {})
                api_to_label = {}
                for api_key, field_info in (saved_fields or {}).items():
                    if isinstance(field_info, dict):
                        label = field_info.get('label', '') or field_info.get('display_name', '')
                    else:
                        label = str(field_info) if field_info else ''
                    if label:
                        api_to_label[api_key] = label
                for api_key, ftype in api_type_map.items():
                    label = api_to_label.get(api_key, api_key)
                    if label in cleaned_headers:
                        display_type_map[label] = ftype

            if cleaned_rows and cleaned_headers:
                table_name = f"对象-{display_name}"
                ok, msg = mc.replace_cleaned_all(table_name, cleaned_rows, cleaned_headers,
                                                  cleanup_old=False, field_type_map=display_type_map)
                if ok:
                    self.update_output.emit(f"[对象查询] MySQL 清洗表已同步: '{table_name}' {msg}")
                else:
                    self.update_output.emit(f"[对象查询] MySQL 清洗表同步失败: {msg}")
            mc.close()
            self.update_output.emit(f"[对象查询] MySQL 同步完成: '{api_name}' {len(data)} 条")
            return True, ""
        except Exception as e:
            self.update_output.emit(f"[对象查询] MySQL 同步异常: {str(e)[:80]}")
            logging.error(f"[对象查询] MySQL 同步失败: {e}")
            return False, str(e)[:200]


    def _on_obj_query_sync_to_mysql(self):
        """手动将当前对象查询数据同步到 MySQL 数据库（后台线程执行）"""
        api_name = self.obj_query_object_combo.currentData() or ''
        data = getattr(self, 'obj_query_all_data', [])
        if not api_name:
            QMessageBox.warning(self, "提示", "请先选择一个业务对象。")
            return
        if not data:
            QMessageBox.information(self, "提示", "当前没有数据可同步。")
            return

        # 同步按钮状态：同步中（任务完成时由 _on_mysql_sync_completed 恢复）
        if hasattr(self, 'obj_query_sync_btn'):
            self.obj_query_sync_btn.setText("⏳ 同步中...")
            self.obj_query_sync_btn.setEnabled(False)

        display_name = self.obj_query_object_combo.currentText().strip()
        self.update_output.emit(f"[对象查询] 手动同步 MySQL 开始: '{api_name}' {len(data)} 条")
        self.task_manager.start(
            f'mysql_sync_manual_{api_name}',
            f'MySQL手动同步: {display_name}',
            self._do_obj_query_sync_to_mysql_bg,
            api_name, data, display_name
        )


    def _on_obj_query_page_size_changed(self):
        """对象查询每页条数变更"""
        self.obj_query_current_page = 1
        self._save_page_sizes()
        self._obj_query_populate_table()


    def _on_obj_query_search(self):
        """搜索框输入变化"""
        self.obj_query_current_page = 1
        self._obj_query_populate_table()


    def _on_obj_query_manual_refresh(self):
        """
        手动刷新对象查询数据（强制重新加载并更新缓存）

        【功能说明】：
        用户点击"🔄 刷新"按钮时触发，强制重新从CRM API获取数据。

        【核心逻辑】：
        1. 清除当前对象的旧缓存
        2. 从CRM API重新获取最新数据
        3. 将新数据存入缓存
        4. 更新表格显示

        【使用场景】：
        - 首次进入对象查询后需要加载数据
        - 数据过期需要更新
        - 切换到新对象后需要加载数据
        """
        api_name = self.obj_query_object_combo.currentData() or ''
        if not api_name:
            QMessageBox.warning(self, "提示", "请先选择一个业务对象。")
            return

        # 刷新按钮状态：加载中
        if hasattr(self, 'obj_query_refresh_btn'):
            self.obj_query_refresh_btn.setText("⏳ 刷新中...")
            self.obj_query_refresh_btn.setEnabled(False)

        print(f"\n[DEBUG-对象查询] 🔄 用户点击手动刷新 | 对象: {api_name}")

        # 清除字段映射缓存，强制从配置文件重新读取最新设置
        self._reset_obj_query_field_mapping()

        # 清除内存缓存，强制从 CRM 重新获取
        if hasattr(self, '_obj_query_mem_cache'):
            self._obj_query_mem_cache.pop(api_name, None)

        # 清除 MySQL 缓存
        try:
            mc = MysqlCache()
            mc.clear(api_name)
            mc.close()
        except Exception:
            pass

        # 重置分页
        self.obj_query_current_page = 1

        # 清空旧数据
        self.obj_query_all_data = []

        # 强制重新获取数据（重置字段映射缓存，保留已保存的字段显示设置）
        self._reset_obj_query_field_mapping()

        # 重新加载数据：API 筛选仅从设置面板读取，UI 筛选面板做客户端过滤
        api_filters = self._build_api_filters_from_settings(api_name)
        build_message = getattr(self, '_obj_query_filter_build_message', '')
        if build_message:
            self._show_obj_query_empty_filter_result(api_name, build_message)
            return
        self._obj_query_fetch_data(api_name, filters=api_filters if api_filters else None)

        print(f"[DEBUG-对象查询] ✅ 手动刷新完成 | 数据已重新加载并缓存")

    # ===== 快捷筛选器（加载条数后面的内联标签） =====


    # ── 筛选面板操作方法（兼容旧 API，委托给 FilterPanel） ──

    # 操作符常量（供 FilterConditionRow 使用）
    obj_query_text_ops = [
        ("包含", "contains"), ("不包含", "not_contains"),
        ("等于", "eq"), ("不等于", "ne"),
        ("属于", "in"),
        ("开头是", "starts_with"), ("结尾是", "ends_with"),
        ("为空", "empty"), ("不为空", "not_empty"),
    ]

    obj_query_date_ops = [
        ("等于", "eq"), ("不等于", "ne"),
        ("早于", "date_before"), ("晚于", "date_after"),
        ("区间", "date_range"),
        ("过去N天", "past_n_days"),
        ("为空", "empty"), ("不为空", "not_empty"),
    ]

    def _obj_query_is_date_field(self, display_name):
        """FilterConditionRow 回调：判断字段是否为日期类型。"""
        return self._get_obj_query_field_type(display_name) in (
            'datetime', 'date', 'timestamp', 'date_time', 'dateonly')

    def _obj_query_on_row_picker(self, row):
        """FilterConditionRow 回调：多选按钮点击。"""
        f_combo = row.field_combo
        f_display = f_combo.currentText().strip()
        display_to_api = (getattr(self, '_obj_query_display_to_api', None) or {})
        f_key = display_to_api.get(f_display, f_display)
        obj_api = self.obj_query_object_combo.currentData() or ''
        mappings = self.config.get('fxiaoke', {}).get(
            'crm_option_mappings', {}).get(obj_api, {}).get(f_key, {})
        if not mappings:
            mappings = self.config.get('business_rules', {}).get(
                'crm_option_mappings', {}).get(f_key, {})
        if not mappings:
            field_config = self.config.get('fxiaoke', {}).get(
                'crm_object_fields', {}).get(obj_api, {})
            for fk, fi in field_config.items():
                lbl = (fi.get('label', fk) if isinstance(fi, dict) else str(fi)) if fi else fk
                if lbl.strip() == f_display.strip():
                    mappings = self.config.get('fxiaoke', {}).get(
                        'crm_option_mappings', {}).get(obj_api, {}).get(fk, {})
                    if not mappings:
                        mappings = self.config.get('business_rules', {}).get(
                            'crm_option_mappings', {}).get(fk, {})
                    break
        if mappings:
            current = row.text_input.text().strip()
            show_multi_select_dropdown(self, mappings, current,
                                       anchor=row.text_input,
                                       target_input=row.text_input,
                                       on_change=lambda: self._schedule_obj_query_filter_populate())

    # ── 兼容方法（委托给 FilterPanel） ──

    def _toggle_obj_query_filter_panel(self):
        """切换筛选面板 — 以独立弹窗形式弹出在原位置。"""
        if not hasattr(self, '_obj_query_filter_panel'):
            return

        panel = self._obj_query_filter_panel._panel_frame
        visible = panel.isVisible()

        if not visible:
            # 打开前先刷新字段列表
            self._sync_obj_query_filter_fields()

            # 动态调整高度
            self._obj_query_filter_panel._adjust_panel_height()

            # 将 panel_frame 提升为独立窗口弹窗
            panel.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            panel.setVisible(True)
            panel.raise_()
            panel.activateWindow()

            # 定位在筛选按钮下方
            p = self.obj_query_filter_btn.mapToGlobal(
                QPoint(0, self.obj_query_filter_btn.height()))
            x, y = p.x(), p.y() + 4
            screen = self.screen()
            if screen:
                geo = screen.availableGeometry()
                x = max(geo.x() + 10, min(x, geo.right() - 500 - 10))
                y = max(geo.y() + 10, min(y, geo.bottom() - panel.height() - 10))
            panel.move(x, y)

            # 点击外部关闭事件过滤器
            if not hasattr(self, '_obj_panel_outside_filter'):
                panel.reject = lambda: panel.hide()
                self._obj_panel_outside_filter = common._DialogOutsideCloseFilter(panel)
            panel._outside_close_armed = False
            app = QApplication.instance()
            if app:
                app.installEventFilter(self._obj_panel_outside_filter)
            QTimer.singleShot(200, lambda: (
                setattr(panel, '_outside_close_armed', True)
                if not panel.isHidden() else None
            ))
        else:
            panel.hide()
            app = QApplication.instance()
            if app and hasattr(self, '_obj_panel_outside_filter'):
                app.removeEventFilter(self._obj_panel_outside_filter)
            panel._outside_close_armed = False

        self._update_obj_query_filter_btn()

    def _update_obj_query_filter_btn(self):
        """更新筛选按钮徽标（委托）。"""
        if hasattr(self, '_obj_query_filter_panel'):
            self._obj_query_filter_panel._update_toggle_badge()

    def _sync_obj_query_filter_fields(self):
        """同步搜索字段下拉框 → 筛选面板的字段选项。"""
        if not hasattr(self, '_obj_query_filter_panel'):
            return
        headers = []
        for i in range(self.obj_query_search_field.count()):
            data = self.obj_query_search_field.itemData(i)
            text = self.obj_query_search_field.itemText(i)
            if data and text != "全字段":
                headers.append((text, data))
        if headers:
            self._obj_query_filter_panel.set_available_fields(headers)

    def _add_obj_query_condition_row(self, condition=None):
        """添加一条筛选条件（委托）。"""
        if hasattr(self, '_obj_query_filter_panel'):
            row = self._obj_query_filter_panel.add_row(condition)
            # 自动连接行变化信号到弹窗刷新
            row.filtersChanged.connect(self._schedule_obj_query_filter_populate)
            # 行变化时刷新外露标签
            if row.expose_check:
                row.expose_check.toggled.connect(
                    lambda: self._refresh_obj_query_exposed_tags())
            # 操作符变化连接
            row.op_combo.currentIndexChanged.connect(
                lambda: self._obj_query_populate_table(rebuild_columns=False))
            return row

    def _remove_obj_query_condition_row(self, row_info):
        """移除一条筛选条件（委托）。"""
        if hasattr(self, '_obj_query_filter_panel'):
            if isinstance(row_info, FilterConditionRow):
                self._obj_query_filter_panel.remove_row(row_info)
            elif isinstance(row_info, dict) and 'row' in row_info:
                self._obj_query_filter_panel.remove_row(row_info['row'])
            else:
                # 回退：尝试在 _rows 中找到匹配
                pass
        self._update_obj_query_filter_btn()
        self._refresh_obj_query_exposed_tags()

    def _clear_obj_query_conditions(self):
        """清空所有条件（委托）。"""
        if hasattr(self, '_obj_query_filter_panel'):
            self._obj_query_filter_panel.clear_all()
        self._update_obj_query_filter_btn()
        self._refresh_obj_query_exposed_tags()

    def _collect_obj_query_conditions(self):
        """收集所有条件（委托）。"""
        if hasattr(self, '_obj_query_filter_panel'):
            return self._obj_query_filter_panel.get_all_conditions()
        return []

    def _refresh_obj_query_exposed_tags(self):
        """刷新外露标签（使用 ExposedTagsBar）。"""
        if not hasattr(self, '_obj_query_exposed_tags_bar'):
            return
        conds = self._collect_obj_query_conditions() if hasattr(
            self, '_obj_query_filter_panel') else []
        self._obj_query_exposed_tags_bar.refresh(conds)

    def _on_obj_query_exposed_tag_removed(self, cond):
        """外露标签被移除时，取消对应行的外露勾选。"""
        if hasattr(self, '_obj_query_filter_panel'):
            self._obj_query_filter_panel._on_exposed_tag_removed(cond)

    def _apply_obj_query_filter_and_close(self):
        """应用筛选面板条件 → 客户端过滤表格数据。"""
        self.obj_query_current_page = 1
        self._obj_query_populate_table()
        self._refresh_obj_query_exposed_tags()
        if hasattr(self, '_obj_query_filter_panel'):
            self._obj_query_filter_panel.set_panel_visible(False)

    def _schedule_obj_query_filter_populate(self):
        """启动防抖定时器，延迟重建筛选表格（250ms）。"""
        if hasattr(self, '_obj_query_filter_populate_timer'):
            self._obj_query_filter_populate_timer.stop()
            self._obj_query_filter_populate_timer.start(250)

    # ── 以下方法保持不变 ──

    def _on_obj_query_op_changed(self, ri, idx):
        """No-op: operator changes handled by FilterPanel internally."""
        pass
    def _update_obj_query_condition_input_mode(self, ri):
        """No-op: input mode is automatically handled by FilterPanel."""
        pass
    def _schedule_obj_query_filter_populate(self):
        """启动防抖定时器，延迟重建筛选表格（250ms）"""
        if hasattr(self, '_obj_query_filter_populate_timer'):
            self._obj_query_filter_populate_timer.stop()
            self._obj_query_filter_populate_timer.start(250)


    def _on_obj_query_op_changed(self, ri, idx):
        """操作符变化时切换值输入控件"""
        op = ri['op_combo'].itemData(idx) if idx >= 0 else 'contains'
        value_stack = ri['value_stack']
        if op in ('empty', 'not_empty'):
            value_stack.setCurrentIndex(0)
            value_stack.setEnabled(False)
        elif op == 'date_range':
            value_stack.setCurrentIndex(2)
            value_stack.setEnabled(True)
        elif op == 'in':
            # "属于" → 检查是否有选项映射，有则显示多选按钮
            f_display = ri['field_combo'].currentText().strip()
            display_to_api = (getattr(self, '_obj_query_display_to_api', None) or {})
            f_key = display_to_api.get(f_display, f_display)
            obj_api = self.obj_query_object_combo.currentData() or ''
            mappings = self.config.get('fxiaoke', {}).get('crm_option_mappings', {}).get(obj_api, {}).get(f_key, {})
            # 回退到 business_rules.crm_option_mappings（扁平结构）
            if not mappings:
                mappings = self.config.get('business_rules', {}).get('crm_option_mappings', {}).get(f_key, {})
            if 'picker_btn' in ri:
                ri['picker_btn'].setVisible(bool(mappings))
            value_stack.setCurrentIndex(0)
            value_stack.setEnabled(True)
        elif op == 'past_n_days':
            value_stack.setCurrentIndex(3)
            value_stack.setEnabled(True)
        elif op in ('date_before', 'date_after', 'lt', 'gt', 'lte', 'gte', 'eq', 'ne'):
            f = ri['field_combo'].currentText().strip()
            field_type = self._get_obj_query_field_type(f) if f else ''
            if field_type in ('datetime', 'date', 'timestamp', 'date_time', 'dateonly'):
                value_stack.setCurrentIndex(1)
            else:
                value_stack.setCurrentIndex(0)
            value_stack.setEnabled(True)
        else:
            value_stack.setCurrentIndex(0)
            value_stack.setEnabled(True)


    def _get_obj_query_field_type(self, display_name):
        """根据字段显示名获取字段类型（缓存优先 + 关键词兜底）"""
        api_name = self.obj_query_object_combo.currentData() or ''
        if not api_name:
            return ''
        type_map = getattr(self, '_obj_query_field_type_map', {})
        if not type_map:
            crm_fields = self._get_crm_object_fields_cached(api_name)
            for f in (crm_fields or []):
                if isinstance(f, dict):
                    fn = f.get('apiName', '') or f.get('name', '')
                    ft = f.get('type', '') or f.get('dataType', '')
                    fl = f.get('label', '')
                    ft_lower = ft.lower()
                    if ft_lower in ('datetime', 'timestamp', 'date_time'):
                        type_map[fn] = 'datetime'
                        if fl: type_map[fl] = 'datetime'
                    elif ft_lower in ('date', 'dateonly'):
                        type_map[fn] = 'date'
                        if fl: type_map[fl] = 'date'
            self._obj_query_field_type_map = type_map
        if display_name in type_map:
            return type_map[display_name]
        d2a = getattr(self, '_obj_query_display_to_api', None) or {}
        api = d2a.get(display_name, display_name)
        if api in type_map:
            return type_map[api]
        # 关键词兜底
        label = str(display_name).lower()
        if any(kw in label for kw in ('日期', '时间', 'create_time', 'update_time',
                                        'modify_time', 'close_date', 'submit_time')):
            return 'datetime'
        return ''


    def _open_obj_query_date_range(self, btn):
        """对象查询日期范围选择弹窗（兼容旧调用路径）。"""
        dr = btn.property('date_range') or {'start': None, 'end': None}
        dlg = QuickDatePickerDialog(start_date=dr.get('start'), end_date=dr.get('end'), parent=self)
        dlg.set_popup_anchor_widget(btn)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.start_date and dlg.end_date:
            btn.setProperty('date_range', {'start': dlg.start_date, 'end': dlg.end_date})
            btn.setText(f"{dlg.start_date.toString('yyyy-MM-dd')} ~ {dlg.end_date.toString('yyyy-MM-dd')}")
            self._obj_query_populate_table()


    def _build_obj_query_api_filters(self):
        """将 UI 筛选条件转为 CRM API filter 格式"""
        self._obj_query_filter_build_message = ''
        api_filters = []
        client_filters = []
        obj_api = self.obj_query_object_combo.currentData() or ''
        fx_cfg = self.config.get('fxiaoke', {}) if isinstance(self.config, dict) else {}
        field_config = fx_cfg.get('crm_object_fields', {}).get(obj_api, {})
        # 优先从 fxiaoke.crm_option_mappings 读取（嵌套结构：{api_name: {field: {id: text}}}）
        option_mappings = fx_cfg.get('crm_option_mappings', {}).get(obj_api, {})
        # 回退到 business_rules.crm_option_mappings（扁平结构：{field: {id: text}}）
        if not option_mappings:
            option_mappings = self.config.get('business_rules', {}).get('crm_option_mappings', {})
        display_to_option = {}
        for field_key, mappings in option_mappings.items():
            if not isinstance(mappings, dict):
                continue
            field_label = field_key
            field_info = field_config.get(field_key)
            if isinstance(field_info, dict):
                field_label = field_info.get('label', field_key).strip() or field_key
            elif isinstance(field_info, str) and field_info.strip():
                field_label = field_info.strip()
            rev = {str(text).strip(): option_id for option_id, text in mappings.items() if str(text).strip()}
            if rev:
                display_to_option[field_label] = rev

        # UI → API 操作符映射
        op_map = {
            'eq': 'EQ',
            'ne': 'N',
            'contains': 'LIKE',
            'not_contains': 'NLIKE',
            'starts_with': 'STARTWITH',
            'ends_with': 'ENDWITH',
            'gt': 'GT',
            'lt': 'LT',
            'gte': 'GTE',
            'lte': 'LTE',
            'empty': 'IS',
            'not_empty': 'ISN',
            'in': 'IN',
            'not_in': 'NIN',
            'has_any_of': 'HASANYOF',
            'not_has_any_of': 'NHASANYOF',
            'date_before': 'LTE',
            'date_after': 'GTE',
        }

        conds = self._collect_obj_query_conditions()
        if getattr(self, 'obj_query_condition_rows', []) and not conds:
            self._obj_query_filter_build_message = "⚠️ 筛选条件未填写完整，已返回空结果"
            return [], []
        skipped_conditions = []
        for cond in conds:
            field_name = cond['field']
            op = cond['operator']
            value = cond['value']

            # 将显示名映射回 API 字段名
            display_to_api = (getattr(self, '_obj_query_display_to_api', None) or {})
            api_field = display_to_api.get(field_name, field_name)

            if op == 'date_range':
                # 日期范围 → CRM BETWEEN
                parts = value.split('~')
                if len(parts) == 2:
                    api_filters.append({
                        'field_name': api_field,
                        'operator': 'BETWEEN',
                        'field_values': [
                            parts[0].strip() + ' 00:00:00',
                            parts[1].strip() + ' 23:59:59',
                        ],
                    })
                else:
                    skipped_conditions.append(field_name)
            elif op == 'past_n_days':
                # 过去N天 → CRM BETWEEN
                from datetime import datetime, timedelta
                try:
                    n = int(value)
                    end_date = datetime.now().strftime('%Y-%m-%d 23:59:59')
                    start_date = (datetime.now() - timedelta(days=n)).strftime('%Y-%m-%d 00:00:00')
                    api_filters.append({'field_name': api_field, 'operator': 'BETWEEN', 'field_values': [start_date, end_date]})
                except ValueError:
                    skipped_conditions.append(field_name)
            elif op in ('in', 'not_in', 'has_any_of', 'not_has_any_of') and re.search(r'[,，;；、]', str(value)):
                # "属于" + 多值 → IN（值转为 option ID）
                value_list = [v.strip() for v in re.split(r'[,，;；、]', str(value)) if v.strip()]
                value_map = display_to_option.get(field_name, {})
                api_values = [value_map.get(v, v) for v in value_list]
                if api_values:
                    api_filters.append({'field_name': api_field, 'operator': op_map.get(op, 'IN'), 'field_values': api_values})
                else:
                    skipped_conditions.append(field_name)
            elif op in ('in', 'not_in', 'has_any_of', 'not_has_any_of'):
                # "属于" + 单值 → IN（值转为 option ID）
                value_map = display_to_option.get(field_name, {})
                api_value = value_map.get(value, value)
                if api_value:
                    api_filters.append({'field_name': api_field, 'operator': op_map.get(op, 'IN'), 'field_values': [api_value]})
                else:
                    skipped_conditions.append(field_name)
            elif op in op_map:
                crm_op = op_map[op]
                if crm_op in ('IS', 'ISN'):
                    api_filters.append({
                        'field_name': api_field,
                        'operator': crm_op,
                        'field_values': [],
                    })
                else:
                    api_filters.append({
                        'field_name': api_field,
                        'operator': crm_op,
                        'field_values': [value],
                    })
            else:
                # 无法映射到 API 的操作符，保留客户端过滤
                skipped_conditions.append(field_name)

        if skipped_conditions:
            self._obj_query_filter_build_message = f"⚠️ 筛选条件无法转换为CRM过滤条件：{', '.join(skipped_conditions)}，已返回空结果"
            return [], []

        return api_filters, client_filters


    def _refresh_obj_query_exposed_tags(self):
        """刷新外露标签（委托给 ExposedTagsBar）。"""
        if hasattr(self, '_obj_query_exposed_tags_bar'):
            conds = self._collect_obj_query_conditions()
            self._obj_query_exposed_tags_bar.refresh(conds)


    def _open_obj_query_column_settings(self):
        """字段显示设置（与 CRM 订单逻辑完全一致）"""
        if not hasattr(self, 'obj_query_table') or self.obj_query_table.columnCount() == 0:
            QMessageBox.information(self, "提示", "请先选择对象加载数据。"); return
        # 使用保存的全量标签（首次从表格收集）
        all_labels = getattr(self, '_obj_query_all_labels', None)
        if all_labels is None:
            all_labels = []
            for col in range(self.obj_query_table.columnCount()):
                h = self.obj_query_table.horizontalHeaderItem(col)
                if h and h.text().strip():
                    all_labels.append(h.text().strip())
            self._obj_query_all_labels = list(all_labels)
        visible_labels = getattr(self, '_obj_query_visible_headers', None)
        if visible_labels is None:
            visible_labels = list(all_labels)
        header_order = getattr(self, '_obj_query_header_order', None)
        if header_order is None:
            header_order = list(all_labels)

        print(f"[DEBUG-对象查询] 打开字段设置 | all_labels: {len(all_labels)} | 当前visible: {len(visible_labels)}")
        dialog = ExcelFieldSettingsDialog(
            headers=all_labels,
            visible_headers=visible_labels[:],
            header_order=header_order[:],
            parent=self
        )
        try:
            result = dialog.exec()
            print(f"[DEBUG-对象查询] dialog.exec() 返回: {result} | Accepted={QDialog.DialogCode.Accepted}")
            if result == QDialog.DialogCode.Accepted:
                new_vis, new_order = dialog.get_settings()
                print(f"[DEBUG-对象查询] ✅ 字段设置确认成功!")
                print(f"[DEBUG-对象查询] 新可见字段数: {len(new_vis)}")
                print(f"[DEBUG-对象查询] 新可见字段列表: {new_vis}")
                if not new_vis:
                    print(f"[DEBUG-对象查询] ❌ 警告: 可见字段为空, 返回")
                    return
                old_vis = getattr(self, '_obj_query_visible_headers') or []
                self._obj_query_visible_headers = list(new_vis)
                self._obj_query_header_order = list(new_order)
                # 持久化保存：每个对象独立记忆字段显示设置
                api_name = self.obj_query_object_combo.currentData() or ''
                if api_name:
                    self._save_obj_query_field_settings(api_name, new_vis, new_order)
                old_count = len(old_vis) if old_vis else 0
                new_count = len(new_vis) if new_vis else 0
                print(f"[DEBUG-对象查询] 已更新 _obj_query_visible_headers: {old_count} → {new_count}")
                logging.info(f"字段设置变更: 之前{self.obj_query_table.columnCount()}列 → 新设置{len(new_vis)}列, 前5项:{new_vis[:5]}")

                print(f"[DEBUG-对象查询] 准备调用 _rebuild_obj_query_table_columns()")
                print(f"[DEBUG-对象查询] 调用前表格列数: {self.obj_query_table.columnCount()}")
                self._rebuild_obj_query_table_columns(new_vis)
                print(f"[DEBUG-对象查询] 调用后表格列数: {self.obj_query_table.columnCount()}")
                print(f"[DEBUG-对象查询] 表格headers: {[self.obj_query_table.horizontalHeaderItem(i).text() for i in range(min(10, self.obj_query_table.columnCount()))]}")
                print(f"[DEBUG-对象查询] ✅ _rebuild_obj_query_table_columns() 完成")
            else:
                print(f"[DEBUG-对象查询] ❌ 对话框被取消或关闭")

        except Exception as e:
            import traceback
            print("[Error] Field settings exception: " + str(e))
            traceback.print_exc()
            logging.error("Field settings exception: " + str(e), exc_info=True)

    def _rebuild_obj_query_table_columns(self, visible_labels):
        """用给定标签重建表格列"""
        print(f"[DEBUG-对象查询] _rebuild_obj_query_table_columns 开始 | 可见字段数: {len(visible_labels)} | 字段列表: {visible_labels[:10]}")
        display_to_api = (getattr(self, '_obj_query_display_to_api', None) or {})
        api_to_display = {}
        if not display_to_api:
            display_headers = getattr(self, '_obj_query_display_headers', [])
            all_api_fields = getattr(self, '_obj_query_all_api_fields', [])
            print(f"[DEBUG-对象查询] display_to_api 为空, 尝试重建 | display_headers数: {len(display_headers)} | all_api_fields数: {len(all_api_fields)}")
            if display_headers and all_api_fields:
                display_to_api = dict(zip(display_headers, all_api_fields))
                api_to_display = dict(zip(all_api_fields, display_headers))
                print(f"[DEBUG-对象查询] 重建映射成功 | display_to_api 示例: {list(display_to_api.items())[:5]}")
        else:
            api_to_display = {v: k for k, v in display_to_api.items()}
            print(f"[DEBUG-对象查询] 使用已有映射 | display_to_api 数: {len(display_to_api)}")
        table = self.obj_query_table
        old_col_count = table.columnCount()
        new_col_count = len(visible_labels)
        print(f"[DEBUG-对象查询] 列数变化: {old_col_count} → {new_col_count}")
        table.setColumnCount(new_col_count)
        table.setHorizontalHeaderLabels(visible_labels)
        self._apply_obj_query_column_widths()
        data = getattr(self, 'obj_query_all_data', [])
        print(f"[DEBUG-对象查询] 总数据行数: {len(data)}")
        if not data:
            table.setRowCount(0)
            print(f"[DEBUG-对象查询] 数据为空, 提前返回")
            return
        page_size = self._get_combo_page_size(self.obj_query_page_size)
        start = (self.obj_query_current_page - 1) * page_size if hasattr(self, 'obj_query_current_page') else 0
        end = min(start + page_size, len(data))
        page_data = data[start:end]
        print(f"[DEBUG-对象查询] 当前页数据行数: {len(page_data)} (第{start+1}-{end}行)")
        table.setRowCount(len(page_data))
        # 复用与 _obj_query_populate_table 相同的格式化逻辑
        field_type_map = getattr(self, '_obj_query_field_type_map', {}) or {}
        user_ref_name_set = {'owner', 'created_by', 'last_modified_by', 'submit_by', 'belong_to'}
        option_mappings = self.config.get('fxiaoke', {}).get('crm_option_mappings', {}).get(
            self.obj_query_object_combo.currentData() or '', {}
        )
        filled_count = 0
        for row_idx, row in enumerate(page_data):
            for col_idx, label in enumerate(visible_labels):
                api = display_to_api.get(label, label)
                raw_value = row.get(api, '')
                if raw_value is None or raw_value == '':
                    for api_key, display_name in api_to_display.items():
                        if display_name == label and api_key in row:
                            raw_value = row.get(api_key, '')
                            api = api_key
                            break
                # 0️⃣ 字段明细映射
                field_mappings = option_mappings.get(api, {})
                if field_mappings:
                    raw_str = str(raw_value).strip() if raw_value else ''
                    if raw_str and raw_str in field_mappings:
                        table.setItem(row_idx, col_idx, QTableWidgetItem(field_mappings[raw_str]))
                        filled_count += 1
                        continue
                ftype = field_type_map.get(api, '')
                # 1️⃣ __r 关联检测
                if not api.endswith('__r') and f'{api}__r' in row:
                    ref_val = row.get(f'{api}__r')
                    if ref_val is not None and ref_val != '':
                        ftype = 'user_ref'
                # 2️⃣ 已知用户字段名兜底
                api_clean = api.rstrip('_r').rstrip('_')
                if ftype != 'user_ref' and api_clean in user_ref_name_set:
                    ftype = 'user_ref'
                # 3️⃣ 标签/字段名兜底：时间/日期字段
                label_lower = label.lower()
                if ftype not in ('user_ref', 'datetime', 'date'):
                    if any(kw in label for kw in ('时间', '日期')) or any(kw in label_lower for kw in ('time', 'date')):
                        ftype = 'datetime'
                    elif any(kw in api_clean for kw in ('create_time', 'update_time', 'modify_time', 'submit_time')):
                        ftype = 'datetime'
                # 按类型格式化
                if ftype == 'user_ref':
                    ref_val = row.get(f'{api}__r')
                    if ref_val is not None and ref_val != '':
                        display_value = self._extract_display_value(ref_val)
                    else:
                        display_value = self._extract_display_value(raw_value)
                elif ftype in ('datetime', 'timestamp'):
                    display_value = self._format_timestamp(raw_value)
                elif ftype == 'date':
                    display_value = self._format_date(raw_value)
                else:
                    display_value = self._auto_format_value(raw_value)
                table.setItem(row_idx, col_idx, QTableWidgetItem(display_value))
                filled_count += 1
        print(f"[DEBUG-对象查询] 填充单元格数: {filled_count}")
        if hasattr(self, 'obj_query_search_field'):
            combo = self.obj_query_search_field
            combo.blockSignals(True)
            combo.clear()
            for h in visible_labels:
                api_field = display_to_api.get(h, h)
                combo.addItem(h, api_field)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        print(f"[DEBUG-对象查询] _rebuild_obj_query_table_columns 完成")

    # ===== 对象查询方案管理 =====


    def _get_obj_query_presets_key(self):
        """获取当前对象的筛选方案配置键"""
        api = self.obj_query_object_combo.currentData() or ''
        return f'obj_query_filter_presets_{api}' if api else 'obj_query_filter_presets'


    def _show_obj_query_preset_popup(self):
        """弹出方案选择面板"""
        key = self._get_obj_query_presets_key()
        presets = self.config.get(key, [])
        if not isinstance(presets, list): presets = []
        popup = QFrame()
        popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setStyleSheet("QFrame { border: 1px solid #D9D9D9; border-radius: 4px; background: #FFF; }")
        pl = QVBoxLayout(popup); pl.setContentsMargins(4, 4, 4, 4); pl.setSpacing(2)

        none_btn = QPushButton("(未选择)")
        none_btn.setFixedHeight(28); none_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        none_btn.setStyleSheet("QPushButton { border: none; text-align: left; padding: 4px 8px; font-size: 12px; color: #999; background: transparent; } QPushButton:hover { background: #F5F5F5; }")
        none_btn.clicked.connect(lambda: [self._clear_obj_query_conditions(), self._obj_query_populate_table(), popup.close()])
        pl.addWidget(none_btn)

        for preset in presets:
            name = preset.get('name', '')
            row = QFrame(); row.setFixedHeight(30); row.setStyleSheet("QFrame { border: none; background: transparent; }")
            rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(4)
            load_btn = QPushButton(name); load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            load_btn.setStyleSheet("QPushButton { border: none; text-align: left; padding: 4px 8px; font-size: 12px; color: #333; background: transparent; } QPushButton:hover { background: #E6F7FF; color: #1890FF; }")
            load_btn.clicked.connect(lambda checked, n=name: [self._load_obj_query_preset(n), popup.close()])
            rl.addWidget(load_btn, stretch=1)
            del_btn = QPushButton("✕"); del_btn.setFixedSize(22, 22)
            del_btn.setStyleSheet("QPushButton { border: none; color: #999; font-size: 12px; } QPushButton:hover { color: #FF4D4F; background: #FFF2F0; }")
            del_btn.clicked.connect(lambda checked, n=name: [self._delete_obj_query_preset(n), popup.close()])
            rl.addWidget(del_btn)
            pl.addWidget(row)

        popup.adjustSize()
        p = self.obj_query_preset_btn.mapToGlobal(QPoint(0, self.obj_query_preset_btn.height()))
        popup.move(p.x(), p.y() + 2)
        popup.reject = popup.close; popup._outside_close_armed = False
        pf = common._DialogOutsideCloseFilter(popup)
        QApplication.instance().installEventFilter(pf)
        QTimer.singleShot(0, lambda pp=popup: setattr(pp, '_outside_close_armed', True))
        popup.destroyed.connect(lambda obj, f=pf: QApplication.instance().removeEventFilter(f))
        popup.show()


    def _save_obj_query_preset(self, name=None):
        """保存当前筛选条件为方案（按对象独立存储）"""
        conditions = self._collect_obj_query_conditions()
        if name is None:
            name, ok = QInputDialog.getText(self, "保存筛选方案", "请输入方案名称：")
            if not ok or not name or not name.strip(): return
        name = name.strip()
        key = self._get_obj_query_presets_key()
        presets = self.config.get(key, [])
        if not isinstance(presets, list): presets = []
        existing = next((i for i, p in enumerate(presets) if p.get('name') == name), None)
        if existing is not None:
            presets[existing] = {'name': name, 'conditions': conditions}
        else:
            presets.append({'name': name, 'conditions': conditions})
        self.config[key] = presets
        save_config(self.config)


    def _load_obj_query_preset(self, name):
        """加载筛选方案（按对象独立存储）"""
        key = self._get_obj_query_presets_key()
        presets = self.config.get(key, [])
        if not isinstance(presets, list): return
        target = next((p for p in presets if p.get('name') == name), None)
        if not target: return
        self._clear_obj_query_conditions()
        for cond in target.get('conditions', []):
            self._add_obj_query_condition_row(cond)
        self.obj_query_current_page = 1
        self._obj_query_populate_table()


    def _delete_obj_query_preset(self, name):
        """删除筛选方案（按对象独立存储）"""
        key = self._get_obj_query_presets_key()
        presets = self.config.get(key, [])
        if not isinstance(presets, list): return
        reply = QMessageBox.question(self, '确认删除', f'确定删除方案「{name}」吗？')
        if reply != QMessageBox.StandardButton.Yes: return
        self.config[key] = [p for p in presets if p.get('name') != name]
        save_config(self.config)


    def _infer_field_type_from_value(self, val, field_key=''):
        """从样本值推断字段类型，用于自定义对象字段的类型检测。

        返回值对应 CRM 字段类型的简写：
        - 'datetime': Unix 毫秒时间戳
        - 'date': 日期字符串或较小的时间戳
        - 'user_ref': 包含 name/id 的对象引用
        - 'text': 文本
        - 'number': 数字
        - '': 未知类型
        """
        if val is None:
            return ''
        # 对象/字典类型 → 可能是引用字段
        if isinstance(val, dict):
            if 'name' in val or 'id' in val or '_id' in val:
                return 'user_ref'
            return ''
        # 列表类型 → 可能是多选或关联
        if isinstance(val, list):
            return ''
        # 整数/浮点数 → 判断是否为时间戳
        if isinstance(val, (int, float)):
            if val <= 0:
                return 'number'
            s = str(int(val))
            # 13位毫秒时间戳（2001-2286年范围）
            if len(s) == 13 and s.startswith('1'):
                return 'datetime'
            # 10位秒级时间戳
            if len(s) == 10 and s.startswith('1'):
                return 'datetime'
            return 'number'
        # 字符串
        if isinstance(val, str):
            val_stripped = val.strip()
            if not val_stripped:
                return ''
            # 纯数字字符串 → 可能为时间戳
            if val_stripped.isdigit():
                if len(val_stripped) == 13 and val_stripped.startswith('1'):
                    return 'datetime'
                if len(val_stripped) == 10 and val_stripped.startswith('1'):
                    return 'datetime'
            # 日期格式检测：yyyy-MM-dd
            import re
            if re.match(r'^\d{4}-\d{2}-\d{2}', val_stripped):
                return 'date'
            # 日期时间格式：yyyy-MM-dd HH:mm:ss
            if re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', val_stripped):
                return 'datetime'
            # 关键词兜底
            key_lower = field_key.lower()
            if any(kw in key_lower for kw in ('time', 'date', 'created', 'updated', 'modified')):
                return 'datetime'
            return 'text'
        return ''


    def _get_object_name_by_api_name(self, api_name):
        """根据API Name查找对象显示名称。"""
        all_primary = self._get_primary_crm_objects()
        for obj in all_primary:
            if obj['api_name'] == api_name:
                return obj['name']
        # 如果在主对象里找不到，就先用api_name作为名字
        return api_name


    def fetch_object_fields(self, object_api_name):
        """调用CRM元数据接口获取对象字段清单（字段Key、名称、类型等）- 带缓存"""
        if object_api_name in self.crm_object_fields_cache:
            return self.crm_object_fields_cache[object_api_name]

        # ✅【性能优化】使用已有的异步方法，避免主线程阻塞
        return self._get_crm_object_fields_api(object_api_name)


    def fetch_object_fields_async(self, object_api_name, callback=None):
        """
        异步获取对象字段列表（不阻塞主线程）

        【关键改进】：
        - 在后台线程执行网络请求，避免界面卡顿
        - 通过回调函数返回结果
        - 自动处理缓存和错误情况

        Args:
            object_api_name: 对象API名称
            callback: 回调函数 callback(fields, error)
        """
        # 先检查缓存
        if object_api_name in getattr(self, 'crm_object_fields_cache', {}):
            cached_fields = self.crm_object_fields_cache[object_api_name]
            if callback:
                callback(cached_fields, None)
            return cached_fields

        # 显示加载状态（如果有状态标签）
        if hasattr(self, 'obj_query_status_label'):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.obj_query_status_label.setText(
                f"⏳ 正在获取 {object_api_name} 字段定义..."))

        import threading
        def _async_fetch():
            try:
                fields = self._get_crm_object_fields_api(object_api_name)
                if callback:
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: callback(fields, None))

                # 更新状态
                if hasattr(self, 'obj_query_status_label') and fields:
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda f=fields: self.obj_query_status_label.setText(
                        f"✅ 已获取 {len(f)} 个字段"))
            except Exception as e:
                error_msg = f"获取字段失败: {str(e)}"
                print(f"[ERROR] {error_msg}")
                if callback:
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: callback([], error_msg))

                # 更新错误状态
                if hasattr(self, 'obj_query_status_label'):
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda em=error_msg: self.obj_query_status_label.setText(
                        f"❌ {em[:30]}"))

        thread = threading.Thread(target=_async_fetch, daemon=True)
        thread.start()
        return None  # 异步返回None，结果通过回调获取


    def _on_obj_query_column_resized(self, logicalIndex, oldSize, newSize):
        """对象查询表格列宽调整时防抖保存"""
        if not hasattr(self, '_obj_query_column_width_save_timer'):
            return
        if self._obj_query_column_width_save_timer.isActive():
            self._obj_query_column_width_save_timer.stop()
        self._obj_query_column_width_save_timer.start(1000)


    def _debounced_save_obj_query_column_widths(self):
        """防抖后保存对象查询表格列宽"""
        self._save_obj_query_column_widths()


    def _save_obj_query_column_widths(self):
        """保存对象查询表格列宽到用户运行状态"""
        if not hasattr(self, 'obj_query_table') or self.obj_query_table.columnCount() == 0:
            return
        table = self.obj_query_table
        widths_by_index = {}
        widths_by_header = {}
        for col in range(table.columnCount()):
            width = table.columnWidth(col)
            widths_by_index[col] = width
            header_item = table.horizontalHeaderItem(col)
            header_key = header_item.text().strip() if header_item else ''
            if header_key:
                widths_by_header[header_key] = width
        self.save_user_runtime_state_patch({
            'table_column_widths': {
                'obj_query': widths_by_index,
                'obj_query_by_header': widths_by_header,
            }
        }, immediate=False)


    def _get_saved_obj_query_column_widths(self):
        """获取保存的对象查询列宽（按索引）"""
        state = self.runtime_state.get('table_column_widths', {})
        if isinstance(state, dict):
            widths = state.get('obj_query', {})
            if isinstance(widths, dict):
                return {int(k): v for k, v in widths.items() if str(k).isdigit()}
        return {}


    def _get_saved_obj_query_column_widths_by_header(self):
        """获取保存的对象查询列宽（按表头标签，可抗列序变化）"""
        state = self.runtime_state.get('table_column_widths', {})
        if isinstance(state, dict):
            widths = state.get('obj_query_by_header', {})
            if isinstance(widths, dict):
                return {str(k): v for k, v in widths.items()}
        return {}


    def _apply_obj_query_column_widths(self):
        """应用保存的对象查询列宽"""
        if not hasattr(self, 'obj_query_table') or self.obj_query_table.columnCount() == 0:
            return
        try:
            saved_by_header = self._get_saved_obj_query_column_widths_by_header()
            saved_by_index = self._get_saved_obj_query_column_widths()
            table = self.obj_query_table
            for col in range(table.columnCount()):
                header_item = table.horizontalHeaderItem(col)
                header_key = header_item.text().strip() if header_item else ''
                if header_key and header_key in saved_by_header:
                    table.setColumnWidth(col, saved_by_header[header_key])
                elif col in saved_by_index:
                    table.setColumnWidth(col, saved_by_index[col])
        except Exception as e:
            print(f"应用对象查询列宽失败: {e}")


    def _on_obj_query_table_cell_clicked(self, row, col):
        """对象查询表格：第0列（复选框）选中整行，其他列点哪选哪"""
        if col == 0:
            self.obj_query_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.obj_query_table.selectRow(row)
            self.obj_query_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)

