# -*- coding: utf-8 -*-
from core import *
from common import *
from common import frameless_message_box
import common  # 显式导入，用于访问模块级私有函数

"""
department.py — 部门员工管理 Mixin
─────────────────────────────────
负责：MainFrame 中部门员工页面相关方法
  - create_department_page()     部门员工页面（部门树 / 员工列表 / 同步）
  - _usergroup_* / _on_usergroup_*  数据获取 / 表格填充 / 字段设置
  - _do_usergroup_sync_to_mysql  同步到 MySQL
  - _clean_user_value / _get_user_cn_header  数据清洗
依赖：core.py / common.py / network.py
被导入：主程序（作为 MainFrame 的 Mixin 父类）
"""
"""department Mixin"""

# 导入所需模块
import os

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

class departmentMixin:
    """department functionality."""

    def create_department_page(self):
        """创建部门与员工页面（页面8）—— 单表格，固定数据源"""
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(8)

        # ===== 第一行：标题 + 搜索框 + 刷新 + 字段显示 =====
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        title_label = QLabel("部门与员工")
        title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #333;")
        top_row.addWidget(title_label)

        # 部门ID 输入框
        top_row.addWidget(QLabel("部门ID:"))
        self.usergroup_group_id_input = QLineEdit()
        self.usergroup_group_id_input.setPlaceholderText("999999=全公司")
        self.usergroup_group_id_input.setFixedWidth(150)
        self.usergroup_group_id_input.setFixedHeight(30)
        self.usergroup_group_id_input.setStyleSheet("QLineEdit { border: 1px solid #D9D9D9; border-radius: 4px; padding: 2px 6px; font-size: 12px; }")
        self.usergroup_group_id_input.setText("999999")
        top_row.addWidget(self.usergroup_group_id_input)
        top_row.addSpacing(12)

        # 搜索字段选择下拉框
        self.usergroup_search_field = QComboBox()
        self.usergroup_search_field.setFixedHeight(30)
        self.usergroup_search_field.setFixedWidth(90)
        self.usergroup_search_field.setStyleSheet("QComboBox { border: 1px solid #D9D9D9; border-radius: 4px; padding: 2px 6px; font-size: 12px; background: #FFF; } QComboBox:hover { border-color: #1890FF; }")
        self.usergroup_search_field.currentIndexChanged.connect(self._on_usergroup_search)
        top_row.addWidget(self.usergroup_search_field)

        # 搜索框
        search_frame = QFrame()
        search_frame.setFixedHeight(30)
        search_frame.setMaximumWidth(260)
        search_frame.setStyleSheet("QFrame { border: 1px solid #D9D9D9; border-radius: 4px; background: #FFF; }")
        sf_layout = QHBoxLayout(search_frame)
        sf_layout.setContentsMargins(0, 0, 0, 0)
        sf_layout.setSpacing(0)

        self.usergroup_search_input = QLineEdit()
        self.usergroup_search_input.setPlaceholderText("搜索")
        self.usergroup_search_input.setFixedHeight(28)
        self.usergroup_search_input.setStyleSheet("QLineEdit { border: none; background: transparent; padding: 2px 8px; font-size: 12px; }")
        self.usergroup_search_input.textChanged.connect(self._on_usergroup_search)
        sf_layout.addWidget(self.usergroup_search_input, stretch=1)
        top_row.addWidget(search_frame)

        top_row.addStretch()

        # 刷新按钮
        self.usergroup_refresh_btn = QPushButton("🔄 刷新")
        self.usergroup_refresh_btn.setFixedWidth(80)
        self.usergroup_refresh_btn.setFixedHeight(30)
        self.usergroup_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.usergroup_refresh_btn.setToolTip("手动刷新数据")
        self.usergroup_refresh_btn.setStyleSheet("QPushButton { border: 1px solid #D9D9D9; border-radius: 4px; padding: 4px 12px; font-size: 13px; background: #FFF; color: #333; } QPushButton:hover { border-color: #1890FF; color: #1890FF; }")
        self.usergroup_refresh_btn.clicked.connect(self._on_usergroup_manual_refresh)
        top_row.addWidget(self.usergroup_refresh_btn)

        # 字段显示按钮
        self.usergroup_column_btn = QPushButton("字段显示")
        self.usergroup_column_btn.setFixedWidth(80)
        self.usergroup_column_btn.clicked.connect(self._open_usergroup_column_settings)
        top_row.addWidget(self.usergroup_column_btn)

        # MySQL 同步模式
        sync_mode_cfg = self.config.get('fxiaoke', {}).get('usergroup_sync_mode', 'auto')
        self.usergroup_sync_mode_combo = QComboBox()
        self.usergroup_sync_mode_combo.setFixedHeight(30)
        self.usergroup_sync_mode_combo.setFixedWidth(90)
        self.usergroup_sync_mode_combo.addItem("自动同步", "auto")
        self.usergroup_sync_mode_combo.addItem("手动同步", "manual")
        self.usergroup_sync_mode_combo.setCurrentIndex(0 if sync_mode_cfg == 'auto' else 1)
        self.usergroup_sync_mode_combo.setStyleSheet("QComboBox { border: 1px solid #D9D9D9; border-radius: 4px; padding: 2px 6px; font-size: 12px; background: #FFF; }")
        self.usergroup_sync_mode_combo.currentIndexChanged.connect(self._on_usergroup_sync_mode_changed)
        top_row.addWidget(self.usergroup_sync_mode_combo)

        # 同步到数据库按钮
        self.usergroup_sync_btn = QPushButton("同步")
        self.usergroup_sync_btn.setFixedWidth(50)
        self.usergroup_sync_btn.setFixedHeight(30)
        self.usergroup_sync_btn.setToolTip("将当前数据同步到 MySQL 数据库")
        self.usergroup_sync_btn.setStyleSheet("QPushButton { border: 1px solid #D9D9D9; border-radius: 4px; padding: 2px 8px; font-size: 12px; background: #FFF; color: #333; } QPushButton:hover { border-color: #1890FF; color: #1890FF; }")
        self.usergroup_sync_btn.clicked.connect(self._on_usergroup_sync_to_mysql)
        top_row.addWidget(self.usergroup_sync_btn)

        layout.addLayout(top_row)

        # ===== 表格 =====
        self.usergroup_table = QTableWidget()
        install_table_edit_context_menu(self.usergroup_table)
        self.usergroup_table.setColumnCount(0)
        self.usergroup_table.setRowCount(0)
        self.usergroup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.usergroup_table.setAlternatingRowColors(True)
        self._usergroup_af_header = install_autofilter_header(self.usergroup_table)
        self.usergroup_table.horizontalHeader().setStretchLastSection(False)
        self.usergroup_table.verticalHeader().setVisible(False)
        layout.addWidget(self.usergroup_table, stretch=1)

        # ===== 底部状态栏 =====
        bar = QHBoxLayout()
        self.usergroup_status_label = QLabel("")
        self.usergroup_status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.usergroup_status_label.setStyleSheet("color: #1890FF; font-size: 11px;")
        bar.addWidget(self.usergroup_status_label)

        self.usergroup_source_label = QLabel("")
        self.usergroup_source_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.usergroup_source_label.setStyleSheet("color: #999; font-size: 10px;")
        bar.addWidget(self.usergroup_source_label)
        bar.addStretch()

        layout.addLayout(bar)

        self.usergroup_data_ready.connect(self._usergroup_populate_table_safe)
        self.content_stack.addWidget(page)


    def _on_usergroup_search(self):
        """搜索框输入变化"""
        self._usergroup_populate_table()


    def _on_usergroup_manual_refresh(self):
        """手动刷新数据"""
        self.usergroup_refresh_btn.setText("⏳ 加载中...")
        self.usergroup_refresh_btn.setEnabled(False)
        self._usergroup_fetch_data()


    def _usergroup_fetch_data(self):
        """获取部门下成员信息"""
        dept_id_str = self.usergroup_group_id_input.text().strip() if hasattr(self, 'usergroup_group_id_input') else "999999"
        if not dept_id_str:
            self.usergroup_all_data = []
            if hasattr(self, 'usergroup_status_label'):
                self.usergroup_status_label.setText("⚠️ 请输入部门ID")
            return
        try:
            department_id = int(dept_id_str)
        except ValueError:
            self.usergroup_all_data = []
            if hasattr(self, 'usergroup_status_label'):
                self.usergroup_status_label.setText("⚠️ 部门ID必须为整数")
            return

        if hasattr(self, 'usergroup_status_label'):
            self.usergroup_status_label.setText("⏳ 正在加载...")
        if hasattr(self, 'usergroup_source_label'):
            self.usergroup_source_label.setText("☁️ CRM API 加载中...")

        # 使用 BackgroundTaskManager 确保线程安全（替代原始 threading.Thread）
        self.task_manager.start(
            'usergroup_fetch',
            '部门员工加载',
            self._usergroup_fetch_worker,
            department_id
        )


    def _usergroup_fetch_worker(self, department_id):
        """后台线程：获取部门成员和部门列表（不直接操作 GUI）"""
        cfg = load_config()
        fx_cfg = cfg.get('fxiaoke', {})

        crm = FXiaokeCRM(
            app_id=fx_cfg.get('app_id', 'FSAID_1323c1a'),
            app_secret=fx_cfg.get('app_secret', 'e7f4188d14704299b375c91ddda92cb0'),
            permanent_code=fx_cfg.get('permanent_code', 'E8B8D8536B0385D035657AC2528928F0'),
            admin_mobile=fx_cfg.get('admin_mobile', '15889740213')
        )

        # 并行获取用户列表和部门列表
        rows, err = crm.query_user_list(department_id=department_id, fetch_child=True, show_department_detail=True)
        dept_list, dept_err = crm.query_department_list(department_id=999999, fetch_child=True)

        if err:
            self.usergroup_all_data = []
            self.usergroup_dept_map = {}
            self._usergroup_error_msg = str(err)
            self.usergroup_data_ready.emit('usergroup')
            self.update_output.emit(f"[部门员工] 加载失败: {err}")
            return

        # 构建 部门ID → 部门名称 映射
        dept_map = {}
        if dept_err:
            self.update_output.emit(f"[部门员工] 部门列表加载失败: {dept_err}")
        elif dept_list:
            for d in dept_list:
                if isinstance(d, dict):
                    did = d.get('id')
                    dname = d.get('name', '')
                    if did is not None:
                        dept_map[int(did)] = dname
            self.update_output.emit(f"[部门员工] 部门列表加载完成: {len(dept_map)} 个部门")

        self.usergroup_all_data = rows if rows else []
        self.usergroup_dept_map = dept_map
        self._usergroup_error_msg = ''
        self.usergroup_data_ready.emit('usergroup')


    def _usergroup_populate_table_safe(self, page_type):
        """在主线程中安全地填充表格"""
        if hasattr(self, 'usergroup_refresh_btn'):
            self.usergroup_refresh_btn.setText("🔄 刷新")
            self.usergroup_refresh_btn.setEnabled(True)

        data = getattr(self, 'usergroup_all_data', [])
        error_msg = getattr(self, '_usergroup_error_msg', '')

        if error_msg:
            if hasattr(self, 'usergroup_status_label'):
                self.usergroup_status_label.setText(f"❌ 加载失败")
            if hasattr(self, 'usergroup_source_label'):
                self.usergroup_source_label.setText("❌ 加载失败")
            return

        if hasattr(self, 'usergroup_status_label'):
            self.usergroup_status_label.setText(f"✅ 已加载 {len(data)} 条记录")
        if hasattr(self, 'usergroup_source_label'):
            self.usergroup_source_label.setText(f"☁️ CRM API | {len(data)} 条")

        try:
            self._usergroup_populate_table()
        except Exception as e:
            print(f"[ERROR-部门员工] ❌ 表格填充失败: {e}")
            import traceback
            traceback.print_exc()

        # 自动同步 MySQL
        if data and self._get_usergroup_sync_mode() == 'auto':
            self.update_output.emit(f"[部门员工] 自动同步 MySQL 开始: {len(data)} 条")
            self.task_manager.start(
                'mysql_sync_usergroup',
                'MySQL同步: 部门员工',
                self._do_usergroup_sync_to_mysql_bg,
                data
            )

    # 字段名 → 中文表头映射
    USER_FIELD_CN_MAP = {
        'openUserId': '员工ID',
        'account': '账号',
        'name': '姓名',
        'nickName': '昵称',
        'isStop': '状态',
        'email': '邮箱',
        'mobile': '手机',
        'gender': '性别',
        'position': '职位',
        'profileImageUrl': '头像',
        'departmentIds': '所属部门',
        'employeeNumber': '工号',
        'hireDate': '入职日期',
        'birthDate': '生日',
        'startWorkDate': '参加工作日期',
        'createTime': '创建时间',
        'leaderId': '汇报对象',
        'qq': 'QQ',
        'weixin': '微信',
        'mainDepartmentId': '主属部门',
        'attachingDepartmentIds': '附属部门',
    }


    def _clean_user_value(self, field, val, id_name_map=None, dept_map=None):
        """清洗用户字段值"""
        if val is None:
            return ''
        if field == 'isStop':
            return '离职' if val else '在职'
        if field == 'gender':
            return '男' if val == 'M' else '女' if val == 'F' else str(val)
        if field == 'createTime' and isinstance(val, (int, float)):
            from datetime import datetime
            try:
                return datetime.fromtimestamp(val / 1000).strftime('%Y-%m-%d %H:%M')
            except Exception:
                return str(val)
        if field == 'leaderId':
            if id_name_map and val in id_name_map:
                return id_name_map[val]
            return str(val)
        if field == 'departmentIds' and isinstance(val, list):
            if dept_map:
                return ', '.join(dept_map.get(int(v), str(v)) for v in val)
            return ', '.join(str(v) for v in val)
        if field in ('mainDepartmentId', 'attachingDepartmentIds'):
            if dept_map:
                if isinstance(val, list):
                    return ', '.join(dept_map.get(int(v), str(v)) for v in val)
                return dept_map.get(int(val), str(val))
            return str(val) if not isinstance(val, list) else ', '.join(str(v) for v in val)
        if isinstance(val, list):
            return ', '.join(str(v) for v in val)
        if isinstance(val, dict):
            return val.get('name', str(val))
        return str(val)


    def _get_user_cn_header(self, field):
        """获取字段的中文表头"""
        return self.USER_FIELD_CN_MAP.get(field, field)


    def _usergroup_populate_table(self):
        """填充用户组表格（中文表头 + 数据清洗）"""
        data = getattr(self, 'usergroup_all_data', [])
        table = self.usergroup_table

        if not data:
            table.setColumnCount(0)
            table.setRowCount(0)
            return

        meta_keys = {'_id', '_from_mapped_cache', 'mapped_at'}
        all_fields = []
        for row in data:
            for key in row.keys():
                if key not in all_fields and key not in meta_keys:
                    all_fields.append(key)

        all_fields_sorted = sorted(all_fields, key=lambda f: (not f.startswith('_'), f.lower()))

        api_name = 'usergroup'
        vis, order = self._load_usergroup_field_settings(api_name)
        # 默认按常用字段顺序
        default_order = ['name', 'mobile', 'position', 'isStop', 'gender', 'email',
                         'departmentIds', 'employeeNumber', 'hireDate', 'leaderId',
                         'account', 'nickName', 'openUserId', 'birthDate', 'startWorkDate',
                         'createTime', 'profileImageUrl', 'qq', 'weixin']
        visible_labels = vis if vis else default_order
        if order:
            ordered = [f for f in order if f in all_fields_sorted]
            remaining = [f for f in all_fields_sorted if f not in ordered]
            all_fields_sorted = ordered + remaining
        else:
            ordered = [f for f in default_order if f in all_fields_sorted]
            remaining = [f for f in all_fields_sorted if f not in ordered]
            all_fields_sorted = ordered + remaining

        visible_fields = [f for f in visible_labels if f in all_fields_sorted]
        if not visible_fields:
            visible_fields = list(all_fields_sorted)

        # 搜索过滤（搜索中文显示值）
        search_text = self.usergroup_search_input.text().strip().lower()
        search_api_field = self.usergroup_search_field.currentData() or ''
        _search_id_map = {r.get('openUserId'): r.get('name', '') for r in data if r.get('openUserId')}
        _search_dept_map = getattr(self, 'usergroup_dept_map', {})
        filtered = list(data)
        if search_text:
            if search_api_field:
                filtered = [r for r in filtered if search_text in self._clean_user_value(search_api_field, r.get(search_api_field), _search_id_map, _search_dept_map).lower()]
            else:
                filtered = [r for r in filtered if any(search_text in self._clean_user_value(k, v, _search_id_map, _search_dept_map).lower() for k, v in r.items())]

        # 更新搜索字段下拉框（中文显示）
        current_search = self.usergroup_search_field.currentData()
        self.usergroup_search_field.blockSignals(True)
        self.usergroup_search_field.clear()
        for f in visible_fields:
            self.usergroup_search_field.addItem(self._get_user_cn_header(f), f)
        for i in range(self.usergroup_search_field.count()):
            if self.usergroup_search_field.itemData(i) == current_search:
                self.usergroup_search_field.setCurrentIndex(i)
                break
        if self.usergroup_search_field.currentIndex() < 0:
            self.usergroup_search_field.setCurrentIndex(0)
        self.usergroup_search_field.blockSignals(False)

        # 构建 openUserId → 姓名 映射（用于转换汇报对象等）
        id_name_map = {r.get('openUserId'): r.get('name', '') for r in data if r.get('openUserId')}
        # 获取部门ID → 部门名称映射
        dept_map = getattr(self, 'usergroup_dept_map', {})

        # 填充表格（中文表头 + 清洗数据）
        cn_headers = [self._get_user_cn_header(f) for f in visible_fields]
        table.setColumnCount(len(visible_fields))
        table.setHorizontalHeaderLabels(cn_headers)
        table.setRowCount(len(filtered))

        for row_idx, row_data in enumerate(filtered):
            for col_idx, field in enumerate(visible_fields):
                val = self._clean_user_value(field, row_data.get(field), id_name_map, dept_map)
                item = QTableWidgetItem(val)
                item.setToolTip(val)
                table.setItem(row_idx, col_idx, item)

        table.resizeColumnsToContents()


    def _open_usergroup_column_settings(self):
        """打开字段显示设置（中文标签）"""
        data = getattr(self, 'usergroup_all_data', [])
        if not data:
            return

        meta_keys = {'_id', '_from_mapped_cache', 'mapped_at'}
        all_api_fields = []
        for row in data:
            for key in row.keys():
                if key not in all_api_fields and key not in meta_keys:
                    all_api_fields.append(key)

        # 用中文标签显示
        cn_labels = [self._get_user_cn_header(f) for f in all_api_fields]
        # 建立中文→API 映射
        cn_to_api = {self._get_user_cn_header(f): f for f in all_api_fields}

        api_name = 'usergroup'
        vis, order = self._load_usergroup_field_settings(api_name)
        # visible/order 存的是 API 字段名，转为中文显示
        current_visible = [self._get_user_cn_header(f) for f in vis] if vis else list(cn_labels)
        header_order = [self._get_user_cn_header(f) for f in order] if order else list(cn_labels)

        dialog = ExcelFieldSettingsDialog(cn_labels, visible_headers=current_visible, header_order=header_order, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_vis_cn, new_order_cn = dialog.get_settings()
            # 转回 API 字段名保存
            new_vis = [cn_to_api.get(h, h) for h in new_vis_cn if h in cn_to_api]
            new_order = [cn_to_api.get(h, h) for h in new_order_cn if h in cn_to_api]
            self._save_usergroup_field_settings(api_name, new_vis, new_order)
            self._usergroup_populate_table()

    # ===== MySQL 同步 =====

    def _get_usergroup_sync_mode(self):
        """获取当前同步模式"""
        if hasattr(self, 'usergroup_sync_mode_combo'):
            return self.usergroup_sync_mode_combo.currentData() or 'auto'
        return self.config.get('fxiaoke', {}).get('usergroup_sync_mode', 'auto')


    def _on_usergroup_sync_mode_changed(self):
        """同步模式切换"""
        mode = self._get_usergroup_sync_mode()
        cfg = load_config()
        cfg.setdefault('fxiaoke', {})['usergroup_sync_mode'] = mode
        save_config_with_delay(cfg)


    def _on_usergroup_sync_to_mysql(self):
        """手动同步到 MySQL"""
        data = getattr(self, 'usergroup_all_data', [])
        if not data:
            from PyQt6.QtWidgets import QMessageBox
            frameless_message_box(self, "提示", "当前没有数据可同步。")
            return
        if hasattr(self, 'usergroup_sync_btn'):
            self.usergroup_sync_btn.setText("⏳")
            self.usergroup_sync_btn.setEnabled(False)
        self.update_output.emit(f"[部门员工] 手动同步 MySQL 开始: {len(data)} 条")
        self.task_manager.start(
            'mysql_sync_usergroup',
            'MySQL同步: 部门员工',
            self._do_usergroup_sync_to_mysql_bg,
            data
        )


    def _do_usergroup_sync_to_mysql_bg(self, data):
        """后台执行 MySQL 同步（清洗表）"""
        try:
            mc = MysqlCache()
            if not mc.available:
                self.update_output.emit("[部门员工] MySQL 未启用，跳过同步")
                mc.close()
                return False, "MySQL 未启用"

            # 构建清洗数据：中文表头 + 清洗值
            id_name_map = {r.get('openUserId'): r.get('name', '') for r in data if r.get('openUserId')}
            dept_map = getattr(self, 'usergroup_dept_map', {})
            fields = [f for f in data[0].keys() if f not in {'_id', '_from_mapped_cache', 'mapped_at'}] if data else []
            cn_headers = [self._get_user_cn_header(f) for f in fields]
            cleaned_rows = []
            for row in data:
                cleaned_row = {'_id': row.get('openUserId', '')}
                for f in fields:
                    cn = self._get_user_cn_header(f)
                    cleaned_row[cn] = self._clean_user_value(f, row.get(f), id_name_map, dept_map)
                cleaned_rows.append(cleaned_row)

            table_name = "部门员工"
            ok, msg = mc.replace_cleaned_all(table_name, cleaned_rows, cn_headers, cleanup_old=False)
            mc.close()
            if ok:
                self.update_output.emit(f"[部门员工] MySQL 同步完成: '{table_name}' {msg}")
                if hasattr(self, 'usergroup_sync_btn'):
                    self.usergroup_sync_btn.setText("同步")
                    self.usergroup_sync_btn.setEnabled(True)
                return True, ""
            else:
                self.update_output.emit(f"[部门员工] MySQL 同步失败: {msg}")
                if hasattr(self, 'usergroup_sync_btn'):
                    self.usergroup_sync_btn.setText("同步")
                    self.usergroup_sync_btn.setEnabled(True)
                return False, msg
        except Exception as e:
            self.update_output.emit(f"[部门员工] MySQL 同步异常: {str(e)[:80]}")
            logging.error(f"[部门员工] MySQL 同步失败: {e}")
            if hasattr(self, 'usergroup_sync_btn'):
                self.usergroup_sync_btn.setText("同步")
                self.usergroup_sync_btn.setEnabled(True)
            return False, str(e)[:200]


    def _load_usergroup_field_settings(self, api_name):
        """加载用户组页面的字段显示设置"""
        settings = self.config.get('app_settings', {}).get('usergroup_field_settings', {}).get(api_name, {})
        visible = settings.get('visible_headers', None)
        order = settings.get('header_order', None)
        return visible if visible else None, order if order else None


    def _save_usergroup_field_settings(self, api_name, visible_headers, header_order):
        """保存用户组页面的字段显示设置到配置文件"""
        config = load_config()
        config.setdefault('app_settings', {}).setdefault('usergroup_field_settings', {})
        config['app_settings']['usergroup_field_settings'][api_name] = {
            'visible_headers': list(visible_headers),
            'header_order': list(header_order),
        }
        save_config_with_delay(config)
        self.config = config

