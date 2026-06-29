# -*- coding: utf-8 -*-
from core import *
from common import *
import common  # 显式导入，用于访问模块级私有函数

"""
pdf_watermark.py — PDF 水印与加密 Mixin
───────────────────────────────────────
负责：MainFrame 中 PDF 水印页面相关方法
  - create_pdf_watermark_page()  PDF 水印页面
  - process_pdf_watermark()      PDF 水印添加 / 加密
  - on_pdf_* / _pdf_* 方法       文件选择 / 水印参数配置
依赖：core.py / common.py
被导入：主程序（作为 MainFrame 的 Mixin 父类）
"""
"""pdf_watermark Mixin"""

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

class pdf_watermarkMixin:
    """pdf_watermark functionality."""

    def create_pdf_watermark_page(self):
        """创建PDF水印功能页面（页面 2）"""
        page = QFrame()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(15, 10, 20, 10)

        main_group = QGroupBox("PDF水印设置")
        main_group.setStyleSheet(get_glass_groupbox_style())
        main_layout = QVBoxLayout(main_group)
        main_layout.setContentsMargins(15, 20, 15, 15)
        main_layout.setSpacing(8)

        config = load_config()
        pdf_config = config.get('pdf_watermark', {})
        product_models = pdf_config.get('product_models', ['产品A', '产品B', '产品C'])

        sub_group_style = get_glass_groupbox_style(compact=True)

        # ================================================================
        # 上半部分：三列布局（源文件选择 | 已选文件 | 水印参数+执行+备注）
        # 宽度比例：3 : 3 : 4
        # ================================================================
        upper_row = QHBoxLayout()
        upper_row.setSpacing(8)

        # ---------- 左列(30%)：源文件选择 ----------
        left_col = QVBoxLayout()
        left_col.setSpacing(4)
        left_col.setContentsMargins(0, 0, 0, 0)

        source_group = QGroupBox("源文件选择")
        source_group.setStyleSheet(sub_group_style)
        source_layout = QVBoxLayout(source_group)
        source_layout.setContentsMargins(6, 8, 6, 6)
        source_layout.setSpacing(4)

        left_header_layout = QHBoxLayout()
        self.file_search_input = QLineEdit()
        self.file_search_input.setPlaceholderText("搜索文件名...")
        self.file_search_input.textChanged.connect(self.on_search_files)
        left_header_layout.addWidget(self.file_search_input, 1)
        self.refresh_pdf_file_btn = QPushButton("刷新")
        self.refresh_pdf_file_btn.clicked.connect(self.on_refresh_file_list)
        left_header_layout.addWidget(self.refresh_pdf_file_btn)
        self.pdf_file_select_all_checkbox = QCheckBox("全选/取消")
        self.pdf_file_select_all_checkbox.setTristate(True)
        self.pdf_file_select_all_checkbox.clicked.connect(self.on_pdf_file_select_all_toggled)
        left_header_layout.addWidget(self.pdf_file_select_all_checkbox)
        # >> 按钮放到全选/取消旁边
        self.add_files_btn = QPushButton(">")
        self.add_files_btn.setFixedSize(40, 28)
        self.add_files_btn.clicked.connect(self.on_add_files)
        left_header_layout.addWidget(self.add_files_btn)
        source_layout.addLayout(left_header_layout)

        self.file_list_widget = QListWidget()
        self.file_list_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        self.file_list_widget.itemDoubleClicked.connect(self.on_file_double_clicked)
        self.file_list_widget.itemSelectionChanged.connect(self._update_pdf_file_select_all_state)
        source_layout.addWidget(self.file_list_widget, 1)

        left_col.addWidget(source_group, 1)

        upper_row.addLayout(left_col, 1)

        # ---------- 中列(2.5)：已选中文件 ----------
        center_col = QVBoxLayout()
        center_col.setSpacing(4)
        center_col.setContentsMargins(0, 0, 0, 0)

        selected_group = QGroupBox("已选中")
        selected_group.setStyleSheet(sub_group_style)
        selected_layout = QVBoxLayout(selected_group)
        selected_layout.setContentsMargins(6, 8, 6, 6)
        selected_layout.setSpacing(4)

        right_header_layout = QHBoxLayout()
        # << 按钮放到已选中左上角
        self.remove_files_btn = QPushButton("<")
        self.remove_files_btn.setFixedSize(40, 28)
        self.remove_files_btn.clicked.connect(self.on_remove_files)
        right_header_layout.addWidget(self.remove_files_btn)
        right_header_layout.addStretch()
        self.clear_selected_pdf_btn = QPushButton("清空")
        self.clear_selected_pdf_btn.clicked.connect(self.on_clear_selected_files)
        right_header_layout.addWidget(self.clear_selected_pdf_btn)
        selected_layout.addLayout(right_header_layout)

        self.selected_files_widget = QListWidget()
        self.selected_files_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        self.selected_files_widget.itemDoubleClicked.connect(self.on_selected_file_double_clicked)
        selected_layout.addWidget(self.selected_files_widget, 1)

        center_col.addWidget(selected_group, 1)
        upper_row.addLayout(center_col, 1)

        # ---------- 右列(5)：水印参数+执行+备注 ----------
        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        right_col.setContentsMargins(0, 0, 0, 0)

        # 第一行：招标设置 | 目标文件 | 执行（并列）
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        pdf_source_grp = QGroupBox("招标设置")
        pdf_source_grp.setStyleSheet(sub_group_style)
        pdf_source_lay = QHBoxLayout(pdf_source_grp)
        pdf_source_lay.setContentsMargins(6, 4, 6, 4)
        self.product_combo = QComboBox()
        self.product_combo.addItem("自定义")
        self.product_combo.addItems(product_models)
        self.product_combo.currentIndexChanged.connect(self.on_refresh_file_list)
        pdf_source_lay.addWidget(self.product_combo, 1)
        self.product_path_text = QLineEdit()
        self.product_path_text.setReadOnly(True)
        pdf_source_lay.addWidget(self.product_path_text, 2)
        self.product_path_btn = QPushButton("浏览")
        self.product_path_btn.clicked.connect(self.on_browse_product_path)
        pdf_source_lay.addWidget(self.product_path_btn)
        top_bar.addWidget(pdf_source_grp, 5)

        target_grp = QGroupBox("目标文件")
        target_grp.setStyleSheet(sub_group_style)
        target_lay = QHBoxLayout(target_grp)
        target_lay.setContentsMargins(6, 4, 6, 4)
        self.pdf_target_dir_text = QLineEdit()
        self.pdf_target_dir_text.setText(pdf_config.get('target_dir', ''))
        target_lay.addWidget(self.pdf_target_dir_text, 1)
        self.pdf_target_dir_btn = QPushButton("浏览")
        self.pdf_target_dir_btn.clicked.connect(self.on_browse_pdf_target_dir)
        target_lay.addWidget(self.pdf_target_dir_btn)
        top_bar.addWidget(target_grp, 4)

        exec_grp = QGroupBox("确认")
        exec_grp.setStyleSheet(sub_group_style)
        exec_lay = QHBoxLayout(exec_grp)
        exec_lay.setContentsMargins(6, 4, 6, 4)

        # 输出格式下拉框
        keep_opp_fmt = self.config.get('app_settings', {}).get('keep_opp_output_format', 'word_pdf')
        self.opp_keep_format_combo = QComboBox()
        self.opp_keep_format_combo.addItems(["Word+PDF", "Word", "PDF"])
        opp_fmt_map = {"word_pdf": "Word+PDF", "word": "Word", "pdf": "PDF"}
        self.opp_keep_format_combo.setCurrentText(opp_fmt_map.get(keep_opp_fmt, "Word+PDF"))
        self.opp_keep_format_combo.setFixedWidth(100)
        self.opp_keep_format_combo.setToolTip("生成后保留的文件格式")
        self.opp_keep_format_combo.currentIndexChanged.connect(self._on_opp_keep_format_changed)
        exec_lay.addWidget(self.opp_keep_format_combo)

        self.pdf_watermark_btn = QPushButton("确认生成")
        self.pdf_watermark_btn.setMinimumHeight(28)
        self.pdf_watermark_btn.clicked.connect(self.on_pdf_watermark)
        exec_lay.addWidget(self.pdf_watermark_btn, 1)
        top_bar.addWidget(exec_grp, 2)

        right_col.addLayout(top_bar)

        # 参数行：大小 / 角度 / 透明度 / 颜色 / 字体
        param_row1 = QHBoxLayout()
        param_row1.setSpacing(4)

        for label_text, attr_name, default_val, suffix in [
            ("大小", "watermark_font_size", int(pdf_config.get('watermark_font_size', 100)), "%"),
            ("角度", "watermark_angle", int(pdf_config.get('watermark_angle', 45)), "°"),
            ("透明度", "watermark_opacity", int(pdf_config.get('watermark_opacity', 70)), "%"),
        ]:
            grp = QGroupBox(label_text)
            grp.setStyleSheet(sub_group_style)
            grp_layout = QHBoxLayout(grp)
            grp_layout.setContentsMargins(4, 2, 4, 2)
            slider = QSlider(Qt.Horizontal)
            if attr_name == "watermark_angle":
                slider.setRange(0, 360)
            else:
                slider.setRange(10, 100)
            slider.setValue(default_val)
            grp_layout.addWidget(slider, 1)
            lbl = QLabel(f"{default_val}{suffix}")
            slider.valueChanged.connect(lambda v, l=lbl, s=suffix: l.setText(f"{v}{s}"))
            grp_layout.addWidget(lbl)
            setattr(self, attr_name, slider)
            setattr(self, f"{attr_name}_label", lbl)
            param_row1.addWidget(grp, 1)

        color_grp = QGroupBox("颜色")
        color_grp.setStyleSheet(sub_group_style)
        color_lay = QHBoxLayout(color_grp)
        color_lay.setContentsMargins(4, 2, 4, 2)
        self.watermark_color = QPushButton()
        self.watermark_color.setMinimumHeight(22)
        apply_color_chip_style(self.watermark_color, pdf_config.get('watermark_color', '#808080'))
        self.watermark_color.clicked.connect(self.on_select_watermark_color)
        color_lay.addWidget(self.watermark_color, 1)
        param_row1.addWidget(color_grp, 1)

        font_grp = QGroupBox("字体")
        font_grp.setStyleSheet(sub_group_style)
        font_lay = QHBoxLayout(font_grp)
        font_lay.setContentsMargins(4, 2, 4, 2)
        self.watermark_font = QComboBox()
        self.watermark_font.addItems(['微软雅黑', '宋体', '仿宋', '黑体', '楷体'])
        self.watermark_font.setCurrentText(pdf_config.get('watermark_font', '宋体'))
        font_lay.addWidget(self.watermark_font, 1)
        param_row1.addWidget(font_grp, 1)

        right_col.addLayout(param_row1)

        # 参数行：密码 / 后缀 / 水印文本
        param_row2 = QHBoxLayout()
        param_row2.setSpacing(4)

        password_grp = QGroupBox("密码")
        password_grp.setStyleSheet(sub_group_style)
        password_lay = QHBoxLayout(password_grp)
        password_lay.setContentsMargins(4, 2, 4, 2)
        password_lay.setSpacing(4)
        self.encrypt_checkbox = QCheckBox("启用")
        self.encrypt_checkbox.setChecked(pdf_config.get('encrypt_pdf', False))
        password_lay.addWidget(self.encrypt_checkbox)
        self.encrypt_password = QLineEdit()
        self.encrypt_password.setEchoMode(QLineEdit.Password)
        self.encrypt_password.setText(pdf_config.get('encrypt_password', ''))
        self.encrypt_password.setEnabled(pdf_config.get('encrypt_pdf', False))
        self.encrypt_password.setPlaceholderText("密码")
        password_lay.addWidget(self.encrypt_password, 1)
        # 密码显示/隐藏切换按钮
        self.pdf_pwd_visibility_btn = QPushButton("👁")
        self.pdf_pwd_visibility_btn.setFixedSize(28, 26)
        self.pdf_pwd_visibility_btn.setCheckable(True)
        self.pdf_pwd_visibility_btn.setToolTip("显示/隐藏密码")
        self.pdf_pwd_visibility_btn.setStyleSheet("QPushButton { border: none; font-size: 14px; } QPushButton:checked { color: #1890FF; }")
        self.pdf_pwd_visibility_btn.toggled.connect(lambda checked: (
            self.encrypt_password.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password),
            self.pdf_pwd_visibility_btn.setText("🔒" if checked else "👁")
        ))
        password_lay.addWidget(self.pdf_pwd_visibility_btn)
        self.encrypt_checkbox.stateChanged.connect(self.on_encrypt_state_changed)
        param_row2.addWidget(password_grp, 2)

        suffix_grp = QGroupBox("后缀")
        suffix_grp.setStyleSheet(sub_group_style)
        suffix_lay = QHBoxLayout(suffix_grp)
        suffix_lay.setContentsMargins(4, 2, 4, 2)
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("如：备案版")
        suffix_lay.addWidget(self.suffix_input, 1)
        param_row2.addWidget(suffix_grp, 1)

        # 公司资质复选框
        qual_grp = QGroupBox("公司资质")
        qual_grp.setStyleSheet(sub_group_style)
        qual_lay = QHBoxLayout(qual_grp)
        qual_lay.setContentsMargins(4, 2, 4, 2)
        self.company_qual_checkbox = QCheckBox("加载资质")
        self.company_qual_checkbox.setChecked(False)
        self.company_qual_checkbox.setToolTip("勾选后自动将资质存放路径中的PDF加载到已选中列表")
        self.company_qual_checkbox.stateChanged.connect(self._on_company_qual_toggled)
        qual_lay.addWidget(self.company_qual_checkbox)
        param_row2.addWidget(qual_grp, 1)

        wt_grp = QGroupBox("水印文本")
        wt_grp.setStyleSheet(sub_group_style)
        wt_lay = QHBoxLayout(wt_grp)
        wt_lay.setContentsMargins(4, 2, 4, 2)
        self.watermark_text = QLineEdit()
        self.watermark_text.setText(pdf_config.get('watermark_text', '机密'))
        self.watermark_text.setPlaceholderText("请输入水印文本")
        wt_lay.addWidget(self.watermark_text, 1)
        param_row2.addWidget(wt_grp, 3)

        right_col.addLayout(param_row2)

        # 选中商机的招标授权备注（给更多空间）
        remark_grp = QGroupBox("授权备注")
        remark_grp.setStyleSheet(sub_group_style)
        remark_lay = QVBoxLayout(remark_grp)
        remark_lay.setContentsMargins(6, 6, 6, 6)
        remark_lay.setSpacing(4)
        self.opportunity_remark_text = QTextEdit()
        self.opportunity_remark_text.setReadOnly(True)
        self.opportunity_remark_text.setPlaceholderText("勾选下方商机后，此处将显示该商机的授权备注")
        self.opportunity_remark_text.setStyleSheet("""
            QTextEdit {
                background-color: #F5F5F5;
                border: 1px solid #D9D9D9;
                border-radius: 4px;
                padding: 4px 8px;
                color: #666;
                font-size: 12px;
            }
        """)
        remark_lay.addWidget(self.opportunity_remark_text, 1)
        right_col.addWidget(remark_grp, 1)

        upper_row.addLayout(right_col, 2)

        main_layout.addLayout(upper_row, 1)

        # ================================================================
        # 下半部分：商机明细（NewOpportunityObj）
        opportunity_group = QGroupBox("商机明细")
        opportunity_group.setStyleSheet(get_glass_groupbox_style())
        opportunity_layout = QVBoxLayout(opportunity_group)

        # 商机工具栏（完全照搬CRM订单筛选器）
        opportunity_toolbar = QHBoxLayout()
        opportunity_toolbar.setSpacing(8)

        self.opportunity_preset_btn = QPushButton("方案 ▼")
        self.opportunity_preset_btn.setFixedHeight(30)
        self.opportunity_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.opportunity_preset_btn.setToolTip("选择筛选方案")
        self.opportunity_preset_btn.setStyleSheet("QPushButton { border: 1px solid #D9D9D9; border-radius: 4px; padding: 2px 10px; font-size: 12px; color: #333; background: #FFF; } QPushButton:hover { border-color: #1890FF; color: #1890FF; }")
        self.opportunity_preset_btn.clicked.connect(self._show_opportunity_preset_popup)
        opportunity_toolbar.addWidget(self.opportunity_preset_btn)

        self.opportunity_filter_toggle_btn = QPushButton("筛选")
        self.opportunity_filter_toggle_btn.setFixedHeight(30)
        self.opportunity_filter_toggle_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 4px 12px; font-size: 13px;
                background-color: #FFFFFF; color: #333;
            }
            QPushButton:hover { border-color: #1890FF; color: #1890FF; }
        """)
        self.opportunity_filter_toggle_btn.clicked.connect(self._toggle_opportunity_filter_panel)
        opportunity_toolbar.addWidget(self.opportunity_filter_toggle_btn)

        opp_search_frame = QFrame()
        opp_search_frame.setFixedHeight(30)
        opp_search_frame.setMaximumWidth(260)
        opp_search_frame.setStyleSheet("QFrame { border: 1px solid #D9D9D9; border-radius: 4px; background: #FFF; } QFrame:focus-within { border-color: #1890FF; }")
        opp_search_lay = QHBoxLayout(opp_search_frame)
        opp_search_lay.setContentsMargins(0, 0, 0, 0)
        opp_search_lay.setSpacing(0)

        self.opp_search_stack = QStackedWidget()

        self.opp_search_input = QLineEdit()
        self.opp_search_input.setPlaceholderText("搜索")
        self.opp_search_input.setFixedHeight(28)
        self.opp_search_input.setStyleSheet("QLineEdit { border: none; background: transparent; padding: 2px 8px; font-size: 12px; }")
        self.opp_search_input.textChanged.connect(self.on_opp_search_changed)
        self.opp_search_input.returnPressed.connect(self._apply_opp_filters)
        self.opp_search_stack.addWidget(self.opp_search_input)

        self.opp_search_date_btn = QPushButton("选择日期范围")
        self.opp_search_date_btn.setFixedHeight(28)
        self.opp_search_date_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.opp_search_date_btn.setStyleSheet("QPushButton { border: none; background: transparent; padding: 2px 8px; font-size: 11px; color: #999; } QPushButton:hover { color: #1890FF; }")
        self.opp_search_date_btn.setProperty('date_range', {'start': None, 'end': None})
        self.opp_search_date_btn.clicked.connect(lambda: self._open_opp_search_date_range())
        self.opp_search_stack.addWidget(self.opp_search_date_btn)

        opp_search_lay.addWidget(self.opp_search_stack, stretch=1)
        opportunity_toolbar.addWidget(opp_search_frame)

        opportunity_toolbar.addStretch()

        self.opportunity_column_settings_btn = QPushButton("字段显示")
        self.opportunity_column_settings_btn.setFixedWidth(80)
        self.opportunity_column_settings_btn.clicked.connect(self.open_opportunity_field_settings_dialog)
        opportunity_toolbar.addWidget(self.opportunity_column_settings_btn)

        self.opportunity_refresh_btn = QPushButton("刷新")
        self.opportunity_refresh_btn.setFixedSize(92, 30)
        self.opportunity_refresh_btn.setToolTip("从CRM API获取最新数据")
        self.opportunity_refresh_btn.setStyleSheet(get_compact_refresh_button_style())
        self.opportunity_refresh_btn.clicked.connect(self._on_opp_refresh_btn_clicked)
        opportunity_toolbar.addWidget(self.opportunity_refresh_btn)

        opportunity_layout.addLayout(opportunity_toolbar)

        # 外露标签行（与CRM订单一致）
        self.opp_exposed_tags = QFrame()
        self.opp_exposed_tags.setVisible(False)
        self.opp_exposed_tags.setStyleSheet("QFrame { background: transparent; border: none; }")
        opp_exposed_layout = QHBoxLayout(self.opp_exposed_tags)
        opp_exposed_layout.setContentsMargins(0, 2, 0, 2)
        opp_exposed_layout.setSpacing(4)
        opportunity_layout.addWidget(self.opp_exposed_tags)

        # 筛选条件面板（内嵌，与CRM订单一致）
        self.opp_filter_panel = QFrame()
        self.opp_filter_panel.setVisible(False)
        self.opp_filter_panel.setFixedWidth(500)
        self.opp_filter_panel.setStyleSheet("QFrame { border: 1px solid #E8E8E8; border-radius: 6px; background: #FFF; }")
        ofp_layout = QVBoxLayout(self.opp_filter_panel)
        ofp_layout.setContentsMargins(0, 0, 0, 0)
        ofp_layout.setSpacing(0)

        ofp_header = QFrame()
        ofp_header.setFixedHeight(36)
        ofp_header.setStyleSheet("QFrame { background: #FAFAFA; border-bottom: 1px solid #E8E8E8; border-top-left-radius: 6px; border-top-right-radius: 6px; }")
        ofp_h_lay = QHBoxLayout(ofp_header)
        ofp_h_lay.setContentsMargins(12, 0, 8, 0)
        ofp_h_lay.addWidget(QLabel("设置筛选"))
        ofp_h_lay.addStretch()
        ofp_close = QPushButton("×")
        ofp_close.setFixedSize(24, 24)
        ofp_close.setStyleSheet("QPushButton { border: none; font-size: 14px; color: #999; background: transparent; } QPushButton:hover { color: #333; }")
        ofp_close.clicked.connect(self._toggle_opportunity_filter_panel)
        ofp_h_lay.addWidget(ofp_close)
        ofp_layout.addWidget(ofp_header)

        self.opp_conditions_frame = QFrame()
        self.opp_conditions_frame.setStyleSheet("QFrame { background: #FFF; border: none; }")
        self.opp_conditions_layout = QVBoxLayout(self.opp_conditions_frame)
        self.opp_conditions_layout.setContentsMargins(8, 8, 8, 4)
        self.opp_conditions_layout.setSpacing(4)
        self.opp_conditions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.opp_condition_rows = []

        ofp_footer = QFrame()
        ofp_footer.setFixedHeight(44)
        ofp_footer.setStyleSheet("QFrame { background: #FAFAFA; border-top: 1px solid #E8E8E8; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; }")
        ofp_f_lay = QHBoxLayout(ofp_footer)
        ofp_f_lay.setContentsMargins(12, 6, 12, 6)
        ofp_f_lay.setSpacing(8)

        opp_save_btn = QPushButton("另存为")
        opp_save_btn.setFixedHeight(28)
        opp_save_btn.setStyleSheet("QPushButton { border: 1px solid #D9D9D9; border-radius: 4px; font-size: 12px; padding: 2px 12px; background: #FFF; color: #333; } QPushButton:hover { border-color: #1890FF; color: #1890FF; }")
        opp_save_btn.clicked.connect(lambda: self._save_opp_filter_preset())
        ofp_f_lay.addWidget(opp_save_btn)

        opp_add_btn = QPushButton("+ 添加条件")
        opp_add_btn.setFixedHeight(28)
        opp_add_btn.setStyleSheet("QPushButton { border: 1px dashed #1890FF; border-radius: 4px; color: #1890FF; font-size: 12px; padding: 2px 12px; background: transparent; } QPushButton:hover { background: #E6F7FF; }")
        opp_add_btn.clicked.connect(lambda: self._add_opp_condition_row())
        ofp_f_lay.addWidget(opp_add_btn)

        opp_clear_btn = QPushButton("清除")
        opp_clear_btn.setFixedHeight(28)
        opp_clear_btn.setStyleSheet("QPushButton { border: 1px solid #D9D9D9; border-radius: 4px; font-size: 12px; padding: 2px 12px; background: #FFF; color: #666; } QPushButton:hover { border-color: #FF4D4F; color: #FF4D4F; }")
        opp_clear_btn.clicked.connect(lambda: [self._clear_all_opp_conditions(), self._apply_opp_filters()])
        ofp_f_lay.addWidget(opp_clear_btn)

        ofp_f_lay.addStretch()
        opp_apply_btn = QPushButton("筛选")
        opp_apply_btn.setFixedHeight(28)
        opp_apply_btn.setFixedWidth(70)
        opp_apply_btn.setStyleSheet("QPushButton { background: #1890FF; color: #FFF; border: none; border-radius: 4px; font-size: 12px; } QPushButton:hover { background: #40A9FF; }")
        opp_apply_btn.clicked.connect(self._apply_opp_filter_and_close)
        ofp_f_lay.addWidget(opp_apply_btn)

        ofp_layout.addWidget(self.opp_conditions_frame, stretch=1)
        ofp_layout.addWidget(ofp_footer)
        opportunity_layout.addWidget(self.opp_filter_panel)

        # 商机表格
        opportunity_table_widget = QWidget()
        opportunity_table_layout = QVBoxLayout(opportunity_table_widget)
        opportunity_table_layout.setContentsMargins(0, 0, 0, 0)

        self.opportunity_table = QTableWidget()
        install_table_edit_context_menu(self.opportunity_table)
        install_header_alignment_menu(self.opportunity_table, 'opportunity_table_settings', self._populate_opportunity_table)
        self.opportunity_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.opportunity_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.opportunity_table.cellClicked.connect(self._on_opp_table_cell_clicked)
        self.opportunity_table.setAlternatingRowColors(True)
        self.opportunity_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.opportunity_table.verticalHeader().setVisible(False)
        # 选中行时显示该商机的授权备注
        self.opportunity_table.itemSelectionChanged.connect(self._on_opportunity_selection_changed)

        # 安装复选框表头（与CRM订单一致）+ 列头筛选
        self.opportunity_table_header = CheckBoxAutoFilterHeader(self.opportunity_table)
        self.opportunity_table.setHorizontalHeader(self.opportunity_table_header)
        self.opportunity_table_header.toggled.connect(self.on_opportunity_header_select_all_toggled)
        self.opportunity_table_header.filter_changed.connect(lambda: apply_autofilter_to_table(self.opportunity_table, self.opportunity_table_header))

        header = self.opportunity_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionsMovable(False)
        header.setStretchLastSection(False)
        header.sectionResized.connect(self._on_opportunity_column_resized)

        # 商机表格默认表头（从设置中动态获取字段映射列表）
        opp_field_mapping_list_init = self.config.get('opportunity', {}).get('field_mapping_list', [])
        if opp_field_mapping_list_init:
            opportunity_headers = [m.get('display_name', m.get('api_name', '')) for m in opp_field_mapping_list_init if m.get('api_name')]
        else:
            opportunity_headers = [
                "商机名称", "项目名称", "负责人", "意向产品（多选）", "报价（元/台）",
                "医院等级", "授权类型", "招标日期", "项目号",
                "是否招投标项目", "创建时间", "创建人"
            ]
        self.opportunity_default_headers = opportunity_headers

        # 从配置加载保存的字段显示设置（必须先加载再设置表头）
        app_set = self.config.get('app_settings', {})
        opp_set = app_set.get('opportunity_table_settings', {})
        saved_visible = opp_set.get('visible_columns', [])
        saved_order = opp_set.get('header_order', [])
        if saved_visible:
            self.opportunity_visible_columns = list(saved_visible)
        if saved_order:
            self.opportunity_header_order = list(saved_order)

        # 使用保存的列设置，否则使用默认
        init_headers = saved_visible if saved_visible else opportunity_headers
        init_display_headers = [""] + list(init_headers)
        self.opportunity_table.setColumnCount(len(init_display_headers))
        self.opportunity_table.setHorizontalHeaderLabels(init_display_headers)
        # 首列固定宽度（复选框列）
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.opportunity_table.setColumnWidth(0, 28)

        # 应用保存的列宽
        self._delayed_apply_opportunity_column_widths()

        # 初始化已选行ID集合和分页变量
        self.opportunity_selected_row_ids = set()
        self.opportunity_current_page = 1
        self.opportunity_page_size = 20
        self.opportunity_filtered_data = []

        opportunity_table_layout.addWidget(self.opportunity_table, 1)

        # 商机状态栏（仿CRM订单布局）
        opportunity_status_bar = QHBoxLayout()
        self.opportunity_status_label = QLabel("共 0 条记录")
        self.opportunity_status_label.setStyleSheet("font-weight: bold; color: #555;")
        opportunity_status_bar.addWidget(self.opportunity_status_label)

        opportunity_status_bar.addStretch()

        opportunity_status_bar.addWidget(QLabel("每页："))
        self.opportunity_page_size_combo = QComboBox()
        self.opportunity_page_size_combo.setEditable(True)
        self.opportunity_page_size_combo.addItem("自定义", -1)
        for sz in (20, 50, 80, 100, 200):
            self.opportunity_page_size_combo.addItem(str(sz), sz)
        self.opportunity_page_size_combo.setCurrentIndex(1)
        self.opportunity_page_size_combo.setFixedWidth(70)
        self.opportunity_page_size_combo.setStyleSheet("QComboBox { font-size: 11px; padding: 2px 4px; }")
        self.opportunity_page_size_combo.currentIndexChanged.connect(self._on_opp_page_size_changed)
        opportunity_status_bar.addWidget(self.opportunity_page_size_combo)

        opportunity_status_bar.addSpacing(12)

        self.opportunity_prev_btn = QPushButton("<")
        self.opportunity_prev_btn.setFixedWidth(30)
        self.opportunity_prev_btn.setFixedHeight(26)
        self.opportunity_prev_btn.clicked.connect(self._on_opp_prev_page)
        opportunity_status_bar.addWidget(self.opportunity_prev_btn)

        self.opportunity_pagination_label = QLabel("1/1")
        self.opportunity_pagination_label.setFixedWidth(50)
        self.opportunity_pagination_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.opportunity_pagination_label.setStyleSheet("font-weight: bold; color: #333;")
        opportunity_status_bar.addWidget(self.opportunity_pagination_label)

        self.opportunity_next_btn = QPushButton(">")
        self.opportunity_next_btn.setFixedWidth(30)
        self.opportunity_next_btn.setFixedHeight(26)
        self.opportunity_next_btn.clicked.connect(self._on_opp_next_page)
        opportunity_status_bar.addWidget(self.opportunity_next_btn)

        opportunity_table_layout.addLayout(opportunity_status_bar)

        opportunity_layout.addWidget(opportunity_table_widget, 2)

        main_layout.addWidget(opportunity_group, 3)

        page_layout.addWidget(main_group, 1)
        self.content_stack.addWidget(page)
        self.on_refresh_file_list()


    def create_pdf_watermark_tab(self):
        """创建PDF批量添加水印标签页"""
        pdf_tab = QFrame()
        pdf_layout = QVBoxLayout(pdf_tab)

        # 产品型号和目标文件夹并排
        top_layout = QHBoxLayout()

        # 产品型号设置
        product_group = QGroupBox("请选择文件")
        product_layout = QHBoxLayout(product_group)
        # 移除"选择文件："标签
        self.product_combo = QComboBox()
        # 从配置中加载产品型号
        config = load_config()
        pdf_config = config.get('pdf_watermark', {})
        product_models = pdf_config.get('product_models', ['产品A', '产品B', '产品C'])
        # 添加"自定义"选项作为第一个选项
        self.product_combo.addItem("自定义")
        self.product_combo.addItems(product_models)
        # 连接信号，选择产品型号后自动刷新文件列表
        self.product_combo.currentIndexChanged.connect(self.on_refresh_file_list)
        product_layout.addWidget(self.product_combo)

        # 添加路径选择框
        self.product_path_text = QLineEdit()
        self.product_path_text.setReadOnly(True)
        # 初始显示（因为默认选择的是"自定义"）
        self.product_path_text.setVisible(True)
        product_layout.addWidget(self.product_path_text)
        self.product_path_btn = QPushButton("浏览")
        self.product_path_btn.clicked.connect(self.on_browse_product_path)
        # 初始显示（因为默认选择的是"自定义"）
        self.product_path_btn.setVisible(True)
        product_layout.addWidget(self.product_path_btn)

        top_layout.addWidget(product_group)

        # 目标文件夹设置
        target_group = QGroupBox("目标文件夹")
        target_layout = QHBoxLayout(target_group)
        # 移除"文件夹路径："标签
        self.pdf_target_dir_text = QLineEdit()
        self.pdf_target_dir_text.setText(pdf_config.get('target_dir', ''))
        target_layout.addWidget(self.pdf_target_dir_text)
        self.pdf_target_dir_btn = QPushButton("浏览")
        self.pdf_target_dir_btn.clicked.connect(lambda: self.on_browse_pdf_target_dir())
        target_layout.addWidget(self.pdf_target_dir_btn)
        top_layout.addWidget(target_group)

        pdf_layout.addLayout(top_layout)

        # 水印设置
        watermark_group = QGroupBox("水印设置")
        watermark_layout = QVBoxLayout(watermark_group)

        # 水印设置区域 - 使用水平布局将水印文本和文件名后缀分开
        watermark_top_layout = QHBoxLayout()

        # 水印文本框
        watermark_text_group = QGroupBox("水印文本")
        watermark_text_group.setStyleSheet("QGroupBox { border: 1px solid #333333; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        watermark_text_layout = QHBoxLayout(watermark_text_group)
        self.watermark_text = QLineEdit()
        self.watermark_text.setText(pdf_config.get('watermark_text', '机密'))
        self.watermark_text.setPlaceholderText("请输入水印文本内容")
        watermark_text_layout.addWidget(self.watermark_text)

        # 文件名后缀框
        suffix_group = QGroupBox("文件名后缀")
        suffix_group.setStyleSheet("QGroupBox { border: 1px solid #333333; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        suffix_layout = QHBoxLayout(suffix_group)
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("可选，如：备案版")
        suffix_layout.addWidget(self.suffix_input)

        # 添加到水平布局
        watermark_top_layout.addWidget(watermark_text_group, 1)
        watermark_top_layout.addWidget(suffix_group)

        watermark_layout.addLayout(watermark_top_layout)

        # 水印位置 - 移除选项，默认居中
        # 水印位置不再作为用户可配置选项，始终使用居中位置

        # 透明度、倾斜角度、水印大小
        watermark_settings_layout = QHBoxLayout()

        # 水印透明度
        watermark_opacity_group = QGroupBox("水印透明度")
        watermark_opacity_group.setStyleSheet("QGroupBox { border: 1px solid #333333; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        watermark_opacity_layout = QHBoxLayout(watermark_opacity_group)
        # 移除"透明度："标签
        self.watermark_opacity = QSlider(Qt.Horizontal)
        self.watermark_opacity.setRange(10, 100)
        opacity_value = pdf_config.get('watermark_opacity', 50)
        self.watermark_opacity.setValue(opacity_value)
        watermark_opacity_layout.addWidget(self.watermark_opacity)
        self.watermark_opacity_label = QLabel(f"{opacity_value}%")
        self.watermark_opacity.valueChanged.connect(lambda value: self.watermark_opacity_label.setText(f"{value}%"))
        watermark_opacity_layout.addWidget(self.watermark_opacity_label)
        watermark_settings_layout.addWidget(watermark_opacity_group)

        # 水印倾斜角度
        watermark_angle_group = QGroupBox("角度")
        watermark_angle_group.setStyleSheet("QGroupBox { border: 1px solid #333333; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        watermark_angle_layout = QHBoxLayout(watermark_angle_group)
        # 移除"角度："标签
        self.watermark_angle = QSlider(Qt.Horizontal)
        self.watermark_angle.setRange(0, 360)
        angle_value = pdf_config.get('watermark_angle', 45)
        self.watermark_angle.setValue(angle_value)
        watermark_angle_layout.addWidget(self.watermark_angle)
        self.watermark_angle_label = QLabel(f"{angle_value}°")
        self.watermark_angle.valueChanged.connect(lambda value: self.watermark_angle_label.setText(f"{value}°"))
        watermark_angle_layout.addWidget(self.watermark_angle_label)
        watermark_settings_layout.addWidget(watermark_angle_group)

        # 水印大小
        watermark_font_size_group = QGroupBox("水印大小")
        watermark_font_size_group.setStyleSheet("QGroupBox { border: 1px solid #333333; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        watermark_font_size_layout = QHBoxLayout(watermark_font_size_group)
        # 移除"大小："标签
        self.watermark_font_size = QSlider(Qt.Horizontal)
        self.watermark_font_size.setRange(1, 100)
        font_size_value = pdf_config.get('watermark_font_size', 15)
        self.watermark_font_size.setValue(font_size_value)
        watermark_font_size_layout.addWidget(self.watermark_font_size)
        self.watermark_font_size_label = QLabel(f"{font_size_value}%")
        self.watermark_font_size.valueChanged.connect(lambda value: self.watermark_font_size_label.setText(f"{value}%"))
        watermark_font_size_layout.addWidget(self.watermark_font_size_label)
        watermark_settings_layout.addWidget(watermark_font_size_group)

        watermark_layout.addLayout(watermark_settings_layout)

        # 字体样式、字体颜色和PDF加密
        font_layout = QHBoxLayout()

        # 字体样式
        watermark_font_group = QGroupBox("字体样式")
        watermark_font_group.setStyleSheet("QGroupBox { border: 1px solid #333333; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        watermark_font_layout = QHBoxLayout(watermark_font_group)
        # 移除"样式："标签
        self.watermark_font = QComboBox()
        # 只显示指定的候选字体
        candidate_fonts = [
            '微软雅黑',
            '宋体',
            '仿宋',
            '新宋体',
            '微软雅黑 Light',
            '等线',
            '等线 Light',
            '方正姚体',
            '隶书',
            '黑体',
            '楷体'
        ]
        self.watermark_font.addItems(candidate_fonts)
        font_value = pdf_config.get('watermark_font', '宋体')
        if font_value in candidate_fonts:
            self.watermark_font.setCurrentText(font_value)
        # 缩小字体样式选项的大小
        self.watermark_font.setFixedWidth(120)
        watermark_font_layout.addWidget(self.watermark_font)
        font_layout.addWidget(watermark_font_group)

        # 字体颜色
        watermark_color_group = QGroupBox("字体颜色")
        watermark_color_group.setStyleSheet("QGroupBox { border: 1px solid #333333; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        watermark_color_layout = QHBoxLayout(watermark_color_group)
        # 移除"颜色："标签
        self.watermark_color = QPushButton()
        color_value = pdf_config.get('watermark_color', '#808080')  # 默认灰色
        apply_color_chip_style(self.watermark_color, color_value)
        self.watermark_color.clicked.connect(self.on_select_watermark_color)
        # 增加按钮宽度
        self.watermark_color.setFixedWidth(80)
        # 去除颜色编号输入框，只保留颜色选择按钮
        watermark_color_layout.addWidget(self.watermark_color)
        font_layout.addWidget(watermark_color_group)

        # PDF加密设置
        encrypt_group = QGroupBox("PDF密码")
        encrypt_group.setStyleSheet("QGroupBox { border: 1px solid #333333; border-radius: 4px; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }")
        encrypt_layout = QHBoxLayout(encrypt_group)
        encrypt_label = QLabel("加密：")
        encrypt_layout.addWidget(encrypt_label)
        self.encrypt_checkbox = QCheckBox()
        self.encrypt_checkbox.setChecked(pdf_config.get('encrypt_pdf', False))
        encrypt_layout.addWidget(self.encrypt_checkbox)

        self.encrypt_password_label = QLabel("密码：")
        self.encrypt_password_label.setEnabled(pdf_config.get('encrypt_pdf', False))
        self.encrypt_password = QLineEdit()
        self.encrypt_password.setEchoMode(QLineEdit.Password)
        self.encrypt_password.setText(pdf_config.get('encrypt_password', ''))
        self.encrypt_password.setEnabled(pdf_config.get('encrypt_pdf', False))
        encrypt_layout.addWidget(self.encrypt_password_label)
        encrypt_layout.addWidget(self.encrypt_password)

        # 添加眼睛图标按钮用于切换密码显示
        self.password_visibility_btn = QPushButton()
        self.password_visibility_btn.setText("👁️")
        self.password_visibility_btn.setFixedWidth(30)
        self.password_visibility_btn.setEnabled(pdf_config.get('encrypt_pdf', False))
        self.password_visibility_btn.clicked.connect(self.on_toggle_password_visibility)
        apply_password_input_height(self.encrypt_password, toggle_button=self.password_visibility_btn)
        encrypt_layout.addWidget(self.password_visibility_btn)

        # 连接信号
        self.encrypt_checkbox.stateChanged.connect(self.on_encrypt_state_changed)
        font_layout.addWidget(encrypt_group)

        watermark_layout.addLayout(font_layout)

        pdf_layout.addWidget(watermark_group)

        # 源文件选择
        source_group = QGroupBox("源文件选择")
        source_layout = QHBoxLayout(source_group)

        # 左侧：所有文件列表
        left_layout = QVBoxLayout()

        # 文件列表标题和搜索框（水平布局）
        header_layout = QHBoxLayout()
        header_layout.setSpacing(5)  # 减小标签和搜索框之间的间距
        left_label = QLabel("文件列表：")
        header_layout.addWidget(left_label)

        # 添加搜索框
        self.file_search_input = QLineEdit()
        self.file_search_input.setPlaceholderText("搜索文件名...")
        self.file_search_input.setFixedWidth(200)  # 缩小宽度
        self.file_search_input.textChanged.connect(self.on_search_files)
        header_layout.addWidget(self.file_search_input)

        # 添加弹性空间，让搜索框紧贴标签
        header_layout.addStretch()

        left_layout.addLayout(header_layout)

        self.file_list_widget = QListWidget()
        self.file_list_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        # 添加双击事件
        self.file_list_widget.itemDoubleClicked.connect(self.on_file_double_clicked)
        left_layout.addWidget(self.file_list_widget)

        # 中间：移动按钮
        center_layout = QVBoxLayout()
        center_layout.addStretch()

        self.add_btn = QPushButton(">>>")
        self.add_btn.setFixedWidth(40)  # 设置按钮宽度为40像素
        self.add_btn.clicked.connect(self.on_add_files)
        center_layout.addWidget(self.add_btn)

        self.remove_btn = QPushButton("<<<")
        self.remove_btn.setFixedWidth(40)  # 设置按钮宽度为40像素
        self.remove_btn.clicked.connect(self.on_remove_files)
        center_layout.addWidget(self.remove_btn)

        center_layout.addStretch()

        # 右侧：已选择文件列表
        right_layout = QVBoxLayout()
        right_label = QLabel("已选择文件：")
        right_layout.addWidget(right_label)

        self.selected_files_widget = QListWidget()
        self.selected_files_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        # 添加双击事件
        self.selected_files_widget.itemDoubleClicked.connect(self.on_selected_file_double_clicked)
        right_layout.addWidget(self.selected_files_widget)

        # 组装布局
        source_layout.addLayout(left_layout)
        source_layout.addLayout(center_layout)
        source_layout.addLayout(right_layout)

        pdf_layout.addWidget(source_group)

        # 按钮布局：刷新文件列表、执行PDF水印添加、清空已选择
        buttons_layout = QHBoxLayout()

        # 刷新文件列表按钮
        refresh_btn = QPushButton("刷新文件列表")
        refresh_btn.clicked.connect(self.on_refresh_file_list)
        buttons_layout.addWidget(refresh_btn)

        # 执行PDF水印添加按钮
        self.pdf_watermark_btn = QPushButton("确认生成")
        self.pdf_watermark_btn.setFixedWidth(200)
        self.pdf_watermark_btn.clicked.connect(self.on_pdf_watermark)
        buttons_layout.addWidget(self.pdf_watermark_btn)

        # 清空已选择文件按钮
        clear_btn = QPushButton("清空已选择")
        clear_btn.clicked.connect(self.on_clear_selected_files)
        buttons_layout.addWidget(clear_btn)

        pdf_layout.addLayout(buttons_layout)
        pdf_layout.addSpacing(15)

        # 添加PDF水印标签页到标签页控件
        self.tab_widget.addTab(pdf_tab, "PDF水印")

        # 初始化文件列表
        self.on_refresh_file_list()



    def on_refresh_file_list(self):
        """刷新文件列表"""
        # 从产品型号获取文件夹路径
        product_model = self.product_combo.currentText()

        # 显示/隐藏自定义路径选择框
        if product_model == "自定义":
            if hasattr(self, 'product_path_text'):
                self.product_path_text.setVisible(True)
            if hasattr(self, 'product_path_btn'):
                self.product_path_btn.setVisible(True)
            # 使用路径选择框中的路径
            source_dir = self.product_path_text.text() if hasattr(self, 'product_path_text') else ''
        else:
            if hasattr(self, 'product_path_text'):
                self.product_path_text.setVisible(False)
            if hasattr(self, 'product_path_btn'):
                self.product_path_btn.setVisible(False)
            # 从配置中获取产品对应的文件夹路径
            config = load_config()
            pdf_config = config.get('pdf_watermark', {})
            product_folders = pdf_config.get('product_folders', {})
            source_dir = product_folders.get(product_model, '')
            # 加载预设路径到路径选择框（虽然隐藏但保持同步）
            if hasattr(self, 'product_path_text'):
                self.product_path_text.setText(source_dir)

        if not source_dir:
            self.all_pdf_files = []
            self.file_list_widget.clear()
            self._update_pdf_file_select_all_state()
            return

        if not os.path.exists(source_dir):
            self.append_output(f"提示: 预设 '{product_model}' 的文件夹不存在")
            self.all_pdf_files = []
            self.file_list_widget.clear()
            self._update_pdf_file_select_all_state()
            return

        if not os.path.isdir(source_dir):
            self.append_output(f"提示: 产品 '{product_model}' 的路径不是文件夹")
            self.all_pdf_files = []
            self.file_list_widget.clear()
            self._update_pdf_file_select_all_state()
            return

        # 清空文件列表
        self.file_list_widget.clear()

        # 查找PDF文件
        import glob
        pdf_files = glob.glob(os.path.join(source_dir, "*.pdf"))

        if not pdf_files:
            self.append_output(f"提示: 产品 '{product_model}' 的文件夹中没有PDF文件")
            self.all_pdf_files = []
            self.file_list_widget.clear()
            self._update_pdf_file_select_all_state()
            return

        # 保存完整的文件列表（用于搜索过滤）
        self.all_pdf_files = [(os.path.basename(f), f) for f in pdf_files]

        # 应用当前搜索过滤（如果有）
        self._apply_file_search_filter()

        self.append_output(f"成功加载 {len(pdf_files)} 个PDF文件")


    def _apply_file_search_filter(self):
        """应用搜索过滤到文件列表"""
        # 如果当前页面没有文件列表控件，直接返回
        if not hasattr(self, 'file_list_widget'):
            return

        # 清空当前列表
        self.file_list_widget.clear()

        # 如果没有保存的完整文件列表，直接返回
        if not hasattr(self, 'all_pdf_files') or not self.all_pdf_files:
            return

        # 获取搜索关键词
        search_text = self.file_search_input.text().strip().lower() if hasattr(self, 'file_search_input') else ''

        # 过滤并显示文件
        for file_name, file_path in self.all_pdf_files:
            if not search_text or search_text in file_name.lower():
                list_item = QListWidgetItem(file_name)
                list_item.setData(Qt.UserRole, file_path)  # 存储完整路径
                self.file_list_widget.addItem(list_item)

        self._update_pdf_file_select_all_state()


    def _update_pdf_file_select_all_state(self):
        """更新招标设置列表全选复选框状态。"""
        if not hasattr(self, 'pdf_file_select_all_checkbox') or not hasattr(self, 'file_list_widget'):
            return

        total_count = self.file_list_widget.count()
        selected_count = len(self.file_list_widget.selectedItems())

        self._updating_pdf_file_select_all = True
        try:
            self.pdf_file_select_all_checkbox.setEnabled(bool(total_count))
            if total_count == 0 or selected_count == 0:
                self.pdf_file_select_all_checkbox.setCheckState(Qt.CheckState.Unchecked)
            elif selected_count == total_count:
                self.pdf_file_select_all_checkbox.setCheckState(Qt.CheckState.Checked)
            else:
                self.pdf_file_select_all_checkbox.setCheckState(Qt.CheckState.PartiallyChecked)
        finally:
            self._updating_pdf_file_select_all = False


    def on_pdf_file_select_all_toggled(self, checked):
        """切换招标设置列表当前显示项的全选状态。"""
        if getattr(self, '_updating_pdf_file_select_all', False) or not hasattr(self, 'file_list_widget'):
            return

        self.file_list_widget.blockSignals(True)
        try:
            for row in range(self.file_list_widget.count()):
                item = self.file_list_widget.item(row)
                if item is not None:
                    item.setSelected(bool(checked))
        finally:
            self.file_list_widget.blockSignals(False)

        self._update_pdf_file_select_all_state()


    def on_search_files(self):
        """搜索框文本变化时触发，实时过滤文件列表"""
        self._apply_file_search_filter()


    def on_file_double_clicked(self, item):
        """双击左侧文件列表中的文件，将其移动到右侧已选择文件列表"""
        # 获取文件名称
        file_name = item.text()
        # 直接从列表项获取完整路径（已在_apply_file_search_filter中存储）
        file_path = item.data(Qt.UserRole)

        # 如果没有存储路径，则构建路径（兼容旧逻辑）
        if not file_path:
            product_model = self.product_combo.currentText()
            config = load_config()
            pdf_config = config.get('pdf_watermark', {})
            product_folders = pdf_config.get('product_folders', {})
            source_dir = product_folders.get(product_model, '')
            file_path = os.path.join(source_dir, file_name)

        # 添加到右侧已选择文件列表（只显示文件名，存储完整路径）
        list_item = QListWidgetItem(file_name)
        list_item.setData(Qt.UserRole, file_path)  # 存储完整路径
        self.selected_files_widget.addItem(list_item)
        # 从左侧文件列表中移除
        self.file_list_widget.takeItem(self.file_list_widget.row(item))
        self._update_pdf_file_select_all_state()


    def on_selected_file_double_clicked(self, item):
        """双击右侧已选择文件列表中的文件，将其移回左侧文件列表"""
        # 获取完整文件路径
        file_path = item.data(Qt.UserRole)
        # 提取文件名
        file_name = item.text()  # 直接使用显示的文件名
        # 添加到左侧文件列表
        list_item = QListWidgetItem(file_name)
        list_item.setData(Qt.UserRole, file_path)
        self.file_list_widget.addItem(list_item)
        # 从右侧已选择文件列表中移除
        self.selected_files_widget.takeItem(self.selected_files_widget.row(item))
        self._update_pdf_file_select_all_state()


    def on_add_files(self):
        """点击">>"按钮，将左侧选中的文件移动到右侧"""
        # 获取选中的项目
        selected_items = self.file_list_widget.selectedItems()

        for item in selected_items:
            # 获取文件名称
            file_name = item.text()
            # 直接从列表项获取完整路径（已在_apply_file_search_filter中存储）
            file_path = item.data(Qt.UserRole)

            # 如果没有存储路径，则构建路径（兼容旧逻辑）
            if not file_path:
                product_model = self.product_combo.currentText()
                if product_model == "自定义":
                    source_dir = self.product_path_text.text().strip()
                else:
                    config = load_config()
                    pdf_config = config.get('pdf_watermark', {})
                    product_folders = pdf_config.get('product_folders', {})
                    source_dir = product_folders.get(product_model, '')
                file_path = os.path.join(source_dir, file_name)

            # 添加到右侧已选择文件列表（只显示文件名，存储完整路径）
            list_item = QListWidgetItem(file_name)
            list_item.setData(Qt.UserRole, file_path)  # 存储完整路径
            self.selected_files_widget.addItem(list_item)
        # 从左侧文件列表中移除选中的项目
        for item in selected_items:
            self.file_list_widget.takeItem(self.file_list_widget.row(item))
        self._update_pdf_file_select_all_state()


    def on_remove_files(self):
        """点击"<<"按钮，将右侧选中的文件移回左侧"""
        # 获取选中的项目
        selected_items = self.selected_files_widget.selectedItems()
        for item in selected_items:
            # 获取完整文件路径
            file_path = item.data(Qt.UserRole)
            # 提取文件名
            file_name = item.text()  # 直接使用显示的文件名
            # 添加到左侧文件列表
            list_item = QListWidgetItem(file_name)
            list_item.setData(Qt.UserRole, file_path)
            self.file_list_widget.addItem(list_item)
        # 从右侧已选择文件列表中移除选中的项目
        for item in selected_items:
            self.selected_files_widget.takeItem(self.selected_files_widget.row(item))
        self._update_pdf_file_select_all_state()


    def on_clear_selected_files(self):
        """清空已选择文件 - 直接清空右侧列表，不移回左侧"""
        self.selected_files_widget.clear()


    def on_browse_pdf_target_dir(self):
        """浏览目标文件夹"""
        from PyQt6.QtWidgets import QFileDialog

        # 获取输入框中的当前路径作为初始路径
        current_path = self.pdf_target_dir_text.text().strip()
        if not current_path or not os.path.exists(current_path):
            current_path = ""

        dir_path = QFileDialog.getExistingDirectory(self, "选择目标文件夹", current_path)
        if dir_path:
            self.pdf_target_dir_text.setText(dir_path)
            # 保存到配置
            config = load_config()
            if 'pdf_watermark' not in config:
                config['pdf_watermark'] = {}
            config['pdf_watermark']['target_dir'] = dir_path
            save_config_with_delay(config)


    def on_browse_pdf_source_dir(self):
        """浏览源文件夹（PDF水印功能）"""
        from PyQt6.QtWidgets import QFileDialog

        # 获取输入框中的当前路径作为初始路径
        current_path = self.pdf_source_dir_text.text().strip()
        if not current_path or not os.path.exists(current_path):
            current_path = ""

        dir_path = QFileDialog.getExistingDirectory(self, "选择源文件夹", current_path)
        if dir_path:
            self.pdf_source_dir_text.setText(dir_path)
            # 保存到配置
            config = load_config()
            if 'pdf_watermark' not in config:
                config['pdf_watermark'] = {}
            config['pdf_watermark']['source_dir'] = dir_path
            save_config_with_delay(config)


    def _sync_watermark_text(self, text):
        """同步两个水印文本框的内容"""
        sender = self.sender()
        if sender == self.watermark_text and hasattr(self, 'watermark_text_center'):
            self.watermark_text_center.blockSignals(True)
            self.watermark_text_center.setText(text)
            self.watermark_text_center.blockSignals(False)
        elif sender == self.watermark_text_center and hasattr(self, 'watermark_text'):
            self.watermark_text.blockSignals(True)
            self.watermark_text.setText(text)
            self.watermark_text.blockSignals(False)


    def on_select_watermark_color(self):
        """选择水印颜色"""
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor

        # 获取当前颜色
        # 从配置中获取当前颜色
        config = load_config()
        pdf_config = config.get('pdf_watermark', {})
        current_color_hex = pdf_config.get('watermark_color', '#808080')
        current_color = QColor(current_color_hex)

        color = QColorDialog.getColor(current_color, self, "选择水印颜色")
        if color.isValid():
            color_hex = color.name()
            apply_color_chip_style(self.watermark_color, color_hex)
            # 保存到配置
            if 'pdf_watermark' not in config:
                config['pdf_watermark'] = {}
            config['pdf_watermark']['watermark_color'] = color_hex
            save_config_with_delay(config)


    def on_encrypt_state_changed(self, state):
        """处理加密选项状态变化"""
        enabled = self.encrypt_checkbox.isChecked() if hasattr(self, 'encrypt_checkbox') else state == Qt.CheckState.Checked
        if hasattr(self, 'encrypt_password'):
            self.encrypt_password.setEnabled(enabled)
            if not enabled:
                self.encrypt_password.setEchoMode(QLineEdit.Password)


    def on_toggle_password_visibility(self):
        """切换密码显示状态"""
        if hasattr(self, 'password_toggle_btn'):
            checked = self.password_toggle_btn.isChecked()
            self.encrypt_password.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            self.password_toggle_btn.setText("🙈" if checked else "👁️")
            return
        if self.encrypt_password.echoMode() == QLineEdit.Password:
            self.encrypt_password.setEchoMode(QLineEdit.Normal)
            self.password_visibility_btn.setText("👁️‍🗨️")
        else:
            self.encrypt_password.setEchoMode(QLineEdit.Password)
            self.password_visibility_btn.setText("👁️")


    def on_pdf_watermark(self):
        """确认生成入口：商机勾选→生成文件 / PDF已选→加水印 / 两者都选→生成+水印"""
        try:
            # 检测勾选的商机（通过 opportunity_selected_row_ids）
            opp_has_selection = bool(getattr(self, 'opportunity_selected_row_ids', set()))

            # 检测已选中的PDF文件
            pdf_has_selection = False
            if hasattr(self, 'selected_files_widget'):
                for i in range(self.selected_files_widget.count()):
                    if self.selected_files_widget.item(i):
                        pdf_has_selection = True
                        break

            # 情况: 只勾选商机 → 生成文件后直接返回
            if opp_has_selection and not pdf_has_selection:
                self._do_opp_generate_files()
                return
            # 情况: 有商机+有PDF → 先生成文件，再继续加水印流程（水印输出与生成文件同目录）
            if opp_has_selection and pdf_has_selection:
                self._do_opp_generate_files()

            # 以下为PDF水印流程
            # 水印输出目录：有商机时使用生成文件的子目录，否则用PDF水印设置的目标路径
            cfg = load_config()
            opp_out = cfg.get('path_config', {}).get('opp_output_dir', '')
            saved_target = cfg.get('pdf_watermark', {}).get('target_dir', '')
            if opp_out and opp_has_selection:
                base_dir = str(resolve_app_path(opp_out))
                sub_dir = self._get_opp_first_subdir()
                target_dir = os.path.join(base_dir, sub_dir) if sub_dir else base_dir
            elif saved_target:
                target_dir = saved_target
            else:
                target_dir = self.pdf_target_dir_text.text().strip()
            product_model = self.product_combo.currentText()

            # 检查是否选择了产品型号
            if product_model == "自定义":
                # 使用自定义路径
                source_dir = self.product_path_text.text().strip()
            else:
                # 从配置中获取产品对应的文件夹路径
                config = load_config()
                pdf_config = config.get('pdf_watermark', {})
                product_folders = pdf_config.get('product_folders', {})
                source_dir = product_folders.get(product_model, '')

            watermark_text = self.watermark_text.text().strip()
            # 获取自定义后缀
            file_suffix = self.suffix_input.text().strip()
            watermark_position = "中央"  # 默认居中
            watermark_opacity = self.watermark_opacity.value() / 100.0
            watermark_angle = self.watermark_angle.value()
            watermark_font = self.watermark_font.currentText()
            watermark_font_size = self.watermark_font_size.value()
            # 从配置中获取当前颜色
            config = load_config()
            pdf_config = config.get('pdf_watermark', {})
            watermark_color = pdf_config.get('watermark_color', '#808080')
            encrypt_pdf = self.encrypt_checkbox.isChecked()
            encrypt_password = self.encrypt_password.text() if encrypt_pdf else ""

            # 检查源文件夹
            if not source_dir:
                if product_model == "自定义":
                    self.append_output("提示: 请选择文件路径")
                else:
                    self.append_output(f"提示: 请在设置界面为产品 '{product_model}' 配置PDF文件夹路径")
                return

            if not os.path.exists(source_dir):
                if product_model == "自定义":
                    self.append_output(f"提示: 选择的文件夹不存在: {source_dir}")
                else:
                    self.append_output(f"提示: 产品 '{product_model}' 的文件夹不存在")
                return

            if not os.path.isdir(source_dir):
                if product_model == "自定义":
                    self.append_output(f"提示: 选择的路径不是文件夹: {source_dir}")
                else:
                    self.append_output(f"提示: 产品 '{product_model}' 的路径不是文件夹")
                return

            # 检查目标文件夹
            if not target_dir:
                self.append_output("提示: 请选择目标文件夹")
                return

            # 检查水印文本
            if not watermark_text:
                self.append_output("提示: 请输入水印文本")
                return

            # 检查选择的文件
            selected_count = self.selected_files_widget.count()
            if selected_count == 0:
                self.append_output("提示: 请至少选择一个PDF文件")
                return

            # 获取选择的文件路径
            selected_files = []
            for i in range(selected_count):
                item = self.selected_files_widget.item(i)
                file_path = item.data(Qt.ItemDataRole.UserRole)
                if not file_path:
                    self.append_output(f"警告: 文件 '{item.text()}' 路径无效，已跳过")
                    continue
                selected_files.append(file_path)
                self.append_output(f"选中的文件 {i+1}: {os.path.basename(str(file_path))}")

            # 保存配置
            if 'pdf_watermark' not in config:
                config['pdf_watermark'] = {}
            # 保存产品型号时排除"自定义"选项
            product_models = []
            for i in range(self.product_combo.count()):
                item_text = self.product_combo.itemText(i)
                if item_text != "自定义":
                    product_models.append(item_text)
            config['pdf_watermark']['product_models'] = product_models
            config['pdf_watermark']['target_dir'] = target_dir
            config['pdf_watermark']['watermark_text'] = watermark_text
            config['pdf_watermark']['file_suffix'] = file_suffix  # 保存后缀设置
            # 移除水印位置配置，默认居中
            # config['pdf_watermark']['watermark_position'] = self.watermark_position.currentIndex()
            config['pdf_watermark']['watermark_opacity'] = self.watermark_opacity.value()
            config['pdf_watermark']['watermark_angle'] = watermark_angle
            config['pdf_watermark']['watermark_font'] = watermark_font
            config['pdf_watermark']['watermark_font_size'] = watermark_font_size
            config['pdf_watermark']['watermark_color'] = watermark_color
            config['pdf_watermark']['encrypt_pdf'] = encrypt_pdf
            config['pdf_watermark']['encrypt_password'] = encrypt_password
            save_config_with_delay(config)

            # 执行PDF水印添加
            self.append_output(f"\n=== 开始PDF水印添加 ===")
            self.append_output(f"源文件夹: {source_dir}")
            self.append_output(f"目标文件夹: {target_dir}")
            self.append_output(f"选择的文件数量: {len(selected_files)}")
            for i, file_path in enumerate(selected_files):
                self.append_output(f"文件 {i+1}: {os.path.basename(file_path)}")
            self.append_output(f"水印文本: {watermark_text}")
            self.append_output(f"水印位置: {watermark_position}")
            self.append_output(f"水印透明度: {watermark_opacity:.2f}")
            self.append_output(f"水印角度: {watermark_angle}°")
            self.append_output(f"字体样式: {watermark_font}")
            self.append_output(f"字体大小: {watermark_font_size}%")
            self.append_output(f"字体颜色: {watermark_color}")

            # 禁用按钮并更新文本
            self.pdf_watermark_btn.setEnabled(False)
            self.pdf_watermark_btn.setText("请稍后>>>>>")

            # 在后台线程中执行处理
            thread = threading.Thread(target=self.process_pdf_watermark, args=(source_dir, target_dir, selected_files, watermark_text, file_suffix, watermark_position, watermark_opacity, watermark_angle, watermark_font, watermark_font_size, watermark_color, encrypt_pdf, encrypt_password))
            thread.daemon = True
            thread.start()

        except Exception as e:
            self._enable_pdf_watermark_button()
            show_error("错误", f"执行PDF水印添加失败: {str(e)}")
            self.append_output(f"\n=== PDF水印添加失败 ===")
            self.append_output(f"错误信息: {str(e)}")
            self.append_output("====================")


    def process_pdf_watermark(self, source_dir, target_dir, selected_files, watermark_text, file_suffix, watermark_position, watermark_opacity, watermark_angle, watermark_font, watermark_font_size, watermark_color, encrypt_pdf, encrypt_password):
        """处理PDF水印添加"""
        _original_append_output = self.append_output
        try:
            # 导入必要的库
            import pypdf
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.colors import HexColor
            import io
            import os

            # 高频逐页日志会显著拖慢水印速度，这里仅保留关键信息。
            suppressed_prefixes = (
                "处理页面 ",
                "📄 第 ",
                "   MediaBox:",
                "   CropBox:",
                "   旋转角度:",
                "   水印中心坐标:",
                "页面 ",
                "水印文本过长",
                "水印文本长度合适",
                "当前字体:",
                "成功设置颜色:",
                "成功设置透明度:",
                "尝试加载字体:",
                "字体 ",
                "使用备用字体:",
                "尝试备用字体 ",
                "✅ 第 ",
            )

            def _fast_append_output(text):
                """内部方法：处理fastappend输出逻辑。"""
                msg = str(text)
                if msg.startswith(suppressed_prefixes):
                    return
                _original_append_output(msg)

            self.append_output = _fast_append_output

            # 输出函数参数，便于诊断
            self.append_output(f"=== 开始PDF水印添加 ===")
            self.append_output(f"目标文件夹: {target_dir}")
            self.append_output(f"选择的文件数量: {len(selected_files)}")
            self.append_output(f"水印参数: 文本='{watermark_text}', 字体={watermark_font}, 大小={watermark_font_size}, 颜色={watermark_color}, 透明度={watermark_opacity}, 角度={watermark_angle}, 位置={watermark_position}")
            self.append_output(f"加密参数: encrypt_pdf={encrypt_pdf}, encrypt_password={encrypt_password}")
            self.append_output(f"pypdf版本: {pypdf.__version__}")

            # 确保目标文件夹存在
            os.makedirs(target_dir, exist_ok=True)

            # 检查选择的文件
            if not selected_files:
                self.append_output(f"错误: 没有选择PDF文件")
                return

            processed_count = 0
            total_files = len(selected_files)
            self.append_output(f"开始处理 {total_files} 个文件")

            # 处理每个PDF文件
            for index, pdf_path in enumerate(selected_files):
                original_filename = os.path.basename(pdf_path)
                # 处理文件名后缀
                if file_suffix and file_suffix.strip():
                    # 有后缀，添加后缀：原文件名 - 后缀.pdf
                    name_parts = os.path.splitext(original_filename)
                    filename = f"{name_parts[0]}-{file_suffix.strip()}{name_parts[1]}"
                    self.append_output(f"原文件名：{original_filename} | 后缀：{file_suffix} | 新文件名：{filename}")
                else:
                    # 无后缀，使用原文件名
                    filename = original_filename
                self.append_output(f"\n=====================================")
                self.append_output(f"处理文件 {index + 1}/{total_files}: {filename}")
                self.append_output(f"文件路径: {pdf_path}")
                self.append_output(f"=====================================")

                try:
                    # 验证文件存在
                    if not os.path.exists(pdf_path):
                        self.append_output(f"错误: 文件不存在: {pdf_path}")
                        continue

                    # 验证文件是PDF
                    if not pdf_path.lower().endswith('.pdf'):
                        self.append_output(f"错误: 不是PDF文件: {pdf_path}")
                        continue

                    # 验证文件大小
                    file_size = os.path.getsize(pdf_path)
                    if file_size == 0:
                        self.append_output(f"错误: 文件为空: {pdf_path}")
                        continue

                    self.append_output(f"文件大小: {file_size} 字节")

                    # 读取PDF文件
                    with open(pdf_path, 'rb') as file:
                        try:
                            reader = pypdf.PdfReader(file)
                            self.append_output(f"成功创建PDF阅读器实例")

                            # 检查PDF是否有效
                            if len(reader.pages) == 0:
                                self.append_output(f"警告: PDF文件没有页面: {filename}")
                                continue

                            # 检查PDF是否加密
                            if reader.is_encrypted:
                                self.append_output(f"警告: PDF文件已加密: {filename}")
                                try:
                                    # 尝试使用空密码解密
                                    reader.decrypt('')
                                    self.append_output(f"成功使用空密码解密PDF")
                                except Exception as decrypt_error:
                                    self.append_output(f"解密PDF失败: {str(decrypt_error)}")
                                    continue

                            # 创建PDF写入器，将原文件的内容拷贝到一个新的 PdfWriter 中，不直接复用 PdfReader 中的对象引用
                            # 这样可以断开长PDF对原始大文件流缓存依赖的某些状态
                            writer = pypdf.PdfWriter()
                            self.append_output(f"成功创建PDF写入器实例")
                        except Exception as read_error:
                            self.append_output(f"读取PDF文件失败: {str(read_error)}")
                            import traceback
                            self.append_output(f"读取错误详情: {traceback.format_exc()}")
                            continue

                        # 处理每一页
                        page_count = len(reader.pages)
                        self.append_output(f"PDF页数: {page_count}")

                        # 核心修改：在循环外不保留旧状态，确保循环内每页的数据隔离
                        import gc

                        for page_num in range(page_count):
                            # 手动执行垃圾回收，清理上一页可能残留的 pypdf 和 reportlab 内存对象
                            if page_num > 0 and page_num % 30 == 0:
                                gc.collect()

                            try:
                                # 每次都从原始 reader 重新获取当前页的独立引用
                                page = reader.pages[page_num]
                                self.append_output(f"处理页面 {page_num + 1}/{page_count}")

                                # 获取页面大小，使用 mediabox 并考虑 origin
                                try:
                                    if hasattr(page, 'cropbox'):
                                        box = page.cropbox
                                        box_type = "CropBox"
                                    else:
                                        box = page.mediabox
                                        box_type = "MediaBox"

                                    width = float(box.width)
                                    height = float(box.height)
                                    left = float(box.left)
                                    bottom = float(box.bottom)

                                    self.append_output(f"📄 第 {page_num + 1} 页 | 边界框: {box_type}, 尺寸: {width:.2f}x{height:.2f}, 起点: ({left:.2f}, {bottom:.2f})")
                                    if hasattr(page, 'mediabox'):
                                        self.append_output(f"   MediaBox: {page.mediabox}")
                                    if hasattr(page, 'cropbox'):
                                        self.append_output(f"   CropBox: {page.cropbox}")
                                except Exception as size_error:
                                    self.append_output(f"获取页面大小失败: {str(size_error)}")
                                    width, height = letter
                                    left, bottom = 0.0, 0.0
                                    self.append_output(f"使用默认页面大小: {width:.2f}x{height:.2f}")

                                # 处理页面旋转
                                page_rotation = page.get('/Rotate', 0)
                                self.append_output(f"   旋转角度: {page_rotation}°")
                                if isinstance(page_rotation, int) and (page_rotation == 90 or page_rotation == 270):
                                    visual_width, visual_height = height, width
                                else:
                                    visual_width, visual_height = width, height
                                    page_rotation = 0

                                # 计算水印字体大小
                                # 根据页面尺寸和用户设定的比例计算
                                # 字体最大30
                                max_font_size = 30
                                # 计算页面对角线长度作为参考
                                import math
                                diagonal = math.sqrt(visual_width**2 + visual_height**2)
                                # 根据用户设定的比例计算字体大小
                                # watermark_font_size 是百分比值 (1-100)
                                calculated_font_size = (diagonal * watermark_font_size / 100) / 10
                                # 限制最大字体大小为30
                                actual_font_size = min(max_font_size, max(8, calculated_font_size))

                                # 生成水印 (创建一个大小覆盖 CropBox/MediaBox 的 Canvas)
                                # 为确保不会相互干扰，使用纯净的全新的流对象
                                packet = io.BytesIO()
                                c = canvas.Canvas(packet, pagesize=(left + width, bottom + height))

                                # 导入字体相关库
                                from reportlab.pdfbase import pdfmetrics
                                from reportlab.pdfbase.ttfonts import TTFont
                                import os

                                # 设置字体
                                try:
                                    # 输出字体加载开始信息
                                    self.append_output(f"尝试加载字体: {watermark_font}")

                                    # 字体映射，将中文名称映射到英文名称
                                    font_mapping = {
                                        '微软雅黑': 'Microsoft YaHei',
                                        '微软雅黑 Light': 'Microsoft YaHei Light',
                                        '等线': 'Dengxian',
                                        '等线 Light': 'Dengxian Light',
                                        '仿宋': 'FangSong',
                                        '新宋体': 'NSimSun',
                                        '方正姚体': 'FZYaoTi',
                                        '黑体': 'SimHei',
                                        '宋体': 'SimSun',
                                        '楷体': 'KaiTi',
                                        '隶书': 'LiSu'
                                    }

                                    # 获取字体名称
                                    font_name = font_mapping.get(watermark_font, watermark_font)

                                    # 尝试注册字体
                                    font_registered = False

                                    # 为了解决循环中的字体缓存/多次注册冲突，如果字体已经注册过，直接标记为成功
                                    if font_name in pdfmetrics.getRegisteredFontNames():
                                        font_registered = True
                                        self.append_output(f"字体 {font_name} 已在之前的页面注册过")
                                    else:
                                        try:
                                            # 尝试获取字体，如果不存在会抛出异常
                                            pdfmetrics.getFont(font_name)
                                            font_registered = True
                                            self.append_output(f"字体 {font_name} 存在于内存缓存中")
                                        except:
                                            # 字体未注册，尝试从系统字体目录加载
                                            try:
                                                # 获取Windows字体目录
                                                font_dir = os.environ.get('WINDIR', 'C:\\Windows') + '\\Fonts'

                                                # 字体文件映射
                                                font_files = {
                                                    'Microsoft YaHei': 'msyh.ttc',  # 修复为 ttc
                                                    'Microsoft YaHei Light': 'msyhl.ttc', # 修复为 ttc
                                                    'Dengxian': 'deng.ttf', # 修复等线文件名
                                                    'Dengxian Light': 'dengl.ttf', # 修复等线文件名
                                                    'FangSong': 'simfang.ttf',
                                                    'NSimSun': 'simsun.ttc', # 新宋体通常在 simsun.ttc 中
                                                    'FZYaoTi': 'fzyaoti.ttf',
                                                    'SimHei': 'simhei.ttf',
                                                    'SimSun': 'simsun.ttc',
                                                    'KaiTi': 'simkai.ttf',
                                                    'LiSu': 'simli.ttf', # 修复隶书文件名
                                                    'Arial': 'arial.ttf'
                                                }

                                                if font_name in font_files:
                                                    font_file = font_files[font_name]
                                                    font_path = os.path.join(font_dir, font_file)

                                                    # 尝试几个常见的字体后缀
                                                    if not os.path.exists(font_path):
                                                        base_name = os.path.splitext(font_file)[0]
                                                        for ext in ['.ttf', '.ttc', '.otf']:
                                                            test_path = os.path.join(font_dir, base_name + ext)
                                                            if os.path.exists(test_path):
                                                                font_path = test_path
                                                                break

                                                    if os.path.exists(font_path):
                                                        # 注册字体
                                                        pdfmetrics.registerFont(TTFont(font_name, font_path))
                                                        font_registered = True
                                                        self.append_output(f"成功注册字体: {font_name} 从 {font_path}")
                                                    else:
                                                        self.append_output(f"字体文件不存在: {font_path}")
                                                else:
                                                    self.append_output(f"未知字体: {font_name}")
                                            except Exception as e:
                                                self.append_output(f"注册字体失败: {str(e)}")

                                    # 尝试使用字体
                                    font_used = False
                                    if font_registered:
                                        try:
                                            c.setFont(font_name, actual_font_size)
                                            font_used = True
                                            self.append_output(f"成功使用字体: {font_name}")
                                        except Exception as e:
                                            self.append_output(f"使用字体失败: {str(e)}")

                                    # 如果注册的字体失败，尝试使用备用字体
                                    if not font_used:
                                        fallback_fonts = ['SimHei', 'SimSun', 'KaiTi', 'Microsoft YaHei', 'Arial', 'Helvetica']
                                        for font in fallback_fonts:
                                            try:
                                                if font in pdfmetrics.getRegisteredFontNames():
                                                    c.setFont(font, actual_font_size)
                                                    font_used = True
                                                    self.append_output(f"使用已注册的备用字体: {font}")
                                                    break

                                                # 尝试注册备用字体
                                                try:
                                                    pdfmetrics.getFont(font)
                                                except:
                                                    # 尝试从系统字体目录加载
                                                    font_dir = os.environ.get('WINDIR', 'C:\\Windows') + '\\Fonts'
                                                    font_files = {
                                                        'SimHei': 'simhei.ttf',
                                                        'SimSun': 'simsun.ttc',
                                                        'KaiTi': 'simkai.ttf',
                                                        'Microsoft YaHei': 'msyh.ttc',
                                                        'Arial': 'arial.ttf'
                                                    }
                                                    if font in font_files:
                                                        font_file = font_files[font]
                                                        font_path = os.path.join(font_dir, font_file)
                                                        if not os.path.exists(font_path):
                                                            base_name = os.path.splitext(font_file)[0]
                                                            for ext in ['.ttf', '.ttc', '.otf']:
                                                                test_path = os.path.join(font_dir, base_name + ext)
                                                                if os.path.exists(test_path):
                                                                    font_path = test_path
                                                                    break

                                                        if os.path.exists(font_path):
                                                            pdfmetrics.registerFont(TTFont(font, font_path))

                                                # 使用备用字体
                                                c.setFont(font, actual_font_size)
                                                font_used = True
                                                self.append_output(f"使用备用字体: {font}")
                                                break
                                            except Exception as e:
                                                self.append_output(f"尝试备用字体 {font} 失败: {str(e)}")
                                                continue

                                    # 最后的 fallback
                                    if not font_used:
                                        c.setFont("Helvetica", actual_font_size)
                                        self.append_output(f"所有字体尝试失败，使用默认字体 Helvetica")
                                except Exception as e:
                                    # 最后的 fallback
                                    c.setFont("Helvetica", actual_font_size)
                                    self.append_output(f"字体加载失败: {str(e)}")

                                # 确认字体是否成功设置
                                self.append_output(f"当前字体: {c._fontname}, 字体大小: {actual_font_size}")

                                # 解析颜色
                                try:
                                    color = HexColor(watermark_color)
                                    c.setFillColor(color)
                                    self.append_output(f"成功设置颜色: {watermark_color}")
                                except Exception as e:
                                    # 如果颜色解析失败，使用默认灰色
                                    c.setFillColorRGB(0.6, 0.6, 0.6)
                                    self.append_output(f"警告: 颜色 {watermark_color} 无效，使用默认灰色, 错误: {str(e)}")

                                # 设置透明度
                                try:
                                    c.setFillAlpha(watermark_opacity)
                                    self.append_output(f"成功设置透明度: {watermark_opacity:.2f}")
                                except Exception as e:
                                    self.append_output(f"设置透明度失败: {str(e)}")
                                    pass

                                # 计算水印位置（考虑页面原点 left 和 bottom，以及页面的旋转状态）
                                # 对于居中对齐，使用 MediaBox/CropBox 的绝对中心坐标
                                center_x = left + width / 2
                                center_y = bottom + height / 2

                                if watermark_position == "中央":
                                    x = center_x
                                    y = center_y
                                elif watermark_position == "左上角":
                                    if page_rotation == 90:
                                        x = left + width - 100
                                        y = bottom + height - 100
                                    elif page_rotation == 270:
                                        x = left + 100
                                        y = bottom + 100
                                    else:
                                        x = left + 100
                                        y = bottom + height - 100
                                elif watermark_position == "右上角":
                                    if page_rotation == 90:
                                        x = left + width - 100
                                        y = bottom + 100
                                    elif page_rotation == 270:
                                        x = left + 100
                                        y = bottom + height - 100
                                    else:
                                        x = left + width - 100
                                        y = bottom + height - 100
                                elif watermark_position == "左下角":
                                    if page_rotation == 90:
                                        x = left + 100
                                        y = bottom + height - 100
                                    elif page_rotation == 270:
                                        x = left + width - 100
                                        y = bottom + 100
                                    else:
                                        x = left + 100
                                        y = bottom + 100
                                elif watermark_position == "右下角":
                                    if page_rotation == 90:
                                        x = left + 100
                                        y = bottom + 100
                                    elif page_rotation == 270:
                                        x = left + width - 100
                                        y = bottom + height - 100
                                    else:
                                        x = left + width - 100
                                        y = bottom + 100
                                else:
                                    # 默认居中
                                    x = center_x
                                    y = center_y

                                self.append_output(f"   水印中心坐标: ({x:.2f}, {y:.2f})")

                                # 对于文本的自动换行，基于视觉宽度计算
                                is_landscape = visual_width > visual_height
                                if is_landscape:
                                    max_text_width = visual_width * 0.85
                                else:
                                    max_text_width = visual_width * 0.99
                                def wrap_text(text, font_size, max_width, canvas):
                                    """自动换行文本，支持长字符串换行"""
                                    lines = []
                                    current_line = ""
                                    # 先按空格分割成单词
                                    words = text.split()

                                    for word in words:
                                        # 计算单词宽度
                                        word_width = canvas.stringWidth(word, canvas._fontname, font_size)

                                        # 如果单词本身就超过最大宽度，需要在单词内部换行
                                        if word_width > max_width:
                                            # 单词内部换行
                                            current_word = ""
                                            for char in word:
                                                test_word = current_word + char
                                                test_width = canvas.stringWidth(test_word, canvas._fontname, font_size)
                                                if test_width > max_width:
                                                    # 当前字符会导致超出宽度，先添加当前单词到行
                                                    if current_line:
                                                        lines.append(current_line)
                                                        current_line = ""
                                                    lines.append(current_word)
                                                    current_word = char
                                                else:
                                                    current_word = test_word
                                            # 添加最后一部分
                                            if current_word:
                                                if current_line:
                                                    lines.append(current_line)
                                                    current_line = ""
                                                lines.append(current_word)
                                        else:
                                            # 计算添加当前单词后的宽度
                                            test_line = current_line + (" " if current_line else "") + word
                                            test_width = canvas.stringWidth(test_line, canvas._fontname, font_size)

                                            if test_width <= max_width:
                                                # 可以添加到当前行
                                                if current_line:
                                                    current_line += " " + word
                                                else:
                                                    current_line = word
                                            else:
                                                # 换行
                                                if current_line:
                                                    lines.append(current_line)
                                                current_line = word

                                    # 添加最后一行
                                    if current_line:
                                        lines.append(current_line)

                                    # 确保换行顺序正确（从上到下）
                                    # 这里返回的lines列表已经是正确的顺序，因为我们是按顺序添加的
                                    return lines

                                # 计算水印文本的宽度
                                text_width = c.stringWidth(watermark_text, c._fontname, actual_font_size)

                                # 输出详细的宽度信息，便于调试
                                self.append_output(f"页面 {page_num + 1} - 文本宽度: {text_width:.2f}, 最大宽度: {max_text_width:.2f}, 字体大小: {actual_font_size}, 页面大小: {width:.2f}x{height:.2f}, 视觉大小: {visual_width:.2f}x{visual_height:.2f}")

                                # 自动换行
                                if text_width > max_text_width:
                                    wrapped_lines = wrap_text(watermark_text, actual_font_size, max_text_width, c)
                                    self.append_output(f"水印文本过长，自动换行处理，行数: {len(wrapped_lines)}")
                                else:
                                    wrapped_lines = [watermark_text]
                                    self.append_output(f"水印文本长度合适，无需换行")

                                # 计算文本总高度
                                line_height = actual_font_size * 1.2  # 行高
                                total_text_height = len(wrapped_lines) * line_height

                                # 绘制水印 - 只绘制一个水印
                                c.saveState()

                                # 移动到水印位置并旋转
                                c.translate(x, y)  # 移动到中心点
                                # 注意：如果页面有旋转，我们需要抵消或增加旋转角度
                                actual_angle = watermark_angle - page_rotation
                                c.rotate(actual_angle)

                                # 计算起始Y坐标，确保文本从顶部开始绘制
                                start_y = total_text_height / 2 - line_height / 2

                                # 对于文本透明度，显式使用 RGB 颜色同时附带 alpha
                                try:
                                    c.setFillColorRGB(color.red, color.green, color.blue, watermark_opacity)
                                except Exception:
                                    pass

                                # 绘制每一行文本，确保顺序正确（从上到下）
                                for i, line in enumerate(wrapped_lines):
                                    line_y = start_y - i * line_height
                                    # 确保文本居中绘制
                                    c.drawCentredString(0, line_y, line)

                                # 恢复状态
                                c.restoreState()
                                # 确保在尝试读取之前将 canvas 彻底写入 packet
                                c.save()

                                # 读取水印（如果每页都要合并，需要每次都创建一个新的 PdfReader 实例以防流状态耗尽）
                                try:
                                    # 确保流回到最前面
                                    packet.seek(0)
                                    # 将内存中的 BytesIO 读取为独立的数据流，确保不受其它页面读取影响
                                    watermark_bytes = packet.getvalue()

                                    # 利用全新的内存流实例化读取器
                                    watermark_pdf = pypdf.PdfReader(io.BytesIO(watermark_bytes))
                                    watermark_page = watermark_pdf.pages[0]

                                    # 同步水印页面的各种 Box 到原页面，防止对齐错乱
                                    # 这里极其关键，很多带有偏移的PDF，如果没有对齐会导致水印跑到页面外面
                                    if hasattr(page, 'mediabox'):
                                        watermark_page.mediabox = page.mediabox
                                    if hasattr(page, 'cropbox'):
                                        watermark_page.cropbox = page.cropbox
                                    if hasattr(page, 'bleedbox'):
                                        watermark_page.bleedbox = page.bleedbox
                                    if hasattr(page, 'trimbox'):
                                        watermark_page.trimbox = page.trimbox
                                    if hasattr(page, 'artbox'):
                                        watermark_page.artbox = page.artbox

                                    # 对于存在旋转的页面，水印也必须赋予相同的旋转元数据属性
                                    # 否则在某些阅读器中，合并后水印会转90度
                                    if page_rotation != 0:
                                        watermark_page.rotate(page_rotation)

                                    # 执行合并
                                    # 注意：为了彻底解决白底遮挡问题，我们将水印页面作为底层(under)合并到原页面
                                    # 这样可以避免覆盖原页面的交互元素，但如果原页面不透明，水印需要设置在最上方(over)
                                    # 某些文档(如扫描件)全是不透明图片，如果放底层(under)会完全看不见
                                    # 因此我们强制置顶 over=True，这是最保险的策略
                                    try:
                                        # 在 pypdf>=3.0 中，merge_page 默认是在底层，如果 over=True 则是在表层
                                        # 为了确保绝对不会被遮挡，并且断开引用，我们反向操作：
                                        # 将原始页面 merge 到水印页面（或者强制要求水印在顶层）
                                        # 新版 pypdf 中，merge_page 可以通过 over 参数控制图层
                                        watermark_page.merge_page(page, over=False)
                                        # 使用 watermark_page 作为基础页来覆盖原页，保证水印绝对在顶层
                                        page = watermark_page
                                    except Exception:
                                        # 如果不支持 over 参数，就直接在原页面 merge 水印
                                        page.merge_page(watermark_page)

                                    self.append_output(f"✅ 第 {page_num + 1} 页：水印合并成功！")
                                except Exception as e:
                                    self.append_output(f"❌ 第 {page_num + 1} 页：水印合并失败，错误原因: {str(e)}")
                                    import traceback
                                    self.append_output(traceback.format_exc())
                                    raise e  # 抛出异常，让外层捕获并回退到添加原始页面

                                # 添加页面到写入器
                                # 处理完一页后，更新写入器
                                writer.add_page(page)
                                self.append_output(f"✅ 第 {page_num + 1} 页：成功添加页面到写入器")

                                # 强制清理内存流
                                packet.close()
                                del packet
                                del c
                                del watermark_bytes
                                del watermark_pdf
                                del watermark_page

                            except Exception as e:
                                self.append_output(f"❌ 第 {page_num + 1} 页：处理失败: {str(e)}")
                                import traceback
                                self.append_output(traceback.format_exc())
                                # 发生错误时，回退添加原始页面
                                try:
                                    writer.add_page(reader.pages[page_num])
                                    self.append_output(f"⚠️ 第 {page_num + 1} 页：已回退添加原始页面")
                                except Exception as inner_e:
                                    self.append_output(f"❌ 第 {page_num + 1} 页：连原始页面也无法添加: {str(inner_e)}")

                        # 设置PDF密码
                        encryption_success = False
                        if encrypt_pdf:
                            try:
                                self.append_output(f"开始设置PDF加密，密码长度: {len(encrypt_password)}")
                                self.append_output(f"encrypt_pdf: {encrypt_pdf}")
                                self.append_output(f"encrypt_password: {encrypt_password}")

                                # 检查pypdf版本
                                import pypdf
                                version = pypdf.__version__
                                self.append_output(f"pypdf版本: {version}")
                                self.append_output(f"目标: 查看不用密码，编辑需要密码")

                                # 尝试不同的加密方法，确保兼容性
                                # 方法1: 使用permissions_flag参数（PyPDF2 3.0+）
                                try:
                                    self.append_output("尝试方法1: 使用permissions_flag参数")
                                    # 只允许查看和打印，禁止编辑
                                    writer.encrypt(
                                        user_password="",  # 查看无需密码
                                        owner_password=encrypt_password,  # 编辑需要密码
                                        use_128bit=True,  # 使用128位加密
                                        permissions_flag=4 + 512 + 2048  # 允许打印、屏幕阅读器、降级打印
                                    )
                                    self.append_output(f"成功设置PDF加密（方法1）")
                                    encryption_success = True
                                except Exception as e1:
                                    self.append_output(f"方法1失败: {str(e1)}")
                                    # 方法2: 使用简单方法
                                    try:
                                        self.append_output("尝试方法2: 使用简单方法")
                                        writer.encrypt(
                                            user_password="",  # 查看无需密码
                                            owner_password=encrypt_password  # 编辑需要密码
                                        )
                                        self.append_output(f"成功设置PDF加密（方法2）")
                                        encryption_success = True
                                    except Exception as e2:
                                        self.append_output(f"方法2失败: {str(e2)}")
                                        # 方法3: 尝试使用旧版本参数名
                                        try:
                                            self.append_output("尝试方法3: 使用旧版本参数名")
                                            writer.encrypt(
                                                user_pwd="",  # 查看无需密码
                                                owner_pwd=encrypt_password  # 编辑需要密码
                                            )
                                            self.append_output(f"成功设置PDF加密（方法3）")
                                            encryption_success = True
                                        except Exception as e3:
                                            self.append_output(f"方法3失败: {str(e3)}")
                            except Exception as e:
                                self.append_output(f"加密设置失败: {str(e)}")
                                import traceback
                                self.append_output(f"加密错误详情: {traceback.format_exc()}")
                        else:
                            self.append_output(f"未启用PDF加密")

                        self.append_output(f"加密状态: {'成功' if encryption_success else '失败'}")
                        if encryption_success:
                            self.append_output(f"设置完成: 查看无需密码，编辑需要密码")
                            self.append_output(f"注意: PDF权限控制主要影响PDF阅读器的行为，而不是所有PDF处理库")
                            self.append_output(f"在大多数PDF阅读器中，尝试编辑时会要求输入密码: {encrypt_password}")
                        else:
                            self.append_output(f"加密失败: PDF可能仍然可以编辑")

                        # 保存输出文件
                        output_path = os.path.join(target_dir, filename)
                        self.append_output(f"准备保存文件到: {output_path}")
                        try:
                            with open(output_path, 'wb') as output_file:
                                # 写入文件
                                writer.write(output_file)
                            self.append_output(f"文件保存成功")

                            # 验证文件是否成功保存
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                processed_count += 1
                                self.append_output(f"成功添加水印: {filename}")
                            else:
                                self.append_output(f"警告: 文件保存后为空或不存在")
                        except Exception as save_error:
                            self.append_output(f"保存文件失败: {str(save_error)}")
                            import traceback
                            self.append_output(f"保存错误详情: {traceback.format_exc()}")

                except Exception as e:
                    self.append_output(f"处理文件 {filename} 失败: {str(e)}")
                    import traceback
                    self.append_output(f"错误详情: {traceback.format_exc()}")

            self.append_output(f"\n=== PDF水印添加完成 ===")
            self.append_output(f"成功处理 {processed_count} 个文件")
            self.append_output(f"失败 {total_files - processed_count} 个文件")

            # 打开目标文件夹（受通用设置控制）
            if self.config.get('app_settings', {}).get('open_output_folder', True):
                open_folder(target_dir)

            # 提交到SVN
            self.commit_to_svn(target_dir)

        except Exception as e:
            self.append_output(f"\n=== PDF水印添加失败 ===")
            self.append_output(f"错误信息: {str(e)}")
            import traceback
            self.append_output(f"错误详情: {traceback.format_exc()}")
        finally:
            self.append_output = _original_append_output
            # 启用按钮
            self.enable_pdf_watermark_button.emit()


    def _enable_pdf_watermark_button(self):
        """启用PDF水印按钮并恢复文本"""
        if hasattr(self, 'pdf_watermark_btn'):
            self.pdf_watermark_btn.setEnabled(True)
            self.pdf_watermark_btn.setText("执行PDF水印添加")

