# -*- coding: utf-8 -*-
import core
from core import *
from common import *
from common import messagebox, frameless_input_text, frameless_message_box

"""
order_to_contract.py — 订单转合同 Mixin（CRM 订单 + 商机管理）
───────────────────────────────────────────────────────────
负责：MainFrame 中 CRM 订单和商机管理相关方法
  - create_crm_order_page()      CRM 订单页面（数据加载 / 筛选 / 排序 / 分页）
  - 所有 on_crm_* / _crm_* 方法   CRM 订单交互（字段映射 / 价格匹配 / 产品匹配 / 合同生成）
  - 所有 on_opportunity_* / _opp_* 方法  商机管理（模板匹配 / 资格文件 / 文件生成）
  - commit_to_svn()              SVN 提交
依赖：core.py / common.py / network.py
被导入：主程序（作为 MainFrame 的 Mixin 父类）
"""
"""order_to_contract Mixin"""

# 导入所需模块
import os
import common  # 显式导入，用于访问模块级私有函数

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

class order_to_contractMixin:
    """order_to_contract functionality."""

    def create_crm_order_page(self):
        """创建CRM订单查询页面（页面1）"""
        from PyQt6.QtWidgets import QDateEdit, QCalendarWidget, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(8)

        crm_group = QGroupBox("订单转合同")
        crm_layout = QVBoxLayout(crm_group)

        # 初始化 CRM 字段定义（_build_crm_filter_bar 及其他方法依赖）
        self.CRM_OPTION_FIELDS = {
            'field_jv2dq__c': '订单产品类型',
            'record_type': '业务类型',
            'life_status': '生命周期状态',
        }
        self.crm_fixed_headers = [""]
        self.crm_special_headers = ["模板选择", "规格型号", "客户类型", "匹配价格", "折扣单价", "产品备注", "大写", "地址", "手机"]
        self.CRM_ALL_FIELDS = [
            ("create_time", "创建时间", True),
            ("field_2maFO__c", "ERP订单号", False),
            ("name", "销售订单编号", False),
            ("owner__r", "负责人", False),
            ("field_jv2dq__c", "订单产品类型", False),
            ("account_id__r", "客户名称", False),
            ("customer_mobile", "手机", False),
            ("field_8pAwf__c", "关联客户（分销商&诊所）", False),
            ("customer_address", "地址", False),
            ("field_41yfW__c", "发货地址", False),
            ("created_by__r", "创建人", False),
            ("warranty_period__c", "保修期", False),
            ("order_amount", "销售订单金额(元)", False),
            ("field_Xqs0n__c", "订单数量", False),
            ("product_amount", "产品合计", False),
            ("payment_amount", "已收金额", False),
            ("receivable_amount", "应收金额", False),
            ("life_status", "生命周期状态", False),
            ("remark", "备注", False),
            ("record_type", "业务类型", False),
            ("submit_time", "提交时间", True),
            ("last_modified_time", "最后修改时间", True),
        ]

        # 初始化日期范围（None = 不筛选，用户可通过添加"创建时间"条件来筛选）
        self.crm_date_start = None
        self.crm_date_end = None

        # 使用新的多条件筛选栏
        filter_bar = self._build_crm_filter_bar()
        crm_layout.addLayout(filter_bar)

        data_group = QGroupBox("订单明细")
        data_layout = QVBoxLayout(data_group)

        self.crm_table = QTableWidget()
        install_table_edit_context_menu(self.crm_table)
        install_header_alignment_menu(self.crm_table, 'crm_table_settings', self._populate_crm_table)
        self.crm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.crm_table.cellClicked.connect(self.on_crm_table_cell_clicked)
        self.crm_table.setAlternatingRowColors(True)
        self.crm_table.verticalHeader().setVisible(False)
        self.crm_table_header = CheckBoxAutoFilterHeader(self.crm_table)
        self.crm_table_header.filter_changed.connect(self._on_crm_filter_changed)
        self.crm_table_header._data_provider = self._get_crm_autofilter_values
        self.crm_table.setHorizontalHeader(self.crm_table_header)
        header = self.crm_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # ✅ 修复：移除setStretchLastSection，避免最后一列自动拉伸导致保存的列宽被覆盖
        # 不再使用 setStretchLastSection(True)，让用户调整的列宽完全保持
        header.setSectionsMovable(False)
        header.setSortIndicatorShown(False)
        self.crm_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.crm_customer_type_delegate = CRMInlineComboDelegate(self, 'customer_type', self.crm_table)
        self.crm_matched_price_delegate = CRMInlineComboDelegate(self, 'matched_price', self.crm_table)
        self.crm_product_remark_delegate = CRMInlineComboDelegate(self, 'product_remark', self.crm_table)
        self.crm_default_item_delegate = QStyledItemDelegate(self.crm_table)
        self.crm_table_header.toggled.connect(self.on_crm_header_select_all_toggled)
        header.sectionResized.connect(self._on_crm_column_resized)
        self.crm_table_header.sectionClicked.connect(self.on_crm_table_header_clicked)
        data_layout.addWidget(self.crm_table, stretch=1)

        pag_bar = QHBoxLayout()

        self.crm_record_label = QLabel("共 0 条记录")
        self.crm_record_label.setStyleSheet("font-weight: bold; color: #555;")
        pag_bar.addWidget(self.crm_record_label)

        pag_bar.addStretch()

        pag_bar.addWidget(QLabel("每页："))
        self.crm_page_size_combo = QComboBox()
        self.crm_page_size_combo.setEditable(True)
        self.crm_page_size_combo.addItem("自定义", -1)
        for sz in (20, 50, 80, 100, 200):
            self.crm_page_size_combo.addItem(str(sz), sz)
        self.crm_page_size_combo.setCurrentIndex(1)
        self.crm_page_size_combo.setStyleSheet("QComboBox { font-size: 11px; padding: 2px 4px; }")
        self.crm_page_size_combo.currentIndexChanged.connect(self.on_crm_page_size_changed)
        pag_bar.addWidget(self.crm_page_size_combo)

        pag_bar.addSpacing(12)
        self.crm_prev_btn = QPushButton("<")
        self.crm_prev_btn.setFixedWidth(30)
        self.crm_prev_btn.setFixedHeight(26)
        self.crm_prev_btn.clicked.connect(self.on_crm_prev_page)
        pag_bar.addWidget(self.crm_prev_btn)

        self.crm_page_label = QLabel("1/1")
        self.crm_page_label.setFixedWidth(50)
        self.crm_page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crm_page_label.setStyleSheet("font-weight: bold; color: #333;")
        pag_bar.addWidget(self.crm_page_label)

        self.crm_next_btn = QPushButton(">")
        self.crm_next_btn.setFixedWidth(30)
        self.crm_next_btn.setFixedHeight(26)
        self.crm_next_btn.clicked.connect(self.on_crm_next_page)
        pag_bar.addWidget(self.crm_next_btn)
        data_layout.addLayout(pag_bar)

        crm_layout.addWidget(data_group, stretch=1)
        layout.addWidget(crm_group, stretch=1)

        self.crm_all_data = []
        self.crm_filtered_data = []
        self.crm_current_page_rows = []
        self.crm_current_page = 1
        self.crm_page_size = 20
        # 恢复保存的分页大小（覆盖默认值20）
        if hasattr(self, '_restore_page_sizes'):
            self._restore_page_sizes()
            self.crm_page_size = self._get_combo_page_size(self.crm_page_size_combo)
        self.crm_selected_row_ids = set()
        self.crm_sort_header = ""
        self.crm_sort_order = Qt.SortOrder.AscendingOrder
        self._crm_row_templates = {}
        self.crm_auto_refresh_timer = QTimer()
        self.crm_auto_refresh_timer.setSingleShot(False)
        self.crm_auto_refresh_timer.timeout.connect(self.on_crm_auto_refresh_tick)

        saved_option_mappings = self.config.get('business_rules', {}).get('crm_option_mappings', {})
        self.crm_option_mappings = {}
        for field_name, mappings in saved_option_mappings.items():
            if isinstance(mappings, dict):
                self.crm_option_mappings[field_name] = mappings

        def _load_crm_field_settings():
            """内部方法：加载CRM字段设置。"""
            app_set = self.config.get('app_settings', {})
            crm_set = app_set.get('crm_table_settings', {})
            saved_visible = crm_set.get('visible_headers', [])
            saved_order = crm_set.get('header_order', [])
            default_names = self._get_crm_configurable_headers()
            if not saved_visible and not saved_order:
                return default_names, default_names

            if not saved_visible:
                saved_visible = list(default_names)
            if not saved_order:
                saved_order = list(default_names)

            saved_visible = [label for label in saved_visible if label in default_names]
            saved_order = [label for label in saved_order if label in default_names]

            legacy_layout = not any(label in self.crm_special_headers for label in saved_visible + saved_order)
            if legacy_layout:
                saved_visible = list(self.crm_special_headers) + [
                    label for label in saved_visible if label not in self.crm_special_headers
                ]
                saved_order = list(self.crm_special_headers) + [
                    label for label in saved_order if label not in self.crm_special_headers
                ]

            merged_order = self._compose_crm_header_order(saved_order)

            if '折扣单价' in default_names and '折扣单价' not in saved_visible and '折扣单价' not in saved_order:
                saved_visible.append('折扣单价')

            for must_show_label in ("手机", "关联客户（分销商&诊所）", "地址"):
                if must_show_label in default_names and must_show_label not in saved_visible:
                    saved_visible.append(must_show_label)

            merged_visible = [label for label in merged_order if label in saved_visible]
            return merged_visible, merged_order

        vis, order = _load_crm_field_settings()
        self.crm_visible_headers = vis
        self.crm_header_order = order

        self._apply_crm_table_columns()

        self.content_stack.addWidget(page)
        self._crm_initial_load()


    def _lookup_crm_object_type(self, api_name):
        """从配置中查找对象的类型（preset/custom/usergroup），默认返回 preset"""
        fx_cfg = getattr(self, 'config', {}).get('fxiaoke', {})
        for obj in fx_cfg.get('crm_objects', []):
            if isinstance(obj, dict) and obj.get('api_name') == api_name:
                return obj.get('object_type', 'preset')
        return 'preset'


    def _get_crm_object_fields_cached(self, api_name):
        """从缓存获取 CRM 对象字段（无网络请求，缓存已由字段管理页面预热）"""
        fields = getattr(self, 'crm_object_fields_cache', {}).get(api_name, [])
        if not fields:
            # 尝试同步获取（可能触发网络请求，但数据量小）
            try:
                fields = self._get_crm_object_fields_api(api_name)
            except Exception:
                pass
        return fields or []


    def _get_crm_object_fields_api(self, object_api_name, object_type=None):
        """获取 CRM 对象字段列表并缓存。

        根据对象类型使用不同的API：
        - 预设对象：使用 describeObject API
        - 自定义对象：使用 custom/v2/data/query API
        """
        import requests
        if object_api_name in getattr(self, 'crm_object_fields_cache', {}):
            return self.crm_object_fields_cache[object_api_name]

        # 查找对象类型（如果未传入）
        if object_type is None:
            fx_cfg = getattr(self, 'config', {}).get('fxiaoke', {})
            crm_objs = fx_cfg.get('crm_objects', [])
            for obj in crm_objs:
                if isinstance(obj, dict) and obj.get('api_name') == object_api_name:
                    object_type = obj.get('object_type', 'preset')
                    break
            if object_type is None:
                object_type = 'preset'

        try:
            fx_cfg = getattr(self, 'config', {}).get('fxiaoke', {})
            crm = FXiaokeCRM(
                app_id=fx_cfg.get('app_id', 'FSAID_1323c1a'),
                app_secret=fx_cfg.get('app_secret', 'e7f4188d14704299b375c91ddda92cb0'),
                permanent_code=fx_cfg.get('permanent_code', 'E8B8D8536B0385D035657AC2528928F0'),
                admin_mobile=fx_cfg.get('admin_mobile', '15889740213')
            )
            if not crm.corp_access_token:
                ok, _ = crm.get_corp_access_token()
                if not ok:
                    return []
            if not crm.current_open_user_id:
                uid, _ = crm.get_open_user_id_by_mobile()
                if not uid:
                    return []

            if object_type == 'custom':
                # 自定义对象：使用 custom/v2/data/query 获取字段
                url = "https://open.fxiaoke.com/cgi/crm/custom/v2/data/query"
                req_data = {
                    "corpAccessToken": crm.corp_access_token,
                    "corpId": crm.corp_id,
                    "currentOpenUserId": crm.current_open_user_id,
                    "data": {
                        "dataObjectApiName": object_api_name,
                        "search_query_info": {
                            "limit": 1,
                            "offset": 0,
                            "filters": []
                        }
                    }
                }
                resp = perform_requests_request('post', url, json=req_data, timeout=20)
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("errorCode") == 0:
                        records = result.get("data", {}).get("dataList", [])
                        fields = []
                        if records:
                            sample = records[0]
                            for key, val in sample.items():
                                inferred_type = self._infer_field_type_from_value(val, key)
                                fields.append({
                                    'apiName': key,
                                    'label': key,
                                    'dataType': inferred_type,
                                })
                        if not hasattr(self, 'crm_object_fields_cache'):
                            self.crm_object_fields_cache = {}
                        self.crm_object_fields_cache[object_api_name] = fields
                        return fields
            else:
                # 预设对象：使用 describeObject API
                url = "https://open.fxiaoke.com/cgi/crm/v2/meta/describeObject"
                req_data = {
                    "corpAccessToken": crm.corp_access_token,
                    "corpId": crm.corp_id,
                    "currentOpenUserId": crm.current_open_user_id,
                    "data": {"dataObjectApiName": object_api_name}
                }
                resp = perform_requests_request('post', url, json=req_data, timeout=20)
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("errorCode") == 0:
                        fields = result.get("data", {}).get("fields", [])
                        if not hasattr(self, 'crm_object_fields_cache'):
                            self.crm_object_fields_cache = {}
                        self.crm_object_fields_cache[object_api_name] = fields
                        return fields
        except Exception:
            pass
        return []


    def _get_primary_crm_objects(self):
        """获取可作为主对象的数据源列表（始终包含部门员工内置数据源）。"""
        crm_objs = self.config.get('fxiaoke', {}).get('crm_objects', [])
        if not crm_objs:
            crm_objs = [
                {'name': '商机', 'api_name': 'NewOpportunityObj'},
                {'name': '销售订单', 'api_name': 'SalesOrderObj'},
                {'name': '发货单', 'api_name': 'DeliveryNoteObj'},
                {'name': '发货单产品', 'api_name': 'DeliveryNoteProductObj'},
            ]
        return crm_objs


    def open_crm_date_filter_dialog(self):
        """打开CRM订单日期选择弹窗"""
        dialog = QuickDatePickerDialog(
            self.crm_date_start,
            self.crm_date_end,
            self
        )
        dialog.position_below_widget(self.crm_date_filter_btn)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.crm_date_start = dialog.start_date
            self.crm_date_end = dialog.end_date
            if (
                self.crm_date_start and self.crm_date_end
                and self.crm_date_start.isValid() and self.crm_date_end.isValid()
            ):
                self.crm_date_filter_btn.setText(
                    f"{self.crm_date_start.toString('yyyy-MM-dd')} ~ "
                    f"{self.crm_date_end.toString('yyyy-MM-dd')}"
                )
            self.on_crm_local_filter_changed()


    def _crm_initial_load(self):
        """页面初始化时不自动加载 CRM 订单。"""
        self._crm_auto_refresh_activated = False  # 标记：自动刷新是否已激活
        self._crm_first_load_completed = False   # ✅【新增】标记：首次加载是否已完成
        self._opportunity_first_load_completed = False  # 标记：招投标授权首次加载是否已完成


    def on_crm_auto_refresh_tick(self):
        """响应CRM自动刷新定时轮询相关操作。"""
        if not getattr(self, '_crm_is_loading', False):
            self.on_crm_refresh_orders()


    def _get_opp_filter_headers(self):
        """获取商机可筛选字段列表"""
        headers = getattr(self, 'opportunity_visible_columns', None) or []
        if headers:
            return [str(h).strip() for h in headers if h and str(h).strip()]
        if hasattr(self, 'opportunity_table') and self.opportunity_table.columnCount() > 0:
            result = []
            for col in range(self.opportunity_table.columnCount()):
                item = self.opportunity_table.horizontalHeaderItem(col)
                if item:
                    txt = item.text().strip()
                    if txt:
                        result.append(txt)
            return result
        return []


    def _is_opp_date_field(self, field_label):
        """判断是否为日期/时间字段"""
        if not field_label:
            return False
        label = str(field_label)
        return '日期' in label or '时间' in label


    def _ensure_opp_filter_panel(self):
        """懒初始化商机 FilterPanel（仅创建一次）"""
        if hasattr(self, "_opp_filter_panel"):
            return
        self._opp_filter_panel = FilterPanel(
            self,
            mode="inline",
            title="设置筛选",
            show_title=False,
            show_add_btn=True,
            show_apply_btn=True,
            show_clear_btn=True,
            show_save_btn=True,
            row_defaults={
                "field_options": self._get_opp_filter_headers(),
                "value_pages": ("text", "date", "date_range"),
                "show_expose": True,
                "debounce_ms": 300,
                "is_date_field_cb": self._is_opp_date_field,
                "show_picker": False,
            },
        )
        # 隐藏 pdf_watermark.py 创建的旧 QFrame（已弃用）
        old_frame = getattr(self, 'opp_conditions_frame', None)
        if old_frame is not None:
            p = old_frame.parent()
            if p is not None:
                p.setVisible(False)
        # 兼容层
        self.opp_filter_panel = self._opp_filter_panel._panel_frame
        self.opp_condition_rows = self._opp_filter_panel._legacy_rows
        self._opp_filter_panel._panel_frame.setFixedWidth(500)
        # 连接 FilterPanel 按钮回调
        self._opp_filter_panel._on_save_preset = lambda panel: self._save_opp_filter_preset()
        self._opp_filter_panel._on_apply = lambda panel: self._apply_opp_filter_and_close()
        # "清除" 按钮直接调用 clear_all()，需要在此之后重新筛选
        _orig_clear = self._opp_filter_panel.clear_all
        def _clear_and_refilter():
            _orig_clear()
            self._apply_opp_filters()
        self._opp_filter_panel.clear_all = _clear_and_refilter

    def _toggle_opportunity_filter_panel(self):
        """切换商机筛选面板（照搬CRM订单）"""
        self._ensure_opp_filter_panel()
        panel = self._opp_filter_panel._panel_frame
        visible = panel.isVisible()
        if not visible:
            self._adjust_opp_filter_panel_size()
            panel.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            panel.setVisible(True)
            panel.raise_()
            panel.activateWindow()
            search_frame = self.opp_search_stack.parent()
            if search_frame:
                pos = search_frame.mapToGlobal(QPoint(0, search_frame.height()))
                x, y = pos.x(), pos.y() + 4
            else:
                x, y = self.geometry().x() + 100, self.geometry().y() + 80
            screen = self.screen()
            if screen:
                geo = screen.availableGeometry()
                x = max(geo.x() + 10, min(x, geo.right() - panel.width() - 10))
                y = max(geo.y() + 10, min(y, geo.bottom() - panel.height() - 10))
            panel.move(x, y)
            panel.reject = lambda: panel.setVisible(False)
            panel._outside_close_armed = False
            pf = common._DialogOutsideCloseFilter(panel)
            panel._outside_filter = pf
            QApplication.instance().installEventFilter(pf)
            QTimer.singleShot(0, lambda p=panel: setattr(p, '_outside_close_armed', True))
            panel.destroyed.connect(lambda obj, f=pf: QApplication.instance().removeEventFilter(f))
        else:
            panel.setVisible(False)
        self._update_opp_filter_toggle_btn()


    def _refresh_opp_search_field_combo(self):
        """[兼容层] 搜索字段下拉已移除，保留方法避免调用错误。"""
        pass


    def _update_opp_search_field(self):
        """[兼容层] 搜索字段下拉已移除，保留方法避免调用错误。"""
        pass


    def _open_opp_search_date_range(self):
        """打开商机搜索栏日期范围选择"""
        btn = self.opp_search_date_btn
        dr = btn.property('date_range') or {'start': None, 'end': None}
        dlg = QuickDatePickerDialog(start_date=dr.get('start'), end_date=dr.get('end'), parent=self)
        dlg.set_popup_anchor_widget(btn)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.start_date and dlg.end_date:
            new_range = {'start': dlg.start_date, 'end': dlg.end_date}
            btn.setProperty('date_range', new_range)
            btn.setText(f"{dlg.start_date.toString('yyyy-MM-dd')} ~ {dlg.end_date.toString('yyyy-MM-dd')}")
            self._apply_opp_filters()


    def _update_opp_filter_toggle_btn(self):
        """Update toggle button badge (delegated to FilterPanel)."""
        if hasattr(self, "_opp_filter_panel"):
            self._opp_filter_panel._update_toggle_badge()
    def _add_opp_condition_row(self, condition=None):
        """Add an opportunity filter condition row (delegated to FilterPanel)."""
        self._ensure_opp_filter_panel()
        return self._opp_filter_panel.add_row(condition)
    def _update_opp_condition_input_mode(self, row_info):
        """No-op: input mode is automatically handled by FilterPanel."""
        pass
    def _open_opp_date_range(self, btn):
        """打开商机日期范围选择弹窗"""
        dr = btn.property('date_range') or {'start': None, 'end': None}
        dlg = QuickDatePickerDialog(start_date=dr.get('start'), end_date=dr.get('end'), parent=self)
        dlg.set_popup_anchor_widget(btn)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.start_date and dlg.end_date:
            new_range = {'start': dlg.start_date, 'end': dlg.end_date}
            btn.setProperty('date_range', new_range)
            btn.setText(f"{dlg.start_date.toString('yyyy-MM-dd')} ~ {dlg.end_date.toString('yyyy-MM-dd')}")
            self._apply_opp_filters()


    def _adjust_opp_filter_panel_size(self):
        """动态调整商机筛选面板高度"""
        if not hasattr(self, '_opp_filter_panel'):
            return
        row_count = len(getattr(self, 'opp_condition_rows', []))
        h = 36 + row_count * 32 + max(0, row_count - 1) * 4 + 44 + 24
        h = max(140, min(h, 500))
        self._opp_filter_panel._panel_frame.setFixedHeight(h)


    def _apply_opp_filter_and_close(self):
        """应用商机筛选并关闭弹窗"""
        self._apply_opp_filters()
        self._refresh_opp_exposed_tags()
        if hasattr(self, '_opp_filter_panel'):
            self._opp_filter_panel._panel_frame.setVisible(False)
        self._update_opp_filter_toggle_btn()


    def _remove_opp_condition_row(self, row_info):
        """Remove an opportunity filter condition row (delegated to FilterPanel)."""
        if hasattr(self, "_opp_filter_panel"):
            if isinstance(row_info, dict) and "row" in row_info:
                self._opp_filter_panel.remove_row(row_info["row"])
            else:
                self._opp_filter_panel.remove_row(row_info)
    def _collect_opp_filter_conditions(self):
        """Collect all opportunity filter conditions (delegated to FilterPanel)."""
        if hasattr(self, "_opp_filter_panel"):
            return self._opp_filter_panel.get_all_conditions()
        return []
    def _apply_opp_condition_filter(self, headers, data_rows):
        """应用商机多条件筛选（照搬CRM订单引擎）"""
        conditions = self._collect_opp_filter_conditions()
        if not conditions:
            return data_rows
        col_map = {}
        for idx, h in enumerate(headers):
            if h is not None:
                col_map[str(h).strip()] = idx
        filtered = []
        for entry in data_rows:
            if isinstance(entry, tuple) and len(entry) == 2:
                row_idx, row_values = entry
            else:
                row_values = entry
            match = True
            for cond in conditions:
                field = cond['field']
                op = cond['operator']
                val = cond['value'].lower()
                col_idx = col_map.get(field, -1)
                if col_idx < 0 or col_idx >= len(row_values):
                    continue
                cell_val = str(row_values[col_idx] if row_values[col_idx] is not None else '').strip().lower()
                date_val = cell_val[:10]
                if op == 'contains' and val not in cell_val:
                    match = False
                elif op == 'eq' and cell_val != val:
                    match = False
                elif op == 'ne' and cell_val == val:
                    match = False
                elif op == 'starts_with' and not cell_val.startswith(val):
                    match = False
                elif op == 'ends_with' and not cell_val.endswith(val):
                    match = False
                elif op == 'empty' and cell_val:
                    match = False
                elif op == 'not_empty' and not cell_val:
                    match = False
                elif op == 'date_before' and date_val >= val:
                    match = False
                elif op == 'date_after' and date_val <= val:
                    match = False
                elif op == 'date_range' and '~' in val:
                    parts = val.split('~')
                    if not (parts[0].strip() <= date_val <= parts[1].strip()):
                        match = False
                if not match:
                    break
            if match:
                filtered.append(entry)
        return filtered


    def on_opp_search_changed(self, text):
        """商机搜索框输入变化 → 防抖后重新筛选（300ms）"""
        if hasattr(self, '_opp_search_debounce_timer'):
            if self._opp_search_debounce_timer.isActive():
                self._opp_search_debounce_timer.stop()
            self._opp_search_debounce_timer.start(300)


    def _apply_opp_filters(self):
        """应用商机筛选条件，通过临时数据集交给 _populate_opportunity_table 渲染（复用所有格式化逻辑）"""
        if not hasattr(self, 'opportunity_all_data') or not self.opportunity_all_data:
            return
        if not hasattr(self, 'opportunity_table'):
            return

        visible_columns = getattr(self, 'opportunity_visible_columns', None) or []
        opp_map = getattr(self, 'opportunity_field_map', {})

        # 收集条件筛选
        conditions = self._collect_opp_filter_conditions() if hasattr(self, 'opp_condition_rows') else []
        col_map = {}
        for idx, h in enumerate(visible_columns):
            if h is not None:
                col_map[str(h).strip()] = idx

        # 搜索文本
        search_text = getattr(self, 'opp_search_input', None)
        search_text = search_text.text().strip().lower() if search_text else ""

        # 全字段搜索
        opp_mappings = getattr(self, 'opp_option_mappings', {})

        def _to_display_val(api_name, raw_val):
            """将原始 API 值转换为显示文本（应用选项值映射）"""
            raw_str = str(raw_val or '')
            field_mapping = opp_mappings.get(api_name, {})
            mappings = field_mapping.get('mappings', {}) if isinstance(field_mapping, dict) else {}
            if mappings:
                # 处理多值字段（逗号分隔）
                if ', ' in raw_str or raw_str.startswith('['):
                    parts = [p.strip() for p in raw_str.replace('[', '').replace(']', '').replace("'", '').replace('"', '').split(',')]
                    return ', '.join(str(mappings.get(p, p)) for p in parts)
                else:
                    return str(mappings.get(raw_str, raw_str))
            return raw_str

        filtered_opps = []
        for opp in self.opportunity_all_data:
            # 构建行值用于筛选（应用选项值映射后与用户输入比较）
            row_vals = []
            for header in visible_columns:
                api_name = opp_map.get(header, header)
                raw_val = opp.get(api_name, '')
                display_val = _to_display_val(api_name, raw_val)
                row_vals.append(display_val)

            # 搜索过滤（搜索字段下拉已移除，统一全字段搜索）
            if search_text:
                if not any(search_text in str(v).lower() for v in row_vals):
                    continue

            # 条件筛选
            if conditions:
                match = True
                for cond in conditions:
                    field = cond['field']
                    op = cond['operator']
                    val = cond['value'].lower()
                    col_idx = col_map.get(field, -1)
                    if col_idx < 0 or col_idx >= len(row_vals):
                        continue
                    cell_val = str(row_vals[col_idx] if row_vals[col_idx] is not None else '').strip().lower()
                    date_val = cell_val[:10]
                    if op == 'contains' and val not in cell_val:
                        match = False
                    elif op == 'eq' and cell_val != val:
                        match = False
                    elif op == 'ne' and cell_val == val:
                        match = False
                    elif op == 'starts_with' and not cell_val.startswith(val):
                        match = False
                    elif op == 'ends_with' and not cell_val.endswith(val):
                        match = False
                    elif op == 'empty' and cell_val:
                        match = False
                    elif op == 'not_empty' and not cell_val:
                        match = False
                    elif op == 'date_before' and date_val >= val:
                        match = False
                    elif op == 'date_after' and date_val <= val:
                        match = False
                    elif op == 'date_range' and '~' in val:
                        parts = val.split('~')
                        if not (parts[0].strip() <= date_val <= parts[1].strip()):
                            match = False
                    if not match:
                        break
                if not match:
                    continue

            filtered_opps.append(opp)

        # 暂存原数据，用筛选结果渲染，然后恢复
        self.opportunity_current_page = 1
        saved = self.opportunity_all_data
        self.opportunity_all_data = filtered_opps
        try:
            self._populate_opportunity_table(data=filtered_opps)
        finally:
            self.opportunity_all_data = saved


    def _clear_all_opp_conditions(self):
        """Clear all opportunity filter conditions (delegated to FilterPanel)."""
        if hasattr(self, "_opp_filter_panel"):
            self._opp_filter_panel.clear_all()
    def _show_opportunity_preset_popup(self):
        """弹出商机方案选择面板（含加载/修改/设为默认/删除按钮）"""
        presets = self.config.get('opp_filter_presets', [])
        if not isinstance(presets, list):
            presets = []
        default_name = self.config.get('opp_filter_default_preset', '')

        popup = QFrame()
        popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setStyleSheet("QFrame { border: 1px solid #D9D9D9; border-radius: 4px; background: #FFF; }")
        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(4, 4, 4, 4)
        popup_layout.setSpacing(2)

        none_btn = QPushButton("(未选择)")
        none_btn.setFixedHeight(28)
        none_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        none_btn.setStyleSheet("QPushButton { border: none; text-align: left; padding: 4px 8px; font-size: 12px; color: #999; background: transparent; } QPushButton:hover { background: #F5F5F5; }")
        none_btn.clicked.connect(lambda: [self._clear_all_opp_conditions(), self._apply_opp_filters(), setattr(self, '_opp_active_preset_name', None), self._update_opp_preset_btn_label(), popup.close()])
        popup_layout.addWidget(none_btn)

        icon_style = """
            QPushButton { border: none; border-radius: 2px; font-size: 13px; background: transparent; color: #999; }
            QPushButton:hover { background: #E6F7FF; color: #1890FF; }
        """
        for preset in presets:
            name = preset.get('name', '')
            display = f"★ {name}" if name == default_name else name
            row = QFrame()
            row.setFixedHeight(30)
            row.setStyleSheet("QFrame { border: none; background: transparent; }")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            load_btn = QPushButton(display)
            load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            load_btn.setStyleSheet("QPushButton { border: none; text-align: left; padding: 4px 8px; font-size: 12px; color: #333; background: transparent; } QPushButton:hover { background: #E6F7FF; color: #1890FF; }")
            load_btn.clicked.connect(lambda checked, n=name: [setattr(self, '_opp_active_preset_name', n), self._load_opp_filter_preset(n), self._update_opp_preset_btn_label(), popup.close()])
            row_layout.addWidget(load_btn, stretch=1)
            # 修改按钮（✎）— 用当前条件覆盖方案
            mod_btn = QPushButton("✎")
            mod_btn.setFixedSize(22, 22)
            mod_btn.setStyleSheet(icon_style)
            mod_btn.setToolTip(f"用当前筛选条件覆盖「{name}」")
            mod_btn.clicked.connect(lambda checked, n=name: [self._update_opp_filter_preset(n), popup.close(), self._update_opp_preset_btn_label()])
            row_layout.addWidget(mod_btn)
            # 默认按钮（★）
            def_btn = QPushButton("★")
            def_btn.setFixedSize(22, 22)
            if name == default_name:
                def_btn.setStyleSheet("QPushButton { border: none; border-radius: 2px; font-size: 13px; background: transparent; color: #FA8C16; } QPushButton:hover { background: #FFF7E6; color: #FA8C16; }")
            else:
                def_btn.setStyleSheet(icon_style)
            def_btn.setToolTip(f"设置/取消「{name}」为默认方案")
            def_btn.clicked.connect(lambda checked, n=name: [self._set_opp_filter_default_preset(n), popup.close(), self._update_opp_preset_btn_label()])
            row_layout.addWidget(def_btn)
            # 删除按钮（✕）
            del_btn = QPushButton("✕")
            del_btn.setFixedSize(22, 22)
            del_btn.setStyleSheet(icon_style + "QPushButton:hover { background: #FFF2F0; color: #FF4D4F; }")
            del_btn.setToolTip(f"删除「{name}」")
            del_btn.clicked.connect(lambda checked, n=name: [self._delete_opp_filter_preset(n), popup.close(), self._update_opp_preset_btn_label()])
            row_layout.addWidget(del_btn)
            popup_layout.addWidget(row)

        popup.adjustSize()
        btn_pos = self.opportunity_preset_btn.mapToGlobal(QPoint(0, self.opportunity_preset_btn.height()))
        popup.move(btn_pos.x(), btn_pos.y() + 2)
        popup.reject = popup.close
        popup._outside_close_armed = False
        pf = common._DialogOutsideCloseFilter(popup)
        QApplication.instance().installEventFilter(pf)
        QTimer.singleShot(0, lambda p=popup: setattr(p, '_outside_close_armed', True))
        popup.destroyed.connect(lambda obj, f=pf: QApplication.instance().removeEventFilter(f))
        popup.show()


    def _load_opp_filter_preset(self, name):
        """加载商机筛选方案"""
        presets = self.config.get('opp_filter_presets', [])
        if not isinstance(presets, list):
            return
        target = next((p for p in presets if p.get('name') == name), None)
        if not target:
            return
        conditions = target.get('conditions', [])
        self._clear_all_opp_conditions()
        for cond in conditions:
            self._add_opp_condition_row(cond)
        self._apply_opp_filters()


    def _delete_opp_filter_preset(self, name):
        """删除商机筛选方案"""
        presets = self.config.get('opp_filter_presets', [])
        if not isinstance(presets, list):
            return
        reply = frameless_message_box(self, '确认删除', f'确定删除方案「{name}」吗？', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.config['opp_filter_presets'] = [p for p in presets if p.get('name') != name]
        # 如果删除的是默认方案，清除默认设置
        if self.config.get('opp_filter_default_preset') == name:
            self.config['opp_filter_default_preset'] = ''
        save_config(self.config)


    def _save_opp_filter_preset(self):
        """保存商机筛选条件为方案"""
        conditions = self._collect_opp_filter_conditions()
        name, ok = frameless_input_text(self, "保存筛选方案", "请输入方案名称：")
        if not ok or not name or not name.strip():
            return
        name = name.strip()
        presets = self.config.get('opp_filter_presets', [])
        if not isinstance(presets, list):
            presets = []
        existing = next((i for i, p in enumerate(presets) if p.get('name') == name), None)
        if existing is not None:
            reply = frameless_message_box(self, '确认覆盖', f'方案「{name}」已存在，是否覆盖？', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            presets[existing] = {'name': name, 'conditions': conditions}
        else:
            presets.append({'name': name, 'conditions': conditions})
        self.config['opp_filter_presets'] = presets
        save_config(self.config)
        frameless_message_box(self, "成功", f"方案「{name}」已保存。")


    def _update_opp_filter_preset(self, preset_name):
        """用当前筛选条件覆盖指定方案"""
        if not preset_name:
            return
        presets = self.config.get('opp_filter_presets', [])
        if not isinstance(presets, list):
            return
        idx = next((i for i, p in enumerate(presets) if p.get('name') == preset_name), None)
        if idx is None:
            return
        conditions = self._collect_opp_filter_conditions()
        presets[idx] = {'name': preset_name, 'conditions': conditions}
        self.config['opp_filter_presets'] = presets
        save_config(self.config)


    def _set_opp_filter_default_preset(self, preset_name):
        """切换默认方案：已是默认则取消，否则设为默认"""
        if not preset_name:
            return
        current_default = self.config.get('opp_filter_default_preset', '')
        if current_default == preset_name:
            self.config['opp_filter_default_preset'] = ''
            save_config(self.config)
            self._update_opp_preset_btn_label()
        else:
            presets = self.config.get('opp_filter_presets', [])
            if not isinstance(presets, list) or not any(p.get('name') == preset_name for p in presets):
                return
            self.config['opp_filter_default_preset'] = preset_name
            save_config(self.config)
            self._update_opp_preset_btn_label()


    def _update_opp_preset_btn_label(self):
        """更新方案按钮标签为当前激活的方案名"""
        active = getattr(self, '_opp_active_preset_name', None)
        if active:
            self.opportunity_preset_btn.setText(f"方案: {active} ▼")
        else:
            self.opportunity_preset_btn.setText("方案 ▼")


    def _refresh_opp_exposed_tags(self):
        """Refresh opportunity exposed tags (delegated to FilterPanel)."""
        if hasattr(self, "_opp_filter_panel"):
            self._opp_filter_panel.refresh_exposed_tags()
    def open_opportunity_field_settings_dialog(self):
        """打开商机字段显示设置对话框（与CRM订单保持一致）"""
        operation_log.info("打开商机字段设置对话框")

        # ✅ 从设置中动态获取商机字段列表
        cfg = load_config()
        opp_field_mapping_list = cfg.get('opportunity', {}).get('field_mapping_list', [])
        if opp_field_mapping_list:
            all_headers = [m.get('display_name', m.get('api_name', '')) for m in opp_field_mapping_list if m.get('api_name')]
        else:
            all_headers = [
                "商机名称", "意向产品（多选）", "报价（元/台）", "竞争对手（多选）", "终端客户省份",
                "是否招投标项目", "医院等级", "授权类型", "招标日期",
                "项目号", "项目名称", "授权开始日期", "授权结束日期",
                "是否邮寄原件", "授权备注", "竞争对手产品型号", "把握性百分比(%)",
                "终端用户所在省", "终端用户准确名称", "该项目授权代理商名称",
                "授权经销商资质文件", "招标公告", "创建时间", "创建人",
                "负责人", "业务类型",
            ]
        # 非CRM自定义字段（保持不变）
        for extra in ["模板选择", "产品名称", "规格型号"]:
            if extra not in all_headers:
                all_headers.append(extra)

        visible_headers = getattr(self, 'opportunity_visible_columns', None)
        if visible_headers is None:
            # ✅ 默认显示字段映射列表中的所有字段 + 非CRM字段
            visible_headers = list(all_headers)

        # ✅ 过滤掉已不在字段映射列表中的旧表头
        visible_headers = [h for h in visible_headers if h in all_headers]

        header_order = getattr(self, 'opportunity_header_order', None)
        if header_order is None:
            header_order = visible_headers[:]
        # ✅ 过滤掉已不在字段映射列表中的旧表头
        header_order = [h for h in header_order if h in all_headers]

        dialog = ExcelFieldSettingsDialog(
            headers=all_headers,
            visible_headers=visible_headers[:],
            header_order=header_order[:],
            parent=self
        )
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            new_vis, new_order = dialog.get_settings()
            self.opportunity_visible_columns = new_vis
            self.opportunity_header_order = new_order

            config = load_config()
            app_set = config.setdefault('app_settings', {})
            opportunity_table_settings = app_set.setdefault('opportunity_table_settings', {})
            opportunity_table_settings['visible_columns'] = new_vis
            opportunity_table_settings['header_order'] = new_order
            save_config(config, immediate=True)
            self.config = config

            operation_log.info(f"商机字段设置已变更 | 显示字段数:{len(new_vis)} | 字段顺序已更新")

            # 重置列宽应用标记，以便新列布局重新应用保存的列宽
            self._opportunity_column_widths_applied = False

            # ✅ 延迟重建表格，避免阻塞 UI 线程导致卡顿
            if hasattr(self, 'opportunity_all_data') and self.opportunity_all_data:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(50, self._populate_opportunity_table)


    def _on_opp_refresh_btn_clicked(self):
        """商机刷新按钮点击：从CRM API获取最新数据"""
        flush_pending_config()
        self._force_opp_api_refresh = True
        self.on_refresh_opportunity_data()


    def on_refresh_opportunity_data(self):
        """刷新商机明细数据 — 始终从 CRM API 获取，不使用本地缓存"""
        if getattr(self, '_opportunity_is_loading', False):
            return

        # ✅ 确保待保存的配置已写入磁盘，并加载最新配置（与 CRM on_crm_refresh_orders 一致）
        flush_pending_config()
        self.config = load_config()

        self._force_opp_api_refresh = False
        self._opportunity_is_loading = True
        # ✅ 安全访问：控件可能未创建（PDF水印页面已移除）
        if hasattr(self, 'opportunity_refresh_btn'):
            self.opportunity_refresh_btn.setText("加载中...")
        if hasattr(self, 'opportunity_status_label'):
            self.opportunity_status_label.setText("从CRM加载数据...")
        self.update_output.emit("[商机] 🌐 从CRM API获取数据...")

        import threading
        t = threading.Thread(target=self._opportunity_fetch_worker, daemon=True)
        t.start()


    def _opportunity_fetch_worker(self):
        """商机数据加载工作线程"""
        try:
            cfg = load_config()
            fx_cfg = cfg.get('fxiaoke', {})
            crm = FXiaokeCRM(
                app_id=fx_cfg.get('app_id', 'FSAID_1323c1a'),
                app_secret=fx_cfg.get('app_secret', 'e7f4188d14704299b375c91ddda92cb0'),
                permanent_code=fx_cfg.get('permanent_code', 'E8B8D8536B0385D035657AC2528928F0'),
                admin_mobile=fx_cfg.get('admin_mobile', '15889740213')
            )

            # 商机筛选条件：根据招标映射值的业务类型动态过滤
            filters = []

            # 从 opp 选项映射中读取 record_type 的业务类型选项
            # 优先使用用户选择的筛选类型，否则使用全部已配置的映射值
            opp_query_record_types = fx_cfg.get('opp_query_record_types', [])
            opp_option_mappings = cfg.get('opportunity', {}).get('option_mappings', {})
            record_type_mapping = opp_option_mappings.get('record_type', {})
            if isinstance(record_type_mapping, dict):
                if opp_query_record_types:
                    # 用户选择了特定业务类型
                    filters.append({
                        "field_name": "record_type",
                        "operator": "IN",
                        "field_values": opp_query_record_types,
                    })
                else:
                    # 默认加载全部已配置映射的业务类型
                    record_type_mappings = record_type_mapping.get('mappings', {})
                    if record_type_mappings:
                        filters.append({
                            "field_name": "record_type",
                            "operator": "IN",
                            "field_values": list(record_type_mappings.keys()),
                        })

            # 合并用户设置的筛选条件
            user_filters = getattr(self, 'opportunity_current_filters', [])
            if user_filters:
                filters.extend(user_filters)

            raw_load_count = fx_cfg.get('opportunity_load_count', 100)
            try:
                load_count = int(raw_load_count)
            except (TypeError, ValueError):
                load_count = 100

            if load_count > 10000:
                load_count = 10000
            elif load_count < 1:
                load_count = 100

            # 从设置中获取要加载的商机字段（招标设置-字段映射列表的API名称）
            opp_field_mapping_list = cfg.get('opportunity', {}).get('field_mapping_list', [])
            opp_api_field_keys = [m.get('api_name', '') for m in opp_field_mapping_list if m.get('api_name')]

            # 确保基础必要字段始终加载
            opp_essential = ['_id', 'name', 'owner__r', 'created_by__r', 'life_status', 'record_type', 'owner', 'created_by']
            opportunity_field_projection = list(dict.fromkeys(opp_essential + opp_api_field_keys))
            # ✅ 自动补充 __r 关联字段，确保名称解析有数据来源
            for f in list(opportunity_field_projection):
                if not f.endswith('__r') and f'{f}__r' not in opportunity_field_projection:
                    opportunity_field_projection.append(f'{f}__r')

            # 使用fetch_all_data_object获取商机数据（指定字段投影）
            data, total, err = crm.fetch_all_data_object(
                data_object_api_name='NewOpportunityObj',
                max_records=load_count,
                batch_size=100,
                filters=filters,
                field_projection=opportunity_field_projection
            )

            if err:
                self.update_output.emit(f"[商机] API错误: {err}")
                self.opportunity_all_data = []
            else:
                # 直接从 API 数据过滤 invalid，不使用本地缓存
                self.opportunity_all_data = [r for r in (data or []) if str(r.get('life_status', '')).lower() != 'invalid']
                self.opportunity_current_page = 1

                self.update_output.emit(f"[商机] 数据加载完成: {len(self.opportunity_all_data)} 条 (API总计: {total})")

            # 在主线程中更新表格
            self.opportunity_data_ready.emit()

        except Exception as e:
            self.update_output.emit(f"[商机] 异常: {str(e)}")
            self.opportunity_all_data = []

        self._opportunity_is_loading = False


    def _populate_opportunity_table(self, data=None):
        """填充商机表格。可传入筛选后的数据子集。"""
        if not hasattr(self, 'opportunity_all_data') or not hasattr(self, 'opportunity_table'):
            return

        # ✅ 首次加载数据后自动应用默认筛选方案
        if not getattr(self, '_opp_default_preset_applied', False) and self.opportunity_all_data:
            self._opp_default_preset_applied = True
            default_name = self.config.get('opp_filter_default_preset', '')
            if default_name:
                self._load_opp_filter_preset(default_name)
                setattr(self, '_opp_active_preset_name', default_name)
                self._update_opp_preset_btn_label()

        if data is None:
            data = self.opportunity_all_data or []
        table = self.opportunity_table

        # ✅ 从设置中动态获取商机字段映射（招标设置-字段映射列表）
        cfg = load_config()
        opp_field_mapping_list = cfg.get('opportunity', {}).get('field_mapping_list', [])
        opportunity_field_map = {}
        for m in opp_field_mapping_list:
            api_name = m.get('api_name', '')
            display_name = m.get('display_name', api_name)
            if api_name:
                opportunity_field_map[display_name] = api_name
        # 非CRM自定义字段保持不变
        opportunity_field_map["模板选择"] = "_template_"
        opportunity_field_map["产品名称"] = "_product_name_"
        opportunity_field_map["规格型号"] = "_model_spec_"
        self.opportunity_field_map = opportunity_field_map

        # ✅ 从设置中动态获取字段映射列表的显示名称
        cfg = load_config()
        opp_field_mapping_list = cfg.get('opportunity', {}).get('field_mapping_list', [])
        if opp_field_mapping_list:
            dynamic_field_headers = [m.get('display_name', m.get('api_name', '')) for m in opp_field_mapping_list if m.get('api_name')]
        else:
            dynamic_field_headers = [k for k in opportunity_field_map.keys() if not k.startswith('_')]

        # 获取当前显示的列
        visible_columns = getattr(self, 'opportunity_visible_columns', None)
        if visible_columns is None:
            visible_columns = list(dynamic_field_headers)
        # ✅ 过滤掉已不在字段映射列表中的旧表头
        valid_headers = set(dynamic_field_headers)
        visible_columns = [c for c in visible_columns if c in valid_headers]
        # ✅ 模板选择固定在第二列（复选框后），产品名称/规格型号确保存在即可自由排序
        if "模板选择" in visible_columns:
            visible_columns = [c for c in visible_columns if c != "模板选择"]
        visible_columns = ["模板选择"] + list(visible_columns)
        for extra_col in ("产品名称", "规格型号"):
            if extra_col not in visible_columns:
                visible_columns.append(extra_col)

        # 设置表头（col 0 为复选框列）
        display_headers = [""] + list(visible_columns)
        table.setColumnCount(len(display_headers))
        table.setHorizontalHeaderLabels(display_headers)

        # 保存过滤后全量数据，按页切片展示
        self.opportunity_filtered_data = list(data)
        total = len(data)
        max_page = max(1, (total + self.opportunity_page_size - 1) // self.opportunity_page_size) if total else 1
        if self.opportunity_current_page > max_page:
            self.opportunity_current_page = max_page
        start = (self.opportunity_current_page - 1) * self.opportunity_page_size
        end = min(start + self.opportunity_page_size, total)
        page_data = data[start:end]

        table.setUpdatesEnabled(False)
        table.setRowCount(len(page_data))
        _cached_template_names = self._get_opp_template_names()
        _cached_default_template = self.config.get('app_settings', {}).get('default_bid_template', '')
        opp_column_alignments = cfg.get('app_settings', {}).get('opportunity_table_settings', {}).get('column_alignments', {})
        try:
            for row_idx, opp in enumerate(page_data):
                row_id = self._get_opportunity_row_id(opp, row_idx)

                # col 0: 复选框
                checkbox_item = QTableWidgetItem()
                checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                checkbox_item.setData(Qt.ItemDataRole.UserRole, row_id)
                table.setItem(row_idx, 0, checkbox_item)

                checkbox_widget = TableRowCheckBox(row_id=row_id)
                checkbox_widget.blockSignals(True)
                checkbox_widget.setChecked(row_id in self.opportunity_selected_row_ids)
                checkbox_widget.blockSignals(False)
                checkbox_widget.toggled_with_row_id.connect(self.on_opportunity_row_checkbox_toggled)

                checkbox_container = QWidget()
                checkbox_layout = QHBoxLayout(checkbox_container)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)
                checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                checkbox_layout.addWidget(checkbox_widget)
                table.setCellWidget(row_idx, 0, checkbox_container)

                # cols 1..N: 数据
                for col_idx, header in enumerate(visible_columns):
                    api_field = opportunity_field_map.get(header, '')

                    # 模板选择列（QComboBox，使用招标设置中的模板）—— 与 CRM 订单逻辑一致
                    if header == '模板选择':
                        template_combo = QComboBox()
                        template_combo.addItem("-", "")
                        for tpl_name in _cached_template_names:
                            template_combo.addItem(tpl_name, tpl_name)
                        preferred = self._get_opp_template_name(row_id) or _cached_default_template
                        if preferred:
                            idx = template_combo.findData(preferred)
                            if idx >= 0:
                                template_combo.setCurrentIndex(idx)
                        template_combo.currentIndexChanged.connect(
                            lambda index, rid=row_id: self._on_opp_template_changed(rid, index))
                        self.opportunity_table.setCellWidget(row_idx, col_idx + 1, template_combo)
                        continue

                    # 产品名称 — 从意向产品字段映射查找
                    if header == '产品名称':
                        pn, _ = self._get_opp_product_info(opp)
                        item = QTableWidgetItem(pn)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        table.setItem(row_idx, col_idx + 1, item)
                        continue

                    # 规格型号 — 从意向产品字段映射查找
                    if header == '规格型号':
                        _, ms = self._get_opp_product_info(opp)
                        item = QTableWidgetItem(ms)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        table.setItem(row_idx, col_idx + 1, item)
                        continue

                    # ✅ 使用通用方法获取字段值（自动 __r 名称解析）
                    value = self._resolve_crm_ref_value(opp, api_field)

                    # 日期字段：统一转为 YYYY-MM-DD
                    _opp_date_fields = {
                        'create_time', 'authorization_start_date__c',
                        'authorization_end_date__c', 'tender_date__c'
                    }
                    if api_field in _opp_date_fields and value:
                        try:
                            if isinstance(value, (int, float)):
                                ts = value / 1000 if value > 1e12 else value
                                value = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                            elif isinstance(value, str) and value.strip().isdigit():
                                ts = int(value.strip())
                                ts = ts / 1000 if ts > 1e12 else ts
                                value = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                        except Exception:
                            value = str(value)

                    # 多选字段：展平为逗号分隔
                    if api_field in ('field_fEKk5__c', 'field_8A8tZ__c'):
                        if isinstance(value, list):
                            value = ', '.join(str(v) for v in value)
                        elif isinstance(value, str) and value.startswith('[') and value.endswith(']'):
                            try:
                                import ast
                                parsed = ast.literal_eval(value)
                                if isinstance(parsed, list):
                                    value = ', '.join(str(v) for v in parsed)
                            except (ValueError, SyntaxError):
                                pass
                    elif api_field == 'field_fQr3j__c':
                        try:
                            value = f"{float(value):,.2f}" if value else ""
                        except (ValueError, TypeError):
                            value = str(value) if value else ""
                    elif api_field == 'confidence_percentage__c':
                        try:
                            value = f"{float(value)}%" if value else ""
                        except (ValueError, TypeError):
                            value = str(value) if value else ""

                    # ✅ 从招投标映射值查找显示名称（优先于原始值）
                    opp_mappings = getattr(self, 'opp_option_mappings', {})
                    field_mapping = opp_mappings.get(api_field, {})
                    if isinstance(field_mapping, dict) and isinstance(field_mapping.get('mappings'), dict):
                        raw_str = str(value)
                        # 处理多选字段（逗号分隔）
                        if ', ' in raw_str or raw_str.startswith('['):
                            parts = [p.strip() for p in raw_str.replace('[', '').replace(']', '').replace("'", '').replace('"', '').split(',')]
                            mapped_parts = []
                            for part in parts:
                                part = part.strip()
                                if part:
                                    mapped = field_mapping['mappings'].get(part, part)
                                    mapped_parts.append(mapped)
                            value = ', '.join(mapped_parts)
                        else:
                            value = field_mapping['mappings'].get(raw_str, raw_str)

                    item = QTableWidgetItem(str(value))
                    user_align = opp_column_alignments.get(header, '')
                    if user_align == 'right':
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    elif user_align == 'center':
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    elif user_align == 'left':
                        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    elif api_field in ('field_fQr3j__c',):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    elif api_field in _opp_date_fields:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row_idx, col_idx + 1, item)
        finally:
            table.setUpdatesEnabled(True)

        # 更新分页标签
        self.opportunity_pagination_label.setText(f"{self.opportunity_current_page}/{max_page}")

        # 更新表头复选框状态
        self._update_opportunity_header_checkbox_state()

        # 刷新勾选行的备注和水印显示
        self._refresh_opportunity_checked_display()

        # 应用保存的列宽（重置标记以覆盖 setColumnCount 导致的宽度重置）
        self._opportunity_column_widths_applied = False
        self._delayed_apply_opportunity_column_widths()

        # 更新状态栏
        total_count = len(data)
        if hasattr(self, 'opportunity_status_label'):
            self.opportunity_status_label.setText(f"共 {total_count} 条记录")
        if hasattr(self, 'opportunity_pagination_label'):
            page_count = max(1, (total_count + 19) // 20)
            self.opportunity_pagination_label.setText(f"1/{page_count}")


    def _on_opportunity_selection_changed(self):
        """商机表格选中行变化时（备注/水印已改为复选框驱动，此处仅保留接口兼容）"""
        pass


    def _get_opportunity_row_id(self, opp, fallback_index=None):
        """获取商机行唯一标识"""
        rid = opp.get('_id') if isinstance(opp, dict) else None
        if rid is not None:
            return rid
        return fallback_index if fallback_index is not None else 0


    def _get_opp_template_names(self):
        """获取招标设置中的Word模板名称列表（始终读取最新配置）"""
        config = load_config()
        templates = config.get('pdf_watermark', {}).get('word_templates', {})
        return list(templates.keys()) if isinstance(templates, dict) else []


    def _get_opp_product_info(self, opp):
        """从意向产品字段映射中获取产品名称和规格型号
        返回 (product_name_str, model_spec_str) 用 ',' 连接多个值"""
        config = getattr(self, 'config', None) or load_config()
        product_names = []
        model_specs = []
        seen_pn = set()

        opp_option_mappings = config.get('opportunity', {}).get('option_mappings', {})

        # 从 field_fEKk5__c（意向产品（多选））读取选中的产品ID
        raw_val = opp.get('field_fEKk5__c', '')
        if raw_val:
            # 展平多选字段
            ids = []
            if isinstance(raw_val, list):
                ids = [str(v).strip() for v in raw_val if str(v).strip()]
            elif isinstance(raw_val, str):
                if raw_val.startswith('['):
                    try:
                        import ast
                        parsed = ast.literal_eval(raw_val)
                        if isinstance(parsed, list):
                            ids = [str(v).strip() for v in parsed if str(v).strip()]
                    except (ValueError, SyntaxError):
                        ids = [p.strip() for p in raw_val.strip('[]').replace("'", '').replace('"', '').split(',') if p.strip()]
                else:
                    ids = [p.strip() for p in raw_val.split(',') if p.strip()]

            if ids:
                # 只取第一个意向产品ID匹配招投标映射值
                first_id = ids[0]

                # 加载 product_match_rows（招投标映射值），匹配产品名称和规格型号
                product_match_rows = config.get('opportunity', {}).get('product_match_rows', [])
                if not isinstance(product_match_rows, list):
                    product_match_rows = []
                match_map = {}
                for pm in product_match_rows:
                    if isinstance(pm, dict):
                        pid = str(pm.get('order_product', '')).strip()
                        if pid:
                            match_map[pid] = pm

                pm = match_map.get(first_id, {})
                pn = str(pm.get('product_name', '') or '').strip()
                if pn:
                    product_names.append(pn)

                ms = str(pm.get('model_spec', '') or '').strip()
                if ms:
                    model_specs.append(ms)

        return ','.join(product_names), ','.join(model_specs)


    def _get_opp_template_name(self, row_id):
        """获取指定商机行的模板选择"""
        if not hasattr(self, '_opp_row_templates'):
            self._opp_row_templates = {}
        return self._opp_row_templates.get(row_id, '')


    def _on_opp_template_changed(self, row_id, index):
        """商机模板选择变更"""
        if not hasattr(self, '_opp_row_templates'):
            self._opp_row_templates = {}
        combo = self.sender()
        if combo and index >= 0:
            template_name = combo.itemData(index) or ""
            if template_name:
                self._opp_row_templates[row_id] = template_name
            else:
                self._opp_row_templates.pop(row_id, None)


    def _get_opp_first_subdir(self):
        """获取第一个勾选商机对应的子目录名（与文件命名规则一致）"""
        selected_ids = getattr(self, 'opportunity_selected_row_ids', set())
        if not selected_ids:
            return ''
        opp_data = getattr(self, 'opportunity_all_data', [])
        from datetime import date
        today_str = date.today().strftime('%Y%m%d')
        for opp in opp_data:
            rid = self._get_opportunity_row_id(opp)
            if rid not in selected_ids:
                continue
            agent_name = str(opp.get('this_project_authorized_ag__c', '') or '').strip()
            end_user = str(opp.get('end_user_accurate_name__c', '') or '').strip()
            pn, ms = self._get_opp_product_info(opp)
            name_parts = [today_str]
            if agent_name:
                name_parts.append(agent_name)
            if end_user or ms:
                detail = f"{end_user} {ms}".strip()
                if detail:
                    name_parts.append(f"({detail})")
            return '-'.join(name_parts)
        return ''


    def _update_opp_target_preview(self):
        """根据勾选的商机更新目标路径输入框（仅预览，不影响实际存储路径）"""
        if not hasattr(self, 'pdf_target_dir_text'):
            return
        selected_ids = getattr(self, 'opportunity_selected_row_ids', set())
        if not selected_ids:
            config = load_config()
            default_dir = config.get('path_config', {}).get('opp_output_dir', '') or config.get('pdf_watermark', {}).get('target_dir', '')
            self.pdf_target_dir_text.setText(default_dir)
            self.pdf_target_dir_text.setStyleSheet("")
            return
        opp_data = getattr(self, 'opportunity_all_data', [])
        from datetime import date
        today_str = date.today().strftime('%Y%m%d')
        config = load_config()
        base_dir = config.get('path_config', {}).get('opp_output_dir', '') or config.get('pdf_watermark', {}).get('target_dir', '')
        if not base_dir:
            base_dir = str(resolve_app_path('output'))
        first_path = ""
        for opp in opp_data:
            rid = self._get_opportunity_row_id(opp)
            if rid not in selected_ids:
                continue
            agent_name = str(opp.get('this_project_authorized_ag__c', '') or '').strip()
            end_user = str(opp.get('end_user_accurate_name__c', '') or '').strip()
            pn, ms = self._get_opp_product_info(opp)
            name_parts = [today_str]
            if agent_name:
                name_parts.append(agent_name)
            if end_user or ms:
                detail = f"{end_user} {ms}".strip()
                if detail:
                    name_parts.append(f"({detail})")
            first_path = f"{base_dir}\\{'-'.join(name_parts)}"
            break
        if first_path:
            self.pdf_target_dir_text.setText(first_path)
            self.pdf_target_dir_text.setStyleSheet("color: #1890FF;")
        else:
            self.pdf_target_dir_text.setStyleSheet("")


    def _match_opp_product_to_files(self, product_name):
        """根据意向产品智能匹配源文件列表中的PDF（匹配文件名包含产品名的）"""
        if not product_name or not hasattr(self, 'file_list_widget'):
            return
        # 支持多选产品名（逗号/顿号分隔），取第一个匹配的文件
        product_list = [p.strip() for p in product_name.replace('、', ',').split(',') if p.strip()]
        if not product_list:
            return
        # 在源文件列表中查找匹配的文件
        matched_items = []
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item:
                item_lower = item.text().lower()
                for pn in product_list:
                    if pn.lower() in item_lower:
                        matched_items.append(item)
                        break
        self.file_list_widget.clearSelection()
        if matched_items:
            # 自动选中匹配的文件
            for item in matched_items:
                item.setSelected(True)
            self.file_list_widget.scrollToItem(matched_items[0])


    def _on_opp_keep_format_changed(self, index):
        """商机页面输出格式变更"""
        fmt_map = {0: 'word_pdf', 1: 'word', 2: 'pdf'}
        fmt = fmt_map.get(index, 'word_pdf')
        config = load_config()
        if 'app_settings' not in config:
            config['app_settings'] = {}
        config['app_settings']['keep_opp_output_format'] = fmt
        save_config(config, immediate=False)
        self.config = config


    def _do_opp_generate_files(self):
        """商机文件生成（后台线程），使用 opportunity_selected_row_ids 获取勾选数据"""
        self.update_output.emit("开始生成招标授权文件...")
        import threading
        t = threading.Thread(target=self._opp_generate_worker, daemon=True)
        t.start()


    def _opp_generate_worker(self):
        try:
            self.pdf_watermark_btn.setEnabled(False)
            self.pdf_watermark_btn.setText("执行中...")

            config = load_config()
            bid_templates = config.get('pdf_watermark', {}).get('word_templates', {})
            bid_template_dir = config.get('path_config', {}).get('bid_template_dir', '')
            if not bid_template_dir:
                bid_template_dir = config.get('path_config', {}).get('template_dir', 'template')

            if not bid_templates:
                self.update_output.emit("[招标授权] 未配置模板，请在招标设置中添加模板。")
                return

            opp_field_mapping = load_common_config().get('opportunity', {}).get('word_field_mapping', {})
            opp_output_dir = config.get('path_config', {}).get('opp_output_dir', '')
            if not opp_output_dir:
                opp_output_dir = config.get('path_config', {}).get('target_roots', {}).get('1', './output/opportunity')

            output_dir = resolve_app_path(opp_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            keep_fmt = config.get('app_settings', {}).get('keep_opp_output_format', 'word_pdf')
            core._keep_word_override = keep_fmt

            from docxtpl import DocxTemplate
            from datetime import date
            today_str = date.today().strftime('%Y%m%d')

            # 安全方案：先在缓存文件夹生成，再按需移动到目标目录
            cache_dir = output_dir / f'_cache_{today_str}'
            cache_dir.mkdir(parents=True, exist_ok=True)

            generated_count = 0
            _last_generated_subdir = None
            generated_files = []  # [{word_path, pdf_path, pdf_success, base_name, target_subdir}]

            selected_ids = getattr(self, 'opportunity_selected_row_ids', set())
            all_data = getattr(self, 'opportunity_all_data', [])

            for opp in all_data:
                row_id = self._get_opportunity_row_id(opp)
                if row_id not in selected_ids:
                    continue

                template_name = self._get_opp_template_name(row_id)
                if not template_name:
                    template_name = config.get('app_settings', {}).get('default_bid_template', '')
                if not template_name:
                    template_name = list(bid_templates.keys())[0] if bid_templates else ''
                if not template_name:
                    continue

                template_path = bid_templates.get(template_name, '')
                if not template_path:
                    continue

                template_full = resolve_app_path(bid_template_dir) / template_path
                if not template_full.exists():
                    self.update_output.emit(f"[招标授权] 模板不存在: {template_full}")
                    continue

                try:
                    agent_name = str(opp.get('this_project_authorized_ag__c', '') or '').strip()
                    end_user = str(opp.get('end_user_accurate_name__c', '') or '').strip()
                    pn, ms = self._get_opp_product_info(opp)
                    name_parts = [today_str]
                    if agent_name:
                        name_parts.append(agent_name)
                    if end_user or ms:
                        detail = f"{end_user} {ms}".strip()
                        if detail:
                            name_parts.append(f"({detail})")
                    base_name = sanitize_output_name('-'.join(name_parts))

                    # 构建 source_values（显示名称 → 值），参考 CRM 映射逻辑
                    opp_field_map = getattr(self, 'opportunity_field_map', {})
                    source_values = {}
                    _date_api_fields = {
                        'create_time', 'authorization_start_date__c',
                        'authorization_end_date__c', 'tender_date__c'
                    }
                    special_fmts = {}
                    for sc in load_common_config().get('opportunity', {}).get('word_special_columns', []):
                        if isinstance(sc, dict):
                            special_fmts[sc.get('name', '')] = sc.get('format', '')
                    for display_name, api_field in opp_field_map.items():
                        if api_field == '_template_' or api_field == '_product_name_' or api_field == '_model_spec_':
                            continue
                        val = opp.get(api_field, '')
                        if val is None:
                            val = ''
                        if isinstance(val, dict):
                            val = val.get('name', str(val))
                        if api_field in _date_api_fields and isinstance(val, (int, float)) and val > 0:
                            try:
                                if val > 1e12:
                                    dt = datetime.fromtimestamp(val / 1000)
                                else:
                                    dt = datetime.fromtimestamp(val)
                                fmt_key = special_fmts.get(display_name, '')
                                if fmt_key and fmt_key not in ('{}', ''):
                                    import re
                                    m = re.match(r'\{:(.+)\}', fmt_key)
                                    if m:
                                        val = dt.strftime(m.group(1))
                                    else:
                                        val = dt.strftime('%Y-%m-%d')
                                else:
                                    val = dt.strftime('%Y-%m-%d')
                            except Exception:
                                val = str(val)
                        source_values[display_name] = val
                    source_values['产品名称'] = pn
                    source_values['规格型号'] = ms
                    source_values['代理商名称'] = agent_name
                    source_values['终端用户准确名称'] = end_user

                    doc = DocxTemplate(str(template_full))
                    ctx_special_fmts = {
                        k: v for k, v in special_fmts.items()
                        if not (k in opp_field_map and opp_field_map.get(k, '') in _date_api_fields)
                    }
                    context = build_context_from_mapping_values(
                        source_values, opp_field_mapping, ctx_special_fmts)

                    # 先输出到缓存文件夹（不与历史文件混在一起）
                    result = render_document_files(doc, context, base_name, output_dir=str(cache_dir), skip_pdf=(core._keep_word_override == 'word'))
                    generated_files.append({
                        **result,
                        'base_name': base_name,
                        'target_subdir': base_name,
                    })
                    generated_count += 1
                    _last_generated_subdir = output_dir / base_name
                except Exception as e:
                    self.update_output.emit(f"[招标授权] 生成失败: {e}")

            if generated_count > 0:
                keep_word = keep_fmt in ('word', 'word_pdf')
                keep_pdf = keep_fmt in ('pdf', 'word_pdf')

                # 从缓存文件夹按需移动到目标子目录
                for fi in generated_files:
                    target_dir = output_dir / fi['target_subdir']
                    target_dir.mkdir(parents=True, exist_ok=True)
                    word_path = fi.get('word_path')
                    pdf_path = fi.get('pdf_path')
                    pdf_success = fi.get('pdf_success', False)

                    if keep_word and word_path:
                        safe_move_to_dir(Path(word_path), target_dir)
                    if keep_pdf and pdf_success and pdf_path:
                        safe_move_to_dir(Path(pdf_path), target_dir)

                # 清理缓存文件夹（剩余未移动的文件直接删除）
                try:
                    shutil.rmtree(str(cache_dir), ignore_errors=True)
                except Exception:
                    pass

                self.update_output.emit(f"[招标授权] ✅ 合同生成完成: {generated_count} 个")
                if config.get('app_settings', {}).get('open_output_folder', True):
                    open_target = str(_last_generated_subdir) if generated_count == 1 and _last_generated_subdir else str(output_dir)
                    open_folder(open_target)
            else:
                self.update_output.emit("[招标授权] ⚠️ 没有生成任何合同")
                # 无生成时也清理缓存
                try:
                    shutil.rmtree(str(cache_dir), ignore_errors=True)
                except Exception:
                    pass

        except Exception as e:
            self.update_output.emit(f"[招标授权] 异常: {str(e)}")
        finally:
            self.pdf_watermark_btn.setEnabled(True)
            self.pdf_watermark_btn.setText("确认生成")


    def on_opportunity_row_checkbox_toggled(self, row_id, checked):
        """商机行复选框状态变化（单选模式 + 更新授权备注 + 更新水印文本）"""
        if not hasattr(self, 'opportunity_selected_row_ids'):
            self.opportunity_selected_row_ids = set()

        table = self.opportunity_table
        opp_data = getattr(self, 'opportunity_all_data', [])

        if checked:
            # 单选模式：先取消所有其他行的选中
            for row in range(table.rowCount()):
                checkbox_container = table.cellWidget(row, 0)
                checkbox = checkbox_container.findChild(TableRowCheckBox) if checkbox_container else None
                if checkbox and checkbox.row_id != row_id and checkbox.isChecked():
                    checkbox.blockSignals(True)
                    checkbox.setChecked(False)
                    checkbox.blockSignals(False)
            self.opportunity_selected_row_ids = {row_id}

            # 更新授权备注显示
            remark = ''
            watermark_target = ''
            for idx, opp in enumerate(opp_data):
                rid = self._get_opportunity_row_id(opp, idx)
                if rid == row_id:
                    remark = opp.get('authorization_remark__c', '') or ''
                    watermark_target = opp.get('end_user_accurate_name__c', '') or ''
                    break
            if hasattr(self, 'opportunity_remark_text'):
                self.opportunity_remark_text.setText(str(remark))

            # 提取当前商机的意向产品 + 规格型号
            # pn（意向产品）→ 用于匹配产品预设下拉框
            # ms（规格型号）→ PDF 文件名匹配
            pn = ''
            ms = ''
            opp = None
            for idx, o in enumerate(opp_data):
                rid = self._get_opportunity_row_id(o, idx)
                if rid == row_id:
                    opp = o
                    pn, ms = self._get_opp_product_info(opp)
                    break

            # 1) 根据意向产品自动切换招标设置的产品型号
            if hasattr(self, 'product_combo') and self.product_combo.count() > 0:
                pn_list = [s.strip() for s in pn.replace('、', ',').split(',') if s.strip()] if pn else []
                product_matched = False
                for keyword in pn_list:
                    idx = self.product_combo.findText(keyword)
                    if idx >= 0:
                        operation_log.info(f"[产品匹配] 意向产品 '{keyword}' 匹配产品预设，切换 product_combo 到索引 {idx}")
                        self.product_combo.setCurrentIndex(idx)
                        product_matched = True
                        break
                if not product_matched:
                    # fallback: 用 field_fEKk5__c（意向产品多选）原始值通过 option_mappings 映射后匹配
                    raw_ids = []
                    if opp:
                        raw_val = opp.get('field_fEKk5__c', '')
                        if raw_val:
                            if isinstance(raw_val, list):
                                raw_ids = [str(v).strip() for v in raw_val if str(v).strip()]
                            elif isinstance(raw_val, str):
                                if raw_val.startswith('['):
                                    try:
                                        import ast
                                        raw_ids = [str(v).strip() for v in ast.literal_eval(raw_val) if str(v).strip()]
                                    except Exception:
                                        raw_ids = [p.strip() for p in raw_val.strip('[]').replace("'", '').replace('"', '').split(',') if p.strip()]
                                else:
                                    raw_ids = [p.strip() for p in raw_val.split(',') if p.strip()]
                    if raw_ids:
                        config = load_config()
                        opp_mappings = config.get('opportunity', {}).get('option_mappings', {}).get('field_fEKk5__c', {}).get('mappings', {})
                        if not isinstance(opp_mappings, dict):
                            opp_mappings = {}
                        for rid_val in raw_ids:
                            # 查映射文本，映射文本和原始值都尝试匹配
                            display_name = str(opp_mappings.get(rid_val, '')).strip()
                            candidates = [rid_val]
                            if display_name:
                                candidates.insert(0, display_name)
                            for kw in candidates:
                                if kw:
                                    idx = self.product_combo.findText(kw)
                                    if idx >= 0:
                                        operation_log.info(f"[产品匹配] 意向产品原始值 '{kw}' 匹配产品预设，切换 product_combo 到索引 {idx}")
                                        self.product_combo.setCurrentIndex(idx)
                                        product_matched = True
                                        break
                            if product_matched:
                                break
                if not product_matched:
                    operation_log.info(f"[产品匹配] 意向产品 '{pn}' 未匹配任何产品预设，跳转到自定义并清空路径")
                    if hasattr(self, 'product_path_text'):
                        self.product_path_text.clear()
                    if hasattr(self, 'file_list_widget'):
                        self.file_list_widget.clear()
                    self.product_combo.setCurrentIndex(0)

            # 2) 再根据意向产品匹配已加载的文件列表（必须在 combo 切换之后，确保文件列表已刷新）
            if hasattr(self, 'file_list_widget'):
                if pn:
                    self._match_opp_product_to_files(pn)
                else:
                    self.file_list_widget.clearSelection()

            # 更新水印文本（放在最后，避免被 combo 切换触发的 Qt 事件循环打断）
            has_wm = hasattr(self, 'watermark_text')
            print(f"[DEBUG-WM] hasattr watermark_text={has_wm}, watermark_target='{watermark_target}'")
            if has_wm:
                wm = self.watermark_text
                print(f"[DEBUG-WM] watermark_text type={type(wm).__name__}, isVisible={wm.isVisible()}, currentText='{wm.text()}'")
                if watermark_target:
                    new_text = f"仅供{watermark_target}招投标使用，他用无效。"
                    wm.setText(new_text)
                    print(f"[DEBUG-WM] setText done, verify='{wm.text()}'")
                else:
                    wm.setText('')
                    print(f"[DEBUG-WM] cleared (empty watermark_target)")
            else:
                print("[DEBUG-WM] ERROR: self.watermark_text does NOT exist!")
            # 选中商机时自动勾选公司资质并加载
            if hasattr(self, 'company_qual_checkbox') and not self.company_qual_checkbox.isChecked():
                self.company_qual_checkbox.setChecked(True)
        else:
            self.opportunity_selected_row_ids.discard(row_id)
            # 如果取消后没有选中的行，清空显示
            if not self.opportunity_selected_row_ids:
                if hasattr(self, 'opportunity_remark_text'):
                    self.opportunity_remark_text.setText('')
                if hasattr(self, 'watermark_text'):
                    self.watermark_text.setText('')
                # 取消所有商机选中时，取消公司资质勾选并清空资质文件
                if hasattr(self, 'company_qual_checkbox') and self.company_qual_checkbox.isChecked():
                    self.company_qual_checkbox.setChecked(False)
                if hasattr(self, 'file_list_widget'):
                    self.file_list_widget.clearSelection()
                # 恢复招标设置产品型号为自定义
                if hasattr(self, 'product_combo'):
                    self.product_combo.setCurrentIndex(0)

        self._update_opp_target_preview()
        self._update_opportunity_header_checkbox_state()


    def on_opportunity_header_select_all_toggled(self, state):
        """商机表头复选框（单选模式：点击全选按钮清除所有选中）"""
        is_checked = bool(state)
        if not hasattr(self, 'opportunity_selected_row_ids'):
            self.opportunity_selected_row_ids = set()

        table = self.opportunity_table
        if is_checked:
            # 单选模式不支持全选，改为清除所有选中
            for row in range(table.rowCount()):
                checkbox_container = table.cellWidget(row, 0)
                checkbox = checkbox_container.findChild(TableRowCheckBox) if checkbox_container else None
                if checkbox and checkbox.isChecked():
                    checkbox.blockSignals(True)
                    checkbox.setChecked(False)
                    checkbox.blockSignals(False)
            self.opportunity_selected_row_ids.clear()
            if hasattr(self, 'opportunity_remark_text'):
                self.opportunity_remark_text.setText('')
            if hasattr(self, 'watermark_text'):
                self.watermark_text.setText('')
            # 取消所有商机选中时，取消公司资质勾选并清空资质文件
            if hasattr(self, 'company_qual_checkbox') and self.company_qual_checkbox.isChecked():
                self.company_qual_checkbox.setChecked(False)
            if hasattr(self, 'file_list_widget'):
                self.file_list_widget.clearSelection()
            # 恢复招标设置产品型号为自定义
            if hasattr(self, 'product_combo'):
                self.product_combo.setCurrentIndex(0)

        # 始终将表头设为未选中状态（单选模式无全选概念）
        self.opportunity_table_header.set_check_state(Qt.CheckState.Unchecked)
        self.opportunity_table_header.viewport().update()


    def _update_opportunity_header_checkbox_state(self):
        """更新商机表头复选框状态（全选/部分选/未选）"""
        if not hasattr(self, 'opportunity_table_header'):
            return
        table = self.opportunity_table
        if table.rowCount() == 0:
            self.opportunity_table_header.set_check_state(Qt.CheckState.Unchecked)
            return

        selected_ids = getattr(self, 'opportunity_selected_row_ids', set())
        checked_count = 0
        total_count = table.rowCount()
        for row in range(total_count):
            checkbox_container = table.cellWidget(row, 0)
            checkbox = checkbox_container.findChild(TableRowCheckBox) if checkbox_container else None
            if checkbox and checkbox.row_id in selected_ids:
                checked_count += 1

        if checked_count == 0:
            self.opportunity_table_header.set_check_state(Qt.CheckState.Unchecked)
        elif checked_count == total_count:
            self.opportunity_table_header.set_check_state(Qt.CheckState.Checked)
        else:
            self.opportunity_table_header.set_check_state(Qt.CheckState.PartiallyChecked)


    def _refresh_opportunity_checked_display(self):
        """根据当前勾选行刷新授权备注和水印文本"""
        if not hasattr(self, 'opportunity_selected_row_ids'):
            return
        opp_data = getattr(self, 'opportunity_all_data', [])
        checked_id = None
        for rid in self.opportunity_selected_row_ids:
            checked_id = rid
            break  # 单选模式，取第一个

        if checked_id is None:
            if hasattr(self, 'opportunity_remark_text'):
                self.opportunity_remark_text.setText('')
            if hasattr(self, 'watermark_text'):
                self.watermark_text.setText('')
            return

        remark = ''
        watermark_target = ''
        for idx, opp in enumerate(opp_data):
            rid = self._get_opportunity_row_id(opp, idx)
            if rid == checked_id:
                remark = opp.get('authorization_remark__c', '') or ''
                watermark_target = opp.get('end_user_accurate_name__c', '') or ''
                break

        if hasattr(self, 'opportunity_remark_text'):
            self.opportunity_remark_text.setText(str(remark))
        if hasattr(self, 'watermark_text'):
            if watermark_target:
                self.watermark_text.setText(f"仅供{watermark_target}招投标使用，他用无效。")
            else:
                self.watermark_text.setText('')

    # ========== 商机表格列宽持久化 ==========


    def _get_opportunity_column_width_key(self, header_label):
        """获取商机列宽度键名"""
        header_text = str(header_label or '').strip()
        return header_text or '__checkbox__'


    def _get_opportunity_column_default_width(self, header_label):
        """获取商机列默认宽度"""
        defaults = {
            '商机名称': 220,
            '项目名称': 200,
            '负责人': 100,
            '意向产品（多选）': 180,
            '报价（元/台）': 120,
            '医院等级': 100,
            '授权类型': 120,
            '招标日期': 120,
            '项目号': 130,
            '是否招投标项目': 130,
            '创建时间': 150,
            '创建人': 100,
            '竞争对手（多选）': 180,
            '终端客户省份': 120,
            '授权开始日期': 130,
            '授权结束日期': 130,
            '是否邮寄原件': 120,
            '授权备注': 200,
            '竞争对手产品型号': 160,
            '把握性百分比(%)': 130,
            '终端用户所在省': 130,
            '终端用户准确名称': 180,
            '该项目授权代理商名称': 200,
            '授权经销商资质文件': 160,
            '招标公告': 160,
            '业务类型': 120,
        }
        return defaults.get(header_label, 140)


    def _get_saved_opportunity_column_widths(self):
        """获取已保存的商机表格列宽（按列索引）"""
        config = load_config()
        app_set = config.get('app_settings', {})
        opp_set = app_set.get('opportunity_table_settings', {})
        runtime_state = load_user_runtime_state()
        runtime_widths = runtime_state.get('table_column_widths', {})

        runtime_saved = runtime_widths.get('opportunity_table', {})
        if runtime_saved:
            saved_widths = {}
            for k, v in runtime_saved.items():
                try:
                    saved_widths[int(k)] = v
                except (ValueError, TypeError):
                    pass
            return saved_widths

        raw = opp_set.get('column_widths', {})
        saved_widths = {}
        for k, v in raw.items():
            try:
                saved_widths[int(k)] = v
            except (ValueError, TypeError):
                pass
        return saved_widths


    def _get_saved_opportunity_column_widths_by_header(self):
        """获取已保存的商机表格列宽（按表头标签）"""
        config = load_config()
        app_set = config.get('app_settings', {})
        opp_set = app_set.get('opportunity_table_settings', {})
        runtime_state = load_user_runtime_state()
        runtime_widths = runtime_state.get('table_column_widths', {})

        raw = runtime_widths.get('opportunity_table_by_header', {})
        if not raw:
            raw = opp_set.get('column_widths_by_header', {})

        saved_widths = {}
        for key, value in (raw or {}).items():
            try:
                saved_widths[key] = int(value)
            except (TypeError, ValueError):
                pass
        return saved_widths


    def _save_opportunity_column_widths(self):
        """保存商机表格列宽设置"""
        try:
            if not hasattr(self, 'opportunity_table'):
                return

            table = self.opportunity_table
            column_widths = {}
            column_widths_by_header = {}
            for col in range(table.columnCount()):
                width = table.columnWidth(col)
                column_widths[col] = width
                if col == 0:
                    header_key = '__checkbox__'
                else:
                    header_item = table.horizontalHeaderItem(col)
                    header_key = header_item.text().strip() if header_item else ''
                column_widths_by_header[header_key] = width

            config = load_config()
            if 'app_settings' not in config:
                config['app_settings'] = {}
            if 'opportunity_table_settings' not in config['app_settings']:
                config['app_settings']['opportunity_table_settings'] = {}

            config['app_settings']['opportunity_table_settings']['column_widths'] = column_widths
            config['app_settings']['opportunity_table_settings']['column_widths_by_header'] = column_widths_by_header
            save_config(config, immediate=False)
            self.save_user_runtime_state_patch({
                'table_column_widths': {
                    'opportunity_table': column_widths,
                    'opportunity_table_by_header': column_widths_by_header
                }
            }, immediate=True)
            self.config = config
        except Exception as e:
            print(f"保存商机列宽失败: {e}")


    def _on_opportunity_column_resized(self, logicalIndex, oldSize, newSize):
        """商机表格列宽调整时防抖保存"""
        try:
            if not hasattr(self, '_opportunity_column_width_save_timer'):
                return
            if self._opportunity_column_width_save_timer.isActive():
                self._opportunity_column_width_save_timer.stop()
            self._opportunity_column_width_save_timer.start(1000)
        except Exception as e:
            print(f"商机列宽调整事件处理失败: {e}")


    def _debounced_save_opportunity_column_widths(self):
        """防抖后保存商机表格列宽"""
        self._save_opportunity_column_widths()


    def _delayed_apply_opportunity_column_widths(self):
        """延迟应用商机表格列宽（首次加载时）"""
        try:
            if getattr(self, '_opportunity_column_widths_applied', False):
                return
            if not hasattr(self, 'opportunity_table') or self.opportunity_table.columnCount() == 0:
                return

            saved_widths = self._get_saved_opportunity_column_widths()
            saved_widths_by_header = self._get_saved_opportunity_column_widths_by_header()

            table = self.opportunity_table
            for col in range(table.columnCount()):
                if col == 0:
                    header_key = '__checkbox__'
                else:
                    header_item = table.horizontalHeaderItem(col)
                    header_key = header_item.text().strip() if header_item else ''

                if header_key in saved_widths_by_header:
                    table.setColumnWidth(col, saved_widths_by_header[header_key])
                elif col in saved_widths:
                    table.setColumnWidth(col, saved_widths[col])
                elif col != 0:
                    default_width = self._get_opportunity_column_default_width(header_key)
                    table.setColumnWidth(col, default_width)

            self._opportunity_column_widths_applied = True
        except Exception as e:
            print(f"延迟应用商机列宽失败: {e}")


    def _on_crm_refresh_btn_clicked(self):
        """CRM刷新按钮点击：强制从API获取最新数据"""
        self._force_api_refresh = True
        self.on_crm_manual_refresh()


    def on_crm_manual_refresh(self):
        """响应CRM手动刷新相关操作。"""
        if getattr(self, '_crm_is_loading', False):
            return

        if not getattr(self, '_crm_auto_refresh_activated', False):
            cfg = load_config()
            self.config = cfg
            fx_cfg = cfg.get('fxiaoke', {})
            interval = fx_cfg.get('auto_refresh_interval', 0)
            if interval > 0:
                self.crm_auto_refresh_timer.start(interval)
                self._crm_auto_refresh_activated = True
                operation_log.info(f"CRM自动刷新已激活 | 间隔:{interval}秒")

        self._reset_crm_filters_and_selection()

        # 直接从 CRM API 加载数据，不使用本地缓存
        self.on_crm_refresh_orders()


    def _load_crm_data_from_local_cache(self):
        """从本地映射缓存表读取 CRM 数据（不调 API，不动态映射，直接读取已映射+清洗后的值）"""
        try:
            cache_path = self._get_crm_cache_path()
            cache = CRMCache(cache_path)
            mapped_count = cache.get_mapped_record_count('SalesOrderObj')
            if mapped_count == 0:
                cache.close()
                return False
            records = cache.get_all_mapped_records('SalesOrderObj')
            cache.close()
            if records:
                self.crm_all_data = records
                print(f"[缓存读取] ✓ 从本地映射表读取 {len(records)} 条 CRM 记录")
                return True
            return False
        except Exception as e:
            print(f"[缓存读取] ⚠️ 读取映射表失败: {e}，回退到动态映射模式")
            return False


    def _refresh_crm_table_from_cache(self):
        """
        使用本地缓存数据刷新CRM订单表格。优先使用映射表（每个字段独立列），
        映射表为空时回退到原始数据 + 动态映射。
        """
        if getattr(self, '_crm_use_mapped_cache', True):
            if self._load_crm_data_from_local_cache():
                self.config = load_config()
                new_option_mappings = self.config.get('business_rules', {}).get('crm_option_mappings', {})
                if isinstance(new_option_mappings, dict) and hasattr(self, 'crm_option_mappings'):
                    self.crm_option_mappings.update(new_option_mappings)
                self._populate_crm_table_from_mapped_data()
                operation_log.info(f"CRM订单表格已从映射缓存刷新: {len(self.crm_all_data)} 条记录")
                return

        # 回退：使用原始数据 + 动态映射
        if not hasattr(self, 'crm_all_data') or not self.crm_all_data:
            print("[WARNING-CRM] ⚠️ 无缓存数据，无法使用缓存刷新")
            return

        try:
            self.config = load_config()
            new_option_mappings = self.config.get('business_rules', {}).get('crm_option_mappings', {})
            if isinstance(new_option_mappings, dict) and hasattr(self, 'crm_option_mappings'):
                self.crm_option_mappings.update(new_option_mappings)
                print(f"[DEBUG-CRM] ✓ 已同步 {len(new_option_mappings)} 个字段的选项值映射")

            if hasattr(self, '_populate_crm_order_table'):
                self._populate_crm_order_table(self.crm_all_data)
            elif hasattr(self, 'crm_table'):
                self._populate_crm_table()

            operation_log.info(f"CRM订单表格已从缓存刷新: {len(self.crm_all_data)} 条记录")
            print(f"[DEBUG-CRM] ✅ CRM订单表格已从本地缓存刷新完成")

        except Exception as e:
            print(f"[ERROR-CRM] ❌ 缓存刷新失败: {e}")
            operation_log.error(f"CRM订单缓存刷新失败: {e}")


    def _rebuild_crm_table_with_current_data(self):
        """使用当前数据重建CRM表格"""
        if hasattr(self, 'crm_table') and hasattr(self, 'crm_all_data') and self.crm_all_data:
            self._populate_crm_table()


    def on_crm_refresh_orders(self):
        """响应CRM刷新订单相关操作。"""
        if getattr(self, '_crm_is_loading', False):
            return

        # 确保待保存的配置已写入磁盘
        flush_pending_config()
        # CRM刷新时强制使用最新设置
        self.config = load_config()
        AppConfig.reload_config()

        self._crm_is_loading = True
        self.crm_refresh_btn.setText("加载中...")
        self.crm_record_label.setText("从API加载数据...")

        # 记录CRM查询操作
        operation_log.info("--- CRM订单查询开始 ---")

        # 通过任务管理器启动后台线程（状态栏可见）
        self.task_manager.start(
            'crm_fetch',
            'CRM订单加载',
            self._crm_fetch_worker
        )


    def _crm_fetch_worker(self):
        """内部方法：处理CRMfetch工作线程逻辑。"""
        try:
            self._crm_is_loading = True
            cfg = load_config()
            self.config = cfg
            fx_cfg = cfg.get('fxiaoke', {})
            crm = FXiaokeCRM(
                app_id=fx_cfg.get('app_id', 'FSAID_1323c1a'),
                app_secret=fx_cfg.get('app_secret', 'e7f4188d14704299b375c91ddda92cb0'),
                permanent_code=fx_cfg.get('permanent_code', 'E8B8D8536B0385D035657AC2528928F0'),
                admin_mobile=fx_cfg.get('admin_mobile', '15889740213')
            )
            # CRM订单筛选条件：根据设置中的业务类型动态过滤
            filters = [
                # {"field_name": "life_status", "operator": "EQ", "field_values": "normal"},
            ]

            selected_record_types = fx_cfg.get('query_record_types', [])
            if isinstance(selected_record_types, list) and selected_record_types:
                filters.append({
                    "field_name": "record_type",
                    "operator": "IN",
                    "field_values": selected_record_types,
                })

            raw_load_count = fx_cfg.get('load_count', 100)
            try:
                load_count = int(raw_load_count)
            except (TypeError, ValueError):
                load_count = 100

            if load_count > 10000:
                operation_log.warning(f"CRM加载数量超出接口上限，已限制为 10000 | 原值: {load_count}")
                self.update_output.emit("[CRM] 加载数量超过接口上限，已自动限制为 10000 条")
                load_count = 10000
            elif load_count < 1:
                load_count = 100

            # ✅ 从设置中获取要加载的CRM字段（字段映射列表的API名称）
            field_mapping_list = fx_cfg.get('crm_field_mapping_list', [])
            api_field_keys = [m.get('api_name', '') for m in field_mapping_list if m.get('api_name')]

            # 确保基础必要字段始终加载
            essential_fields = ['_id', 'name', 'account_id', 'account_id__r', 'field_8pAwf__c', 'life_status', 'record_type', 'owner__r', 'created_by__r', 'last_modified_by__r', 'submit_by__r']
            field_projection = list(dict.fromkeys(essential_fields + api_field_keys))
            # ✅ 自动补充 __r 关联字段，确保名称解析有数据来源
            for f in list(field_projection):
                if not f.endswith('__r') and f'{f}__r' not in field_projection:
                    field_projection.append(f'{f}__r')

            data, total, err = crm.fetch_all_data_object(
                data_object_api_name='SalesOrderObj',
                max_records=load_count,
                batch_size=100,
                filters=filters,
                field_projection=field_projection
            )
            if err:
                self.update_output.emit(f"[CRM] API错误: {err}")
                self.crm_all_data = []
                operation_log.error(f"CRM订单查询失败: {err}")
            else:
                self.crm_all_data = [r for r in (data or []) if str(r.get('life_status', '')).lower() != 'invalid']
                self.update_output.emit(f"[CRM] 加载完成: {len(self.crm_all_data)} 条 (API总计: {total})")
                customer_ids = []
                for order in self.crm_all_data:
                    for field_name in ('account_id', 'field_8pAwf__c'):
                        customer_id = str(order.get(field_name, '')).strip()
                        if customer_id:
                            customer_ids.append(customer_id)

                customer_map, customer_err = crm.fetch_customer_accounts_by_ids(customer_ids)
                if customer_err:
                    self.crm_customer_account_map = {}
                    operation_log.error(f"CRM客户账户查询失败: {customer_err}")
                else:
                    self.crm_customer_account_map = customer_map

                # 地址/手机列默认可见时，在线程中预热 Excel 缓存
                self._load_crm_customer_address_excel_map()

                self.update_output.emit(f"[CRM] 加载完成: {len(self.crm_all_data)} 条 (API总计: {total})")
                operation_log.info(f"CRM订单查询成功: 加载 {len(self.crm_all_data)} 条记录 (总计: {total})")
        except Exception as e:
            self.update_output.emit(f"[CRM] 异常: {str(e)}")
            self.crm_all_data = []
            operation_log.error(f"CRM订单查询异常: {str(e)}")

        self._crm_is_loading = False
        self.enable_crm_button.emit()


    def _migrate_crm_column_widths(self, saved_widths_raw, width_version=1):
        """内部方法：处理migrateCRM列widths逻辑。"""
        saved_widths = {}
        for k, v in (saved_widths_raw or {}).items():
            try:
                saved_widths[int(k)] = v
            except (ValueError, TypeError):
                pass

        if not saved_widths:
            return {}

        try:
            width_version = int(width_version)
        except (TypeError, ValueError):
            width_version = 1

        migrated_widths = dict(saved_widths)

        if width_version < 2:
            old_widths = migrated_widths
            migrated_widths = {}
            for col_idx, width in old_widths.items():
                if col_idx < 2:
                    migrated_widths[col_idx] = width
                else:
                    migrated_widths[col_idx + 2] = width

        if width_version < 3:
            old_widths = migrated_widths
            migrated_widths = {}
            for col_idx, width in old_widths.items():
                if col_idx < 5:
                    migrated_widths[col_idx] = width
                else:
                    migrated_widths[col_idx + 1] = width

        if width_version < 4:
            old_widths = migrated_widths
            migrated_widths = {}
            for col_idx, width in old_widths.items():
                if col_idx < 2:
                    migrated_widths[col_idx] = width
                else:
                    migrated_widths[col_idx + 1] = width

        return migrated_widths


    def _get_saved_crm_column_widths(self):
        """内部方法：获取savedCRM列widths。"""
        from __main__ import load_user_runtime_state
        config = load_config()
        app_set = config.get('app_settings', {})
        crm_set = app_set.get('crm_table_settings', {})
        runtime_state = load_user_runtime_state()
        runtime_widths = runtime_state.get('table_column_widths', {})
        runtime_versions = runtime_state.get('table_column_width_versions', {})

        runtime_saved_widths = runtime_widths.get('crm_table', {})
        if runtime_saved_widths:
            return self._migrate_crm_column_widths(runtime_saved_widths, runtime_versions.get('crm_table', 1))

        return self._migrate_crm_column_widths(
            crm_set.get('column_widths', {}),
            crm_set.get('column_widths_version', 1)
        )


    def _get_saved_crm_column_widths_by_header(self):
        """内部方法：获取savedCRM列widthsby表头。"""
        from __main__ import load_user_runtime_state
        config = load_config()
        app_set = config.get('app_settings', {})
        crm_set = app_set.get('crm_table_settings', {})
        runtime_state = load_user_runtime_state()
        runtime_widths = runtime_state.get('table_column_widths', {})

        saved_widths_raw = runtime_widths.get('crm_table_by_header', {})
        if not saved_widths_raw:
            saved_widths_raw = crm_set.get('column_widths_by_header', {})

        saved_widths = {}
        for key, value in (saved_widths_raw or {}).items():
            width_key = self._get_crm_column_width_key(key)
            try:
                saved_widths[width_key] = int(value)
            except (TypeError, ValueError):
                continue
        return saved_widths


    def _get_crm_configurable_headers(self):
        """内部方法：获取CRMconfigurableheaders（从设置中动态获取字段映射列表）。"""
        special_headers = list(getattr(self, 'crm_special_headers', ["模板选择", "规格型号", "客户类型", "匹配价格", "折扣单价", "产品备注", "大写"]))
        # ✅ 从设置中动态获取CRM字段显示名称
        cfg = load_config()
        field_mapping_list = cfg.get('fxiaoke', {}).get('crm_field_mapping_list', [])
        dynamic_headers = [m.get('display_name', m.get('api_name', '')) for m in field_mapping_list if m.get('api_name')]
        return special_headers + [label for label in dynamic_headers if label not in special_headers]


    def _compose_crm_header_order(self, ordered_headers):
        """内部方法：组合CRM表头订单。"""
        all_headers = self._get_crm_configurable_headers()
        ordered_headers = [header for header in ordered_headers if header in all_headers]
        return ordered_headers + [header for header in all_headers if header not in ordered_headers]


    def _get_crm_display_headers(self):
        """内部方法：获取CRM显示headers（模板选择始终在第2列）。"""
        visible = list(getattr(self, 'crm_visible_headers', []))
        # 确保模板选择在复选框后第一列
        if "模板选择" in visible:
            visible = [h for h in visible if h != "模板选择"]
        visible = ["模板选择"] + visible
        return list(getattr(self, 'crm_fixed_headers', [""])) + visible


    def _get_crm_column_width_key(self, header_label):
        """内部方法：获取CRM列宽度key。"""
        header_text = str(header_label or '').strip()
        return header_text or '__checkbox__'


    def _get_crm_header_label(self, column_index):
        """内部方法：获取CRM表头标签。"""
        if not hasattr(self, 'crm_table'):
            return ''
        header_item = self.crm_table.horizontalHeaderItem(column_index)
        if header_item is None:
            return ''
        return header_item.text().strip()


    def _get_crm_column_index(self, header_label):
        """内部方法：获取CRM列索引。"""
        return getattr(self, 'crm_column_index_map', {}).get(header_label, -1)


    def _get_crm_column_default_width(self, header_label):
        """内部方法：获取CRM列默认宽度。"""
        if header_label == '模板选择':
            return 120
        if header_label == '规格型号':
            return 180
        if header_label == '客户类型':
            return 90
        if header_label == '匹配价格':
            return 120
        if header_label == '折扣单价':
            return 120
        if header_label == '产品备注':
            return 180
        if header_label == '大写':
            return 220
        if header_label in ('创建时间', '提交时间', '最后修改时间'):
            return 150
        if header_label in ('销售订单金额(元)', '已收金额', '应收金额',  '产品合计'):
            return 130
        if header_label in ('客户名称', '关联客户（分销商&诊所）'):
            return 180
        if header_label in ('地址', '发货地址'):
            return 260
        return 100


    def _configure_crm_table_delegates(self):
        """内部方法：配置CRM表格delegates。"""
        if not hasattr(self, 'crm_table'):
            return

        default_delegate = getattr(self, 'crm_default_item_delegate', None)
        if default_delegate is None:
            default_delegate = QStyledItemDelegate(self.crm_table)
            self.crm_default_item_delegate = default_delegate

        for col_idx in range(self.crm_table.columnCount()):
            self.crm_table.setItemDelegateForColumn(col_idx, default_delegate)

        delegate_map = {
            '客户类型': getattr(self, 'crm_customer_type_delegate', None),
            '匹配价格': getattr(self, 'crm_matched_price_delegate', None),
            '产品备注': getattr(self, 'crm_product_remark_delegate', None),
        }
        for header_label, delegate in delegate_map.items():
            col_idx = self._get_crm_column_index(header_label)
            if delegate is not None and col_idx > 0:
                self.crm_table.setItemDelegateForColumn(col_idx, delegate)


    def _apply_crm_table_columns(self):
        """内部方法：应用CRM表格列。"""
        print(f"[DEBUG-列宽] _apply_crm_table_columns 被调用 | _crm_table_column_widths_applied={getattr(self, '_crm_table_column_widths_applied', False)}")
        display_headers = self._get_crm_display_headers()
        total_cols = len(display_headers)
        self.crm_table.setColumnCount(total_cols)
        self.crm_table.setHorizontalHeaderLabels(display_headers)
        self.crm_table.setHorizontalHeader(self.crm_table_header)
        self.crm_column_index_map = {header_label: idx for idx, header_label in enumerate(display_headers)}
        header = self.crm_table.horizontalHeader()
        for col_idx in range(total_cols):
            resize_mode = QHeaderView.ResizeMode.Fixed if col_idx == 0 else QHeaderView.ResizeMode.Interactive
            header.setSectionResizeMode(col_idx, resize_mode)

        saved_widths = self._get_saved_crm_column_widths()
        saved_widths_by_header = self._get_saved_crm_column_widths_by_header()

        print(f"[DEBUG-列宽] CRM表格 | 保存的列宽数量: {len(saved_widths)} | 总列数: {total_cols}")

        default_count = 0
        for col_idx, header_label in enumerate(display_headers):
            width_key = self._get_crm_column_width_key(header_label)
            if width_key in saved_widths_by_header:
                self.crm_table.setColumnWidth(col_idx, saved_widths_by_header[width_key])
            elif col_idx in saved_widths:
                self.crm_table.setColumnWidth(col_idx, saved_widths[col_idx])
            else:
                default_width = 28 if col_idx == 0 else self._get_crm_column_default_width(header_label)
                self.crm_table.setColumnWidth(col_idx, default_width)
                if col_idx != 0:
                    default_count += 1

        print(f"[DEBUG-列宽] CRM表格 | 使用默认值的列数: {default_count}")

        # ✅ 关键修复：标记为已应用（防止后续操作覆盖）
        self._crm_table_column_widths_applied = True
        print(f"[DEBUG-列宽] CRM表格 | 已标记为已应用 (_crm_table_column_widths_applied=True)")

        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        self._configure_crm_table_delegates()
        self._update_crm_table_sort_indicator()


    def _save_crm_column_widths(self):
        """保存CRM表格列宽设置"""
        try:
            if not hasattr(self, 'crm_table'):
                print(f"[DEBUG-保存CRM] 保存失败: crm_table不存在")
                return

            column_widths = {}
            column_widths_by_header = {}
            for col in range(self.crm_table.columnCount()):
                width = self.crm_table.columnWidth(col)
                column_widths[col] = width
                header_key = self._get_crm_column_width_key(self._get_crm_header_label(col))
                column_widths_by_header[header_key] = width

            print(f"[DEBUG-保存CRM] 准备保存 | 列数:{self.crm_table.columnCount()} | 列宽数据:{column_widths}")

            config = load_config()  # 强制加载最新配置
            if 'app_settings' not in config:
                config['app_settings'] = {}
            if 'crm_table_settings' not in config['app_settings']:
                config['app_settings']['crm_table_settings'] = {}

            config['app_settings']['crm_table_settings']['column_widths'] = column_widths
            config['app_settings']['crm_table_settings']['column_widths_by_header'] = column_widths_by_header
            config['app_settings']['crm_table_settings']['column_widths_version'] = 4
            save_config(config, immediate=False)
            self.save_user_runtime_state_patch({
                'table_column_widths': {
                    'crm_table': column_widths,
                    'crm_table_by_header': column_widths_by_header
                },
                'table_column_width_versions': {
                    'crm_table': 4
                }
            }, immediate=True)
            # 同步更新 self.config
            self.config = config

            print(f"[DEBUG-保存CRM] 保存成功 | 已写入配置文件")

        except Exception as e:
            print(f"保存CRM列宽失败: {e}")
            operation_log.error(f"保存CRM列宽失败: {e}")


    def _debounced_save_crm_column_widths(self):
        """延迟保存CRM表格列宽（防抖后的实际保存操作）"""
        self._save_crm_column_widths()


    def _on_crm_column_resized(self, logicalIndex, oldSize, newSize):
        """CRM表格列宽调整时使用防抖机制保存（避免频繁IO）"""
        try:
            # ✅ 性能优化：不再每次调整都记录日志和保存，使用防抖机制
            # 只在停止调整1秒后才保存一次

            # 检查定时器是否存在
            if not hasattr(self, '_crm_column_width_save_timer'):
                return

            # 复用定时器，重置防抖计时
            if self._crm_column_width_save_timer.isActive():
                self._crm_column_width_save_timer.stop()

            # 启动防抖定时器（1秒后保存）
            self._crm_column_width_save_timer.start(1000)
        except Exception as e:
            print(f"CRM列宽调整事件处理失败: {e}")


    def _delayed_apply_crm_column_widths(self):
        """延迟应用CRM表格列宽 - 只在首次加载时应用，防止重复覆盖"""
        try:
            # ✅ 如果已经应用过，不再重复设置（保护用户调整的列宽）
            if getattr(self, '_crm_table_column_widths_applied', False):
                print(f"[DEBUG-列宽] _delayed_apply_crm_column_widths 跳过 (已应用过)")
                return

            if not hasattr(self, 'crm_table') or self.crm_table.columnCount() == 0:
                print(f"[DEBUG-列宽] _delayed_apply_crm_column_widths 跳过 (表格不存在或无列)")
                return

            saved_widths = self._get_saved_crm_column_widths()
            saved_widths_by_header = self._get_saved_crm_column_widths_by_header()

            # print(f"[延迟加载] CRM表格 - 转换后的列宽数据: {saved_widths}")

            if saved_widths or saved_widths_by_header:
                applied_count = 0
                for col_idx in range(self.crm_table.columnCount()):
                    header_key = self._get_crm_column_width_key(self._get_crm_header_label(col_idx))
                    if header_key in saved_widths_by_header:
                        self.crm_table.setColumnWidth(col_idx, saved_widths_by_header[header_key])
                        applied_count += 1
                    elif col_idx in saved_widths:
                        self.crm_table.setColumnWidth(col_idx, saved_widths[col_idx])
                        applied_count += 1
                print(f"[DEBUG-列宽] CRM延迟加载 | 已应用 {applied_count}/{self.crm_table.columnCount()} 个保存的列宽")

            # ✅ 标记为已应用
            self._crm_table_column_widths_applied = True
            print(f"[DEBUG-列宽] CRM延迟加载 | 已标记为已应用 (_crm_table_column_widths_applied=True)")

        except Exception as e:
            print(f"[ERROR] 延迟应用CRM列宽失败: {e}")


    def open_crm_field_settings_dialog(self):
        """打开CRM字段设置对话框。"""
        operation_log.info("打开CRM字段设置对话框")
        all_labels = self._get_crm_configurable_headers()
        print(f"[DEBUG-CRM] 打开字段设置 | all_labels数: {len(all_labels)} | 当前visible: {len(self.crm_visible_headers)}")
        dialog = ExcelFieldSettingsDialog(
            headers=all_labels,
            visible_headers=self.crm_visible_headers[:],
            header_order=self.crm_header_order[:],
            parent=self
        )
        result = dialog.exec()
        print(f"[DEBUG-CRM] dialog.exec() 返回值: {result} | Accepted={QDialog.DialogCode.Accepted}")
        if result == QDialog.DialogCode.Accepted:
            new_vis, new_order = dialog.get_settings()
            print(f"[DEBUG-CRM] ✅ 字段设置确认成功!")
            print(f"[DEBUG-CRM] 新可见字段数: {len(new_vis)}")
            print(f"[DEBUG-CRM] 新可见字段列表: {new_vis}")
            print(f"[DEBUG-CRM] 新order数: {len(new_order)}")
            old_vis = self.crm_visible_headers
            self.crm_visible_headers = new_vis
            self.crm_header_order = new_order
            print(f"[DEBUG-CRM] 已更新 self.crm_visible_headers: {len(old_vis)} → {len(new_vis)}")

            # ✅ 使用 load_config() 获取最新配置，避免使用旧的 self.config 缓存
            config = load_config()
            app_set = config.setdefault('app_settings', {})
            crm_table_settings = app_set.setdefault('crm_table_settings', {})
            crm_table_settings['visible_headers'] = new_vis
            crm_table_settings['header_order'] = new_order
            save_config(config, immediate=True)
            # 同步更新 self.config
            self.config = config

            # 记录字段设置变更
            operation_log.info(f"CRM字段设置已变更 | 显示字段数:{len(new_vis)} | 字段顺序已更新")

            print(f"[DEBUG-CRM] 准备调用 _apply_crm_table_columns()")
            print(f"[DEBUG-CRM] 调用前表格列数: {self.crm_table.columnCount()}")
            self._apply_crm_table_columns()
            print(f"[DEBUG-CRM] 调用后表格列数: {self.crm_table.columnCount()}")
            print(f"[DEBUG-CRM] 表格headers: {[self.crm_table.horizontalHeaderItem(i).text() for i in range(self.crm_table.columnCount())]}")

            print(f"[DEBUG-CRM] 准备调用 _populate_crm_table()")
            self._populate_crm_table()
            print(f"[DEBUG-CRM] _populate_crm_table() 完成")
        else:
            print(f"[DEBUG-CRM] ❌ 对话框被取消或关闭")


    def _get_crm_option_mapping_candidate_keys(self, field_key):
        """内部方法：获取CRM选项映射candidatekeys。"""
        normalized_key = str(field_key or '').strip()
        if not normalized_key:
            return []

        candidates = [normalized_key]
        expected_label = self.CRM_OPTION_FIELDS.get(normalized_key, '')
        for mapping_key, field_data in getattr(self, 'crm_option_mappings', {}).items():
            mapping_key_text = str(mapping_key or '').strip()
            if not mapping_key_text or mapping_key_text in candidates:
                continue
            if mapping_key_text == normalized_key:
                candidates.append(mapping_key_text)
                continue
            if not isinstance(field_data, dict):
                continue
            field_label = str(field_data.get('label', '') or '').strip()
            if expected_label and field_label == expected_label:
                candidates.append(mapping_key_text)
        return candidates


    def _get_crm_option_mapping_entry(self, field_key):
        """内部方法：获取CRM选项映射（从内存和配置文件中查找）。"""
        # 先从内存中的 crm_option_mappings 查找
        for candidate_key in self._get_crm_option_mapping_candidate_keys(field_key):
            field_data = getattr(self, 'crm_option_mappings', {}).get(candidate_key, {})
            if isinstance(field_data, dict) and field_data:
                return field_data, candidate_key

        # 如果内存中没有，从配置文件的 option_mapping_fields 查找
        fx_cfg = self.config.get('fxiaoke', {})
        option_mapping_fields = fx_cfg.get('option_mapping_fields', [])
        for entry in option_mapping_fields:
            if isinstance(entry, dict) and entry.get('field_key') == field_key:
                if 'mappings' in entry or 'label' in entry:
                    return entry, field_key

        return {}, str(field_key or '').strip()


    def _get_crm_field_mapping(self, field_key):
        """
        获取字段的映射值（和对象查询的字段管理逻辑一致）

        【功能说明】：
        根据字段名查找映射配置，如果存在映射则返回映射后的字段名（即API名称），
        否则返回原始字段名。

        参数：
        ----------
        field_key : str
            原始字段名（表头显示的名称或API字段名）

        返回：
        ----------
        str : 映射后的API名称或原始字段名
        """
        try:
            if not field_key:
                return ''

            field_mappings = self.config.get('fxiaoke', {}).get('crm_field_mapping_list', [])
            for mapping in field_mappings:
                if isinstance(mapping, dict):
                    api_name = mapping.get('api_name', '')
                    display_name = mapping.get('display_name', '')

                    if field_key == display_name or field_key == api_name:
                        return api_name

            return field_key
        except Exception as e:
            print(f"获取字段映射失败: {e}")
            return field_key


    def _crm_extract_field(self, order, key):
        """内部方法：处理CRMextract字段逻辑（支持字段映射）。"""
        actual_key = self._get_crm_field_mapping(key)
        val = order.get(actual_key, '')

        if val == '' and actual_key != key:
            val = order.get(key, '')

        if key == 'customer_address':
            customer_id = str(order.get('account_id', '')).strip()
            customer_name = self._normalize_crm_display_value(order.get('account_id__r', ''))
            if not customer_name:
                customer_name = self._get_crm_customer_display_name(customer_id)
            return self._get_crm_customer_address(customer_id, customer_name)

        if key == 'customer_mobile':
            customer_id = str(order.get('account_id', '')).strip()
            customer_name = self._normalize_crm_display_value(order.get('account_id__r', ''))
            if not customer_name:
                customer_name = self._get_crm_customer_display_name(customer_id)
            return self._get_crm_customer_mobile(customer_id, customer_name)

        if key == 'account_id__r':
            display_name = self._normalize_crm_display_value(val)
            if display_name:
                return display_name
            return self._get_crm_customer_display_name(str(order.get('account_id', '')).strip())

        if key == 'field_8pAwf__c':
            related_display = self._normalize_crm_display_value(order.get('field_8pAwf__c__r', ''))
            if related_display:
                return related_display
            customer_id = str(val).strip() if val else ''
            return self._get_crm_customer_display_name(customer_id, customer_id)

        if val is None:
            return ''
        if key in ('owner__r', 'created_by__r'):
            return self._normalize_crm_display_value(val)
        if key in self.CRM_OPTION_FIELDS:
            val_str = str(val).strip() if val else ''
            if not val_str:
                return ''
            field_data, _ = self._get_crm_option_mapping_entry(key)
            if isinstance(field_data, dict):
                mappings = field_data.get('mappings', {})
                if mappings and val_str in mappings:
                    return mappings[val_str]
            elif isinstance(field_data, dict) and val_str in field_data:
                return field_data[val_str]
            self._collect_crm_option_value(key, val_str)
            return val_str
        # ✅ 使用通用方法解析（自动 __r 名称转换）
        return self._resolve_crm_ref_value(order, actual_key)


    def _normalize_crm_display_value(self, value):
        """内部方法：规范化CRM显示值。"""
        if value is None:
            return ''
        if isinstance(value, dict):
            for key in ('name', 'label', 'text', 'value'):
                text = value.get(key)
                if text:
                    return str(text).strip()
            return ''
        if isinstance(value, list):
            parts = [self._normalize_crm_display_value(item) for item in value]
            parts = [part for part in parts if part]
            return ', '.join(parts)
        return str(value).strip() if value else ''


    def _sanitize_nan(text):
        """过滤 pandas/numpy NaN 字符串"""
        if not text:
            return ''
        t = str(text).strip()
        return '' if t.lower() == 'nan' else t


    def _resolve_crm_ref_value(self, data, api_field):
        """通用方法：从CRM数据中提取字段值，自动解析 __r 关联名称为名称，适用于所有CRM对象。

        参数：
            data: CRM记录字典（订单或商机等）
            api_field: API字段名

        返回：
            str: 解析后的显示值（名称或格式化后的值）
        """
        val = data.get(api_field, '')
        if val is None:
            val = ''

        # 用户引用字段：自动从 __r 获取名称
        user_ref_fields = {'owner', 'created_by', 'last_modified_by', 'submit_by'}
        if api_field in user_ref_fields:
            ref_data = data.get(f'{api_field}__r', None)
            if ref_data is not None:
                return self._normalize_crm_display_value(ref_data)

        # 客户ID：自动解析为客户名称
        if api_field == 'account_id':
            display_name = self._normalize_crm_display_value(data.get('account_id__r', ''))
            if display_name:
                return display_name
            customer_id = str(val).strip() if val else str(data.get('account_id', '')).strip()
            return self._get_crm_customer_display_name(customer_id)

        # 通用 __r 关联字段自动解析
        if isinstance(val, str) and val and not api_field.endswith('__r'):
            ref_data = data.get(f'{api_field}__r', None)
            if ref_data is not None:
                return self._normalize_crm_display_value(ref_data)

        return self._normalize_crm_display_value(val)


    def _get_crm_customer_display_name(self, customer_id, fallback=''):
        """内部方法：获取CRM客户显示名称。"""
        customer_record = getattr(self, 'crm_customer_account_map', {}).get(customer_id, {})
        for key in ('customer_id__r', 'name'):
            text = self._normalize_crm_display_value(customer_record.get(key, ''))
            if text:
                return text
        return fallback or ''


    def _normalize_crm_excel_lookup_value(self, value):
        """内部方法：规范化CRMExcellookup值。"""
        text = self._normalize_crm_display_value(value)
        return '' if text.lower() == 'nan' else text


    def _get_crm_customer_mobile(self, customer_id, customer_name=''):
        """获取客户手机：Excel1 → Excel2 → 空"""
        customer_name_text = str(customer_name or '').strip() or self._get_crm_customer_display_name(customer_id)
        mobile = self._get_crm_customer_mobile_from_excel(customer_name_text)
        if mobile and mobile.lower() != 'nan':
            return mobile
        mobile2 = self._get_crm_customer_mobile_from_excel2(customer_name_text)
        if mobile2 and mobile2.lower() != 'nan':
            return mobile2
        return ''


    def _on_crm_objects_updated(self):
        """CRM对象管理更新后，缓存新增对象的数据"""
        import threading
        cfg = self.config
        fx_cfg = cfg.get('fxiaoke', {})
        crm_objects = fx_cfg.get('crm_objects', [])
        if not crm_objects:
            return

        # 检查是否有待缓存的对象（从设置对话框传递）
        pending_objects = None
        if hasattr(self, 'settings_dialog') and self.settings_dialog:
            pending_objects = getattr(self.settings_dialog, '_pending_crm_object_cache', None)
            if pending_objects:
                self.settings_dialog._pending_crm_object_cache = None

        def cache_worker():
            crm = FXiaokeCRM(
                app_id=fx_cfg.get('app_id', 'FSAID_1323c1a'),
                app_secret=fx_cfg.get('app_secret', 'e7f4188d14704299b375c91ddda92cb0'),
                permanent_code=fx_cfg.get('permanent_code', 'E8B8D8536B0385D035657AC2528928F0'),
                admin_mobile=fx_cfg.get('admin_mobile', '15889740213')
            )
            load_count = fx_cfg.get('load_count', 100)

            if pending_objects:
                targets = [(api_name, 'preset') for api_name in pending_objects]
            else:
                targets = [(obj.get('api_name', ''), obj.get('object_type', 'preset')) for obj in crm_objects if obj and obj.get('api_name')]
            for api_name, obj_type in targets:
                if not api_name:
                    continue
                is_custom = (obj_type == 'custom')
                try:
                    operation_log.info(f"[CRM对象缓存] 开始获取 {api_name} 的数据 (类型: {'自定义' if is_custom else '预设'})...")
                    data, total, err = crm.fetch_all_data_object(
                        data_object_api_name=api_name,
                        max_records=load_count,
                        is_custom=is_custom,
                        callback=lambda fetched, t, name=api_name: self.update_output.emit(
                            f"[CRM对象缓存] {name}: {fetched}/{t}"
                        )
                    )
                    if err:
                        operation_log.error(f"[CRM对象缓存] {api_name} 获取失败: {err}")
                        self.update_output.emit(f"[CRM对象缓存] {api_name} 获取失败: {err}")
                    else:
                        # ✅ 写入本地缓存（增量 upsert）
                        cache_path = self._get_crm_cache_path()
                        cache = CRMCache(cache_path)
                        ins, upd = cache.upsert_records(api_name, data or [], total)
                        cache.close()
                        operation_log.info(f"[CRM对象缓存] {api_name} 获取完成 | 记录数: {len(data)}/{total} | 缓存: +{ins} ~{upd}")
                        self.update_output.emit(f"[CRM对象缓存] {api_name} 缓存完成，共 {len(data)} 条记录 (新增{ins}, 更新{upd})")
                except Exception as e:
                    operation_log.error(f"[CRM对象缓存] {api_name} 异常: {str(e)}")
                    self.update_output.emit(f"[CRM对象缓存] {api_name} 异常: {str(e)}")

        t = threading.Thread(target=cache_worker, daemon=True)
        t.start()


    def _invalidate_crm_customer_address_excel_cache(self):
        """内部方法：处理invalidateCRM客户地址Excelcache逻辑。"""
        self.crm_customer_address_excel_path = None
        self.crm_customer_address_excel_mtime = None
        self.crm_customer_address_excel_map = {}
        self.crm_customer_contact_excel_map = {}
        self.crm_customer_address_excel_error = ''


    def _get_crm_customer_excel_lookup_keys(self, customer_name):
        """内部方法：获取CRM客户Excellookupkeys。"""
        normalized_name = self._normalize_product_match_text(customer_name)
        if not normalized_name:
            return []

        lookup_keys = [normalized_name]
        fuzzy_suffixes = (
            '有限责任公司',
            '股份有限公司',
            '集团有限公司',
            '有限公司',
            '股份公司',
        )
        for suffix_text in fuzzy_suffixes:
            normalized_suffix = self._normalize_product_match_text(suffix_text)
            if normalized_suffix and normalized_name.endswith(normalized_suffix):
                stripped_name = normalized_name[:-len(normalized_suffix)]
                if stripped_name and stripped_name not in lookup_keys:
                    lookup_keys.append(stripped_name)
                break
        return lookup_keys


    def _lookup_crm_customer_excel_map_value(self, mapping, customer_name):
        """内部方法：处理lookupCRM客户Excel映射值逻辑。"""
        for lookup_key in self._get_crm_customer_excel_lookup_keys(customer_name):
            if lookup_key in mapping:
                return mapping[lookup_key]

        best_match_key = ''
        best_match_score = 0
        for lookup_key in self._get_crm_customer_excel_lookup_keys(customer_name):
            if not lookup_key:
                continue
            for mapping_key in mapping.keys():
                normalized_mapping_key = str(mapping_key or '').strip()
                if not normalized_mapping_key:
                    continue
                if not (
                    lookup_key.startswith(normalized_mapping_key)
                    or normalized_mapping_key.startswith(lookup_key)
                ):
                    continue

                match_score = min(len(lookup_key), len(normalized_mapping_key))
                if match_score < 4:
                    continue
                if match_score > best_match_score:
                    best_match_key = normalized_mapping_key
                    best_match_score = match_score
                elif match_score == best_match_score and len(normalized_mapping_key) > len(best_match_key):
                    best_match_key = normalized_mapping_key

        if best_match_key:
            return mapping.get(best_match_key, '')
        return ''


    def _get_crm_cache_path(self):
        """获取 CRM 本地缓存 SQLite 数据库路径。"""
        config = load_config()
        if not isinstance(config, dict):
            config = {}
        cache_dir = config.get('path_config', {}).get('crm_cache_dir', '')
        if not cache_dir:
            cache_dir = os.path.join(
                config.get('path_config', {}).get('log_dir', 'Cache'), 'crm_cache'
            )
        return str(Path(resolve_app_path(cache_dir)) / 'crm_cache.db')


    def _load_crm_customer_address_excel_map(self):
        """内部方法：加载CRM客户地址Excel映射。"""
        fx_cfg = self.config.get('fxiaoke', {}) if isinstance(self.config, dict) else {}
        configured_path = str(fx_cfg.get('customer_address_excel_path', '') or '').strip()

        cached_path = getattr(self, 'crm_customer_address_excel_path', None)
        cached_mtime = getattr(self, 'crm_customer_address_excel_mtime', None)
        cached_map = getattr(self, 'crm_customer_address_excel_map', None)
        cached_contact_map = getattr(self, 'crm_customer_contact_excel_map', None)

        address_map = {}
        contact_map = {}
        current_mtime = None

        if not configured_path:
            self.crm_customer_address_excel_path = configured_path
            self.crm_customer_address_excel_mtime = None
            self.crm_customer_address_excel_map = address_map
            self.crm_customer_contact_excel_map = contact_map
            self.crm_customer_address_excel_error = ''
            return address_map

        try:
            excel_path = resolve_app_path(configured_path) if configured_path else None
        except Exception:
            excel_path = Path(configured_path) if configured_path else None

        if excel_path.exists() and excel_path.is_file():
            try:
                current_mtime = excel_path.stat().st_mtime
            except OSError:
                current_mtime = None

        if (
            configured_path == cached_path
            and cached_mtime == current_mtime
            and cached_map is not None
            and cached_contact_map is not None
        ):
            return cached_map

        self.crm_customer_address_excel_path = configured_path
        self.crm_customer_address_excel_mtime = current_mtime
        self.crm_customer_address_excel_map = address_map
        self.crm_customer_contact_excel_map = contact_map
        self.crm_customer_address_excel_error = ''

        if not excel_path.exists() or not excel_path.is_file():
            self.crm_customer_address_excel_error = f"CRM地址匹配文件不存在: {configured_path}"
            logging.warning(self.crm_customer_address_excel_error)
            return address_map

        try:
            import pandas as pd

            read_kwargs = {'sheet_name': None}
            if excel_path.suffix.lower() == '.xls':
                read_kwargs['engine'] = 'xlrd'

            try:
                workbook = pd.read_excel(excel_path, **read_kwargs)
            except Exception:
                # .xls 可能实际是 .xlsx 格式重命名，回退到默认引擎
                read_kwargs.pop('engine', None)
                workbook = pd.read_excel(excel_path, **read_kwargs)
            if isinstance(workbook, pd.DataFrame):
                workbook = {'Sheet1': workbook}

            name_candidates = ('客户名称', '企业名称', '客户名', '名称', '公司名称', '单位名称')
            address_candidates = ('地址', '客户地址', '详细地址', '注册地址', '公司地址', '通讯地址')
            mobile_candidates = ('手机', '手机号', '手机号码', '联系电话', '电话', '区电话', '固定电话', '联系电话1', '联系电话2', '联系人电话', '联系人手机')

            # 构建列名映射（去除空格，不区分大小写）
            any_sheet_matched = False
            for sheet_name, sheet_df in (workbook or {}).items():
                if sheet_df is None or not hasattr(sheet_df, 'columns') or sheet_df.empty:
                    continue

                # 为每个 sheet 重新构建列映射
                sheet_column_map = {}
                for col in list(sheet_df.columns):
                    col_stripped = str(col).strip()
                    sheet_column_map[col_stripped] = col
                    sheet_column_map[col_stripped.lower()] = col

                name_column = ''
                address_column = ''
                mobile_column = ''
                for candidate in name_candidates:
                    if candidate in sheet_column_map:
                        name_column = sheet_column_map[candidate]
                        break
                    if candidate.lower() in sheet_column_map:
                        name_column = sheet_column_map[candidate.lower()]
                        break
                    for key, col in sheet_column_map.items():
                        if candidate in key or key in candidate:
                            name_column = col
                            break
                    if name_column:
                        break
                for candidate in address_candidates:
                    if candidate in sheet_column_map:
                        address_column = sheet_column_map[candidate]
                        break
                    if candidate.lower() in sheet_column_map:
                        address_column = sheet_column_map[candidate.lower()]
                        break
                    for key, col in sheet_column_map.items():
                        if candidate in key or key in candidate:
                            address_column = col
                            break
                    if address_column:
                        break
                for candidate in mobile_candidates:
                    if candidate in sheet_column_map:
                        mobile_column = sheet_column_map[candidate]
                        break
                    if candidate.lower() in sheet_column_map:
                        mobile_column = sheet_column_map[candidate.lower()]
                        break
                    for key, col in sheet_column_map.items():
                        if candidate in key or key in candidate:
                            mobile_column = col
                            break
                    if mobile_column:
                        break

                if not name_column or (not address_column and not mobile_column):
                    continue
                any_sheet_matched = True

                address_values = sheet_df[address_column] if address_column else [None] * len(sheet_df)
                mobile_values = sheet_df[mobile_column] if mobile_column else [None] * len(sheet_df)

                for customer_name, address_text, mobile_text in zip(sheet_df[name_column], address_values, mobile_values):
                    normalized_address = self._normalize_crm_excel_lookup_value(address_text)
                    normalized_mobile = self._normalize_crm_excel_lookup_value(mobile_text)
                    # 处理 Excel 中手机号存为数字导致 .0 后缀的问题
                    if normalized_mobile and normalized_mobile.endswith('.0') and '.' not in normalized_mobile[:-2]:
                        try:
                            float_val = float(normalized_mobile)
                            if float_val == int(float_val):
                                normalized_mobile = str(int(float_val))
                        except ValueError:
                            pass
                    lookup_keys = self._get_crm_customer_excel_lookup_keys(customer_name)
                    for lookup_key in lookup_keys:
                        if normalized_address and lookup_key not in address_map:
                            address_map[lookup_key] = normalized_address
                        if normalized_mobile and lookup_key not in contact_map:
                            contact_map[lookup_key] = normalized_mobile

            if not any_sheet_matched and workbook:
                available_cols = []
                for sname, sdf in (workbook or {}).items():
                    if hasattr(sdf, 'columns'):
                        available_cols.extend(str(c).strip() for c in sdf.columns)
                self.crm_customer_address_excel_error = (
                    f"CRM地址匹配Excel未找到匹配列。"
                    f"文件列名: {list(set(available_cols))[:30]}; "
                    f"期望名称列: {name_candidates}; "
                    f"期望地址列: {address_candidates}; "
                    f"期望手机列: {mobile_candidates}"
                )
                logging.warning(self.crm_customer_address_excel_error)
        except Exception as exc:
            self.crm_customer_address_excel_error = f"加载CRM地址匹配Excel失败: {exc}"
            logging.error(self.crm_customer_address_excel_error)
            address_map = {}
            contact_map = {}

        self.crm_customer_address_excel_map = address_map
        self.crm_customer_contact_excel_map = contact_map
        return address_map


    def _get_crm_customer_address_from_excel(self, customer_name):
        """内部方法：获取CRM客户地址fromExcel。"""
        return self._lookup_crm_customer_excel_map_value(
            self._load_crm_customer_address_excel_map(),
            customer_name,
        )


    def _get_crm_customer_mobile_from_excel(self, customer_name):
        """内部方法：获取CRM客户手机号fromExcel。"""
        self._load_crm_customer_address_excel_map()
        return self._lookup_crm_customer_excel_map_value(
            getattr(self, 'crm_customer_contact_excel_map', {}),
            customer_name,
        )



    def _get_crm_customer_address_from_excel2(self, customer_name):
        """从备用地址Excel获取地址"""
        self._load_crm_customer_address2_excel_map()
        return self._lookup_crm_customer_excel_map_value(
            getattr(self, 'crm_customer_address2_excel_map', {}), customer_name)


    def _get_crm_customer_mobile_from_excel2(self, customer_name):
        """从备用地址Excel获取手机"""
        self._load_crm_customer_address2_excel_map()
        return self._lookup_crm_customer_excel_map_value(
            getattr(self, 'crm_customer_address2_contact_excel_map', {}), customer_name)


    def _load_crm_customer_address2_excel_map(self):
        """加载备用地址Excel映射"""
        fx_cfg = self.config.get('fxiaoke', {}) if isinstance(self.config, dict) else {}
        configured_path = str(fx_cfg.get('customer_address2_excel_path', '') or '').strip()
        cached_path = getattr(self, 'crm_customer_address2_excel_path', None)
        cached_mtime = getattr(self, 'crm_customer_address2_excel_mtime', None)
        cached_map = getattr(self, 'crm_customer_address2_excel_map', None)
        cached_contact_map = getattr(self, 'crm_customer_address2_contact_excel_map', None)

        addr_map = {}
        contact_map = {}
        current_mtime = None

        if not configured_path:
            self.crm_customer_address2_excel_path = ''
            self.crm_customer_address2_excel_mtime = None
            self.crm_customer_address2_excel_map = addr_map
            self.crm_customer_address2_contact_excel_map = contact_map
            self.crm_customer_address2_excel_error = ''
            return

        try:
            excel_path = resolve_app_path(configured_path) if configured_path else None
        except Exception:
            excel_path = Path(configured_path) if configured_path else None

        if excel_path and excel_path.exists() and excel_path.is_file():
            try:
                current_mtime = excel_path.stat().st_mtime
            except OSError:
                current_mtime = None

        if (
            configured_path == cached_path
            and cached_mtime == current_mtime
            and cached_map is not None
            and cached_contact_map is not None
        ):
            return

        # 未命中缓存时，先更新缓存路径避免并发重复加载
        self.crm_customer_address2_excel_path = configured_path
        self.crm_customer_address2_excel_mtime = current_mtime
        self.crm_customer_address2_excel_map = addr_map
        self.crm_customer_address2_contact_excel_map = contact_map
        self.crm_customer_address2_excel_error = ''

        if not excel_path or not excel_path.exists() or not excel_path.is_file():
            self.crm_customer_address2_excel_error = f'文件不存在: {configured_path}'
            logging.warning(self.crm_customer_address2_excel_error)
            return

        try:
            import pandas as pd
            read_kwargs = {'sheet_name': None}
            if excel_path.suffix.lower() == '.xls':
                read_kwargs['engine'] = 'xlrd'
            try:
                workbook = pd.read_excel(str(excel_path), **read_kwargs)
            except Exception:
                # .xls 可能实际是 .xlsx 格式重命名，回退到默认引擎
                read_kwargs.pop('engine', None)
                workbook = pd.read_excel(str(excel_path), **read_kwargs)
            if isinstance(workbook, pd.DataFrame):
                workbook = {'Sheet1': workbook}
        except Exception as e:
            self.crm_customer_address2_excel_error = str(e)
            logging.warning(f'地址2 Excel加载失败: {e}')
            return

        name_candidates = ('客户名称', '企业名称', '客户名', '名称', '公司名称', '单位名称')
        address_candidates = ('地址', '客户地址', '详细地址', '注册地址', '公司地址', '通讯地址')
        mobile_candidates = ('手机', '手机号', '手机号码', '联系电话', '电话', '区电话', '固定电话', '联系电话1', '联系电话2', '联系人电话', '联系人手机')

        for sheet_name, sheet_df in (workbook or {}).items():
            if sheet_df is None or not hasattr(sheet_df, 'columns') or sheet_df.empty:
                continue

            sheet_column_map = {}
            for col in list(sheet_df.columns):
                col_stripped = str(col).strip()
                sheet_column_map[col_stripped] = col
                sheet_column_map[col_stripped.lower()] = col

            name_col = None
            addr_col = None
            mobile_col = None

            for candidate in name_candidates:
                if candidate in sheet_column_map:
                    name_col = sheet_column_map[candidate]
                    break
                if candidate.lower() in sheet_column_map:
                    name_col = sheet_column_map[candidate.lower()]
                    break
                for key, col in sheet_column_map.items():
                    if candidate in key or key in candidate:
                        name_col = col
                        break
                if name_col:
                    break

            if not name_col:
                continue

            for candidate in address_candidates:
                if candidate in sheet_column_map:
                    addr_col = sheet_column_map[candidate]
                    break
                if candidate.lower() in sheet_column_map:
                    addr_col = sheet_column_map[candidate.lower()]
                    break
                for key, col in sheet_column_map.items():
                    if candidate in key or key in candidate:
                        addr_col = col
                        break
                if addr_col:
                    break

            for candidate in mobile_candidates:
                if candidate in sheet_column_map:
                    mobile_col = sheet_column_map[candidate]
                    break
                if candidate.lower() in sheet_column_map:
                    mobile_col = sheet_column_map[candidate.lower()]
                    break
                for key, col in sheet_column_map.items():
                    if candidate in key or key in candidate:
                        mobile_col = col
                        break
                if mobile_col:
                    break

            for _, row in sheet_df.iterrows():
                name = self._normalize_crm_excel_lookup_value(row.get(name_col, ''))
                if not name:
                    continue
                if addr_col:
                    addr_map[name] = self._normalize_crm_excel_lookup_value(row.get(addr_col, ''))
                if mobile_col:
                    contact_map[name] = self._normalize_crm_excel_lookup_value(row.get(mobile_col, ''))
            break

        self.crm_customer_address2_excel_path = configured_path
        self.crm_customer_address2_excel_mtime = current_mtime
        self.crm_customer_address2_excel_map = addr_map
        self.crm_customer_address2_contact_excel_map = contact_map
        self.crm_customer_address2_excel_error = ''


    def _get_crm_customer_address(self, customer_id, customer_name=''):
        """获取客户地址：Excel1 → Excel2 → 空"""
        customer_name_text = str(customer_name or '').strip() or self._get_crm_customer_display_name(customer_id)
        # 先查主地址Excel
        addr = self._get_crm_customer_address_from_excel(customer_name_text)
        if addr: return addr
        # 再查备用地址Excel
        addr2 = self._get_crm_customer_address_from_excel2(customer_name_text)
        if addr2: return addr2
        return ''


    def _get_crm_row_id(self, order, fallback_index=None):
        """内部方法：获取CRM行id。"""
        for key in ('_id', 'id', 'name'):
            row_id = str(order.get(key, '')).strip() if order.get(key) is not None else ''
            if row_id:
                return row_id
        suffix = str(order.get('field_2maFO__c', '')).strip()
        if fallback_index is None:
            fallback_index = 0
        return f"crm_{fallback_index}_{suffix}"


    def _get_crm_default_customer_type(self, order):
        """内部方法：获取CRM默认客户类型。"""
        account_id = str(order.get('account_id', '')).strip()
        related_customer_id = str(order.get('field_8pAwf__c', '')).strip()
        if account_id and related_customer_id and account_id == related_customer_id:
            return '终端客户'
        return '经销商'


    def _get_crm_customer_type(self, order, row_id=None):
        """内部方法：获取CRM客户类型。"""
        if row_id is None:
            row_id = self._get_crm_row_id(order)
        override = getattr(self, 'crm_customer_type_overrides', {}).get(row_id, '')
        if override in ('经销商', '终端客户'):
            return override
        return self._get_crm_default_customer_type(order)


    def _get_crm_product_match_rows(self, order):
        """
        内部方法：获取CRM产品匹配rows（使用CRM选项值映射）。

        【功能说明】：
        从 CRM选项值映射 (option_mapping_fields) 中获取订单产品类型的匹配数据，
        替代旧的 business_rules.product_match_rows 机制。
        """
        # 获取订单产品类型的原始值和显示值
        display_product = self._crm_extract_field(order, 'field_jv2dq__c')
        raw_product = self._normalize_crm_display_value(order.get('field_jv2dq__c', ''))

        if not display_product and not raw_product:
            return []

        # 从CRM选项值映射中查找匹配的产品
        fx_cfg = self.config.get('fxiaoke', {})
        option_mapping_fields = fx_cfg.get('option_mapping_fields', [])

        matched_rows = []
        for entry in option_mapping_fields:
            if not isinstance(entry, dict):
                continue

            field_key = entry.get('field_key', '')
            mappings = entry.get('mappings', {})
            if not isinstance(mappings, dict):
                continue

            # ✅ 订单产品类型字段 + option_ 开头的产品选项字段
            if field_key == 'field_jv2dq__c':
                # 原有逻辑：匹配 display_product / raw_product
                for option_id, display_text in mappings.items():
                    normalized_id = self._normalize_product_match_text(option_id)
                    normalized_text = self._normalize_product_match_text(display_text)
                    normalized_display = self._normalize_product_match_text(display_product)
                    normalized_raw = self._normalize_product_match_text(raw_product)

                    if (normalized_id and normalized_id in (normalized_display, normalized_raw)) or \
                       (normalized_text and normalized_text in (normalized_display, normalized_raw)):
                        matched_rows.append({
                            'order_product': display_text or option_id,
                            'model_spec': option_id,
                            'product_remark': '',
                        })

            elif field_key.startswith('option_'):
                # ✅ option_ 字段：直接从订单数据中获取字段值并匹配映射
                order_val = self._normalize_crm_display_value(order.get(field_key, ''))
                if not order_val:
                    continue
                # 多选字段展平
                option_ids = []
                if isinstance(order_val, list):
                    option_ids = [str(v).strip() for v in order_val if str(v).strip()]
                elif isinstance(order_val, str):
                    option_ids = [p.strip() for p in order_val.replace(',', ' ').split() if p.strip()]

                for option_id in option_ids:
                    if option_id in mappings:
                        display_text = str(mappings[option_id])
                        matched_rows.append({
                            'order_product': display_text or option_id,
                            'model_spec': option_id,
                            'product_remark': '',
                        })

        # 如果没有找到CRM选项值映射，尝试使用旧的product_match_rows（向后兼容）
        if not matched_rows:
            product_match_rows = getattr(self, 'config', {}).get('business_rules', {}).get('product_match_rows', [])
            if isinstance(product_match_rows, list):
                match_targets = {
                    self._normalize_product_match_text(display_product),
                    self._normalize_product_match_text(raw_product),
                }
                match_targets.discard('')

                for row_data in product_match_rows:
                    if not isinstance(row_data, dict):
                        continue
                    order_product = self._normalize_product_match_text(row_data.get('order_product', ''))
                    model_spec = self._normalize_product_match_text(row_data.get('model_spec', ''))
                    if (order_product and order_product in match_targets) or \
                       (model_spec and model_spec in match_targets):
                        matched_rows.append(row_data)

        return matched_rows


    def _get_crm_default_product_remark(self, order):
        """内部方法：获取CRM默认产品备注。"""
        for row_data in self._get_crm_product_match_rows(order):
            product_remark = str(row_data.get('product_remark', '') or '').strip()
            if product_remark:
                return product_remark
        return ''


    def _get_crm_model_spec(self, order):
        """根据订单产品类型匹配规格型号"""
        model_specs = []
        seen = set()
        for row_data in self._get_crm_product_match_rows(order):
            model_spec = str(row_data.get('model_spec', '') or '').strip()
            if not model_spec or model_spec in seen:
                continue
            seen.add(model_spec)
            model_specs.append(model_spec)
        return '、'.join(model_specs)


    def _parse_crm_amount_value(self, value):
        """内部方法：解析CRMamount值。"""
        text = str(value or '').strip().replace(',', '')
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None


    def _format_crm_amount_value(self, value):
        """内部方法：格式化CRMamount值。"""
        amount = self._parse_crm_amount_value(value)
        if amount is None:
            return str(value or '').strip()
        if float(amount).is_integer():
            return str(int(amount))
        return f"{amount:.2f}".rstrip('0').rstrip('.')


    def _is_crm_price_floor_product(self, row_data):
        """内部方法：判断CRM价格floor产品。"""
        if not isinstance(row_data, dict):
            return False
        product_name = self._normalize_product_match_text(row_data.get('product_name', ''))
        target_name = self._normalize_product_match_text('口腔颌面锥形束计算机体层摄影设备')
        return product_name == target_name


    def _apply_crm_matched_price_floor(self, matched_price, order, row_data=None):
        """内部方法：应用CRMmatched价格floor。"""
        matched_amount = self._parse_crm_amount_value(matched_price)
        product_amount = self._parse_crm_amount_value(order.get('product_amount', ''))
        if matched_amount is None or product_amount is None:
            return str(matched_price or '').strip()
        if matched_amount >= product_amount:
            return self._format_crm_amount_value(matched_price)
        if self._is_crm_price_floor_product(row_data):
            return self._format_crm_amount_value(product_amount + 5000)
        return self._format_crm_amount_value(product_amount)


    def _get_crm_default_matched_price(self, order, customer_type=None):
        """内部方法：获取CRM默认matched价格。"""
        customer_type = customer_type or self._get_crm_customer_type(order)
        product_match_rows = self._get_crm_product_match_rows(order)
        if not product_match_rows:
            return ''

        price_key = 'end_customer_price' if customer_type == '终端客户' else 'dealer_price'
        for row_data in product_match_rows:
            matched_price = str(row_data.get(price_key, '') or '').strip()
            if matched_price:
                return self._apply_crm_matched_price_floor(matched_price, order, row_data)
        return ''


    def _get_crm_matched_price(self, order, customer_type=None, row_id=None):
        """内部方法：获取CRMmatched价格。"""
        if row_id is None:
            row_id = self._get_crm_row_id(order)
        override = getattr(self, 'crm_price_overrides', {}).get(row_id, '')
        if str(override).strip():
            return str(override).strip()
        return self._get_crm_default_matched_price(order, customer_type)


    def _get_crm_discount_unit_price(self, order, customer_type=None, row_id=None):
        """内部方法：获取CRMdiscount单价价格。"""
        if row_id is None:
            row_id = self._get_crm_row_id(order)

        matched_price = self._parse_crm_amount_value(
            self._get_crm_matched_price(order, customer_type, row_id)
        )
        product_amount = self._parse_crm_amount_value(order.get('product_amount', ''))
        order_quantity = self._parse_crm_amount_value(order.get('field_Xqs0n__c', ''))

        if matched_price is None or product_amount is None or order_quantity in (None, 0):
            return ''

        try:
            discount_unit_price = Decimal(str(matched_price)) - (
                Decimal(str(product_amount)) / Decimal(str(order_quantity))
            )
        except Exception:
            return ''

        discount_unit_price = discount_unit_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return self._format_crm_amount_value(discount_unit_price)


    def _get_crm_product_remark(self, order, row_id=None):
        """内部方法：获取CRM产品备注。"""
        if row_id is None:
            row_id = self._get_crm_row_id(order)
        override = getattr(self, 'crm_product_remark_overrides', {}).get(row_id, '')
        if str(override).strip():
            return str(override).strip()
        return self._get_crm_default_product_remark(order)


    def _get_crm_order_for_page_row(self, row):
        """内部方法：获取CRM订单for页码行。"""
        current_page_rows = getattr(self, 'crm_current_page_rows', [])
        if row < 0 or row >= len(current_page_rows):
            return None, None

        order = current_page_rows[row]
        page_start = max(getattr(self, 'crm_current_page', 1) - 1, 0) * max(getattr(self, 'crm_page_size', 20), 1)
        row_id = self._get_crm_row_id(order, page_start + row)
        return order, row_id


    def _set_crm_customer_type_override(self, order, row_id, new_type):
        """内部方法：设置CRM客户类型override。"""
        if not hasattr(self, 'crm_customer_type_overrides') or not isinstance(self.crm_customer_type_overrides, dict):
            self.crm_customer_type_overrides = {}

        default_type = self._get_crm_default_customer_type(order)
        normalized_type = str(new_type or '').strip()
        if normalized_type not in ('经销商', '终端客户'):
            normalized_type = default_type

        if not normalized_type or normalized_type == default_type:
            self.crm_customer_type_overrides.pop(row_id, None)
        else:
            self.crm_customer_type_overrides[row_id] = normalized_type

        self.save_user_runtime_state_patch({
            'crm_customer_type_overrides': self.crm_customer_type_overrides
        }, immediate=True)
        self._sync_override_to_mapped_cache(row_id, 'customer_type', normalized_type)


    def _set_crm_price_override(self, order, row_id, new_price, customer_type=None):
        """内部方法：设置CRM价格override。"""
        if not hasattr(self, 'crm_price_overrides') or not isinstance(self.crm_price_overrides, dict):
            self.crm_price_overrides = {}

        current_type = customer_type or self._get_crm_customer_type(order, row_id)
        default_price = str(self._get_crm_default_matched_price(order, current_type) or '').strip()
        normalized_price = str(new_price or '').strip()

        if not normalized_price or normalized_price == default_price:
            self.crm_price_overrides.pop(row_id, None)
        else:
            self.crm_price_overrides[row_id] = normalized_price

        self.save_user_runtime_state_patch({
            'crm_price_overrides': self.crm_price_overrides
        }, immediate=True)
        self._sync_override_to_mapped_cache(row_id, 'matched_price', normalized_price)


    def _set_crm_product_remark_override(self, order, row_id, new_remark):
        """内部方法：设置CRM产品备注override。"""
        if not hasattr(self, 'crm_product_remark_overrides') or not isinstance(self.crm_product_remark_overrides, dict):
            self.crm_product_remark_overrides = {}

        default_remark = str(self._get_crm_default_product_remark(order) or '').strip()
        normalized_remark = str(new_remark or '').strip()

        if not normalized_remark or normalized_remark == default_remark:
            self.crm_product_remark_overrides.pop(row_id, None)
        else:
            self.crm_product_remark_overrides[row_id] = normalized_remark

        self.save_user_runtime_state_patch({
            'crm_product_remark_overrides': self.crm_product_remark_overrides
        }, immediate=True)
        self._sync_override_to_mapped_cache(row_id, 'product_remark', normalized_remark)


    def _schedule_crm_table_refresh_after_inline_edit(self):
        """内部方法：调度CRM表格刷新after行内edit。"""
        if getattr(self, '_crm_inline_edit_refresh_pending', False):
            return
        self._crm_inline_edit_refresh_pending = True
        QTimer.singleShot(0, self._refresh_crm_table_after_inline_edit)


    def _refresh_crm_table_after_inline_edit(self):
        """内部方法：刷新CRM表格after行内edit。"""
        self._crm_inline_edit_refresh_pending = False
        self._populate_crm_table()


    def get_crm_price_editor_options(self, row):
        """获取CRM价格编辑器选项。"""
        order, row_id = self._get_crm_order_for_page_row(row)
        if order is None:
            return []

        current_type = self._get_crm_customer_type(order, row_id)
        options = []
        for price in [
            self._get_crm_matched_price(order, current_type, row_id),
            self._get_crm_default_matched_price(order, current_type),
            self._get_crm_default_matched_price(order, '经销商'),
            self._get_crm_default_matched_price(order, '终端客户'),
        ]:
            text = str(price or '').strip()
            if text and text not in options:
                options.append(text)
        return options


    def get_crm_product_remark_editor_options(self, row):
        """获取CRM产品备注编辑器选项。"""
        order, row_id = self._get_crm_order_for_page_row(row)
        if order is None:
            return []

        options = []
        for remark in [
            self._get_crm_product_remark(order, row_id),
            self._get_crm_default_product_remark(order),
        ]:
            text = str(remark or '').strip()
            if text and text not in options:
                options.append(text)

        for row_data in self._get_crm_product_match_rows(order):
            text = str(row_data.get('product_remark', '') or '').strip()
            if text and text not in options:
                options.append(text)

        return options


    def get_crm_inline_editor_options(self, row, column_type):
        """获取CRM行内编辑器选项。"""
        if column_type == 'matched_price':
            return self.get_crm_price_editor_options(row)
        if column_type == 'product_remark':
            return self.get_crm_product_remark_editor_options(row)
        return []


    def apply_crm_inline_cell_override(self, row, col, value):
        """应用CRM行内单元格override。"""
        order, row_id = self._get_crm_order_for_page_row(row)
        if order is None:
            return

        header_label = self._get_crm_header_label(col)

        if header_label == '客户类型':
            self._set_crm_customer_type_override(order, row_id, value)
            self._schedule_crm_table_refresh_after_inline_edit()
        elif header_label == '匹配价格':
            current_type = self._get_crm_customer_type(order, row_id)
            self._set_crm_price_override(order, row_id, value, customer_type=current_type)
            self._schedule_crm_table_refresh_after_inline_edit()
        elif header_label == '产品备注':
            self._set_crm_product_remark_override(order, row_id, value)
            self._schedule_crm_table_refresh_after_inline_edit()


    def _collect_crm_option_value(self, field_key, value):
        """内部方法：收集CRM选项值。"""
        if not hasattr(self, '_crm_new_options'):
            self._crm_new_options = {}
        if field_key not in self._crm_new_options:
            self._crm_new_options[field_key] = set()
        if value and len(value) < 50:
            self._crm_new_options[field_key].add(value)


    def _crm_order_contains_f200(self, order):
        """内部方法：处理CRM订单containsf200逻辑。"""
        target = self._normalize_product_match_text('F200')
        candidates = [
            self._crm_extract_field(order, 'field_jv2dq__c'),
            self._normalize_crm_display_value(order.get('field_jv2dq__c', '')),
        ]
        for row_data in self._get_crm_product_match_rows(order):
            candidates.append(row_data.get('order_product', ''))
            candidates.append(row_data.get('model_spec', ''))

        for candidate in candidates:
            normalized = self._normalize_product_match_text(candidate)
            if normalized and (normalized == target or target in normalized):
                return True
        return False


    def _get_crm_template_names(self):
        """内部方法：获取CRM模板names。"""
        config = getattr(self, 'config', None) or load_config()
        crm_templates = config.get('file_config', {}).get('crm_word_templates', {})
        return list(crm_templates.keys()) if isinstance(crm_templates, dict) else []


    def _get_crm_recommended_template_name(self, order):
        """内部方法：获取CRMrecommended模板名称。"""
        config = getattr(self, 'config', None) or load_config()
        crm_templates = config.get('file_config', {}).get('crm_word_templates', {})
        if not isinstance(crm_templates, dict):
            crm_templates = {}

        erp_order_no = str(order.get('field_2maFO__c', '') or '').strip()
        same_erp_orders = self._get_crm_orders_by_erp_from_all_data(erp_order_no) if erp_order_no else []
        if len(same_erp_orders) > 1 and any(self._crm_order_contains_f200(item) for item in same_erp_orders):
            if 'CT+F200' in crm_templates:
                return 'CT+F200'

        for row_data in self._get_crm_product_match_rows(order):
            template_name = str(row_data.get('default_template', '') or '').strip()
            if template_name and template_name in crm_templates:
                return template_name

        default_template = str(config.get('app_settings', {}).get('default_crm_template', '') or '').strip()
        if default_template and default_template in crm_templates:
            return default_template
        return ''


    def _populate_crm_table(self):
        """内部方法：填充CRM表格。"""
        self.crm_filtered_data = self.crm_all_data[:]

        # 首次加载数据后应用默认筛选方案
        if not getattr(self, '_crm_default_preset_applied', False) and self.crm_filtered_data:
            self._crm_default_preset_applied = True
            default_name = self.config.get('fxiaoke', {}).get('crm_filter_default_preset', '')
            if default_name:
                self._load_crm_filter_preset(default_name)

        start_date = self.crm_date_start
        end_date = self.crm_date_end
        if start_date and end_date:
            ts_start = int(datetime(start_date.year(), start_date.month(), start_date.day()).timestamp() * 1000)
            ts_end = int(datetime(end_date.year(), end_date.month(), end_date.day(), 23, 59, 59).timestamp() * 1000)
            self.crm_filtered_data = [
                r for r in self.crm_filtered_data
                if isinstance(r.get('create_time'), (int, float))
                   and ts_start <= r['create_time'] <= ts_end
            ]

        # 多条件筛选
        conditions = self._collect_crm_filter_conditions()
        if conditions:
            self.crm_filtered_data = [
                r for r in self.crm_filtered_data
                if self._crm_row_matches_all_conditions(r, conditions)
            ]

        # 搜索（全字段模糊搜索 + 日期范围搜索）
        if hasattr(self, 'crm_search_stack') and self.crm_search_stack.currentIndex() == 1:
            # 日期范围搜索
            dr = self.crm_search_date_btn.property('crm_date_range') or {}
            if dr.get('start') and dr.get('end'):
                start_str = dr['start'].toString('yyyy-MM-dd')
                end_str = dr['end'].toString('yyyy-MM-dd')
                self.crm_filtered_data = [
                    r for r in self.crm_filtered_data
                    if start_str <= str(r.get('create_time', '') or '')[:10] <= end_str
                ]
        else:
            search = self.crm_search_input.text().strip().lower() if hasattr(self, 'crm_search_input') else ''
            if search:
                # 全字段搜索
                self.crm_filtered_data = [
                    r for r in self.crm_filtered_data
                    if search in self._build_crm_row_search_text(r)
                ]
        # 列头筛选（AutoFilter）
        self._apply_crm_autofilter()
        # ✅ 从设置中动态获取字段映射，用于排序时标签→API键转换
        cfg = load_config()
        field_mapping_list = cfg.get('fxiaoke', {}).get('crm_field_mapping_list', [])
        known_time_fields = {'create_time', 'submit_time', 'last_modified_time'}
        if field_mapping_list:
            label_to_key = {}
            for m in field_mapping_list:
                api_name = m.get('api_name', '')
                display_name = m.get('display_name', api_name)
                if api_name:
                    label_to_key[display_name] = (api_name, api_name in known_time_fields)
            # 补充 CRM_ALL_FIELDS 中特殊表头（地址、手机等）的映射
            for key, label, is_time in self.CRM_ALL_FIELDS:
                if label not in label_to_key:
                    label_to_key[label] = (key, is_time)
        else:
            label_to_key = {label: (key, is_time) for key, label, is_time in self.CRM_ALL_FIELDS}
        amount_fields = {'order_amount', 'payment_amount', 'receivable_amount', 'invoice_amount', 'product_amount'}
        column_alignments = cfg.get('app_settings', {}).get('crm_table_settings', {}).get('column_alignments', {})

        self.crm_filtered_data = self._sort_crm_data(self.crm_filtered_data, label_to_key)
        total = len(self.crm_filtered_data)
        max_page = max(1, (total + self.crm_page_size - 1) // self.crm_page_size) if total else 1
        if self.crm_current_page > max_page:
            self.crm_current_page = max_page
        start = (self.crm_current_page - 1) * self.crm_page_size
        end = min(start + self.crm_page_size, total)
        page_data = self.crm_filtered_data[start:end]
        self.crm_current_page_rows = list(page_data)

        for row in range(self.crm_table.rowCount()):
            for col in range(self.crm_table.columnCount()):
                if self.crm_table.cellWidget(row, col) is not None:
                    self.crm_table.removeCellWidget(row, col)
        self.crm_table.clearContents()
        self.crm_table.setRowCount(len(page_data))

        crm_template_names = self._get_crm_template_names()
        column_index_map = dict(getattr(self, 'crm_column_index_map', {}))

        self.crm_selected_row_ids = getattr(self, 'crm_selected_row_ids', set())

        self.crm_table.setUpdatesEnabled(False)
        try:
            for row_idx, order in enumerate(page_data):
                row_id = self._get_crm_row_id(order, row_idx + start)

                checkbox_item = QTableWidgetItem()
                checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                checkbox_item.setData(Qt.ItemDataRole.UserRole, row_id)
                self.crm_table.setItem(row_idx, 0, checkbox_item)

                checkbox_widget = TableRowCheckBox(row_id=row_id)
                checkbox_widget.blockSignals(True)
                checkbox_widget.setChecked(row_id in self.crm_selected_row_ids)
                checkbox_widget.blockSignals(False)
                checkbox_widget.toggled_with_row_id.connect(self.on_crm_row_checkbox_toggled)

                checkbox_container = QWidget()
                checkbox_layout = QHBoxLayout(checkbox_container)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)
                checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                checkbox_layout.addWidget(checkbox_widget)
                self.crm_table.setCellWidget(row_idx, 0, checkbox_container)

                model_spec = self._get_crm_model_spec(order)
                customer_type = self._get_crm_customer_type(order, row_id)
                matched_price = self._get_crm_matched_price(order, customer_type, row_id)
                discount_unit_price = self._get_crm_discount_unit_price(order, customer_type, row_id)
                product_remark = self._get_crm_product_remark(order, row_id)
                product_amount_upper = self._convert_amount_to_rmb_upper(order.get('product_amount', ''))

                for header_label in self.crm_visible_headers:
                    col_idx = column_index_map.get(header_label, -1)
                    if col_idx <= 0:
                        continue

                    if header_label == '模板选择':
                        template_combo = QComboBox()
                        template_combo.addItem("-", "")
                        for tpl_name in crm_template_names:
                            template_combo.addItem(tpl_name, tpl_name)
                        preferred_template = self._get_selected_crm_template_name(order, row_id)
                        if preferred_template:
                            idx = template_combo.findData(preferred_template)
                            if idx >= 0:
                                template_combo.setCurrentIndex(idx)
                        template_combo.currentIndexChanged.connect(lambda index, rid=row_id: self.on_crm_template_changed(rid, index))
                        self.crm_table.setCellWidget(row_idx, col_idx, template_combo)
                        continue

                    if header_label == '规格型号':
                        item = QTableWidgetItem(model_spec)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    if header_label == '客户类型':
                        item = QTableWidgetItem(customer_type)
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    if header_label == '匹配价格':
                        item = QTableWidgetItem(matched_price)
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    if header_label == '折扣单价':
                        item = QTableWidgetItem(discount_unit_price)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    if header_label == '产品备注':
                        item = QTableWidgetItem(product_remark)
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    if header_label == '大写':
                        item = QTableWidgetItem(product_amount_upper)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    key_info = label_to_key.get(header_label)
                    if not key_info:
                        continue
                    key, is_time = key_info
                    val = self._crm_extract_field(order, key)

                    if is_time and val:
                        try:
                            if isinstance(val, (int, float)):
                                timestamp = val
                            else:
                                val_str = str(val).strip()
                                if val_str.isdigit():
                                    timestamp = int(val_str)
                                else:
                                    timestamp = 0

                            if timestamp > 0:
                                if timestamp > 1e12:
                                    formatted_time = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d')
                                elif timestamp > 1e9:
                                    formatted_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
                                else:
                                    formatted_time = str(val)
                                val = formatted_time
                        except Exception as e:
                            print(f"[CRM时间格式化错误] 字段={key}, 值={val}, 错误: {e}")
                            val = str(val)
                    elif key in amount_fields:
                        try:
                            val = f"{float(val):,.2f}"
                        except:
                            val = str(val)
                    else:
                        val = str(val) if val else ''
                    item = QTableWidgetItem(val)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    user_align = column_alignments.get(header_label, '')
                    if user_align == 'right':
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    elif user_align == 'center':
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    elif user_align == 'left':
                        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    elif key in amount_fields:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    elif is_time:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.crm_table.setItem(row_idx, col_idx, item)
        finally:
            self.crm_table.setUpdatesEnabled(True)

        self.crm_page_label.setText(f"{self.crm_current_page}/{max_page}")
        self.crm_record_label.setText(f"共 {total} 条记录")

        self._update_crm_header_checkbox_state()
        self._update_crm_table_sort_indicator()

        # ✅ 延迟应用列宽 - 确保在所有其他操作完成后执行，不会被覆盖
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(10, self._delayed_apply_crm_column_widths)

        if hasattr(self, '_crm_new_options') and self._crm_new_options:
            print("\n[CRM选项值] 发现以下未配置的选项ID，请在 设置→CRM设置→选项值映射 中配置：")
            config_changed = False
            for field_key, values in self._crm_new_options.items():
                field_label = self.CRM_OPTION_FIELDS.get(field_key, field_key)
                current_data = self.crm_option_mappings.get(field_key, {})
                if isinstance(current_data, dict):
                    current_mappings = current_data.get('mappings', {})
                else:
                    current_mappings = current_data if isinstance(current_data, dict) else {}
                unmapped = [v for v in values if v not in current_mappings]
                if unmapped:
                    print(f"  • {field_label} ({field_key}): {', '.join(sorted(unmapped)[:20])}")
                    if len(unmapped) > 20:
                        print(f"    ... 共{len(unmapped)}个")
                    if field_key not in self.crm_option_mappings or not isinstance(self.crm_option_mappings[field_key], dict) or 'mappings' not in self.crm_option_mappings[field_key]:
                        self.crm_option_mappings[field_key] = {"label": field_label, "mappings": {}}
                        config_changed = True
            if config_changed:
                try:
                    config = load_config()
                    if 'business_rules' not in config:
                        config['business_rules'] = {}
                    config['business_rules']['crm_option_mappings'] = self.crm_option_mappings
                    save_config(config, immediate=False)
                    print("\n[CRM选项值] 已自动创建字段配置框架，请进入设置界面填写具体的ID=文本映射")
                except Exception as e:
                    print(f"\n[CRM选项值] 自动保存失败: {e}")
            del self._crm_new_options


    def _populate_crm_table_from_mapped_data(self):
        """使用映射缓存数据填充 CRM 表格（数据已包含映射+清洗后的值，跳过动态映射）"""
        self.crm_filtered_data = self.crm_all_data[:]

        if not getattr(self, '_crm_default_preset_applied', False) and self.crm_filtered_data:
            self._crm_default_preset_applied = True
            default_name = self.config.get('fxiaoke', {}).get('crm_filter_default_preset', '')
            if default_name:
                self._load_crm_filter_preset(default_name)

        start_date = self.crm_date_start
        end_date = self.crm_date_end
        if start_date and end_date:
            ts_start = int(datetime(start_date.year(), start_date.month(), start_date.day()).timestamp() * 1000)
            ts_end = int(datetime(end_date.year(), end_date.month(), end_date.day(), 23, 59, 59).timestamp() * 1000)
            self.crm_filtered_data = [
                r for r in self.crm_filtered_data
                if self._parse_crm_create_time_val(r.get('create_time', ''))
                   and ts_start <= self._parse_crm_create_time_val(r.get('create_time', '')) <= ts_end
            ]

        conditions = self._collect_crm_filter_conditions()
        if conditions:
            self.crm_filtered_data = [
                r for r in self.crm_filtered_data
                if self._crm_row_matches_all_conditions_mapped(r, conditions)
            ]

        if hasattr(self, 'crm_search_stack') and self.crm_search_stack.currentIndex() == 1:
            # 日期范围搜索
            dr = self.crm_search_date_btn.property('crm_date_range') or {}
            if dr.get('start') and dr.get('end'):
                start_str = dr['start'].toString('yyyy-MM-dd')
                end_str = dr['end'].toString('yyyy-MM-dd')
                self.crm_filtered_data = [
                    r for r in self.crm_filtered_data
                    if start_str <= str(r.get('create_time', '') or '')[:10] <= end_str
                ]
        else:
            search = self.crm_search_input.text().strip().lower() if hasattr(self, 'crm_search_input') else ''
            if search:
                self.crm_filtered_data = [
                    r for r in self.crm_filtered_data
                    if search in self._build_crm_row_search_text(r)
                ]

        # ✅ 从设置中动态获取字段映射，用于排序时标签→API键转换
        cfg = load_config()
        field_mapping_list = cfg.get('fxiaoke', {}).get('crm_field_mapping_list', [])
        known_time_fields = {'create_time', 'submit_time', 'last_modified_time'}
        if field_mapping_list:
            label_to_key = {}
            for m in field_mapping_list:
                api_name = m.get('api_name', '')
                display_name = m.get('display_name', api_name)
                if api_name:
                    label_to_key[display_name] = (api_name, api_name in known_time_fields)
            # 补充 CRM_ALL_FIELDS 中特殊表头（地址、手机等）的映射
            for key, label, is_time in self.CRM_ALL_FIELDS:
                if label not in label_to_key:
                    label_to_key[label] = (key, is_time)
        else:
            label_to_key = {label: (key, is_time) for key, label, is_time in self.CRM_ALL_FIELDS}
        amount_fields = {'order_amount', 'payment_amount', 'receivable_amount', 'invoice_amount', 'product_amount'}
        column_alignments = cfg.get('app_settings', {}).get('crm_table_settings', {}).get('column_alignments', {})

        self.crm_filtered_data = self._sort_crm_data(self.crm_filtered_data, label_to_key)
        total = len(self.crm_filtered_data)
        max_page = max(1, (total + self.crm_page_size - 1) // self.crm_page_size) if total else 1
        if self.crm_current_page > max_page:
            self.crm_current_page = max_page
        start = (self.crm_current_page - 1) * self.crm_page_size
        end = min(start + self.crm_page_size, total)
        page_data = self.crm_filtered_data[start:end]
        self.crm_current_page_rows = list(page_data)

        for row in range(self.crm_table.rowCount()):
            for col in range(self.crm_table.columnCount()):
                if self.crm_table.cellWidget(row, col) is not None:
                    self.crm_table.removeCellWidget(row, col)
        self.crm_table.clearContents()
        self.crm_table.setRowCount(len(page_data))

        crm_template_names = self._get_crm_template_names()
        column_index_map = dict(getattr(self, 'crm_column_index_map', {}))
        self.crm_selected_row_ids = getattr(self, 'crm_selected_row_ids', set())

        self.crm_table.setUpdatesEnabled(False)
        try:
            for row_idx, order in enumerate(page_data):
                row_id = self._get_crm_row_id(order, row_idx + start)

                checkbox_item = QTableWidgetItem()
                checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                checkbox_item.setData(Qt.ItemDataRole.UserRole, row_id)
                self.crm_table.setItem(row_idx, 0, checkbox_item)

                checkbox_widget = TableRowCheckBox(row_id=row_id)
                checkbox_widget.blockSignals(True)
                checkbox_widget.setChecked(row_id in self.crm_selected_row_ids)
                checkbox_widget.blockSignals(False)
                checkbox_widget.toggled_with_row_id.connect(self.on_crm_row_checkbox_toggled)

                checkbox_container = QWidget()
                checkbox_layout = QHBoxLayout(checkbox_container)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)
                checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                checkbox_layout.addWidget(checkbox_widget)
                self.crm_table.setCellWidget(row_idx, 0, checkbox_container)

                # ✅ 直接从映射缓存取值（不调用 _crm_extract_field）
                model_spec = str(order.get('model_spec', '') or '')
                customer_type = str(order.get('customer_type', '') or '')
                matched_price = str(order.get('matched_price', '') or '')
                discount_unit_price = str(order.get('discount_unit_price', '') or '')
                product_remark = str(order.get('product_remark', '') or '')
                product_amount_upper = str(order.get('product_amount_upper', '') or '')

                for header_label in self.crm_visible_headers:
                    col_idx = column_index_map.get(header_label, -1)
                    if col_idx <= 0:
                        continue

                    if header_label == '模板选择':
                        template_combo = QComboBox()
                        template_combo.addItem("-", "")
                        for tpl_name in crm_template_names:
                            template_combo.addItem(tpl_name, tpl_name)
                        preferred_template = str(order.get('template_name', '') or '')
                        if preferred_template:
                            idx = template_combo.findData(preferred_template)
                            if idx >= 0:
                                template_combo.setCurrentIndex(idx)
                        template_combo.currentIndexChanged.connect(
                            lambda index, rid=row_id: self.on_crm_template_changed(rid, index)
                        )
                        self.crm_table.setCellWidget(row_idx, col_idx, template_combo)
                        continue

                    if header_label == '规格型号':
                        item = QTableWidgetItem(model_spec)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    if header_label == '客户类型':
                        item = QTableWidgetItem(customer_type)
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    if header_label == '匹配价格':
                        item = QTableWidgetItem(matched_price)
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    if header_label == '折扣单价':
                        item = QTableWidgetItem(discount_unit_price)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    if header_label == '产品备注':
                        item = QTableWidgetItem(product_remark)
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    if header_label == '大写':
                        item = QTableWidgetItem(product_amount_upper)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        self.crm_table.setItem(row_idx, col_idx, item)
                        continue

                    # 动态字段：直接从映射缓存取值
                    key_info = label_to_key.get(header_label)
                    if not key_info:
                        continue
                    key, is_time = key_info
                    val = order.get(key, '')
                    if val is None:
                        val = ''

                    if is_time and val:
                        try:
                            val = str(val)
                            if val.isdigit():
                                timestamp = int(val)
                                if timestamp > 0:
                                    if timestamp > 1e12:
                                        val = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d')
                                    elif timestamp > 1e9:
                                        val = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
                        except Exception:
                            val = str(val)
                    elif key in amount_fields:
                        try:
                            val = f"{float(val):,.2f}"
                        except Exception:
                            val = str(val)
                    else:
                        val = str(val) if val else ''
                    item = QTableWidgetItem(val)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.crm_table.setItem(row_idx, col_idx, item)
        finally:
            self.crm_table.setUpdatesEnabled(True)

        self.crm_page_label.setText(f"{self.crm_current_page}/{max_page}")
        self.crm_record_label.setText(f"共 {total} 条记录")


    def _parse_crm_create_time_val(self, val):
        """从映射缓存值解析 create_time 为毫秒时间戳"""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return float(str(val))
        except (ValueError, TypeError):
            return None


    def _crm_row_matches_all_conditions_mapped(self, order, conditions):
        """对映射缓存行应用筛选条件匹配"""
        for cond in conditions:
            api_key = cond.get('api_key', cond.get('field', ''))
            op = cond.get('operator', 'contains')
            expected = str(cond.get('value', '')).strip()
            actual = str(order.get(api_key, '') or '').strip()
            actual_lower = actual.lower()
            expected_lower = expected.lower()
            if op == 'contains' and expected_lower not in actual_lower:
                return False
            elif op == 'eq' and actual_lower != expected_lower:
                return False
            elif op == 'ne' and actual_lower == expected_lower:
                return False
            elif op == 'starts_with' and not actual_lower.startswith(expected_lower):
                return False
            elif op == 'ends_with' and not actual_lower.endswith(expected_lower):
                return False
            elif op == 'empty' and actual:
                return False
            elif op == 'not_empty' and not actual:
                return False
            elif op == 'date_before' and actual[:10] >= expected[:10]:
                return False
            elif op == 'date_after' and actual[:10] <= expected[:10]:
                return False
            elif op == 'date_range' and '~' in expected:
                parts = expected.split('~')
                if not (parts[0].strip() <= actual[:10] <= parts[1].strip()):
                    return False
        return True


    def on_crm_row_checkbox_toggled(self, row_id, checked):
        """响应CRM行复选框toggled相关操作。"""
        if not hasattr(self, 'crm_selected_row_ids'):
            self.crm_selected_row_ids = set()
        if checked:
            self.crm_selected_row_ids.add(row_id)
        else:
            self.crm_selected_row_ids.discard(row_id)
        self._update_crm_header_checkbox_state()


    def on_crm_template_changed(self, row_id, index):
        """响应CRM模板changed相关操作。"""
        if not hasattr(self, '_crm_row_templates'):
            self._crm_row_templates = {}
        combo = self.sender()
        if combo and index >= 0:
            template_name = combo.itemData(index) or ""
            if template_name:
                self._crm_row_templates[row_id] = template_name
            else:
                self._crm_row_templates.pop(row_id, None)
            # ✅ 持久化模板选择到运行时状态（解决重启丢失问题）
            self.save_user_runtime_state_patch({
                'crm_template_selections': self._crm_row_templates
            }, immediate=True)
            # ✅ 同步到本地映射表
            self._sync_override_to_mapped_cache(
                row_id, 'template_name',
                template_name if template_name else ''
            )


    def _update_crm_header_checkbox_state(self):
        """内部方法：更新CRM表头复选框状态。"""
        if not hasattr(self, 'crm_table_header'):
            return
        current_page_rows = getattr(self, 'crm_current_page_rows', [])
        if not current_page_rows:
            self.crm_table_header.set_check_state(Qt.CheckState.Unchecked)
            return
        selected_ids = getattr(self, 'crm_selected_row_ids', set())
        current_page_ids = set()
        page_start = max(getattr(self, 'crm_current_page', 1) - 1, 0) * max(getattr(self, 'crm_page_size', 20), 1)
        for idx, order in enumerate(current_page_rows):
            rid = self._get_crm_row_id(order, page_start + idx)
            current_page_ids.add(rid)
        checked_count = len(selected_ids & current_page_ids)
        total_count = len(current_page_ids)
        if checked_count == 0:
            self.crm_table_header.set_check_state(Qt.CheckState.Unchecked)
        elif checked_count == total_count:
            self.crm_table_header.set_check_state(Qt.CheckState.Checked)
        else:
            self.crm_table_header.set_check_state(Qt.CheckState.PartiallyChecked)


    def on_crm_header_select_all_toggled(self, state):
        """响应CRM表头选择alltoggled相关操作。"""
        is_checked = bool(state)
        print(f"[CRM全选] ========== 开始处理 ==========")
        print(f"[CRM全选] 收到信号: state={state} ({type(state)}), is_checked={is_checked}")
        if not hasattr(self, 'crm_filtered_data'):
            self.crm_filtered_data = []
        if not hasattr(self, 'crm_selected_row_ids'):
            self.crm_selected_row_ids = set()
        if not self.crm_filtered_data:
            print(f"[CRM全选] 无数据，返回")
            return

        start = (self.crm_current_page - 1) * self.crm_page_size
        end = min(start + self.crm_page_size, len(self.crm_filtered_data))
        page_data = self.crm_filtered_data[start:end]
        print(f"[CRM全选] 当前页: {start}-{end}, 共{len(page_data)}条")

        if is_checked:
            print(f"[CRM全选] 执行全选操作")
            for idx, order in enumerate(page_data):
                row_id = self._get_crm_row_id(order, idx + start)
                self.crm_selected_row_ids.add(row_id)
        else:
            print(f"[CRM全选] 执行取消全选操作")
            for idx, order in enumerate(page_data):
                row_id = self._get_crm_row_id(order, idx + start)
                self.crm_selected_row_ids.discard(row_id)

        print(f"[CRM全选] 处理完成, 已选择{len(self.crm_selected_row_ids)}行")

        print(f"[CRM全选] 更新UI复选框（阻止信号）...")
        for row in range(self.crm_table.rowCount()):
            checkbox_container = self.crm_table.cellWidget(row, 0)
            checkbox = checkbox_container.findChild(TableRowCheckBox) if checkbox_container else None
            if checkbox:
                checkbox.blockSignals(True)
                checkbox.setChecked(is_checked)
                checkbox.blockSignals(False)

        new_state = Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked
        print(f"[CRM全选] 直接设置表头状态为: {new_state}")
        self.crm_table_header.set_check_state(new_state)
        self.crm_table_header.viewport().update()
        print(f"[CRM全选] ========== 处理完成 ==========\n")


    def _on_crm_option_mapping_changed(self, field_key, text):
        """内部方法：响应CRM选项映射changed相关操作。"""
        try:
            mappings = {}
            if text and text.strip():
                pairs = text.split(';')
                for pair in pairs:
                    pair = pair.strip()
                    if '=' in pair:
                        key_val = pair.split('=', 1)
                        key = key_val[0].strip()
                        val = key_val[1].strip() if len(key_val) > 1 else ''
                        if key:
                            mappings[key] = val
            self.crm_option_mappings[field_key] = mappings
            config = load_config()
            if 'business_rules' not in config:
                config['business_rules'] = {}
            config['business_rules']['crm_option_mappings'] = self.crm_option_mappings
            save_config(config, immediate=False)
            if hasattr(self, 'crm_filtered_data') and self.crm_filtered_data:
                self._populate_crm_table()
        except Exception as e:
            print(f"保存CRM选项映射失败: {e}")


    def _load_crm_option_combo(self, combo, field_key):
        """从CRM选项值映射配置加载下拉框选项 - 按表格填写顺序显示"""
        try:
            # ✅ 优先从界面表格中读取选项（保持用户填写的行顺序）
            if hasattr(self, 'crm_option_mapping_table') and self.crm_option_mapping_table.rowCount() > 0:
                seen_texts = set()  # 避免重复添加
                for row in range(self.crm_option_mapping_table.rowCount()):
                    key_item = self.crm_option_mapping_table.item(row, 0)
                    text_item = self.crm_option_mapping_table.item(row, 3)

                    if key_item and text_item:
                        row_field_key = key_item.text().strip()
                        option_text = text_item.text().strip()

                        # 只加载匹配 field_key 的行，且文本不为空、未重复
                        if row_field_key == field_key and option_text and option_text not in seen_texts:
                            # 获取对应的ID（如果有）
                            id_item = self.crm_option_mapping_table.item(row, 2)
                            option_id = id_item.text().strip() if id_item else option_text

                            combo.addItem(option_text, option_id)
                            seen_texts.add(option_text)

                # 如果从表格中找到了选项，直接返回
                if seen_texts:
                    return

            # 回退：从内存中的配置加载（保持dict插入顺序）
            field_data, _ = self._get_crm_option_mapping_entry(field_key)
            if isinstance(field_data, dict) and 'mappings' in field_data:
                mappings = field_data.get('mappings', {})
                for option_id, option_text in mappings.items():
                    if option_text:
                        combo.addItem(option_text, option_id)
        except Exception as e:
            print(f"加载CRM选项失败 ({field_key}): {e}")


    def _refresh_crm_filter_combos(self):
        """刷新CRM筛选下拉框选项（从配置重新加载）"""
        try:
            if not hasattr(self, 'config'):
                return
            fx_cfg = self.config.get('fxiaoke', {})

            if hasattr(self, 'crm_product_type_combo'):
                current_text = self.crm_product_type_combo.currentText()
                self.crm_product_type_combo.blockSignals(True)
                self.crm_product_type_combo.clear()
                self.crm_product_type_combo.addItem("全部", "")
                product_type_options = fx_cfg.get('product_type_options', [])
                if product_type_options:
                    for opt in product_type_options:
                        self.crm_product_type_combo.addItem(opt, opt)
                else:
                    self._load_crm_option_combo(self.crm_product_type_combo, 'field_jv2dq__c')
                idx = self.crm_product_type_combo.findText(current_text)
                if idx >= 0:
                    self.crm_product_type_combo.setCurrentIndex(idx)
                else:
                    self.crm_product_type_combo.setCurrentIndex(0)
                self.crm_product_type_combo.blockSignals(False)

            if hasattr(self, 'crm_record_type_combo'):
                current_text = self.crm_record_type_combo.currentText()
                self.crm_record_type_combo.blockSignals(True)
                self.crm_record_type_combo.clear()
                self.crm_record_type_combo.addItem("全部", "")
                fixed_record_types = ["default__c", "record_0a1lw__c", "record_PglSw__c"]
                for opt in fixed_record_types:
                    self.crm_record_type_combo.addItem(opt, opt)
                idx = self.crm_record_type_combo.findText(current_text)
                if idx >= 0:
                    self.crm_record_type_combo.setCurrentIndex(idx)
                else:
                    self.crm_record_type_combo.setCurrentIndex(0)
                self.crm_record_type_combo.blockSignals(False)

            if hasattr(self, 'crm_creator_combo'):
                current_text = self.crm_creator_combo.currentText()
                self.crm_creator_combo.blockSignals(True)
                self.crm_creator_combo.clear()
                self.crm_creator_combo.addItem("全部", "")
                creator_options = fx_cfg.get('creator_options', [])
                for name in creator_options:
                    self.crm_creator_combo.addItem(name, name)
                idx = self.crm_creator_combo.findText(current_text)
                if idx >= 0:
                    self.crm_creator_combo.setCurrentIndex(idx)
                else:
                    self.crm_creator_combo.setCurrentIndex(0)
                self.crm_creator_combo.blockSignals(False)

        except Exception as e:
            print(f"刷新CRM筛选下拉框失败: {e}")


    def _get_crm_option_text(self, field_key, value):
        """根据字段key和value获取选项文本"""
        try:
            if not value:
                return ''
            field_data, _ = self._get_crm_option_mapping_entry(field_key)
            if isinstance(field_data, dict) and 'mappings' in field_data:
                mappings = field_data.get('mappings', {})
                return mappings.get(str(value), str(value))
            return str(value)
        except Exception as e:
            return str(value)


    def _get_crm_option_ids_by_texts(self, field_key, texts):
        """将选项显示文本解析回CRM原始ID，未命中时尽量避免把显示文本误当成ID提交给接口"""
        normalized_pairs = []
        for text in texts or []:
            raw_text = str(text).strip()
            normalized_text = self._normalize_product_match_text(raw_text)
            if raw_text and normalized_text:
                normalized_pairs.append((raw_text, normalized_text))

        if not normalized_pairs:
            return []

        field_data, resolved_field_key = self._get_crm_option_mapping_entry(field_key)
        if isinstance(field_data, dict) and 'mappings' in field_data:
            mappings = field_data.get('mappings', {}) or {}
        elif isinstance(field_data, dict):
            mappings = {k: v for k, v in field_data.items() if k != 'label'}
        else:
            mappings = {}

        resolved_ids = []
        matched_targets = set()
        for option_id, option_text in mappings.items():
            normalized_id = self._normalize_product_match_text(option_id)
            normalized_text = self._normalize_product_match_text(option_text)
            for raw_text, target in normalized_pairs:
                if target in (normalized_id, normalized_text):
                    option_id = str(option_id).strip()
                    if option_id and option_id not in resolved_ids:
                        resolved_ids.append(option_id)
                    matched_targets.add(target)

        if mappings:
            return resolved_ids

        for raw_text, target in normalized_pairs:
            # record_type 这类接口过滤字段必须传真实ID，不能把显示文本直接回传给接口。
            if target not in matched_targets and raw_text not in resolved_ids and resolved_field_key != 'record_type':
                resolved_ids.append(raw_text)

        return resolved_ids


    def _get_crm_option_ids_by_texts(self, field_key, texts):
        """将选项显示文本解析回CRM原始ID，未命中时尽量避免把显示文本误当成ID提交给接口"""
        normalized_pairs = []
        for text in texts or []:
            raw_text = str(text).strip()
            normalized_text = self._normalize_product_match_text(raw_text)
            if raw_text and normalized_text:
                normalized_pairs.append((raw_text, normalized_text))

        if not normalized_pairs:
            return []

        field_data, resolved_field_key = self._get_crm_option_mapping_entry(field_key)
        if isinstance(field_data, dict) and 'mappings' in field_data:
            mappings = field_data.get('mappings', {}) or {}
        elif isinstance(field_data, dict):
            mappings = {k: v for k, v in field_data.items() if k != 'label'}
        else:
            mappings = {}

        resolved_ids = []
        matched_targets = set()
        for option_id, option_text in mappings.items():
            normalized_id = self._normalize_product_match_text(option_id)
            normalized_text = self._normalize_product_match_text(option_text)
            for raw_text, target in normalized_pairs:
                if target in (normalized_id, normalized_text):
                    option_id = str(option_id).strip()
                    if option_id and option_id not in resolved_ids:
                        resolved_ids.append(option_id)
                    matched_targets.add(target)

        if mappings:
            return resolved_ids

        for raw_text, target in normalized_pairs:
            # record_type 这类接口过滤字段必须传真实ID，不能把显示文本直接回传给接口。
            if target not in matched_targets and raw_text not in resolved_ids and resolved_field_key != 'record_type':
                resolved_ids.append(raw_text)

        return resolved_ids

    def on_crm_local_filter_changed(self):
        """响应CRM本地过滤changed相关操作。"""
        self.crm_current_page = 1
        self._populate_crm_table()


    def on_crm_table_search(self):
        """响应CRM表格搜索相关操作。"""
        self._update_crm_filter_toggle_badge()
        self.crm_current_page = 1
        self._populate_crm_table()


    def _update_crm_search_input_mode(self):
        """[兼容层] 搜索字段下拉已移除，保留方法避免调用错误。"""
        pass


    def _open_crm_search_date_range(self):
        """打开搜索栏的日期范围选择弹窗"""
        btn = self.crm_search_date_btn
        dr = btn.property('crm_date_range') or {'start': None, 'end': None}
        dlg = QuickDatePickerDialog(
            start_date=dr.get('start'),
            end_date=dr.get('end'),
            parent=self
        )
        dlg.set_popup_anchor_widget(btn)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.start_date and dlg.end_date:
            new_range = {'start': dlg.start_date, 'end': dlg.end_date}
            btn.setProperty('crm_date_range', new_range)
            btn.setText(f"{dlg.start_date.toString('yyyy-MM-dd')} ~ {dlg.end_date.toString('yyyy-MM-dd')}")
            self.on_crm_table_search()

    # ===== CRM 多条件筛选辅助方法 =====


    @staticmethod
    def _get_crm_text_operators():
        """非日期字段的筛选操作符"""
        return [
            ("等于", "eq"),
            ("不等于", "ne"),
            ("包含", "contains"),
            ("不包含", "not_contains"),
            ("属于", "in"),
            ("不属于", "not_in"),
            ("为空（未填写）", "empty"),
            ("不为空", "not_empty"),
            ("开头是", "starts_with"),
            ("结尾是", "ends_with"),
        ]


    @staticmethod
    def _get_crm_date_operators():
        """日期字段的筛选操作符"""
        return [
            ("等于", "eq"),
            ("不等于", "ne"),
            ("早于", "date_before"),
            ("晚于", "date_after"),
            ("早于等于", "date_before_eq"),
            ("晚于等于", "date_after_eq"),
            ("为空（未填写）", "empty"),
            ("不为空", "not_empty"),
            ("时间段", "date_range"),
            ("过去N天内(不含当天)", "past_n_days_exclusive"),
            ("未来N天内(不含当天)", "future_n_days_exclusive"),
            ("过去N月内(不含当月)", "past_n_months_exclusive"),
            ("未来N月内(不含当月)", "future_n_months_exclusive"),
            ("过去N周内(不含当周)", "past_n_weeks_exclusive"),
            ("未来N周内(不含当周)", "future_n_weeks_exclusive"),
            ("过去N天内(含当天)", "past_n_days_inclusive"),
            ("未来N天内(含当天)", "future_n_days_inclusive"),
            ("过去N周内(含当周)", "past_n_weeks_inclusive"),
            ("未来N周内(含当周)", "future_n_weeks_inclusive"),
            ("过去N月内(含当月)", "past_n_months_inclusive"),
            ("未来N月内(含当月)", "future_n_months_inclusive"),
            ("N天前", "n_days_ago"),
            ("N天后", "n_days_later"),
            ("N周前", "n_weeks_ago"),
            ("N周后", "n_weeks_later"),
            ("过去N季度内(含当季度)", "past_n_quarters_inclusive"),
        ]


    def _is_crm_date_field(self, field_label):
        """判断字段名是否为日期/时间字段"""
        if not field_label:
            return False
        for key, label, is_time in getattr(self, 'CRM_ALL_FIELDS', []):
            if label == field_label and is_time:
                return True
        return False


    def _build_crm_field_label_list(self):
        """构建所有可用字段标签列表（特殊头 + CRM_ALL_FIELDS 标签去重）"""
        labels = []
        seen = set()
        for h in getattr(self, 'crm_special_headers', []):
            if h and h not in seen:
                labels.append(h)
                seen.add(h)
        for key, label, is_time in getattr(self, 'CRM_ALL_FIELDS', []):
            if label and label not in seen:
                labels.append(label)
                seen.add(label)
        return labels


    def _get_crm_api_key_for_label(self, label):
        """字段显示名 → API key"""
        for key, lbl, is_time in getattr(self, 'CRM_ALL_FIELDS', []):
            if lbl == label:
                return key
        if label in getattr(self, 'crm_special_headers', []):
            return label
        return label


    def _build_crm_row_search_text(self, row):
        """收集一行的所有字段值（含计算字段 + 选项字段显示文本），用于全字段模糊搜索"""
        parts = []
        option_fields = getattr(self, 'CRM_OPTION_FIELDS', {})
        for key, label, is_time in getattr(self, 'CRM_ALL_FIELDS', []):
            val = self._crm_extract_field(row, key)
            parts.append(str(val) if val is not None else '')
            # 选项字段追加显示文本，确保按中文选项值也能搜索到
            if key in option_fields:
                display = self._get_crm_option_text(key, row.get(key, ''))
                if display and display != str(val or ''):
                    parts.append(str(display))
        computed = []
        try:
            computed.append(str(self._get_crm_model_spec(row) or ''))
            computed.append(str(self._get_crm_customer_type(row) or ''))
            computed.append(str(self._get_crm_matched_price(row) or ''))
            computed.append(str(self._get_crm_discount_unit_price(row) or ''))
            computed.append(str(self._get_crm_product_remark(row) or ''))
            computed.append(str(self._convert_amount_to_rmb_upper(row.get('product_amount', '')) or ''))
        except Exception:
            pass
        parts.extend(computed)
        return ' '.join(parts).lower()


    @staticmethod
    def _crm_date_value_to_qdate(raw_value):
        """将 CRM 日期值（时间戳/字符串）归一化为 QDate"""
        if raw_value in (None, ''):
            return None
        try:
            from PyQt6.QtCore import QDate
            from datetime import datetime
            if isinstance(raw_value, (int, float)):
                raw_str = str(int(raw_value))
                ts = float(raw_value)
                if len(raw_str) >= 12:
                    ts = ts / 1000
                dt = datetime.fromtimestamp(ts)
                return QDate(dt.year, dt.month, dt.day)
            text = str(raw_value).strip()
            if text.isdigit():
                ts = float(text)
                if len(text) >= 12:
                    ts = ts / 1000
                dt = datetime.fromtimestamp(ts)
                return QDate(dt.year, dt.month, dt.day)
            dt = datetime.strptime(text[:10], '%Y-%m-%d')
            return QDate(dt.year, dt.month, dt.day)
        except Exception:
            return None


    # ────────────── AutoFilter 列头筛选 ──────────────────────────

    def _apply_crm_autofilter(self):
        """根据列头筛选器的筛选状态过滤 CRM 数据"""
        if not hasattr(self, 'crm_table_header') or not self.crm_table_header.is_filter_active():
            return
        state = self.crm_table_header.get_filter_state()
        column_map = dict(getattr(self, 'crm_column_index_map', {}))
        if not column_map:
            return
        filtered = []
        for row in self.crm_filtered_data:
            skip = False
            for display_col, excluded in state.items():
                if not excluded or display_col < 1:
                    continue
                api_key = column_map.get(display_col)
                if not api_key:
                    continue
                val = str(row.get(api_key, '') or '')
                if val in excluded:
                    skip = True
                    break
            if not skip:
                filtered.append(row)
        self.crm_filtered_data = filtered

    def _on_crm_filter_changed(self):
        """列头筛选器变化时回调"""
        self.crm_current_page = 1
        self._populate_crm_table()

    def _get_crm_autofilter_values(self, col):
        """data_provider：获取 CRM 表指定显示列的全部唯一值"""
        column_map = dict(getattr(self, 'crm_column_index_map', {}))
        api_key = column_map.get(col)
        if not api_key:
            return []
        values = set()
        for row in self.crm_filtered_data:
            values.add(str(row.get(api_key, '') or ''))
        return sorted(values)


    def _crm_row_matches_all_conditions(self, row, conditions):
        """判断 CRM 记录是否满足所有筛选条件（AND 逻辑）"""
        from PyQt6.QtCore import QDate
        import re
        for cond in (conditions or []):
            api_key = cond.get('api_key', cond.get('field', ''))
            operator = cond.get('operator', 'contains')
            expected = str(cond.get('value', '')).strip()

            # 获取实际值（特殊 header 使用计算值）
            if api_key in getattr(self, 'crm_special_headers', []):
                special_map = {
                    "模板选择": str(self._get_crm_model_spec(row) or ''),
                    "规格型号": str(self._get_crm_model_spec(row) or ''),
                    "客户类型": str(self._get_crm_customer_type(row) or ''),
                    "匹配价格": str(self._get_crm_matched_price(row) or ''),
                    "折扣单价": str(self._get_crm_discount_unit_price(row) or ''),
                    "产品备注": str(self._get_crm_product_remark(row) or ''),
                    "大写": str(self._convert_amount_to_rmb_upper(row.get('product_amount', '')) or ''),
                }
                actual = special_map.get(api_key, '')
            else:
                actual = str(self._crm_extract_field(row, api_key) or '')
                # 选项字段解析为显示文本
                if api_key in getattr(self, 'CRM_OPTION_FIELDS', {}):
                    actual = str(self._get_crm_option_text(api_key, row.get(api_key, '')) or actual)

            actual_stripped = actual.strip()
            actual_lower = actual_stripped.lower()
            expected_lower = expected.lower()
            values = [v.strip().lower() for v in re.split(r'[,，;；\n]+', expected) if v.strip()]

            # --- 文本/数值操作符 ---
            if operator == 'contains' and expected_lower not in actual_lower:
                return False
            if operator == 'not_contains' and expected_lower in actual_lower:
                return False
            if operator == 'in' and values and actual_lower not in values:
                return False
            if operator == 'not_in' and values and actual_lower in values:
                return False
            if operator == 'eq' and actual_lower != expected_lower:
                return False
            if operator == 'ne' and actual_lower == expected_lower:
                return False
            if operator == 'empty' and actual_stripped:
                return False
            if operator == 'not_empty' and not actual_stripped:
                return False
            if operator == 'starts_with' and not actual_lower.startswith(expected_lower):
                return False
            if operator == 'ends_with' and not actual_lower.endswith(expected_lower):
                return False
            if operator in ('gt', 'lt'):
                try:
                    a = float(actual_stripped.replace(',', ''))
                    e = float(expected.replace(',', ''))
                    if operator == 'gt' and a <= e:
                        return False
                    if operator == 'lt' and a >= e:
                        return False
                except (ValueError, TypeError):
                    return False

            # --- 日期操作符 ---
            if operator in ('eq', 'ne', 'date_before', 'date_after', 'date_before_eq', 'date_after_eq', 'date_range'):
                row_qdate = self._crm_date_value_to_qdate(actual_stripped)
                if row_qdate is None:
                    if operator == 'ne':
                        continue
                    return False

                if operator == 'date_range':
                    if '~' in expected:
                        parts = expected.split('~')
                        start_qdate = QDate.fromString(parts[0].strip(), "yyyy-MM-dd")
                        end_qdate = QDate.fromString(parts[1].strip(), "yyyy-MM-dd")
                        if start_qdate.isValid() and end_qdate.isValid():
                            if not (start_qdate <= row_qdate <= end_qdate):
                                return False
                else:
                    filter_qdate = QDate.fromString(expected[:10], "yyyy-MM-dd")
                    if not filter_qdate.isValid():
                        return False
                    if operator == 'eq' and row_qdate != filter_qdate:
                        return False
                    if operator == 'date_before' and not (row_qdate < filter_qdate):
                        return False
                    if operator == 'date_after' and not (row_qdate > filter_qdate):
                        return False
                    if operator == 'date_before_eq' and not (row_qdate <= filter_qdate):
                        return False
                    if operator == 'date_after_eq' and not (row_qdate >= filter_qdate):
                        return False

            # --- N天/N周/N月/季度相对日期操作符 ---
            n_type_ops = (
                'past_n_days_exclusive', 'future_n_days_exclusive',
                'past_n_months_exclusive', 'future_n_months_exclusive',
                'past_n_weeks_exclusive', 'future_n_weeks_exclusive',
                'past_n_days_inclusive', 'future_n_days_inclusive',
                'past_n_weeks_inclusive', 'future_n_weeks_inclusive',
                'past_n_months_inclusive', 'future_n_months_inclusive',
                'n_days_ago', 'n_days_later',
                'n_weeks_ago', 'n_weeks_later',
                'past_n_quarters_inclusive',
            )
            if operator in n_type_ops:
                row_qdate = self._crm_date_value_to_qdate(actual_stripped)
                if row_qdate is None:
                    return False
                try:
                    n = int(expected)
                except (ValueError, TypeError):
                    return False
                today = QDate.currentDate()

                if operator == 'past_n_days_exclusive':
                    start = today.addDays(-n)
                    if not (start <= row_qdate < today):
                        return False
                elif operator == 'future_n_days_exclusive':
                    end = today.addDays(n)
                    if not (today < row_qdate <= end):
                        return False
                elif operator == 'past_n_days_inclusive':
                    start = today.addDays(-n)
                    if not (start <= row_qdate <= today):
                        return False
                elif operator == 'future_n_days_inclusive':
                    end = today.addDays(n)
                    if not (today <= row_qdate <= end):
                        return False
                elif operator == 'n_days_ago':
                    target = today.addDays(-n)
                    if not (row_qdate <= target):
                        return False
                elif operator == 'n_days_later':
                    target = today.addDays(n)
                    if not (row_qdate >= target):
                        return False
                elif operator in ('past_n_months_exclusive',):
                    start = today.addMonths(-n)
                    if not (start <= row_qdate < today):
                        return False
                elif operator in ('future_n_months_exclusive',):
                    end = today.addMonths(n)
                    if not (today < row_qdate <= end):
                        return False
                elif operator in ('past_n_months_inclusive',):
                    start = today.addMonths(-n)
                    if not (start <= row_qdate <= today):
                        return False
                elif operator in ('future_n_months_inclusive',):
                    end = today.addMonths(n)
                    if not (today <= row_qdate <= end):
                        return False
                elif operator in ('past_n_weeks_exclusive',):
                    start = today.addDays(-n * 7)
                    if not (start <= row_qdate < today):
                        return False
                elif operator in ('future_n_weeks_exclusive',):
                    end = today.addDays(n * 7)
                    if not (today < row_qdate <= end):
                        return False
                elif operator in ('past_n_weeks_inclusive',):
                    start = today.addDays(-n * 7)
                    if not (start <= row_qdate <= today):
                        return False
                elif operator in ('future_n_weeks_inclusive',):
                    end = today.addDays(n * 7)
                    if not (today <= row_qdate <= end):
                        return False
                elif operator == 'n_weeks_ago':
                    target = today.addDays(-n * 7)
                    if not (row_qdate <= target):
                        return False
                elif operator == 'n_weeks_later':
                    target = today.addDays(n * 7)
                    if not (row_qdate >= target):
                        return False
                elif operator == 'past_n_quarters_inclusive':
                    start = today.addMonths(-n * 3)
                    if not (start <= row_qdate <= today):
                        return False

        return True

    # ===== CRM 多条件筛选行管理 =====


    # ──────────────────────────────────────────────────────────
    # CRM 筛选条件行 — 委托给 FilterPanel
    # ──────────────────────────────────────────────────────────

    def _add_crm_condition_row(self, condition=None):
        """添加一条筛选条件（委托给 FilterPanel）。"""
        if hasattr(self, '_crm_filter_panel'):
            row = self._crm_filter_panel.add_row(condition)
            row.filtersChanged.connect(self.on_crm_local_filter_changed)
            if row.expose_check:
                row.expose_check.toggled.connect(
                    lambda: self._refresh_crm_exposed_tags())
            return row

    def _remove_crm_condition_row(self, row_info):
        """移除一条筛选条件（委托给 FilterPanel）。"""
        if hasattr(self, '_crm_filter_panel'):
            if isinstance(row_info, FilterConditionRow):
                self._crm_filter_panel.remove_row(row_info)
            elif isinstance(row_info, dict) and 'row' in row_info:
                self._crm_filter_panel.remove_row(row_info['row'])
        self._update_crm_filter_toggle_badge()
        self._refresh_crm_exposed_tags()
        self.on_crm_local_filter_changed()

    def _clear_all_crm_conditions(self):
        """清除所有条件（委托）。"""
        if hasattr(self, '_crm_filter_panel'):
            self._crm_filter_panel.clear_all()
            self._crm_filter_panel.set_panel_visible(False)

    def _clear_all_crm_conditions_and_search(self):
        """清除筛选条件 + 搜索框。"""
        self._clear_all_crm_conditions()
        if hasattr(self, 'crm_search_input'):
            self.crm_search_input.clear()
        self._update_crm_filter_toggle_badge()
        self._refresh_crm_exposed_tags()
        self.on_crm_local_filter_changed()

    def _collect_crm_filter_conditions(self):
        """收集当前所有筛选条件（委托 + 添加 api_key）。"""
        if hasattr(self, '_crm_filter_panel'):
            raw = self._crm_filter_panel.get_all_conditions()
        else:
            raw = []
        conditions = []
        for cond in raw:
            api_key = self._get_crm_api_key_for_label(cond['field'])
            conditions.append({
                'field': cond['field'],
                'api_key': api_key,
                'operator': cond['operator'],
                'value': cond['value'],
                'expose': cond.get('expose', False),
            })
        return conditions

    def _apply_crm_filter_and_close(self):
        """应用筛选条件并关闭弹窗。"""
        self.on_crm_local_filter_changed()
        self._refresh_crm_exposed_tags()
        if hasattr(self, '_crm_filter_panel'):
            self._crm_filter_panel.set_panel_visible(False)

    def _toggle_crm_filter_panel(self):
        """切换筛选面板 — 以独立弹窗形式弹出在原位置。"""
        if not hasattr(self, '_crm_filter_panel'):
            return

        panel = self._crm_filter_panel._panel_frame
        visible = panel.isVisible()

        if not visible:
            # 动态调整高度
            self._crm_filter_panel._adjust_panel_height()

            # 将 panel_frame 提升为独立窗口弹窗
            panel.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            panel.setVisible(True)
            panel.raise_()
            panel.activateWindow()

            # 定位在筛选按钮下方
            p = self.crm_filter_toggle_btn.mapToGlobal(
                QPoint(0, self.crm_filter_toggle_btn.height()))
            x, y = p.x(), p.y() + 4

            screen = self.screen()
            if screen:
                geo = screen.availableGeometry()
                x = max(geo.x() + 10, min(x, geo.right() - panel.width() - 10))
                y = max(geo.y() + 10, min(y, geo.bottom() - panel.height() - 10))
            panel.move(x, y)

            # 点击外部关闭事件过滤器
            if not hasattr(self, '_crm_panel_outside_filter'):
                panel.reject = lambda: panel.hide()
                self._crm_panel_outside_filter = common._DialogOutsideCloseFilter(panel)
            panel._outside_close_armed = False
            app = QApplication.instance()
            if app:
                app.installEventFilter(self._crm_panel_outside_filter)
            QTimer.singleShot(200, lambda: (
                setattr(panel, '_outside_close_armed', True)
                if not panel.isHidden() else None
            ))
        else:
            panel.hide()
            app = QApplication.instance()
            if app and hasattr(self, '_crm_panel_outside_filter'):
                app.removeEventFilter(self._crm_panel_outside_filter)
            panel._outside_close_armed = False

        self._update_crm_filter_toggle_badge()

    def _update_crm_filter_toggle_badge(self):
        """更新筛选按钮上的计数徽标（委托）。"""
        if hasattr(self, '_crm_filter_panel'):
            self._crm_filter_panel._update_toggle_badge()

    def _update_crm_condition_input_mode(self, row_info):
        """[兼容层] FilterConditionRow 内部已处理输入模式切换，此方法保留为空。"""
        pass

    def _refresh_crm_exposed_tags(self):
        """刷新外露标签（使用 ExposedTagsBar）。"""
        if not hasattr(self, '_crm_exposed_tags_bar'):
            # 创建 ExposedTagsBar 实例
            self._crm_exposed_tags_bar = ExposedTagsBar(
                self, max_tag_text_length=4, max_tag_value_length=8)
            self._crm_exposed_tags_bar.tagRemoved.connect(
                self._on_crm_exposed_tag_removed)
            # 将 ExposedTagsBar 插入到 exposed_tags_frame 中
            if hasattr(self, 'crm_exposed_tags_frame'):
                old_layout = self.crm_exposed_tags_frame.layout()
                if old_layout:
                    # 清除旧 layout 中的内容
                    while old_layout.count():
                        item = old_layout.takeAt(0)
                        if item.widget():
                            item.widget().setParent(None)
                    old_layout.addWidget(self._crm_exposed_tags_bar)
        if hasattr(self, '_crm_exposed_tags_bar'):
            conds = (self._crm_filter_panel.get_all_conditions()
                     if hasattr(self, '_crm_filter_panel') else [])
            self._crm_exposed_tags_bar.refresh(conds)

    def _on_crm_exposed_tag_removed(self, cond):
        """外露标签被移除时的回调。"""
        if hasattr(self, '_crm_filter_panel'):
            self._crm_filter_panel._on_exposed_tag_removed(cond)


    def _install_crm_filter_outside_close(self):
        """[兼容层] 由 FilterPanel 内部管理，保留空方法避免调用错误。"""
        pass

    def _remove_crm_filter_outside_close(self):
        """[兼容层] 由 FilterPanel 内部管理，保留空方法避免调用错误。"""
        pass


    def _open_crm_condition_date_range(self, btn):
        """点击条件行中的时间段按钮，打开日期范围选择弹窗"""
        dr = btn.property('crm_date_range') or {'start': None, 'end': None}
        dlg = QuickDatePickerDialog(
            start_date=dr.get('start'),
            end_date=dr.get('end'),
            parent=self
        )
        dlg.set_popup_anchor_widget(btn)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.start_date and dlg.end_date:
            new_range = {'start': dlg.start_date, 'end': dlg.end_date}
            btn.setProperty('crm_date_range', new_range)
            btn.setText(f"{dlg.start_date.toString('yyyy-MM-dd')} ~ {dlg.end_date.toString('yyyy-MM-dd')}")
            self.on_crm_local_filter_changed()

    # ===== CRM 筛选方案管理 =====


    def _save_crm_filter_preset(self, name=None):
        """保存当前筛选条件和字段显示设置为方案"""
        # clicked 信号会传 checked:bool，忽略非字符串的 name
        if not isinstance(name, str):
            name = None
        conditions = self._collect_crm_filter_conditions()
        if name is None:
            name, ok = frameless_input_text(self, "保存筛选方案", "请输入方案名称：")
            if not ok or not name or not name.strip():
                return
        name = name.strip()
        # 收集当前可见列和顺序（排除固定列如复选框）
        column_visibility = {}  # {col_name: True/False}
        column_order = []       # [col_name, ...] 按当前顺序
        fixed_headers = set(getattr(self, 'crm_fixed_headers', [""]))
        if hasattr(self, 'crm_table'):
            header = self.crm_table.horizontalHeader()
            for vis_idx in range(header.count()):
                logical_idx = header.logicalIndex(vis_idx)
                header_item = self.crm_table.horizontalHeaderItem(logical_idx)
                if header_item:
                    col_name = header_item.text().strip()
                    if col_name in fixed_headers:
                        continue
                    is_hidden = self.crm_table.isColumnHidden(logical_idx)
                    column_visibility[col_name] = not is_hidden
                    column_order.append(col_name)
        preset_data = {
            'name': name,
            'conditions': conditions,
            'column_visibility': column_visibility,
            'column_order': column_order,
        }
        fx_cfg = self.config.setdefault('fxiaoke', {})
        presets = fx_cfg.get('crm_filter_presets', [])
        if not isinstance(presets, list):
            presets = []
        existing_idx = next((i for i, p in enumerate(presets) if p.get('name') == name), None)
        if existing_idx is not None:
            presets[existing_idx] = preset_data
        else:
            presets.append(preset_data)
        fx_cfg['crm_filter_presets'] = presets
        save_config(self.config)
        self._crm_active_preset_name = name
        self._update_crm_preset_btn_label()
        if name is None:
            frameless_message_box(self, '成功', f'方案「{name}」已保存。')


    def _load_crm_filter_preset(self, preset_name=None):
        """加载选中的筛选方案（筛选条件 + 字段显示设置）"""
        if not isinstance(preset_name, str) or not preset_name:
            return
        presets = self.config.get('fxiaoke', {}).get('crm_filter_presets', [])
        if not isinstance(presets, list):
            return
        target = next((p for p in presets if p.get('name') == preset_name), None)
        if not target:
            return
        conditions = target.get('conditions', [])
        self._clear_all_crm_conditions()
        for cond in conditions:
            self._add_crm_condition_row(cond)
        # 恢复字段显示设置和顺序：直接更新运行时状态并重建表格列
        column_visibility = target.get('column_visibility', {})
        column_order = target.get('column_order', [])
        if column_order and hasattr(self, 'crm_table'):
            # 更新运行时状态（排除固定列如复选框列）
            fixed = getattr(self, 'crm_fixed_headers', [""])
            self.crm_header_order = list(column_order)
            self.crm_visible_headers = [n for n in column_order
                                        if n not in fixed and column_visibility.get(n, True)]
            # 重建表格列（包含正确的顺序和可见性）
            self._apply_crm_table_columns()
        elif column_visibility and hasattr(self, 'crm_table'):
            for col in range(self.crm_table.columnCount()):
                header_item = self.crm_table.horizontalHeaderItem(col)
                if header_item:
                    col_name = header_item.text().strip()
                    if col_name in column_visibility:
                        self.crm_table.setColumnHidden(col, not column_visibility[col_name])
        self.on_crm_local_filter_changed()


    def _delete_crm_filter_preset(self, preset_name=None):
        """删除指定筛选方案"""
        if not preset_name:
            preset_name = getattr(self, '_crm_active_preset_name', None)
        if not preset_name:
            frameless_message_box(self, "提示", "请先在方案列表中选择一个方案。")
            return
        presets = self.config.get('fxiaoke', {}).get('crm_filter_presets', [])
        if not isinstance(presets, list):
            return
        idx = next((i for i, p in enumerate(presets) if p.get('name') == preset_name), None)
        if idx is None:
            return
        reply = frameless_message_box(self, '确认删除', f'确定删除方案「{preset_name}」吗？', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        presets.pop(idx)
        self.config.setdefault('fxiaoke', {})['crm_filter_presets'] = presets
        # 如果删除的是默认方案，清除默认
        if self.config.get('fxiaoke', {}).get('crm_filter_default_preset') == preset_name:
            self.config['fxiaoke']['crm_filter_default_preset'] = ''
        save_config(self.config)
        self._crm_active_preset_name = None
        self._update_crm_preset_btn_label()


    def _update_crm_preset_btn_label(self):
        """更新方案按钮文字"""
        if not hasattr(self, 'crm_filter_preset_btn'):
            return
        name = getattr(self, '_crm_active_preset_name', None)
        if name:
            self.crm_filter_preset_btn.setText(f"{name} ▼")
        else:
            self.crm_filter_preset_btn.setText("方案 ▼")


    def _show_crm_filter_preset_popup(self):
        """弹出方案选择面板（含操作按钮）"""
        presets = self.config.get('fxiaoke', {}).get('crm_filter_presets', [])
        if not isinstance(presets, list):
            presets = []
        default_name = self.config.get('fxiaoke', {}).get('crm_filter_default_preset', '')

        popup = QFrame()
        popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setStyleSheet("QFrame { border: 1px solid #D9D9D9; border-radius: 4px; background: #FFF; }")
        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(4, 4, 4, 4)
        popup_layout.setSpacing(2)

        # "(未选择)" 项
        none_btn = QPushButton("(未选择)")
        none_btn.setFixedHeight(28)
        none_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        none_btn.setStyleSheet("QPushButton { border: none; text-align: left; padding: 4px 8px; font-size: 12px; color: #999; background: transparent; } QPushButton:hover { background: #F5F5F5; }")
        none_btn.clicked.connect(lambda: [self._clear_all_crm_conditions(), self.on_crm_local_filter_changed(), setattr(self, '_crm_active_preset_name', None), self._update_crm_preset_btn_label(), popup.close()])
        popup_layout.addWidget(none_btn)

        for preset in presets:
            name = preset.get('name', '')
            display = f"★ {name}" if name == default_name else name
            row = QFrame()
            row.setFixedHeight(30)
            row.setStyleSheet("QFrame { border: none; background: transparent; }")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            # 方案名按钮（点击加载）
            load_btn = QPushButton(display)
            load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            load_btn.setStyleSheet("QPushButton { border: none; text-align: left; padding: 4px 8px; font-size: 12px; color: #333; background: transparent; } QPushButton:hover { background: #E6F7FF; color: #1890FF; }")
            load_btn.clicked.connect(lambda checked, n=name: [setattr(self, '_crm_active_preset_name', n), self._load_crm_filter_preset(n), self._update_crm_preset_btn_label(), popup.close()])
            row_layout.addWidget(load_btn, stretch=1)

            icon_style = """
                QPushButton { border: none; border-radius: 2px; font-size: 13px; background: transparent; color: #999; }
                QPushButton:hover { background: #E6F7FF; color: #1890FF; }
            """
            # 修改按钮（✎）
            mod_btn = QPushButton("✎")
            mod_btn.setFixedSize(22, 22)
            mod_btn.setStyleSheet(icon_style)
            mod_btn.setToolTip(f"用当前筛选+字段覆盖「{name}」")
            mod_btn.clicked.connect(lambda checked, n=name: [self._update_crm_filter_preset(n), popup.close()])
            row_layout.addWidget(mod_btn)
            # 默认按钮（★）
            def_btn = QPushButton("★")
            def_btn.setFixedSize(22, 22)
            if name == default_name:
                def_btn.setStyleSheet("QPushButton { border: none; border-radius: 2px; font-size: 13px; background: transparent; color: #FA8C16; } QPushButton:hover { background: #FFF7E6; color: #FA8C16; }")
            else:
                def_btn.setStyleSheet(icon_style)
            def_btn.setToolTip(f"设置/取消「{name}」为默认方案")
            def_btn.clicked.connect(lambda checked, n=name: [self._set_crm_filter_default_preset(n), popup.close(), self._update_crm_preset_btn_label()])
            row_layout.addWidget(def_btn)
            # 删除按钮（✕）
            del_btn = QPushButton("✕")
            del_btn.setFixedSize(22, 22)
            del_btn.setStyleSheet(icon_style + "QPushButton:hover { background: #FFF2F0; color: #FF4D4F; }")
            del_btn.setToolTip(f"删除「{name}」")
            del_btn.clicked.connect(lambda checked, n=name: [self._delete_crm_filter_preset(n), popup.close(), self._update_crm_preset_btn_label()])
            row_layout.addWidget(del_btn)

            popup_layout.addWidget(row)

        popup.adjustSize()
        # 定位在按钮下方
        btn_pos = self.crm_filter_preset_btn.mapToGlobal(QPoint(0, self.crm_filter_preset_btn.height()))
        popup.move(btn_pos.x(), btn_pos.y() + 2)
        # 点击外部关闭
        popup.reject = popup.close
        popup._outside_close_armed = False
        pf = common._DialogOutsideCloseFilter(popup)
        popup._outside_filter = pf
        QApplication.instance().installEventFilter(pf)
        QTimer.singleShot(0, lambda p=popup: setattr(p, '_outside_close_armed', True))
        popup.destroyed.connect(lambda obj, f=pf: QApplication.instance().removeEventFilter(f))
        popup.show()
        self._crm_preset_popup = popup


    def _update_crm_filter_preset(self, preset_name=None):
        """用当前筛选条件和字段设置覆盖指定方案"""
        if not preset_name:
            preset_name = getattr(self, '_crm_active_preset_name', None)
        if not preset_name:
            frameless_message_box(self, "提示", "请先在方案列表中选择一个方案。")
            return
        presets = self.config.get('fxiaoke', {}).get('crm_filter_presets', [])
        if not isinstance(presets, list):
            return
        old_idx = next((i for i, p in enumerate(presets) if p.get('name') == preset_name), None)
        if old_idx is None:
            return
        # 收集当前条件
        conditions = self._collect_crm_filter_conditions()
        # 收集当前字段设置
        column_visibility = {}
        column_order = []
        fixed_headers = set(getattr(self, 'crm_fixed_headers', [""]))
        if hasattr(self, 'crm_table'):
            header = self.crm_table.horizontalHeader()
            for vis_idx in range(header.count()):
                logical_idx = header.logicalIndex(vis_idx)
                header_item = self.crm_table.horizontalHeaderItem(logical_idx)
                if header_item:
                    col_name = header_item.text().strip()
                    if col_name in fixed_headers:
                        continue
                    is_hidden = self.crm_table.isColumnHidden(logical_idx)
                    column_visibility[col_name] = not is_hidden
                    column_order.append(col_name)
        # 覆盖保存
        presets[old_idx] = {
            'name': preset_name,
            'conditions': conditions,
            'column_visibility': column_visibility,
            'column_order': column_order,
        }
        self.config.setdefault('fxiaoke', {})['crm_filter_presets'] = presets
        save_config(self.config)
        frameless_message_box(self, "成功", f"方案「{preset_name}」已更新。")


    def _set_crm_filter_default_preset(self, preset_name=None):
        """切换默认方案：已是默认则取消，否则设为默认"""
        if not preset_name:
            preset_name = getattr(self, '_crm_active_preset_name', None)
        if not preset_name:
            frameless_message_box(self, "提示", "请先在方案列表中选择一个方案。")
            return
        current_default = self.config.get('fxiaoke', {}).get('crm_filter_default_preset', '')
        if current_default == preset_name:
            self.config.setdefault('fxiaoke', {})['crm_filter_default_preset'] = ''
            save_config(self.config)
            self._update_crm_preset_btn_label()
        else:
            presets = self.config.get('fxiaoke', {}).get('crm_filter_presets', [])
            if not isinstance(presets, list) or not any(p.get('name') == preset_name for p in presets):
                frameless_message_box(self, "提示", "请先在方案列表中选择一个方案。")
                return
            self.config.setdefault('fxiaoke', {})['crm_filter_default_preset'] = preset_name
            save_config(self.config)
            self._update_crm_preset_btn_label()


    def _rename_crm_filter_preset(self, preset_name=None):
        """重命名指定方案"""
        if not preset_name:
            preset_name = getattr(self, '_crm_active_preset_name', None)
        if not preset_name:
            frameless_message_box(self, "提示", "请先在方案列表中选择一个方案。")
            return
        presets = self.config.get('fxiaoke', {}).get('crm_filter_presets', [])
        if not isinstance(presets, list):
            return
        idx = next((i for i, p in enumerate(presets) if p.get('name') == preset_name), None)
        if idx is None:
            return
        old_name = presets[idx].get('name', '')
        new_name, ok = frameless_input_text(self, "重命名方案", "请输入新名称：", old_name)
        if not ok or not new_name or not new_name.strip():
            return
        new_name = new_name.strip()
        # 更新方案名
        presets[idx]['name'] = new_name
        self.config.setdefault('fxiaoke', {})['crm_filter_presets'] = presets
        # 更新默认方案引用
        if self.config.get('fxiaoke', {}).get('crm_filter_default_preset') == old_name:
            self.config['fxiaoke']['crm_filter_default_preset'] = new_name
        save_config(self.config)
        self._crm_active_preset_name = new_name
        self._update_crm_preset_btn_label()  # was _refresh_crm_filter_preset_combo(new_name)

    # ===== 构建新筛选栏 UI =====


    def _build_crm_filter_bar(self):
        """构建 CRM 多条件筛选栏，返回 QVBoxLayout"""
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        from PyQt6.QtCore import Qt

        filter_bar_layout = QVBoxLayout()
        filter_bar_layout.setSpacing(6)

        # ===== 第一行：筛选按钮 + 搜索 + 方案管理 + 操作按钮 =====
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        # 筛选按钮（带计数徽标）- 移到搜索框前面
        self.crm_filter_toggle_btn = QPushButton("筛选")
        self.crm_filter_toggle_btn.setFixedHeight(32)
        self.crm_filter_toggle_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 4px 14px; font-size: 13px;
                background-color: #FFFFFF; color: #333;
            }
            QPushButton:hover { border-color: #1890FF; color: #1890FF; }
        """)
        self.crm_filter_toggle_btn.clicked.connect(self._toggle_crm_filter_panel)

        # 方案选择按钮（点击弹出方案列表）
        self.crm_filter_preset_btn = QPushButton("方案 ▼")
        self.crm_filter_preset_btn.setFixedHeight(30)
        self.crm_filter_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.crm_filter_preset_btn.setToolTip("选择筛选方案")
        self.crm_filter_preset_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 2px 10px; font-size: 12px; color: #333;
                background-color: #FFFFFF;
            }
            QPushButton:hover { border-color: #1890FF; color: #1890FF; }
        """)
        self.crm_filter_preset_btn.clicked.connect(self._show_crm_filter_preset_popup)
        self._crm_active_preset_name = None
        self._update_crm_preset_btn_label()
        top_row.addWidget(self.crm_filter_preset_btn)
        top_row.addWidget(self.crm_filter_toggle_btn)

        top_row.addSpacing(6)

        # 搜索框
        search_frame = QFrame()
        search_frame.setFixedHeight(32)
        search_frame.setMaximumWidth(280)
        search_frame.setStyleSheet("""
            QFrame {
                border: 1px solid #D9D9D9; border-radius: 4px;
                background-color: #FFFFFF;
            }
            QFrame:focus-within { border-color: #1890FF; }
        """)
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)

        # 搜索输入区域（文本搜索）
        self.crm_search_input = QLineEdit()
        self.crm_search_input.setPlaceholderText("搜索")
        self.crm_search_input.setFixedHeight(30)
        self.crm_search_input.setStyleSheet("""
            QLineEdit {
                border: none; background: transparent;
                padding: 2px 8px; font-size: 13px;
            }
        """)
        self.crm_search_input.textChanged.connect(self.on_crm_table_search)
        search_layout.addWidget(self.crm_search_input, stretch=1)

        # 保留兼容（不再显示日期搜索）
        self.crm_search_date_btn = QPushButton("")
        self.crm_search_date_btn.setFixedHeight(0)
        self.crm_search_date_btn.setMaximumWidth(0)
        self.crm_search_date_btn.hide()
        self.crm_search_date_btn.setProperty('crm_date_range', {'start': None, 'end': None})
        self.crm_search_stack = QStackedWidget()
        self.crm_search_stack.setMaximumWidth(0)
        self.crm_search_stack.hide()

        top_row.addWidget(search_frame)
        top_row.addStretch()

        # ✅ CRM输出格式选择
        keep_crm_format = self.config.get('app_settings', {}).get('keep_crm_output_format', 'word_pdf')
        self.crm_keep_format_combo = QComboBox()
        self.crm_keep_format_combo.addItems(["Word+PDF", "Word", "PDF"])
        crm_fmt_map = {"word_pdf": "Word+PDF", "word": "Word", "pdf": "PDF"}
        self.crm_keep_format_combo.setCurrentText(crm_fmt_map.get(keep_crm_format, "Word+PDF"))
        core._keep_crm_word_override = keep_crm_format  # 同步全局变量，避免延迟加载不一致
        self.crm_keep_format_combo.setFixedWidth(110)
        self.crm_keep_format_combo.setToolTip("生成后保留的文件格式")
        self.crm_keep_format_combo.currentIndexChanged.connect(self.on_crm_keep_format_changed)
        top_row.addWidget(self.crm_keep_format_combo)

        top_row.addSpacing(10)

        self.crm_column_settings_btn = QPushButton("字段显示")
        self.crm_column_settings_btn.setFixedWidth(80)
        self.crm_column_settings_btn.setFixedHeight(30)
        self.crm_column_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.crm_column_settings_btn.clicked.connect(self.open_crm_field_settings_dialog)
        top_row.addWidget(self.crm_column_settings_btn)

        top_row.addSpacing(6)

        self.crm_refresh_btn = QPushButton("⟳ 刷新")  #CRM刷新
        self.crm_refresh_btn.setFixedSize(self._scaled_ui_value(104, minimum=98), self._scaled_ui_value(30, minimum=28))
        self.crm_refresh_btn.setToolTip("刷新数据")
        self.crm_refresh_btn.setStyleSheet(get_compact_refresh_button_style(self.ui_scale_percent))
        self.crm_refresh_btn.clicked.connect(self._on_crm_refresh_btn_clicked)
        top_row.addWidget(self.crm_refresh_btn)

        top_row.addSpacing(6)

        self.crm_generate_btn = QPushButton("生成合同")
        self.crm_generate_btn.setMinimumWidth(76)
        self.crm_generate_btn.setFixedHeight(30)
        self.crm_generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF8C00; color: #FFFFFF; border: none;
                border-radius: 4px; font-size: 13px; font-weight: 600;
                padding: 4px 16px;
            }
            QPushButton:hover { background-color: #E67A00; }
        """)
        self.crm_generate_btn.clicked.connect(self.on_generate_crm_contracts)
        top_row.addWidget(self.crm_generate_btn)

        filter_bar_layout.addLayout(top_row)

        # ===== 外露筛选条件标签栏（显示在搜索框下方） =====
        self.crm_exposed_tags_frame = QFrame()
        self.crm_exposed_tags_frame.setVisible(False)
        self.crm_exposed_tags_frame.setStyleSheet("QFrame { background-color: transparent; border: none; }")
        self.crm_exposed_tags_layout = QHBoxLayout(self.crm_exposed_tags_frame)
        self.crm_exposed_tags_layout.setContentsMargins(0, 2, 0, 2)
        self.crm_exposed_tags_layout.setSpacing(6)
        self.crm_exposed_tags_layout.addStretch()
        filter_bar_layout.addWidget(self.crm_exposed_tags_frame)

        # ===== 筛选条件面板（使用公共 FilterPanel） =====
        all_fields = self._build_crm_field_label_list()
        field_options = [(label, label) for label in all_fields]

        self._crm_filter_panel = FilterPanel(
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
            apply_btn_text="筛 选",
            clear_btn_text="清除筛选值",
            save_btn_text="另存为",
            toggle_btn=self.crm_filter_toggle_btn,
            toggle_badge=True,
            row_defaults={
                'field_options': field_options,
                'field_width': 150,
                'text_operators': self._get_crm_text_operators(),
                'date_operators': self._get_crm_date_operators(),
                'op_width': 105,
                'default_operator': 'contains',
                'value_pages': ('text', 'date', 'date_range', 'spin'),
                'show_expose': True,
                'show_picker': False,
                'show_remove': True,
                'debounce_ms': 200,
                'is_date_field_cb': self._is_crm_date_field,
            },
            on_apply=lambda panel: self._apply_crm_filter_and_close(),
        )
        # 覆写「保存」和「清除」按钮回调
        self._crm_filter_panel._on_save_preset = lambda panel: self._save_crm_filter_preset()
        self._crm_filter_panel._on_clear = lambda panel: self._clear_all_crm_conditions_and_search()

        # 兼容旧变量名
        self.crm_filter_panel = self._crm_filter_panel._panel_frame
        self.crm_condition_rows = self._crm_filter_panel._legacy_rows
        self.crm_conditions_layout = self._crm_filter_panel._rows_layout
        filter_bar_layout.addWidget(self._crm_filter_panel)

        return filter_bar_layout


    def on_crm_prev_page(self):
        """响应CRM上一页页码相关操作。"""
        if self.crm_current_page > 1:
            self.crm_current_page -= 1
            self._populate_crm_table()


    def on_crm_next_page(self):
        """响应CRM下一页页码相关操作。"""
        max_page = max(1, (len(self.crm_filtered_data) + self.crm_page_size - 1) // self.crm_page_size) if self.crm_filtered_data else 1
        if self.crm_current_page < max_page:
            self.crm_current_page += 1
            self._populate_crm_table()


    def on_crm_page_size_changed(self):
        """响应CRM页码大小changed相关操作。"""
        self.crm_page_size = self._get_combo_page_size(self.crm_page_size_combo)
        self.crm_current_page = 1
        self._save_page_sizes()
        self._populate_crm_table()


    def _on_opp_prev_page(self):
        """商机列表上一页"""
        if self.opportunity_current_page > 1:
            self.opportunity_current_page -= 1
            self._populate_opportunity_table()


    def _on_opp_next_page(self):
        """商机列表下一页"""
        data = getattr(self, 'opportunity_filtered_data', []) or getattr(self, 'opportunity_all_data', [])
        max_page = max(1, (len(data) + self.opportunity_page_size - 1) // self.opportunity_page_size) if data else 1
        if self.opportunity_current_page < max_page:
            self.opportunity_current_page += 1
            self._populate_opportunity_table()


    def _on_opp_page_size_changed(self):
        """商机列表每页条数变更"""
        self.opportunity_page_size = self._get_combo_page_size(self.opportunity_page_size_combo)
        self.opportunity_current_page = 1
        self._save_page_sizes()
        self._populate_opportunity_table()


    def on_crm_page_spin_changed(self, value):
        """响应CRM页码微调框changed相关操作。"""
        max_page = (len(self.crm_filtered_data) + self.crm_page_size - 1) // self.crm_page_size if self.crm_filtered_data else 1
        if 1 <= value <= max_page:
            self.crm_current_page = value
            self._populate_crm_table()


    def _get_crm_special_column_formats(self, config=None):
        """读取CRM字段格式配置"""
        config = config or load_config()
        special_config = config.get('business_rules', {}).get('crm_special_columns', [])
        format_dict = {}

        if isinstance(special_config, list):
            if special_config and isinstance(special_config[0], dict):
                for column in special_config:
                    if isinstance(column, dict) and column.get('name'):
                        format_dict[str(column['name']).strip()] = str(column.get('format', '{}') or '{}')
            else:
                for column in special_config:
                    column_name = str(column or '').strip()
                    if column_name:
                        format_dict[column_name] = "{}"
        elif isinstance(special_config, dict):
            for name, fmt in special_config.items():
                column_name = str(name or '').strip()
                if column_name:
                    format_dict[column_name] = str(fmt or '{}')

        return format_dict


    def _format_crm_timestamp_text(self, value):
        """将CRM时间戳转为可读文本"""
        if value in ("", None):
            return ""

        try:
            raw_value = value
            if isinstance(raw_value, str):
                raw_value = raw_value.strip()
                if not raw_value:
                    return ""
                if raw_value.isdigit():
                    raw_value = int(raw_value)
                else:
                    return raw_value

            if isinstance(raw_value, (int, float)):
                if raw_value > 1e12:
                    return datetime.fromtimestamp(raw_value / 1000).strftime('%Y-%m-%d')
                if raw_value > 1e9:
                    return datetime.fromtimestamp(raw_value).strftime('%Y-%m-%d')
        except Exception:
            pass

        return str(value).strip()


    def _join_crm_unique_texts(self, values, separator='、'):
        """按顺序去重拼接CRM文本值"""
        result = []
        seen = set()
        for value in values or []:
            text = str(value or '').strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return separator.join(result)


    def _normalize_crm_numeric_value(self, value):
        """尽量避免把整数显示成 x.0"""
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value


    def _get_selected_crm_template_name(self, order, row_id=None):
        """获取指定CRM订单当前选择的模板名"""
        if row_id is None:
            row_id = self._get_crm_row_id(order)

        selected_template = str(getattr(self, '_crm_row_templates', {}).get(row_id, '') or '').strip()
        if selected_template:
            return selected_template
        return self._get_crm_recommended_template_name(order)


    def get_selected_crm_orders(self):
        """获取CRM页面当前勾选的订单及其生成参数"""
        selected_row_ids = set(getattr(self, 'crm_selected_row_ids', set()) or [])
        selected_items = []

        for index, order in enumerate(getattr(self, 'crm_all_data', []) or []):
            row_id = self._get_crm_row_id(order, index)
            if row_id not in selected_row_ids:
                continue

            customer_type = self._get_crm_customer_type(order, row_id)
            selected_items.append({
                'row_id': row_id,
                'order': order,
                'template_name': self._get_selected_crm_template_name(order, row_id),
                'template_is_manual': bool(str(getattr(self, '_crm_row_templates', {}).get(row_id, '') or '').strip()),
                'customer_type': customer_type,
                'matched_price': self._get_crm_matched_price(order, customer_type, row_id),
                'discount_unit_price': self._get_crm_discount_unit_price(order, customer_type, row_id),
                'product_remark': self._get_crm_product_remark(order, row_id),
            })

        return selected_items


    def _sum_crm_amounts(self, values):
        """汇总CRM金额/数量"""
        total = 0.0
        has_value = False
        for value in values or []:
            amount = self._parse_crm_amount_value(value)
            if amount is None:
                continue
            total += amount
            has_value = True
        if not has_value:
            return None
        return self._normalize_crm_numeric_value(total)


    def _get_crm_orders_by_erp(self, erp_order_no, source_orders=None):
        """从指定CRM订单集合中获取相同ERP订单号的所有订单"""
        erp_order_no = str(erp_order_no or '').strip()
        if not erp_order_no:
            return []

        if not source_orders:
            return []

        matched_orders = []
        for order in source_orders:
            current_erp_order_no = str(order.get('field_2maFO__c', '') or '').strip()
            if current_erp_order_no == erp_order_no:
                matched_orders.append(order)
        return matched_orders


    def _get_crm_orders_by_erp_from_all_data(self, erp_order_no):
        """从全部已加载CRM订单中获取相同ERP订单号的所有订单"""
        return self._get_crm_orders_by_erp(erp_order_no, getattr(self, 'crm_all_data', None))


    def _get_crm_orders_by_erp_from_current_list(self, erp_order_no):
        """从当前CRM列表中获取相同ERP订单号的所有订单"""
        source_orders = getattr(self, 'crm_filtered_data', None)
        if not source_orders:
            source_orders = getattr(self, 'crm_all_data', None)
        return self._get_crm_orders_by_erp(erp_order_no, source_orders)


    def _get_crm_group_product_amount(self, erp_order_no, group_items):
        """按ERP订单号汇总当前列表中的产品合计，未命中时回退到勾选项"""
        same_erp_orders = self._get_crm_orders_by_erp_from_current_list(erp_order_no)
        total_product_amount = self._sum_crm_amounts([
            order.get('product_amount') for order in same_erp_orders
        ])
        if total_product_amount is not None:
            return total_product_amount

        total_product_amount = self._sum_crm_amounts([
            item.get('order', {}).get('product_amount') for item in group_items
        ])
        if total_product_amount is not None:
            return total_product_amount

        if group_items:
            return group_items[0].get('order', {}).get('product_amount', '')
        return ''


    def _build_crm_group_source_values(self, group_items):
        """构建按ERP订单号聚合后的CRM合同数据"""
        base_order = group_items[0]['order']
        erp_order_no = str(base_order.get('field_2maFO__c', '') or '').strip()
        amount_fields = {'order_amount', 'payment_amount', 'receivable_amount', 'invoice_amount', 'discount'}

        # ✅ 从设置中动态获取字段列表
        cfg = load_config()
        field_mapping_list = cfg.get('fxiaoke', {}).get('crm_field_mapping_list', [])
        if field_mapping_list:
            known_time_fields = {'create_time', 'submit_time', 'last_modified_time'}
            dynamic_fields = []
            for m in field_mapping_list:
                api_name = m.get('api_name', '')
                if api_name:
                    display_name = m.get('display_name', api_name)
                    is_time = api_name in known_time_fields
                    dynamic_fields.append((api_name, display_name, is_time))
            # 补充 CRM_ALL_FIELDS 中不在映射列表的字段（地址、手机等）
            for key, label, is_time in self.CRM_ALL_FIELDS:
                if not any(f[0] == key for f in dynamic_fields):
                    dynamic_fields.append((key, label, is_time))
        else:
            dynamic_fields = list(self.CRM_ALL_FIELDS)

        values = {}
        for key, label, is_time in dynamic_fields:
            if key == 'field_jv2dq__c' or key.startswith('option_'):
                raw_value = self._join_crm_unique_texts([
                    self._crm_extract_field(item['order'], key)
                    for item in group_items
                ])
            elif key == 'product_amount':
                raw_value = self._get_crm_group_product_amount(erp_order_no, group_items)
            elif key == 'field_Xqs0n__c':
                raw_value = self._sum_crm_amounts([
                    item.get('order', {}).get('field_Xqs0n__c') for item in group_items
                ])
                if raw_value is None:
                    raw_value = base_order.get(key, '')
            elif is_time:
                raw_value = self._format_crm_timestamp_text(base_order.get(key, ''))
            elif key in amount_fields:
                raw_value = base_order.get(key, '')
            else:
                raw_value = self._crm_extract_field(base_order, key)

            values[key] = raw_value
            values[label] = raw_value

        customer_name = self._join_crm_unique_texts([
            self._crm_extract_field(item['order'], 'account_id__r')
            for item in group_items
        ]) or self._crm_extract_field(base_order, 'account_id__r')
        raw_product_type_text = self._join_crm_unique_texts([
            self._crm_extract_field(item['order'], 'field_jv2dq__c')
            for item in group_items
        ])

        model_specs = []
        product_names = []
        for item in group_items:
            for row_data in self._get_crm_product_match_rows(item['order']):
                model_spec = str(row_data.get('model_spec', '') or '').strip()
                product_name = str(row_data.get('product_name', '') or '').strip()
                if model_spec:
                    model_specs.append(model_spec)
                if product_name:
                    product_names.append(product_name)

        model_spec_text = self._join_crm_unique_texts(model_specs)
        product_name_text = self._join_crm_unique_texts(product_names)
        product_type_text = model_spec_text or raw_product_type_text
        customer_type_text = self._join_crm_unique_texts([
            item.get('customer_type') for item in group_items
        ]) or self._get_crm_customer_type(base_order, group_items[0].get('row_id'))
        total_price = self._sum_crm_amounts([item.get('matched_price') for item in group_items])
        total_product_amount = values.get('product_amount', '')
        total_order_quantity = values.get('field_Xqs0n__c', '')
        discount_unit_price = ''
        total_price_value = self._parse_crm_amount_value(total_price)
        total_product_amount_value = self._parse_crm_amount_value(total_product_amount)
        total_order_quantity_value = self._parse_crm_amount_value(total_order_quantity)
        if (
            total_price_value is not None
            and total_product_amount_value is not None
            and total_order_quantity_value not in (None, 0)
        ):
            try:
                discount_unit_price = self._format_crm_amount_value(
                    (
                        Decimal(str(total_price_value)) -
                        (Decimal(str(total_product_amount_value)) / Decimal(str(total_order_quantity_value)))
                    ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                )
            except Exception:
                discount_unit_price = ''
        uppercase_amount = self._convert_amount_to_rmb_upper(total_product_amount)
        remark_text = self._join_crm_unique_texts([
            item.get('product_remark') for item in group_items
        ])

        values['field_2maFO__c'] = erp_order_no
        values['ERP订单号'] = erp_order_no
        values['account_id__r'] = customer_name
        values['客户名称'] = customer_name

        if product_type_text:
            values['field_jv2dq__c'] = product_type_text
            values['订单产品类型'] = product_type_text
        if raw_product_type_text:
            values['订单产品类型原值'] = raw_product_type_text

        if model_spec_text:
            values['订单产品类'] = model_spec_text
            values['规格型号'] = model_spec_text

        if product_name_text:
            values['product_name'] = product_name_text
            values['产品名称'] = product_name_text

        if customer_type_text:
            values['customer_type'] = customer_type_text
            values['客户类型'] = customer_type_text

        if total_price not in ('', None):
            values['matched_price'] = total_price
            values['匹配价格'] = total_price

        if discount_unit_price:
            values['discount_unit_price'] = discount_unit_price
            values['折扣单价'] = discount_unit_price

        if total_product_amount not in ('', None):
            values['product_amount'] = total_product_amount
            values['产品合计'] = total_product_amount

        if uppercase_amount:
            values['大写'] = uppercase_amount

        if remark_text:
            values['product_remark'] = remark_text
            values['产品备注'] = remark_text

        return values


    def _load_crm_doc_template(self, template_name, config=None):
        """按CRM模板名称加载Word模板"""
        config = config or load_config()
        crm_templates = config.get('file_config', {}).get('crm_word_templates', {})
        template_value = str(crm_templates.get(template_name, '') or '').strip()
        if not template_value:
            raise ValueError(f"CRM模板未配置模板文件: {template_name}")

        crm_template_dir = config.get('path_config', {}).get('crm_template_dir', 'template')
        template_dir_path = resolve_app_path(crm_template_dir)
        template_path = Path(template_value)
        if not template_path.is_absolute():
            template_path = template_dir_path / template_path

        if not template_path.exists():
            raise FileNotFoundError(f"CRM模板文件不存在: {template_path}")

        return load_docx_template(template_path)


    def _get_crm_template_target_root(self, template_name, config=None):
        """获取CRM模板对应的目标根目录"""
        config = config or load_config()
        target_paths = config.get('path_config', {}).get('crm_template_target_paths', {})
        target_path = str(target_paths.get(template_name, '') or '').strip()
        if not target_path:
            raise ValueError(f"CRM模板未设置目标文件路径: {template_name}")
        return resolve_app_path(target_path)


    def _resolve_crm_group_template_name(self, erp_order_no, group_items):
        """解析同一ERP订单号分组应使用的CRM模板"""
        manual_template_names = []
        for item in group_items:
            if not item.get('template_is_manual'):
                continue
            template_name = str(item.get('template_name', '') or '').strip()
            if template_name and template_name not in manual_template_names:
                manual_template_names.append(template_name)

        if manual_template_names:
            if len(manual_template_names) > 1:
                self.update_output.emit(f"[CRM] ERP订单号 {erp_order_no} 选择了多个模板，已使用 {manual_template_names[0]}")
            return manual_template_names[0]

        if group_items:
            group_orders = [item.get('order', {}) for item in group_items if isinstance(item.get('order'), dict)]
            if len(group_orders) > 1:
                config = getattr(self, 'config', None) or load_config()
                crm_templates = config.get('file_config', {}).get('crm_word_templates', {})
                if isinstance(crm_templates, dict) and 'CT+F200' in crm_templates:
                    if any(self._crm_order_contains_f200(order) for order in group_orders):
                        return 'CT+F200'

        template_names = []
        for item in group_items:
            template_name = str(item.get('template_name', '') or '').strip()
            if template_name and template_name not in template_names:
                template_names.append(template_name)

        if not template_names:
            raise ValueError(f"ERP订单号 {erp_order_no} 未选择CRM模板")

        if len(template_names) > 1:
            self.update_output.emit(f"[CRM] ERP订单号 {erp_order_no} 选择了多个模板，已使用 {template_names[0]}")

        return template_names[0]


    def _generate_crm_contract_documents(self, selected_items):
        """生成CRM合同并返回生成结果列表"""
        config = load_config()
        self.config = config

        mapping = config.get('business_rules', {}).get('crm_field_mapping', {})
        if not mapping:
            raise ValueError("请先在设置-字段映射-CRM字段中配置字段映射")

        special_formats = self._get_crm_special_column_formats(config)
        grouped_orders = {}
        for item in selected_items:
            order = item.get('order', {})
            erp_order_no = str(order.get('field_2maFO__c', '') or '').strip()
            if not erp_order_no:
                raise ValueError("存在未填写ERP订单号的CRM订单，无法生成合同")
            grouped_orders.setdefault(erp_order_no, []).append(item)

        generated_files = []
        with common._get_main().pdf_conversion_batch():
            for erp_order_no, group_items in grouped_orders.items():
                template_name = self._resolve_crm_group_template_name(erp_order_no, group_items)
                template = self._load_crm_doc_template(template_name, config)
                target_root = self._get_crm_template_target_root(template_name, config)

                source_values = self._build_crm_group_source_values(group_items)
                customer_name = str(
                    source_values.get('客户名称') or source_values.get('account_id__r') or '未命名客户'
                ).strip() or '未命名客户'
                base_name = f"{erp_order_no}-{customer_name}"

                context = build_context_from_mapping_values(source_values, mapping, special_formats)
                # 优先使用全局变量，回退到 config（避免 import 时序导致全局变量未初始化）
                keep_fmt = getattr(core, '_keep_crm_word_override', None)
                if keep_fmt is None:
                    keep_fmt = config.get('app_settings', {}).get('keep_crm_output_format', 'word_pdf')
                skip_pdf = (keep_fmt == 'word')
                print(f"[DEBUG-CRM生成] keep_crm_fmt={keep_fmt} | skip_pdf={skip_pdf}")
                document_info = render_document_files(template, context, base_name, skip_pdf=skip_pdf)
                document_info['target_root'] = target_root
                document_info['template_name'] = template_name
                document_info['erp_order_no'] = erp_order_no
                generated_files.append(document_info)

        return generated_files


    def on_generate_crm_contracts(self):
        """生成勾选的CRM合同"""
        selected_items = self.get_selected_crm_orders()
        if not selected_items:
            messagebox.showwarning("提示", "请先勾选要生成的CRM订单！")
            return

        self.append_output(f"开始处理CRM合同... (已选择 {len(selected_items)} 条记录)")

        thread = threading.Thread(target=self.run_crm_contract_process, args=(selected_items,))
        thread.daemon = True
        thread.start()

        if hasattr(self, 'crm_generate_btn'):
            self.crm_generate_btn.setEnabled(False)
            self.crm_generate_btn.setText("执行中>>>")


    def run_crm_contract_process(self, selected_items):
        """在后台线程中执行CRM合同生成"""
        try:
            self.update_output.emit("开始生成CRM合同...")
            generated_files = self._generate_crm_contract_documents(selected_items)
            self.update_output.emit(f"✓ CRM合同生成完成（共 {len(generated_files)} 个）")

            pdf_count = sum(1 for item in generated_files if item.get('pdf_success'))
            if pdf_count > 0:
                self.update_output.emit(f"✓ PDF转换完成（{pdf_count}/{len(generated_files)} 个成功）")
            else:
                self.update_output.emit("⚠ PDF转换未成功，请检查：")
                self.update_output.emit("   1. 是否安装了Microsoft Word或LibreOffice")
                self.update_output.emit("   2. 是否安装了comtypes库（pip install comtypes）")
                self.update_output.emit("   3. 查看控制台日志了解详细错误信息")

            self.update_output.emit("开始整理CRM输出文件...")
            crm_keep_fmt = self.config.get('app_settings', {}).get('keep_crm_output_format', 'word_pdf')
            crm_keep_word = crm_keep_fmt in ('word', 'word_pdf')
            crm_keep_pdf = crm_keep_fmt in ('pdf', 'word_pdf')
            print(f"[DEBUG-CRM合同] 格式: {crm_keep_fmt} | keep_word={crm_keep_word} | keep_pdf={crm_keep_pdf}")
            target_roots = move_generated_document_files(generated_files, keep_word=crm_keep_word, keep_pdf=crm_keep_pdf)
            self.update_output.emit("CRM文件整理完成")

            if len(target_roots) == 1:
                target_root = target_roots[0]
                self.update_output.emit(f"输出目录: {target_root}")
                if self.config.get('app_settings', {}).get('open_output_folder', True):
                    open_folder(str(target_root))

                config = load_config()
                svn_submission = config.get('app_settings', {}).get('svn_submission', True)
                if svn_submission:
                    self.update_output.emit("准备提交SVN...")
                    import time
                    time.sleep(0.8)
                    commit_to_svn(target_root)
                    self.update_output.emit("SVN提交完成")
                else:
                    self.update_output.emit("SVN提交功能已关闭，跳过提交")
            elif len(target_roots) > 1:
                self.update_output.emit("生成文件分布在多个目标路径：")
                for target_root in target_roots:
                    self.update_output.emit(str(target_root))
                self.update_output.emit("涉及多个目标路径，已跳过自动打开和SVN提交")

            if generated_files:
                self.update_output.emit("\n生成的合同编号:")
                for file_info in generated_files:
                    self.update_output.emit(str(file_info.get('base_name', '')))
            else:
                self.update_output.emit("\n未生成任何合同")
        except Exception as e:
            error_msg = f"CRM合同生成失败: {str(e)}"
            self.update_output.emit(error_msg)
            print(error_msg)
            from PyQt6.QtCore import QTimer
            error_str = str(e)
            QTimer.singleShot(0, lambda: self.show_error_dialog(error_str))
            logging.error(error_msg)
        finally:
            self.enable_crm_generate_button.emit()

    enable_crm_button = pyqtSignal()
    obj_query_data_ready = pyqtSignal(str)
    opportunity_data_ready = pyqtSignal()


    def on_enable_crm_button(self):
        """响应启用CRM按钮相关操作。"""
        self.crm_refresh_btn.setText("刷新")
        self._crm_is_loading = False
        self._populate_crm_table()


    def _crm_first_auto_load(self):
        """CRM订单首次自动加载"""
        print("[DEBUG-CRM] 🚀 执行首次自动加载...")
        self.on_crm_manual_refresh()  # 调用手动刷新方法加载数据


    def _opportunity_first_auto_load(self):
        """招投标授权首次自动加载商机数据"""
        print("[DEBUG-商机] 🚀 执行首次自动加载商机数据...")
        if hasattr(self, 'on_refresh_opportunity_data'):
            self.on_refresh_opportunity_data()


    def _reset_crm_filters_and_selection(self):
        """刷新CRM时重置搜索、筛选和勾选状态"""
        if hasattr(self, 'crm_search_input'):
            self.crm_search_input.blockSignals(True)
            self.crm_search_input.clear()
            self.crm_search_input.blockSignals(False)

        # 清除所有多条件筛选行
        self._clear_all_crm_conditions()

        # 重置方案选择
        self._crm_active_preset_name = None
        self._update_crm_preset_btn_label()

        # 重置日期范围（默认不筛选）
        self.crm_date_start = None
        self.crm_date_end = None

        self.crm_current_page = 1
        self.crm_selected_row_ids = set()

        if hasattr(self, 'crm_table'):
            self.crm_table.clearSelection()
        if hasattr(self, 'crm_table_header'):
            self.crm_table_header.set_check_state(Qt.CheckState.Unchecked)


    def _get_crm_sort_value(self, order, row_index, header_label, label_to_key):
        """内部方法：获取CRM排序值。"""
        row_id = self._get_crm_row_id(order, row_index)

        if header_label == '模板选择':
            return self._get_selected_crm_template_name(order, row_id)
        if header_label == '规格型号':
            return self._get_crm_model_spec(order)
        if header_label == '客户类型':
            return self._get_crm_customer_type(order, row_id)
        if header_label == '匹配价格':
            customer_type = self._get_crm_customer_type(order, row_id)
            return self._get_crm_matched_price(order, customer_type, row_id)
        if header_label == '折扣单价':
            customer_type = self._get_crm_customer_type(order, row_id)
            return self._get_crm_discount_unit_price(order, customer_type, row_id)
        if header_label == '产品备注':
            return self._get_crm_product_remark(order, row_id)
        if header_label == '大写':
            return self._convert_amount_to_rmb_upper(order.get('product_amount', ''))

        key_info = label_to_key.get(header_label)
        if not key_info:
            return ''

        key, is_time = key_info
        if is_time:
            return order.get(key, '')
        return self._crm_extract_field(order, key)


    def _sort_crm_data(self, data_rows, label_to_key):
        """内部方法：处理排序CRM数据逻辑。"""
        sort_header = str(getattr(self, 'crm_sort_header', '') or '').strip()
        available_headers = list(getattr(self, 'crm_visible_headers', []))
        if not sort_header:
            return list(data_rows)
        if sort_header not in available_headers:
            self.crm_sort_header = ''
            return list(data_rows)

        sorted_records = self._sort_records(
            list(enumerate(data_rows)),
            lambda item: self._get_crm_sort_value(item[1], item[0], sort_header, label_to_key),
            getattr(self, 'crm_sort_order', Qt.SortOrder.AscendingOrder)
        )
        return [record for _, record in sorted_records]


    def _update_crm_table_sort_indicator(self):
        """内部方法：更新CRM表格排序indicator。"""
        if not hasattr(self, 'crm_table_header'):
            return

        sort_header = str(getattr(self, 'crm_sort_header', '') or '').strip()
        available_headers = self._get_crm_display_headers()
        if not sort_header or sort_header not in available_headers:
            self.crm_table_header.setSortIndicatorShown(False)
            return

        logical_index = available_headers.index(sort_header)
        self.crm_table_header.setSortIndicatorShown(True)
        self.crm_table_header.setSortIndicator(logical_index, getattr(self, 'crm_sort_order', Qt.SortOrder.AscendingOrder))


    def on_crm_table_header_clicked(self, logical_index):
        """响应CRM表头clicked相关操作。"""
        if logical_index <= 0 or logical_index >= self.crm_table.columnCount():
            return

        header_item = self.crm_table.horizontalHeaderItem(logical_index)
        if header_item is None:
            return

        header_text = header_item.text().strip()
        if not header_text:
            return

        if getattr(self, 'crm_sort_header', '') == header_text:
            if getattr(self, 'crm_sort_order', Qt.SortOrder.AscendingOrder) == Qt.SortOrder.AscendingOrder:
                self.crm_sort_order = Qt.SortOrder.DescendingOrder
            else:
                self.crm_sort_header = ''
                self.crm_sort_order = Qt.SortOrder.AscendingOrder
        else:
            self.crm_sort_header = header_text
            self.crm_sort_order = Qt.SortOrder.AscendingOrder

        self.crm_current_page = 1
        self._populate_crm_table()


    def on_crm_table_cell_clicked(self, row, col):
        """CRM订单表格单元格点击处理：第0列（复选框）选中整行，其他列只选中单元格"""
        if col == 0:
            self.crm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.crm_table.selectRow(row)
            self.crm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)


    def _on_opportunity_data_ready(self):
        """商机数据加载完成（主线程回调）"""
        self._opportunity_is_loading = False
        if hasattr(self, 'opportunity_refresh_btn'):
            self.opportunity_refresh_btn.setText("刷新")
        if hasattr(self, 'opportunity_all_data') and self.opportunity_all_data:
            if hasattr(self, 'opportunity_table'):
                self._populate_opportunity_table()
            if hasattr(self, 'opportunity_status_label'):
                self.opportunity_status_label.setText(f"共 {len(self.opportunity_all_data)} 条记录")
        else:
            if hasattr(self, 'opportunity_status_label'):
                self.opportunity_status_label.setText("共 0 条记录")


    def _on_opp_table_cell_clicked(self, row, col):
        """商机表格：第0列（复选框）选中整行，其他列点哪选哪"""
        if col == 0:
            self.opportunity_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.opportunity_table.selectRow(row)
            self.opportunity_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)


    def on_crm_table_cell_double_clicked(self, row, col):
        """保留兼容接口，实际编辑由表格委托处理"""
        return


    def on_crm_keep_format_changed(self, index):
        """CRM订单页面输出格式变更"""
        fmt_map = {0: 'word_pdf', 1: 'word', 2: 'pdf'}
        fmt = fmt_map.get(index, 'word_pdf')
        config = load_config()
        if 'app_settings' not in config:
            config['app_settings'] = {}
        config['app_settings']['keep_crm_output_format'] = fmt
        core._keep_crm_word_override = fmt
        if hasattr(self, 'config'):
            self.config = config
        save_config(config, immediate=False)


    def _enable_crm_generate_button(self):
        """恢复CRM生成按钮状态"""
        if hasattr(self, 'crm_generate_btn'):
            self.crm_generate_btn.setEnabled(True)
            self.crm_generate_btn.setText("生成合同")


    def commit_to_svn(self, folder_path):
        """提交到SVN"""
        try:
            import os
            import subprocess
            import platform

            # 检查是否开启了SVN提交功能
            config = load_config()
            app_settings = config.get('app_settings', {})
            svn_submission = app_settings.get('svn_submission', True)

            if not svn_submission:
                self.append_output("SVN提交功能已关闭")
                return

            # 检查是否安装了TortoiseSVN
            if platform.system() == "Windows":
                # 确保路径格式正确，处理空格和特殊字符
                # 使用绝对路径
                folder_path = os.path.abspath(folder_path)
                # 将路径中的反斜杠转换为正斜杠
                folder_path = folder_path.replace('\\', '/')

                # 尝试启动TortoiseSVN提交对话框
                # 将/path和路径作为两个单独的参数传递
                tortoise_proc = subprocess.Popen(
                    ["TortoiseProc.exe", "/command:commit", "/path", folder_path, "/closeonend:2"]
                )
                self.append_output(f"启动SVN提交对话框: {folder_path}")
            else:
                # 非Windows系统，提示用户手动提交
                self.append_output(f"请手动提交 {folder_path} 到SVN")
        except Exception as e:
            self.append_output(f"提交SVN失败: {str(e)}")
            import traceback
            self.append_output(f"错误详情: {traceback.format_exc()}")

