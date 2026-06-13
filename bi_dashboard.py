# -*- coding: utf-8 -*-
from core import *
from common import *

"""
bi_dashboard.py — BI 报表 / 仪表板 Mixin
────────────────────────────────────────
负责：MainFrame 中 BI 仪表板相关方法
  - create_bi_dashboard_page()   BI 仪表板页面（设计器 / 查看 / 列表切换）
  - _switch_to_dashboard_*       仪表板视图切换
  - _refresh_dashboard / _prewarm_dashboard  数据刷新与预热
  - ECharts 离线路径初始化
依赖：core.py / common.py / custom_report
被导入：主程序（作为 MainFrame 的 Mixin 父类）
"""
"""bi_dashboard Mixin"""

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

class bi_dashboardMixin:
    """bi_dashboard functionality."""

    def create_bi_dashboard_page(self):
        """创建 BI 报表页面（页面7）—— 独立于自定义报表的 BI 仪表盘模块"""
        page = QFrame()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # 初始化 pyecharts 离线 ECharts 路径
        try:
            from custom_report import set_echarts_base_dir
            import os as _os
            _echarts_dir = _os.path.join(
                _os.path.dirname(_os.path.abspath(__file__)),
                'echarts'
            )
            if _os.path.isdir(_echarts_dir):
                set_echarts_base_dir(_echarts_dir)
        except Exception:
            pass

        mgr = getattr(self, '_report_manager', None)

        # BI 报表内部子页面栈
        self.bi_dashboard_page_stack = QStackedWidget()

        if mgr:
            # 仪表盘列表页
            self.bi_dashboard_list_page = mgr.get_dashboard_list_page()
            self.bi_dashboard_page_stack.addWidget(self.bi_dashboard_list_page)

            # 列表页 → 查看/设计器
            if hasattr(self.bi_dashboard_list_page, 'viewRequested'):
                self.bi_dashboard_list_page.viewRequested.connect(self._switch_to_dashboard_view)
            if hasattr(self.bi_dashboard_list_page, 'editRequested'):
                self.bi_dashboard_list_page.editRequested.connect(self._switch_to_dashboard_designer)
            if hasattr(self.bi_dashboard_list_page, 'newDashboard'):
                self.bi_dashboard_list_page.newDashboard.connect(self._switch_to_dashboard_designer_new)

            # 加载数据源到列表页时刷新
            self.bi_dashboard_list_page.refresh()

            # 如果 CRM 客户端已创建，注入
            if hasattr(self, '_crm_client_instance') and self._crm_client_instance:
                mgr._fetcher._crm = self._crm_client_instance

        # 查看页 & 设计器（懒加载）
        self.bi_dashboard_view_page = None
        self.bi_dashboard_designer_page = None

        # 后台预初始化设计器（立即执行，避免 show 后 WebEngine 初始化触发重绘）
        if mgr:
            self._prewarm_dashboard_designer()

        page_layout.addWidget(self.bi_dashboard_page_stack)
        self.content_stack.addWidget(page)


    def _prewarm_dashboard_designer(self):
        """后台预创建设计器，让 WebEngine 进程提前启动"""
        mgr = getattr(self, '_report_manager', None)
        if not mgr or self.bi_dashboard_designer_page is not None:
            return
        try:
            self.bi_dashboard_designer_page = mgr.get_dashboard_designer()
            self.bi_dashboard_designer_page.backRequested.connect(self._switch_to_dashboard_list)
            self.bi_dashboard_designer_page.dashboardSaved.connect(self._on_dashboard_saved)
            self.bi_dashboard_designer_page.dataRefreshRequested.connect(
                lambda did: self._refresh_designer_data(did))
            self.bi_dashboard_page_stack.addWidget(self.bi_dashboard_designer_page)
            # 用空白页初始化 WebEngine，确保 Chromium 进程在事件循环前启动，避免与 WININET.dll 冲突
            self.bi_dashboard_designer_page._preview_webview.setHtml("<html><body></body></html>")
        except Exception:
            pass

    # ===== BI 报表内部导航 =====


    def _switch_to_dashboard_list(self):
        if not hasattr(self, 'bi_dashboard_page_stack'):
            return
        self.bi_dashboard_list_page.refresh()
        idx = self.bi_dashboard_page_stack.indexOf(self.bi_dashboard_list_page)
        if idx >= 0:
            self.bi_dashboard_page_stack.setUpdatesEnabled(False)
            self.bi_dashboard_page_stack.setCurrentIndex(idx)
            self.bi_dashboard_page_stack.setUpdatesEnabled(True)


    def _switch_to_dashboard_view(self, dashboard_id: str):
        if not hasattr(self, 'bi_dashboard_page_stack'):
            return
        mgr = getattr(self, '_report_manager', None)
        if not mgr:
            return
        dashboard = mgr.get_dashboard(dashboard_id)
        if not dashboard:
            return

        # 懒加载查看页
        if self.bi_dashboard_view_page is None:
            self.bi_dashboard_view_page = mgr.get_dashboard_view_page()
            self.bi_dashboard_view_page.backRequested.connect(self._switch_to_dashboard_list)
            self.bi_dashboard_view_page.editRequested.connect(self._switch_to_dashboard_designer)
            self.bi_dashboard_view_page.dataRefreshRequested.connect(
                lambda did: self._refresh_view_data(did))
            self.bi_dashboard_page_stack.addWidget(self.bi_dashboard_view_page)

        # 查询数据
        data_map = mgr.query_all_chart_data(dashboard)
        self.bi_dashboard_view_page.load_dashboard(dashboard, data_map)

        idx = self.bi_dashboard_page_stack.indexOf(self.bi_dashboard_view_page)
        if idx >= 0:
            self.bi_dashboard_page_stack.setCurrentIndex(idx)


    def _switch_to_dashboard_designer(self, dashboard_id: str):
        if not hasattr(self, 'bi_dashboard_page_stack'):
            return
        mgr = getattr(self, '_report_manager', None)
        if not mgr:
            return
        dashboard = mgr.get_dashboard(dashboard_id)
        if not dashboard:
            return

        # 懒加载设计器
        if self.bi_dashboard_designer_page is None:
            self.bi_dashboard_designer_page = mgr.get_dashboard_designer()
            self.bi_dashboard_designer_page.backRequested.connect(self._switch_to_dashboard_list)
            self.bi_dashboard_designer_page.dashboardSaved.connect(self._on_dashboard_saved)
            self.bi_dashboard_designer_page.dataRefreshRequested.connect(
                lambda did: self._refresh_designer_data(did))
            self.bi_dashboard_page_stack.addWidget(self.bi_dashboard_designer_page)

        # 加载数据源
        sources = mgr.get_available_data_sources()
        self.bi_dashboard_designer_page._data_source_panel.set_data_sources(sources)

        # 查询数据
        data_map = mgr.query_all_chart_data(dashboard)

        # 先加载内容再切换页面，避免切换后 WebEngine 异步渲染完成触发重绘
        self.bi_dashboard_designer_page.load_dashboard(dashboard, data_map)
        idx = self.bi_dashboard_page_stack.indexOf(self.bi_dashboard_designer_page)
        if idx >= 0:
            self.bi_dashboard_page_stack.setCurrentIndex(idx)


    def _switch_to_dashboard_designer_new(self):
        if not hasattr(self, 'bi_dashboard_page_stack'):
            return
        mgr = getattr(self, '_report_manager', None)
        if not mgr:
            return

        if self.bi_dashboard_designer_page is None:
            self.bi_dashboard_designer_page = mgr.get_dashboard_designer()
            self.bi_dashboard_designer_page.backRequested.connect(self._switch_to_dashboard_list)
            self.bi_dashboard_designer_page.dashboardSaved.connect(self._on_dashboard_saved)
            self.bi_dashboard_designer_page.dataRefreshRequested.connect(
                lambda did: self._refresh_designer_data(did))
            self.bi_dashboard_page_stack.addWidget(self.bi_dashboard_designer_page)

        sources = mgr.get_available_data_sources()
        self.bi_dashboard_designer_page._data_source_panel.set_data_sources(sources)

        # 先渲染 HTML（WebEngine 异步加载），再切换页面，避免切换后 WebEngine 渲染完成触发重绘
        self.bi_dashboard_designer_page.new_dashboard()
        idx = self.bi_dashboard_page_stack.indexOf(self.bi_dashboard_designer_page)
        if idx >= 0:
            self.bi_dashboard_page_stack.setCurrentIndex(idx)


    def _on_dashboard_saved(self, dashboard_id: str):
        """仪表盘保存回调"""
        mgr = getattr(self, '_report_manager', None)
        if mgr and self.bi_dashboard_designer_page:
            dashboard = self.bi_dashboard_designer_page._dashboard
            if dashboard:
                mgr.save_dashboard(dashboard)


    def _refresh_designer_data(self, dashboard_id: str):
        """刷新设计器中的数据 —— 同时更新 pyecharts option + 数据"""
        mgr = getattr(self, '_report_manager', None)
        if mgr and self.bi_dashboard_designer_page:
            dashboard = self.bi_dashboard_designer_page._dashboard
            if dashboard:
                data_map = mgr.query_all_chart_data(dashboard)
                if data_map:
                    self.bi_dashboard_designer_page.refresh_data(data_map)


    def _refresh_view_data(self, dashboard_id: str):
        """刷新查看页的数据"""
        mgr = getattr(self, '_report_manager', None)
        if mgr and self.bi_dashboard_view_page:
            dashboard = self.bi_dashboard_view_page._dashboard
            if dashboard:
                data_map = mgr.query_all_chart_data(dashboard)
                if data_map:
                    self.bi_dashboard_view_page.refresh_data(data_map)

