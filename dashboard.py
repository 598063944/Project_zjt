# -*- coding: utf-8 -*-
"""
dashboard.py — 仪表盘设计器/查看器 Mixin
────────────────────────────────────────
负责：MainFrame 中仪表盘页面
  - create_dashboard_page()   创建页面（加入 content_stack）
  - 仪表盘列表（新建/编辑/删除/查看）
  - 仪表盘设计器（添加图表、配置数据源/字段、拖拽布局）
  - 仪表盘查看器（只读展示，ECharts 渲染）
依赖：core.py / common.py / chart_engine.py / custom_report (ReportManager)
被导入：主程序（作为 MainFrame 的 Mixin 父类）
"""

from core import *
from common import *
from common import frameless_input_text, frameless_message_box

import json
import logging
import os
import uuid
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QPushButton, QLabel,
    QComboBox, QLineEdit, QStackedWidget, QScrollArea, QWidget,
    QGridLayout, QSizePolicy, QInputDialog, QSpinBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QUrl, QTimer, QThread, pyqtSignal, QObject
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtGui import QColor, QFont

logger = logging.getLogger(__name__)


# ============================================================
# 仪表盘配置数据模型
# ============================================================

def _new_dashboard_config(name: str) -> dict:
    """创建新仪表盘配置。"""
    return {
        'id': f'db_{uuid.uuid4().hex[:8]}',
        'name': name,
        'charts': [],
        'grid_cols': 3,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
    }


def _new_chart_config(title: str = '', chart_type: str = 'bar') -> dict:
    """创建新图表配置。"""
    return {
        'id': f'c_{uuid.uuid4().hex[:8]}',
        'title': title,
        'chart_type': chart_type,
        'source_id': '',      # MySQL 表名（如 '报表-销售订单'）
        'x_field': '',
        'y_fields': [],
        'agg': 'sum',
        'group_field': '',
        'filters': [],
    }


# ============================================================
# 仪表盘 HTML 生成
# ============================================================

def _build_dashboard_html(dashboard: dict, chart_options: dict,
                          echarts_base_url: str) -> str:
    """生成仪表盘完整 HTML（ECharts 图表网格布局）。

    Args:
        dashboard: 仪表盘配置 dict
        chart_options: {chart_id: echarts_option_dict, ...}
        echarts_base_url: ECharts JS 的 HTTP 基础 URL

    Returns:
        HTML 字符串
    """
    charts = dashboard.get('charts', [])
    grid_cols = dashboard.get('grid_cols', 3)

    # 构建图表卡片 HTML
    cards_html = ''
    for c in charts:
        cid = c['id']
        title = c.get('title', '未命名图表')
        chart_type = c.get('chart_type', 'bar')
        type_label = {
            'bar': '柱状图', 'line': '折线图', 'pie': '饼图', 'scatter': '散点图',
            'area': '面积图', 'stacked_bar': '堆叠柱状图', 'funnel': '漏斗图', 'radar': '雷达图',
        }.get(chart_type, chart_type)

        opt_json = json.dumps(chart_options.get(cid, {}), ensure_ascii=False, default=str)

        cards_html += f'''
        <div class="chart-card" data-id="{cid}">
            <div class="chart-title">{title} <span class="chart-type">({type_label})</span></div>
            <div class="chart-body" id="chart_{cid}"></div>
        </div>
        '''

    # 图表初始化 JS
    init_js = ''
    for c in charts:
        cid = c['id']
        opt = chart_options.get(cid, {})
        opt_json = json.dumps(opt, ensure_ascii=False, default=str)
        init_js += f'''
        (function() {{
            var dom = document.getElementById('chart_{cid}');
            if (!dom) return;
            var chart = echarts.init(dom);
            chart.setOption({opt_json});
            _charts['{cid}'] = chart;
        }})();
        '''

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{dashboard.get('name', '仪表盘')}</title>
    <script src="{echarts_base_url}/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: #f0f2f5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 16px; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat({grid_cols}, 1fr);
            gap: 16px;
        }}
        .chart-card {{
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.08);
            overflow: hidden;
            min-height: 320px;
        }}
        .chart-title {{
            padding: 12px 16px 8px;
            font-size: 14px;
            font-weight: 600;
            color: #333;
            border-bottom: 1px solid #f0f0f0;
        }}
        .chart-type {{ font-weight: normal; color: #999; font-size: 12px; }}
        .chart-body {{ width: 100%; height: 280px; }}
        .empty-hint {{
            text-align: center; padding: 80px 20px; color: #bbb; font-size: 16px;
        }}
    </style>
</head>
<body>
    {f'<div class="grid">{cards_html}</div>' if charts else '<div class="empty-hint">暂无图表，请在设计器中添加</div>'}
    <script>
        var _charts = {{}};
        window.addEventListener('resize', function() {{
            Object.values(_charts).forEach(function(c) {{ c.resize(); }});
        }});
        {init_js}
    </script>
</body>
</html>'''


# ============================================================
# 仪表盘后台查询 Worker
# ============================================================

class _DashboardQueryWorker(QThread):
    """后台查询所有图表数据。"""
    finished = pyqtSignal(dict)  # {chart_id: [rows]}
    error = pyqtSignal(str)

    def __init__(self, db, charts, parent=None):
        super().__init__(parent)
        self._db = db
        self._charts = charts

    def run(self):
        try:
            from chart_engine import ChartEngine
            engine = ChartEngine(self._db)
            result = {}
            for c in self._charts:
                cid = c['id']
                source = c.get('source_id', '')
                x_field = c.get('x_field', '')
                y_fields = c.get('y_fields', [])
                if not source or not x_field:
                    continue
                try:
                    data = engine.query_data(
                        table=source,
                        x_field=x_field,
                        y_fields=y_fields or [''],
                        group_field=c.get('group_field') or None,
                        agg=c.get('agg', 'sum'),
                    )
                    result[cid] = data
                except Exception as e:
                    logger.warning(f"[DashboardWorker] Chart {cid} query failed: {e}")
                    result[cid] = []
            self.finished.emit(result)
        except Exception as e:
            logger.error(f"[DashboardWorker] Failed: {e}")
            self.error.emit(str(e))


# ============================================================
# DashboardMixin
# ============================================================

class DashboardMixin:
    """仪表盘设计器/查看器功能。"""

    def create_dashboard_page(self):
        """创建仪表盘页面，加入 content_stack。"""
        page = QFrame()
        page.setObjectName("dashboard_page")
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 内部子页面栈
        self._dash_stack = QStackedWidget()

        # 子页面 0: 列表页
        self._dash_list_page = self._create_dash_list_page()
        self._dash_stack.addWidget(self._dash_list_page)

        # 子页面 1: 设计器页
        self._dash_designer_page = self._create_dash_designer_page()
        self._dash_stack.addWidget(self._dash_designer_page)

        # 子页面 2: 查看器页
        self._dash_view_page = self._create_dash_view_page()
        self._dash_stack.addWidget(self._dash_view_page)

        root.addWidget(self._dash_stack)
        self.content_stack.addWidget(page)
        self._dashboard_page = page

        # 内部状态
        self._dashboards = {}       # {id: config_dict}
        self._current_dash_id = None
        self._dash_query_worker = None

        # 加载已保存的仪表盘
        QTimer.singleShot(100, self._dash_load_all)

    def create_dashboard_embedded(self):
        """创建仪表盘页面（嵌入模式），返回 QFrame 由调用方嵌入自身布局。

        与 create_dashboard_page() 功能相同，但不加入 content_stack，
        而是返回 page 供 BitableMixin 嵌入其主内容区。
        """
        page = QFrame()
        page.setObjectName("dashboard_embedded_page")
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 内部子页面栈
        self._dash_stack = QStackedWidget()

        # 子页面 0: 列表页
        self._dash_list_page = self._create_dash_list_page()
        self._dash_stack.addWidget(self._dash_list_page)

        # 子页面 1: 设计器页
        self._dash_designer_page = self._create_dash_designer_page()
        self._dash_stack.addWidget(self._dash_designer_page)

        # 子页面 2: 查看器页
        self._dash_view_page = self._create_dash_view_page()
        self._dash_stack.addWidget(self._dash_view_page)

        root.addWidget(self._dash_stack)
        # 不加入 content_stack，返回给调用方嵌入
        self._dashboard_page = page

        # 内部状态
        self._dashboards = {}       # {id: config_dict}
        self._current_dash_id = None
        self._dash_query_worker = None

        # 加载已保存的仪表盘
        QTimer.singleShot(100, self._dash_load_all)
        return page

    # ──────────────── 列表页 ────────────────

    def _create_dash_list_page(self):
        """创建仪表盘列表页。"""
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)

        # 顶栏
        top = QHBoxLayout()
        lbl = QLabel("仪表盘")
        lbl.setFont(QFont("", 14, QFont.Weight.Bold))
        top.addWidget(lbl)
        top.addStretch()
        btn_new = QPushButton("＋ 新建仪表盘")
        btn_new.setStyleSheet(
            "QPushButton { background: #1890ff; color: white; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #40a9ff; }"
        )
        btn_new.clicked.connect(self._dash_on_new)
        top.addWidget(btn_new)
        layout.addLayout(top)

        # 列表表格
        self._dash_list_table = QTableWidget()
        self._dash_list_table.setColumnCount(4)
        self._dash_list_table.setHorizontalHeaderLabels(["名称", "图表数", "更新时间", "操作"])
        install_autofilter_header(self._dash_list_table)
        self._dash_list_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._dash_list_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._dash_list_table.setColumnWidth(3, 220)
        self._dash_list_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._dash_list_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self._dash_list_table, 1)

        return page

    def _dash_load_all(self):
        """从 config 加载所有仪表盘。"""
        try:
            cfg = load_config()
            self._dashboards = cfg.get('dashboards_v2', {})
        except Exception:
            self._dashboards = {}
        self._dash_refresh_list()

    def _dash_save_all(self):
        """保存所有仪表盘到 config。"""
        try:
            cfg = load_config()
            cfg['dashboards_v2'] = self._dashboards
            save_config(cfg)
        except Exception as e:
            logger.error(f"[Dashboard] Save failed: {e}")

    def _dash_refresh_list(self):
        """刷新列表显示。"""
        tbl = self._dash_list_table
        tbl.setRowCount(0)
        for did, d in self._dashboards.items():
            row = tbl.rowCount()
            tbl.insertRow(row)
            tbl.setItem(row, 0, QTableWidgetItem(d.get('name', '')))
            tbl.setItem(row, 1, QTableWidgetItem(str(len(d.get('charts', [])))))
            tbl.setItem(row, 2, QTableWidgetItem(d.get('updated_at', '')[:16]))

            # 操作按钮
            ops = QFrame()
            ol = QHBoxLayout(ops)
            ol.setContentsMargins(4, 2, 4, 2)
            ol.setSpacing(4)
            btn_view = QPushButton("查看")
            btn_view.setFixedHeight(24)
            btn_view.clicked.connect(lambda _, _id=did: self._dash_open_view(_id))
            ol.addWidget(btn_view)
            btn_edit = QPushButton("编辑")
            btn_edit.setFixedHeight(24)
            btn_edit.clicked.connect(lambda _, _id=did: self._dash_open_designer(_id))
            ol.addWidget(btn_edit)
            btn_del = QPushButton("删除")
            btn_del.setFixedHeight(24)
            btn_del.setStyleSheet("QPushButton { color: #ff4d4f; }")
            btn_del.clicked.connect(lambda _, _id=did: self._dash_on_delete(_id))
            ol.addWidget(btn_del)
            tbl.setCellWidget(row, 3, ops)

    def _dash_on_new(self):
        """新建仪表盘。"""
        name, ok = frameless_input_text(self, "新建仪表盘", "仪表盘名称:")
        if not ok or not name.strip():
            return
        cfg = _new_dashboard_config(name.strip())
        self._dashboards[cfg['id']] = cfg
        self._dash_save_all()
        self._dash_refresh_list()
        self._dash_open_designer(cfg['id'])

    def _dash_on_delete(self, dash_id):
        """删除仪表盘。"""
        d = self._dashboards.get(dash_id)
        if not d:
            return
        reply = CustomMessageBox.question(
            self, "确认删除", f"确定删除仪表盘「{d.get('name', '')}」？"
        )
        if reply == 'yes':
            del self._dashboards[dash_id]
            self._dash_save_all()
            self._dash_refresh_list()

    # ──────────────── 设计器页 ────────────────

    def _create_dash_designer_page(self):
        """创建仪表盘设计器页。"""
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 顶栏
        top = QHBoxLayout()
        self._dash_designer_title = QLabel("设计器")
        self._dash_designer_title.setFont(QFont("", 13, QFont.Weight.Bold))
        top.addWidget(self._dash_designer_title)
        top.addStretch()

        btn_back = QPushButton("← 返回列表")
        btn_back.clicked.connect(lambda: self._dash_stack.setCurrentIndex(0))
        top.addWidget(btn_back)

        btn_save = QPushButton("💾 保存")
        btn_save.setStyleSheet(
            "QPushButton { background: #52c41a; color: white; padding: 5px 16px; border-radius: 4px; }"
        )
        btn_save.clicked.connect(self._dash_on_save)
        top.addWidget(btn_save)
        layout.addLayout(top)

        # 图表列表
        self._dash_chart_list = QTableWidget()
        self._dash_chart_list.setColumnCount(7)
        self._dash_chart_list.setHorizontalHeaderLabels([
            "图表名称", "类型", "数据源", "X轴", "Y轴", "聚合", "操作"
        ])
        install_autofilter_header(self._dash_chart_list)
        self._dash_chart_list.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._dash_chart_list.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self._dash_chart_list.setColumnWidth(6, 80)
        self._dash_chart_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._dash_chart_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self._dash_chart_list, 1)

        # 添加图表按钮
        add_bar = QHBoxLayout()
        btn_add = QPushButton("＋ 添加图表")
        btn_add.setStyleSheet(
            "QPushButton { background: #1890ff; color: white; padding: 6px 16px; border-radius: 4px; }"
        )
        btn_add.clicked.connect(self._dash_on_add_chart)
        add_bar.addWidget(btn_add)
        add_bar.addStretch()

        add_bar.addWidget(QLabel("列数:"))
        self._dash_grid_cols = QSpinBox()
        self._dash_grid_cols.setRange(1, 6)
        self._dash_grid_cols.setValue(3)
        add_bar.addWidget(self._dash_grid_cols)
        layout.addLayout(add_bar)

        return page

    def _dash_open_designer(self, dash_id):
        """打开设计器。"""
        self._current_dash_id = dash_id
        d = self._dashboards.get(dash_id)
        if not d:
            return
        self._dash_designer_title.setText(f"设计器 — {d.get('name', '')}")
        self._dash_grid_cols.setValue(d.get('grid_cols', 3))
        self._dash_refresh_chart_list()
        self._dash_stack.setCurrentIndex(1)

    def _dash_refresh_chart_list(self):
        """刷新设计器中的图表列表。"""
        d = self._dashboards.get(self._current_dash_id)
        if not d:
            return
        tbl = self._dash_chart_list
        tbl.setRowCount(0)
        type_labels = {
            'bar': '柱状图', 'line': '折线图', 'pie': '饼图', 'scatter': '散点图',
            'area': '面积图', 'stacked_bar': '堆叠柱状图', 'funnel': '漏斗图', 'radar': '雷达图',
        }
        for c in d.get('charts', []):
            row = tbl.rowCount()
            tbl.insertRow(row)
            tbl.setItem(row, 0, QTableWidgetItem(c.get('title', '')))
            tbl.setItem(row, 1, QTableWidgetItem(type_labels.get(c.get('chart_type', ''), c.get('chart_type', ''))))
            tbl.setItem(row, 2, QTableWidgetItem(c.get('source_id', '')))
            tbl.setItem(row, 3, QTableWidgetItem(c.get('x_field', '')))
            tbl.setItem(row, 4, QTableWidgetItem(', '.join(c.get('y_fields', []))))
            tbl.setItem(row, 5, QTableWidgetItem(c.get('agg', 'sum')))
            btn_del = QPushButton("删除")
            btn_del.setFixedHeight(22)
            btn_del.setStyleSheet("QPushButton { color: #ff4d4f; }")
            btn_del.clicked.connect(lambda _, _cid=c['id']: self._dash_on_delete_chart(_cid))
            tbl.setCellWidget(row, 6, btn_del)

    def _dash_on_add_chart(self):
        """添加图表到仪表盘。"""
        d = self._dashboards.get(self._current_dash_id)
        if not d:
            return

        # 弹出配置对话框
        dlg = _ChartConfigDialog(getattr(self, '_report_manager', None), parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        cfg = dlg.get_config()
        if not cfg:
            return

        d['charts'].append(cfg)
        d['updated_at'] = datetime.now().isoformat()
        self._dash_refresh_chart_list()

    def _dash_on_delete_chart(self, chart_id):
        """从仪表盘删除图表。"""
        d = self._dashboards.get(self._current_dash_id)
        if not d:
            return
        d['charts'] = [c for c in d['charts'] if c['id'] != chart_id]
        d['updated_at'] = datetime.now().isoformat()
        self._dash_refresh_chart_list()

    def _dash_on_save(self):
        """保存仪表盘。"""
        d = self._dashboards.get(self._current_dash_id)
        if not d:
            return
        d['grid_cols'] = self._dash_grid_cols.value()
        d['updated_at'] = datetime.now().isoformat()
        self._dash_save_all()
        CustomMessageBox.information(self, "保存成功", f"仪表盘「{d.get('name', '')}」已保存。")

    # ──────────────── 查看器页 ────────────────

    def _create_dash_view_page(self):
        """创建仪表盘查看页。"""
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶栏
        top = QFrame()
        top.setFixedHeight(40)
        top.setStyleSheet("QFrame { background: #FAFAFA; border-bottom: 1px solid #E8E8E8; }")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 4, 12, 4)

        self._dash_view_title = QLabel("仪表盘")
        self._dash_view_title.setFont(QFont("", 12, QFont.Weight.Bold))
        tl.addWidget(self._dash_view_title)
        tl.addStretch()

        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.clicked.connect(self._dash_on_refresh_view)
        tl.addWidget(btn_refresh)

        btn_edit = QPushButton("编辑")
        btn_edit.clicked.connect(lambda: self._dash_open_designer(self._current_dash_id))
        tl.addWidget(btn_edit)

        btn_back = QPushButton("← 返回列表")
        btn_back.clicked.connect(lambda: self._dash_stack.setCurrentIndex(0))
        tl.addWidget(btn_back)

        layout.addWidget(top)

        # QWebEngineView
        self._dash_webview = QWebEngineView()
        self._dash_webview.setStyleSheet("background: #f0f2f5;")
        try:
            self._dash_webview.page().setBackgroundColor(QColor("#f0f2f5"))
        except Exception:
            pass
        layout.addWidget(self._dash_webview, 1)

        return page

    def _dash_open_view(self, dash_id):
        """打开仪表盘查看页。"""
        self._current_dash_id = dash_id
        d = self._dashboards.get(dash_id)
        if not d:
            return

        self._dash_view_title.setText(d.get('name', '仪表盘'))
        self._dash_stack.setCurrentIndex(2)

        # 查询数据并渲染
        self._dash_query_and_render(d)

    def _dash_query_and_render(self, dashboard: dict):
        """查询所有图表数据并渲染。"""
        mgr = getattr(self, '_report_manager', None)
        if not mgr or not mgr._db or not mgr._db.available:
            self._dash_webview.setHtml("<p style='color:#999;text-align:center;padding:40px;'>数据库不可用</p>")
            return

        charts = dashboard.get('charts', [])
        if not charts:
            self._dash_webview.setHtml("<p style='color:#999;text-align:center;padding:40px;'>暂无图表</p>")
            return

        # 后台查询
        self._dash_query_worker = _DashboardQueryWorker(mgr._db, charts, parent=self)
        self._dash_query_worker.finished.connect(
            lambda data: self._dash_render(dashboard, data)
        )
        self._dash_query_worker.error.connect(
            lambda msg: self._dash_webview.setHtml(f"<p style='color:red;'>查询失败: {msg}</p>")
        )
        self._dash_query_worker.start()

    def _dash_render(self, dashboard: dict, data_map: dict):
        """用查询结果渲染仪表盘。"""
        from chart_engine import ChartEngine
        mgr = getattr(self, '_report_manager', None)
        engine = ChartEngine(mgr._db) if mgr else None

        chart_options = {}
        for c in dashboard.get('charts', []):
            cid = c['id']
            rows = data_map.get(cid, [])
            if not rows or not engine:
                chart_options[cid] = {}
                continue
            try:
                opt = engine.build_option(
                    chart_type=c.get('chart_type', 'bar'),
                    data=rows,
                    x_field=c.get('x_field', ''),
                    y_fields=c.get('y_fields', ['']),
                    group_field=c.get('group_field') or None,
                    title=c.get('title', ''),
                )
                chart_options[cid] = opt
            except Exception as e:
                logger.warning(f"[Dashboard] Build option failed for {cid}: {e}")
                chart_options[cid] = {}

        # 确定 echarts HTTP URL
        from bitable import _bitable_server_port
        port = _bitable_server_port or 19000
        echarts_url = f"http://127.0.0.1:{port}/echarts"

        html = _build_dashboard_html(dashboard, chart_options, echarts_url)
        self._dash_webview.setHtml(html, QUrl(f"http://127.0.0.1:{port}/"))

    def _dash_on_refresh_view(self):
        """刷新当前查看的仪表盘。"""
        d = self._dashboards.get(self._current_dash_id)
        if d:
            self._dash_query_and_render(d)


# ============================================================
# 图表配置对话框
# ============================================================

class _ChartConfigDialog(CenteredPopupDialog):
    """添加/编辑图表配置的对话框。"""

    def __init__(self, report_manager=None, chart_config=None, parent=None):
        super().__init__(parent, title="图表配置")
        self._report_manager = report_manager
        self._chart_config = chart_config
        self._result = None
        self._build_ui()
        if chart_config:
            self._load_config(chart_config)

    def _build_ui(self):
        content = self.content_layout

        # 图表名称
        row = QHBoxLayout()
        row.addWidget(QLabel("名称:"))
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("图表标题")
        row.addWidget(self._title_edit, 1)
        content.addLayout(row)

        # 图表类型
        row = QHBoxLayout()
        row.addWidget(QLabel("类型:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems([
            "柱状图", "折线图", "饼图", "散点图", "面积图", "堆叠柱状图", "漏斗图", "雷达图"
        ])
        self._type_map = {
            "柱状图": "bar", "折线图": "line", "饼图": "pie", "散点图": "scatter",
            "面积图": "area", "堆叠柱状图": "stacked_bar", "漏斗图": "funnel", "雷达图": "radar",
        }
        row.addWidget(self._type_combo, 1)
        content.addLayout(row)

        # 数据源
        row = QHBoxLayout()
        row.addWidget(QLabel("数据源:"))
        self._source_combo = QComboBox()
        self._source_combo.setMinimumWidth(200)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        row.addWidget(self._source_combo, 1)
        content.addLayout(row)

        # 字段选择
        row = QHBoxLayout()
        row.addWidget(QLabel("X轴:"))
        self._x_combo = QComboBox()
        self._x_combo.setMinimumWidth(120)
        row.addWidget(self._x_combo, 1)
        row.addWidget(QLabel("Y轴:"))
        self._y_combo = QComboBox()
        self._y_combo.setMinimumWidth(120)
        row.addWidget(self._y_combo, 1)
        content.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("聚合:"))
        self._agg_combo = QComboBox()
        self._agg_combo.addItems(["求和", "计数", "平均", "最大", "最小"])
        self._agg_map = {
            "求和": "sum", "计数": "count", "平均": "avg", "最大": "max", "最小": "min",
        }
        row.addWidget(self._agg_combo)
        row.addWidget(QLabel("分组:"))
        self._group_combo = QComboBox()
        self._group_combo.addItem("(无)", "")
        row.addWidget(self._group_combo, 1)
        content.addLayout(row)

        # 填充数据源列表
        self._populate_sources()

    def _populate_sources(self):
        """填充数据源下拉框。"""
        self._source_combo.blockSignals(True)
        self._source_combo.clear()
        self._source_combo.addItem("-- 请选择 --", "")
        if self._report_manager:
            try:
                sources = self._report_manager.get_available_data_sources()
                for src in sources.get('reports', []):
                    name = src.get('name', '')
                    table = src.get('table_name', '')
                    self._source_combo.addItem(name, table)
            except Exception:
                pass
        self._source_combo.blockSignals(False)

    def _on_source_changed(self, index):
        """数据源切换，更新字段列表。"""
        table = self._source_combo.currentData()
        self._x_combo.clear()
        self._y_combo.clear()
        self._group_combo.clear()
        self._group_combo.addItem("(无)", "")
        if not table or not self._report_manager:
            return
        try:
            sources = self._report_manager.get_available_data_sources()
            for src in sources.get('reports', []):
                if src.get('table_name') == table:
                    for f in src.get('fields', []):
                        key = f.get('key', '')
                        label = f.get('label', key)
                        self._x_combo.addItem(label, key)
                        self._y_combo.addItem(label, key)
                        self._group_combo.addItem(label, key)
                    break
        except Exception:
            pass

    def _load_config(self, cfg):
        """加载已有图表配置。"""
        self._title_edit.setText(cfg.get('title', ''))
        type_name = {v: k for k, v in self._type_map.items()}.get(cfg.get('chart_type', 'bar'), '柱状图')
        idx = self._type_combo.findText(type_name)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)

    def get_config(self) -> dict:
        """返回图表配置 dict，或 None（取消）。"""
        title = self._title_edit.text().strip()
        source = self._source_combo.currentData()
        x_field = self._x_combo.currentData()
        y_field = self._y_combo.currentData()

        if not source or not x_field:
            return None

        type_name = self._type_combo.currentText()
        agg_name = self._agg_combo.currentText()
        group = self._group_combo.currentData() or ''

        cfg = _new_chart_config(title or f'{type_name}', self._type_map.get(type_name, 'bar'))
        cfg['source_id'] = source
        cfg['x_field'] = x_field
        cfg['y_fields'] = [y_field] if y_field else []
        cfg['agg'] = self._agg_map.get(agg_name, 'sum')
        cfg['group_field'] = group
        return cfg
