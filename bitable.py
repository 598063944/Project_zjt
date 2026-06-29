# -*- coding: utf-8 -*-
"""
bitable.py — 本地多维表格 Mixin
────────────────────────────────
负责：MainFrame 中多维表格页面
  - create_bitable_page()   创建页面（加入 content_stack）
  - AG Grid + QWebEngineView 实现可交互表格
  - 服务端分页、排序、筛选、内联编辑
  - 数据源: MySQL 报表- 表（通过 ReportManager）
依赖：core.py / common.py / custom_report (ReportManager, ReportDatabase)
被导入：主程序（作为 MainFrame 的 Mixin 父类）
"""

from core import *
from common import *
from common import frameless_input_text, frameless_message_box, frameless_input_getitem

import os
import json
import logging
import socketserver
import threading
import re
from datetime import datetime, date, time as dtime
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QPushButton, QLabel,
    QComboBox, QLineEdit, QSizePolicy, QApplication,
    QListWidget, QListWidgetItem, QInputDialog,
)
from PyQt6.QtCore import Qt, QUrl, QTimer, QThread, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtGui import QColor

logger = logging.getLogger(__name__)

# numpy 可选
try:
    import numpy as np
except ImportError:
    np = None


# ============================================================
# 本地 HTTP 服务器（独立于 spreadsheet_page.py 的端口 18900-18999）
# ============================================================

class _QuietBitableHandler(SimpleHTTPRequestHandler):
    """静默 HTTP 请求处理器，支持 bitable/ 和 echarts/ 两个目录"""
    # 由 _start_bitable_http 动态设置
    _echarts_dir = None

    def log_message(self, format, *args):
        pass

    def translate_path(self, path):
        """将 URL 路径映射到文件系统：/echarts/* → echarts 目录，其余 → bitable 目录"""
        from urllib.parse import unquote
        path = unquote(path.split('?', 1)[0].split('#', 1)[0])
        # 去掉开头的 /
        rel = path.lstrip('/')
        if rel.startswith('echarts/') and self._echarts_dir:
            return os.path.join(self._echarts_dir, rel[len('echarts/'):])
        return os.path.join(self.directory, rel)


_bitable_server_port = None


def _start_bitable_http(bitable_dir: str, echarts_dir: str = '') -> int:
    """启动本地 HTTP 服务器，同时服务 bitable/ 和 echarts/ 目录。
    端口范围 19000-19099。"""
    global _bitable_server_port
    if _bitable_server_port is not None:
        return _bitable_server_port

    # 动态设置 echarts 目录
    _QuietBitableHandler._echarts_dir = echarts_dir or None

    handler = partial(_QuietBitableHandler, directory=bitable_dir)

    class _TCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    for port in range(19000, 19100):
        try:
            httpd = _TCPServer(("127.0.0.1", port), handler)
            _bitable_server_port = port
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            logger.info(f"[Bitable] HTTP server started: http://127.0.0.1:{port}")
            return port
        except OSError:
            continue

    raise RuntimeError("无法启动多维表格 HTTP 服务器（19000-19099 端口均被占用）")


# ============================================================
# JSON 安全值转换
# ============================================================

def _to_json_safe_value(val):
    """将 MySQL/Python 值转换为 JSON 可序列化类型。"""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float, str)):
        return val
    if np is not None:
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            f = float(val)
            return None if np.isnan(f) or np.isinf(f) else f
        if isinstance(val, np.bool_):
            return bool(val)
    if isinstance(val, (datetime, date, dtime)):
        return str(val)
    if isinstance(val, Decimal):
        try:
            return float(val)
        except (ValueError, OverflowError):
            return str(val)
    if isinstance(val, (bytes, bytearray)):
        try:
            return val.decode('utf-8')
        except UnicodeDecodeError:
            return val.hex()
    if hasattr(val, 'item'):
        try:
            return _to_json_safe_value(val.item())
        except Exception:
            return str(val)
    return str(val)


# ============================================================
# SQL 注入防御：列名合法性校验
# ============================================================

_SAFE_FIELD_RE = re.compile(r'^[a-zA-Z0-9_一-鿿]+$')


def _safe_column_name(field: str) -> str:
    """校验并转义列名（仅允许字母数字下划线中文），用反引号包裹。"""
    if not field or not _SAFE_FIELD_RE.match(field):
        raise ValueError(f"非法列名: {field!r}")
    return f'`{field}`'


# ============================================================
# 后台查询 Worker
# ============================================================

class _BitableQueryWorker(QThread):
    """后台分页查询线程，构建 SQL WHERE/ORDER BY/LIMIT。"""
    finished = pyqtSignal(list, int)   # (rows, total_count)
    error = pyqtSignal(str)

    def __init__(self, db, table_name, columns_str,
                 start_row, end_row, sort_model, filter_model, parent=None):
        super().__init__(parent)
        self._db = db
        self._table_name = table_name
        self._columns_str = columns_str
        self._start_row = start_row
        self._end_row = end_row
        self._sort_model = sort_model or []
        self._filter_model = filter_model or {}

    def run(self):
        try:
            rows, total = self._execute_query()
            self.finished.emit(rows, total)
        except Exception as e:
            logger.error(f"[BitableQueryWorker] Query failed: {e}")
            self.error.emit(str(e))

    def _build_where(self):
        """从 AG Grid filterModel 构建 WHERE 子句。"""
        where_parts = []
        params = []

        for field, fdef in self._filter_model.items():
            try:
                safe_f = _safe_column_name(field)
            except ValueError:
                continue

            ftype = fdef.get('filterType', 'text')
            operator = fdef.get('type', 'contains')
            filter_val = fdef.get('filter', '')
            filter_to = fdef.get('filterTo', '')

            if ftype == 'text':
                if operator == 'contains':
                    where_parts.append(f"{safe_f} LIKE %s")
                    params.append(f"%{filter_val}%")
                elif operator == 'notContains':
                    where_parts.append(f"{safe_f} NOT LIKE %s")
                    params.append(f"%{filter_val}%")
                elif operator == 'equals':
                    where_parts.append(f"{safe_f} = %s")
                    params.append(filter_val)
                elif operator == 'notEqual':
                    where_parts.append(f"{safe_f} != %s")
                    params.append(filter_val)
                elif operator == 'startsWith':
                    where_parts.append(f"{safe_f} LIKE %s")
                    params.append(f"{filter_val}%")
                elif operator == 'endsWith':
                    where_parts.append(f"{safe_f} LIKE %s")
                    params.append(f"%{filter_val}")
                elif operator in ('blank', 'empty'):
                    where_parts.append(f"({safe_f} IS NULL OR {safe_f} = '')")
                elif operator in ('notBlank', 'notEmpty'):
                    where_parts.append(f"({safe_f} IS NOT NULL AND {safe_f} != '')")

            elif ftype == 'number':
                if operator == 'equals':
                    where_parts.append(f"{safe_f} = %s")
                    params.append(filter_val)
                elif operator == 'notEqual':
                    where_parts.append(f"{safe_f} != %s")
                    params.append(filter_val)
                elif operator == 'greaterThan':
                    where_parts.append(f"{safe_f} > %s")
                    params.append(filter_val)
                elif operator == 'greaterThanOrEqual':
                    where_parts.append(f"{safe_f} >= %s")
                    params.append(filter_val)
                elif operator == 'lessThan':
                    where_parts.append(f"{safe_f} < %s")
                    params.append(filter_val)
                elif operator == 'lessThanOrEqual':
                    where_parts.append(f"{safe_f} <= %s")
                    params.append(filter_val)
                elif operator == 'inRange':
                    where_parts.append(f"({safe_f} >= %s AND {safe_f} <= %s)")
                    params.extend([filter_val, filter_to])

        clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        return clause, params

    def _build_order(self):
        """从 AG Grid sortModel 构建 ORDER BY 子句。"""
        parts = []
        for item in self._sort_model:
            col_id = item.get('colId', '')
            direction = item.get('sort', 'asc')
            try:
                safe_c = _safe_column_name(col_id)
            except ValueError:
                continue
            parts.append(f"{safe_c} {'ASC' if direction == 'asc' else 'DESC'}")
        return ("ORDER BY " + ", ".join(parts)) if parts else ""

    def _execute_query(self):
        table = self._table_name
        db = self._db
        page_size = self._end_row - self._start_row

        where_clause, where_params = self._build_where()
        order_clause = self._build_order()

        # COUNT
        count_sql = f"SELECT COUNT(*) AS cnt FROM `{table}` {where_clause}"
        count_result = db.execute(count_sql, where_params)
        total = count_result[0]['cnt'] if count_result else 0

        # SELECT with pagination
        data_sql = (f"SELECT {self._columns_str} FROM `{table}` "
                    f"{where_clause} {order_clause} LIMIT %s OFFSET %s")
        rows = db.execute(data_sql, where_params + [page_size, self._start_row])

        # 转换为 JSON 安全值
        safe_rows = []
        for row in (rows or []):
            safe_rows.append({k: _to_json_safe_value(v) for k, v in row.items()})

        return safe_rows, total


# ============================================================
# 后台更新 Worker
# ============================================================

class _BitableUpdateWorker(QThread):
    """后台单元格编辑 UPDATE 线程。"""
    finished = pyqtSignal(bool, str)

    def __init__(self, db, table_name, row_id_field, row_id_value,
                 field, new_value, parent=None):
        super().__init__(parent)
        self._db = db
        self._table_name = table_name
        self._row_id_field = row_id_field
        self._row_id_value = row_id_value
        self._field = field
        self._new_value = new_value

    def run(self):
        try:
            safe_field = _safe_column_name(self._field)
            safe_id = _safe_column_name(self._row_id_field)
            sql = f"UPDATE `{self._table_name}` SET {safe_field} = %s WHERE {safe_id} = %s"
            self._db.execute(sql, (self._new_value, self._row_id_value))
            self.finished.emit(True, "ok")
        except Exception as e:
            logger.error(f"[BitableUpdateWorker] Update failed: {e}")
            self.finished.emit(False, str(e))


class _BitableInsertWorker(QThread):
    """后台插入空行。"""
    finished = pyqtSignal(bool, str, object)  # (ok, msg, new_id)

    def __init__(self, db, table_name, parent=None):
        super().__init__(parent)
        self._db = db
        self._table_name = table_name

    def run(self):
        try:
            # 查询表结构，找出需要赋值的列（NOT NULL 且无 DEFAULT）
            cols = self._db.execute(
                "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_DEFAULT, IS_NULLABLE "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION",
                (self._table_name,)
            )
            required_cols = []
            required_vals = []
            for c in (cols or []):
                col_name = c['COLUMN_NAME']
                default = c.get('COLUMN_DEFAULT')
                nullable = c.get('IS_NULLABLE', 'YES')
                # 跳过自增列（Extra 里有 auto_increment 的不需要赋值）
                if col_name == 'id':
                    continue
                # 如果列 NOT NULL 且无默认值，需要我们赋值
                if nullable == 'YES' or default is not None:
                    continue
                data_type = (c.get('DATA_TYPE', '') or '').lower()
                required_cols.append(f'`{col_name}`')
                if 'int' in data_type or 'decimal' in data_type or 'float' in data_type or 'double' in data_type:
                    required_vals.append('0')
                elif col_name == '_row_id':
                    required_vals.append(f"'{uuid.uuid4().hex[:16]}'")
                elif 'date' in data_type or 'time' in data_type:
                    required_vals.append('NULL')
                else:
                    required_vals.append("''")

            if required_cols:
                cols_str = ', '.join(required_cols)
                vals_str = ', '.join(required_vals)
                sql = f"INSERT INTO `{self._table_name}` ({cols_str}) VALUES ({vals_str})"
            else:
                sql = f"INSERT INTO `{self._table_name}` () VALUES ()"

            self._db.execute(sql)
            result = self._db.execute("SELECT LAST_INSERT_ID() AS id")
            new_id = result[0]['id'] if result else None
            self.finished.emit(True, 'ok', new_id)
        except Exception as e:
            logger.error(f"[BitableInsertWorker] Insert failed: {e}")
            self.finished.emit(False, str(e), None)


class _BitableDeleteWorker(QThread):
    """后台删除记录。"""
    finished = pyqtSignal(bool, str, int)  # (ok, msg, deleted_count)

    def __init__(self, db, table_name, row_id_field, row_ids, parent=None):
        super().__init__(parent)
        self._db = db
        self._table_name = table_name
        self._row_id_field = row_id_field
        self._row_ids = row_ids

    def run(self):
        try:
            safe_id = _safe_column_name(self._row_id_field)
            placeholders = ', '.join(['%s'] * len(self._row_ids))
            sql = f"DELETE FROM `{self._table_name}` WHERE {safe_id} IN ({placeholders})"
            self._db.execute(sql, self._row_ids)
            self.finished.emit(True, 'ok', len(self._row_ids))
        except Exception as e:
            logger.error(f"[BitableDeleteWorker] Delete failed: {e}")
            self.finished.emit(False, str(e), 0)


class _BitableAlterWorker(QThread):
    """后台 ALTER TABLE（添加/删除字段）。"""
    finished = pyqtSignal(bool, str)

    def __init__(self, db, table_name, action, field_name,
                 field_type='VARCHAR(255)', parent=None):
        super().__init__(parent)
        self._db = db
        self._table_name = table_name
        self._action = action  # 'add' or 'drop'
        self._field_name = field_name
        self._field_type = field_type

    def run(self):
        try:
            safe_field = _safe_column_name(self._field_name)
            if self._action == 'add':
                sql = f"ALTER TABLE `{self._table_name}` ADD COLUMN {safe_field} {self._field_type}"
            elif self._action == 'drop':
                sql = f"ALTER TABLE `{self._table_name}` DROP COLUMN {safe_field}"
            else:
                self.finished.emit(False, f"未知操作: {self._action}")
                return
            self._db.execute(sql)
            self.finished.emit(True, 'ok')
        except Exception as e:
            logger.error(f"[BitableAlterWorker] Alter failed: {e}")
            self.finished.emit(False, str(e))


# ============================================================
# BitableBridge — Python ↔ JS 桥接
# ============================================================

class BitableBridge(QObject):
    """QWebChannel 桥接对象，处理 AG Grid ↔ Python 双向通信。"""
    actionReceived = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page = None

    def set_page(self, page):
        self._page = page

    @pyqtSlot(str, str)
    def handle_js_action(self, action: str, payload_json: str):
        """JS → Python 统一入口。"""
        self.actionReceived.emit(action, payload_json)

    # ──── Python → JS 调用 ────

    def run_js(self, js: str):
        """执行 JavaScript 代码。"""
        if self._page:
            self._page.runJavaScript(js)

    def set_columns(self, col_defs: list):
        """设置 AG Grid 列定义。"""
        payload = json.dumps(col_defs, ensure_ascii=False)
        self.run_js(f"window.setGridColumns({json.dumps(payload)});")

    def set_datasource(self):
        """设置 Infinite RowModel 数据源，触发首次数据加载。"""
        self.run_js("window.setDataSource();")

    def push_rows(self, rows: list, total: int):
        """将查询结果回传给 AG Grid 的 getRows 回调。"""
        rows_json = json.dumps(rows, ensure_ascii=False, default=str)
        self.run_js(f"window.setRowData({rows_json}, {total});")

    def push_error(self, message: str):
        """通知 AG Grid 查询出错。"""
        self.run_js(f"window.setRowDataError({json.dumps(message)});")

    def refresh_grid(self):
        """清空缓存并重新加载数据。"""
        self.run_js("window.refreshData();")

    def set_editable(self, editable: bool):
        """切换编辑模式。"""
        self.run_js(f"window.setEditable({str(editable).lower()});")

    def export_csv(self, filename='bitable_export.csv'):
        """导出 CSV。"""
        self.run_js(f"window.exportCsv({json.dumps(filename)});")

    def apply_sort_state(self, state: list):
        """应用已保存的排序状态。"""
        self.run_js(f"window.applySortState({json.dumps(json.dumps(state))});")

    def apply_filter_model(self, model: dict):
        """应用已保存的筛选模型。"""
        self.run_js(f"window.setFilterModel({json.dumps(json.dumps(model))});")

    def switch_view(self, view: str):
        """切换视图：'grid' 或 'chart'。"""
        self.run_js(f"window.switchView({json.dumps(view)});")

    def render_chart(self, option: dict):
        """渲染 ECharts 图表。"""
        opt_json = json.dumps(option, ensure_ascii=False, default=str)
        self.run_js(f"window.renderChart({json.dumps(opt_json)});")

    def dispose_chart(self):
        """销毁 ECharts 实例。"""
        self.run_js("window.disposeChart();")

    def set_row_height(self, height: int):
        """设置行高。"""
        self.run_js(f"window.setRowHeight({height});")

    def toggle_search(self):
        """显示/隐藏搜索栏。"""
        self.run_js("window.toggleSearch();")


# ============================================================
# BitableMixin — MainFrame Mixin
# ============================================================

class BitableMixin:
    """本地多维表格功能。"""

    def create_bitable_page(self):
        """创建多维表格页面（WPS 风格：左侧栏 + 主内容区）。"""
        page = QFrame()
        page.setObjectName("bitable_page")
        root = QHBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ════════════════════════════════════════════
        # 左侧栏（WPS/飞书风格表列表面板）
        # ════════════════════════════════════════════
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("""
            QFrame { background: #F7F8FA; border-right: 1px solid #E5E6EB; }
            QListWidget { background: transparent; border: none; outline: none;
                          font-size: 13px; color: #1F2329; }
            QListWidget::item { padding: 8px 16px; border-radius: 0; }
            QListWidget::item:hover { background: #EDF0F2; }
            QListWidget::item:selected { background: #E8F0FE; color: #3370FF; font-weight: 500; }
            QLineEdit { border: 1px solid #DEE0E3; border-radius: 4px; padding: 4px 8px;
                        background: #FFFFFF; font-size: 12px; color: #1F2329; }
            QLineEdit:focus { border-color: #3370FF; }
            QLabel { font-size: 13px; color: #646A73; }
        """)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        # 侧边栏标题
        sb_title = QFrame()
        sb_title.setFixedHeight(48)
        sb_title.setStyleSheet("QFrame { background: #F7F8FA; }")
        sb_tl = QVBoxLayout(sb_title)
        sb_tl.setContentsMargins(16, 12, 16, 4)
        lbl = QLabel("📊 多维表格")
        lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #1F2329;")
        sb_tl.addWidget(lbl)
        sb_layout.addWidget(sb_title)

        # 搜索框
        sb_search_frame = QFrame()
        sb_search_frame.setFixedHeight(36)
        sb_search_l = QHBoxLayout(sb_search_frame)
        sb_search_l.setContentsMargins(12, 4, 12, 4)
        self._bitable_sidebar_search = QLineEdit()
        self._bitable_sidebar_search.setPlaceholderText("搜索表...")
        self._bitable_sidebar_search.textChanged.connect(self._on_sidebar_search_changed)
        sb_search_l.addWidget(self._bitable_sidebar_search)
        sb_layout.addWidget(sb_search_frame)

        # 表列表
        self._bitable_sidebar_list = QListWidget()
        self._bitable_sidebar_list.currentItemChanged.connect(self._on_sidebar_item_changed)
        sb_layout.addWidget(self._bitable_sidebar_list, 1)

        root.addWidget(sidebar)

        # ════════════════════════════════════════════
        # 主内容区
        # ════════════════════════════════════════════
        main_area = QFrame()
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 工具栏 ──
        toolbar = QFrame()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet("""
            QFrame { background: #FFFFFF; border-bottom: 1px solid #E5E6EB; }
            QPushButton { border: none; background: transparent; padding: 4px 10px;
                          border-radius: 4px; font-size: 13px; color: #646A73; }
            QPushButton:hover { background: #F2F3F5; }
            QPushButton:checked { background: #E8F0FE; color: #3370FF; font-weight: 500; }
            QComboBox { border: 1px solid #DEE0E3; border-radius: 4px; padding: 2px 8px;
                        background: #FFFFFF; font-size: 13px; color: #1F2329; }
            QComboBox:hover { border-color: #3370FF; }
            QLabel { font-size: 13px; color: #646A73; }
        """)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(8, 4, 8, 4)
        tb.setSpacing(4)

        # 视图切换（飞书风格 Tab）
        self._bitable_btn_grid = QPushButton("表格")
        self._bitable_btn_grid.setFixedHeight(30)
        self._bitable_btn_grid.setCheckable(True)
        self._bitable_btn_grid.setChecked(True)
        self._bitable_btn_grid.clicked.connect(lambda: self._bitable_switch_view('grid'))
        tb.addWidget(self._bitable_btn_grid)

        self._bitable_btn_chart = QPushButton("图表")
        self._bitable_btn_chart.setFixedHeight(30)
        self._bitable_btn_chart.setCheckable(True)
        self._bitable_btn_chart.clicked.connect(lambda: self._bitable_switch_view('chart'))
        tb.addWidget(self._bitable_btn_chart)

        self._bitable_btn_dashboard = QPushButton("仪表盘")
        self._bitable_btn_dashboard.setFixedHeight(30)
        self._bitable_btn_dashboard.setCheckable(True)
        self._bitable_btn_dashboard.clicked.connect(lambda: self._bitable_switch_view('dashboard'))
        tb.addWidget(self._bitable_btn_dashboard)

        # 分隔线
        sep = QFrame()
        sep.setFixedSize(1, 20)
        sep.setStyleSheet("QFrame { background: #DEE0E3; }")
        tb.addWidget(sep)

        tb.addStretch()

        self._bitable_btn_columns = QPushButton("隐藏字段")
        self._bitable_btn_columns.setFixedHeight(30)
        self._bitable_btn_columns.setToolTip("显示/隐藏列")
        self._bitable_btn_columns.clicked.connect(self._on_bitable_columns_popup)
        tb.addWidget(self._bitable_btn_columns)

        self._bitable_btn_sort = QPushButton("排序")
        self._bitable_btn_sort.setFixedHeight(30)
        self._bitable_btn_sort.setToolTip("配置多列排序")
        self._bitable_btn_sort.clicked.connect(self._on_bitable_sort_dialog)
        tb.addWidget(self._bitable_btn_sort)

        self._bitable_btn_search = QPushButton("查找")
        self._bitable_btn_search.setFixedHeight(30)
        self._bitable_btn_search.setToolTip("搜索表格内容")
        self._bitable_btn_search.clicked.connect(lambda: self._bitable_bridge.toggle_search())
        tb.addWidget(self._bitable_btn_search)

        self._bitable_row_height = QComboBox()
        self._bitable_row_height.setFixedHeight(30)
        self._bitable_row_height.setFixedWidth(80)
        self._bitable_row_height.addItems(["标准", "紧凑", "宽松"])
        self._bitable_row_height_map = {"紧凑": 28, "标准": 36, "宽松": 48}
        self._bitable_row_height.currentTextChanged.connect(
            lambda t: self._bitable_bridge.set_row_height(self._bitable_row_height_map.get(t, 36))
        )
        tb.addWidget(self._bitable_row_height)

        # 分隔线
        sep2 = QFrame()
        sep2.setFixedSize(1, 20)
        sep2.setStyleSheet("QFrame { background: #DEE0E3; }")
        tb.addWidget(sep2)

        self._bitable_btn_export = QPushButton("导出")
        self._bitable_btn_export.setFixedHeight(30)
        self._bitable_btn_export.clicked.connect(self._on_bitable_export)
        tb.addWidget(self._bitable_btn_export)

        self._bitable_btn_refresh = QPushButton("刷新")
        self._bitable_btn_refresh.setFixedHeight(30)
        self._bitable_btn_refresh.clicked.connect(self._on_bitable_refresh)
        tb.addWidget(self._bitable_btn_refresh)

        main_layout.addWidget(toolbar)

        # ── 图表配置面板（飞书风格）──
        self._bitable_chart_panel = QFrame()
        self._bitable_chart_panel.setFixedHeight(44)
        self._bitable_chart_panel.setStyleSheet("""
            QFrame { background: #F7F8FA; border-bottom: 1px solid #E5E6EB; }
            QComboBox { border: 1px solid #DEE0E3; border-radius: 4px; padding: 2px 8px;
                        background: #FFFFFF; font-size: 12px; color: #1F2329; }
            QComboBox:hover { border-color: #3370FF; }
            QLabel { font-size: 12px; color: #8F959E; }
            QPushButton { border: none; background: transparent; padding: 4px 10px;
                          border-radius: 4px; font-size: 12px; color: #646A73; }
            QPushButton:hover { background: #F2F3F5; }
        """)
        self._bitable_chart_panel.setVisible(False)
        cp = QHBoxLayout(self._bitable_chart_panel)
        cp.setContentsMargins(12, 6, 12, 6)
        cp.setSpacing(8)

        cp.addWidget(QLabel("类型:"))
        self._bitable_chart_type = QComboBox()
        self._bitable_chart_type.setFixedHeight(28)
        self._bitable_chart_type.addItems([
            "柱状图", "折线图", "饼图", "散点图", "面积图", "堆叠柱状图", "漏斗图", "雷达图"
        ])
        self._bitable_chart_type_map = {
            "柱状图": "bar", "折线图": "line", "饼图": "pie", "散点图": "scatter",
            "面积图": "area", "堆叠柱状图": "stacked_bar", "漏斗图": "funnel", "雷达图": "radar",
        }
        cp.addWidget(self._bitable_chart_type)

        cp.addWidget(QLabel("X轴:"))
        self._bitable_chart_x = QComboBox()
        self._bitable_chart_x.setFixedHeight(28)
        self._bitable_chart_x.setMinimumWidth(120)
        cp.addWidget(self._bitable_chart_x)

        cp.addWidget(QLabel("Y轴:"))
        self._bitable_chart_y = QComboBox()
        self._bitable_chart_y.setFixedHeight(28)
        self._bitable_chart_y.setMinimumWidth(120)
        cp.addWidget(self._bitable_chart_y)

        cp.addWidget(QLabel("聚合:"))
        self._bitable_chart_agg = QComboBox()
        self._bitable_chart_agg.setFixedHeight(28)
        self._bitable_chart_agg.addItems(["求和", "计数", "平均", "最大", "最小"])
        self._bitable_chart_agg_map = {
            "求和": "sum", "计数": "count", "平均": "avg", "最大": "max", "最小": "min",
        }
        cp.addWidget(self._bitable_chart_agg)

        cp.addWidget(QLabel("分组:"))
        self._bitable_chart_group = QComboBox()
        self._bitable_chart_group.setFixedHeight(28)
        self._bitable_chart_group.setMinimumWidth(100)
        self._bitable_chart_group.addItem("(无)", "")
        cp.addWidget(self._bitable_chart_group)

        btn_gen = QPushButton("生成图表")
        btn_gen.setFixedHeight(28)
        btn_gen.setStyleSheet(
            "QPushButton { background: #3370FF; color: white; padding: 0 14px; border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background: #5B8FF9; }"
        )
        btn_gen.clicked.connect(self._on_bitable_render_chart)
        cp.addWidget(btn_gen)
        cp.addStretch()

        main_layout.addWidget(self._bitable_chart_panel)

        # ── AG Grid WebEngineView ──
        self._bitable_webview = QWebEngineView()
        self._bitable_webview.setStyleSheet("background: #FFFFFF;")
        try:
            self._bitable_webview.page().setBackgroundColor(QColor("#FFFFFF"))
        except Exception:
            pass
        self._bitable_webview.setContextMenuPolicy(
            Qt.ContextMenuPolicy.NoContextMenu
        )

        # QWebChannel
        self._bitable_bridge = BitableBridge(self)
        self._bitable_channel = QWebChannel(self._bitable_webview.page())
        self._bitable_channel.registerObject("bridge", self._bitable_bridge)
        self._bitable_webview.page().setWebChannel(self._bitable_channel)
        self._bitable_bridge.set_page(self._bitable_webview.page())
        self._bitable_bridge.actionReceived.connect(self._on_bitable_js_action)

        main_layout.addWidget(self._bitable_webview, 1)

        # ── 仪表盘视图（嵌入模式，初始隐藏）──
        if hasattr(self, 'create_dashboard_embedded'):
            self._bitable_dash_widget = self.create_dashboard_embedded()
            self._bitable_dash_widget.setVisible(False)
            main_layout.addWidget(self._bitable_dash_widget, 1)

        # ── 飞书风格状态栏 ──
        status_bar = QFrame()
        status_bar.setFixedHeight(28)
        status_bar.setStyleSheet(
            "QFrame { background: #F7F8FA; border-top: 1px solid #E5E6EB; }"
        )
        sb = QHBoxLayout(status_bar)
        sb.setContentsMargins(12, 0, 12, 0)
        self._bitable_status_label = QLabel("选择数据源开始使用")
        self._bitable_status_label.setStyleSheet("color: #8F959E; font-size: 12px;")
        sb.addWidget(self._bitable_status_label)
        sb.addStretch()
        self._bitable_selection_label = QLabel("")
        self._bitable_selection_label.setStyleSheet("color: #646A73; font-size: 12px;")
        sb.addWidget(self._bitable_selection_label)
        main_layout.addWidget(status_bar)

        # 主内容区加入根布局
        root.addWidget(main_area, 1)

        # ── 内部状态 ──
        self._bitable_ready = False
        self._bitable_page_is_ready = False
        self._bitable_current_table = None
        self._bitable_current_row_id_field = 'id'
        self._bitable_current_columns = []  # AG Grid columnDefs
        self._bitable_display_cols_str = ''  # SQL SELECT 列列表
        self._bitable_visible_columns = []
        self._bitable_query_worker = None
        self._bitable_update_worker = None
        self._bitable_source_data = []
        self._bitable_query_cache = {}   # {(start,end,sort_key,filter_key): (rows, total)}
        self._bitable_cache_version = 0  # 缓存版本，编辑/刷新时自增使缓存失效

        # 注册页面
        self.content_stack.addWidget(page)
        self._bitable_page = page

        # 延迟初始化
        QTimer.singleShot(0, self._bitable_lazy_init)

    # ──────────────────── 初始化 ────────────────────

    def _bitable_lazy_init(self):
        """首次显示时启动 HTTP 服务器并加载 AG Grid。"""
        if self._bitable_ready:
            return
        self._bitable_ready = True

        self._bitable_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'bitable'
        )
        self._echarts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'echarts'
        )
        html_path = Path(self._bitable_dir, 'ag-grid.html')
        if html_path.exists():
            try:
                port = _start_bitable_http(self._bitable_dir, self._echarts_dir)
                url = QUrl(f"http://127.0.0.1:{port}/ag-grid.html")
                self._bitable_webview.load(url)
                logger.info(f"[Bitable] Loading: {url}")
            except Exception as e:
                logger.error(f"[Bitable] HTTP server failed: {e}")
                self._bitable_status_label.setText(f"❌ 加载失败: {e}")
        else:
            self._bitable_status_label.setText(f"❌ 模板文件不存在: {html_path}")

        QTimer.singleShot(200, self._bitable_init_sidebar)

    def _bitable_init_sidebar(self):
        """初始化侧边栏并自动选中第一个表。"""
        self._bitable_refresh_source_list()
        # 自动选中第一个表
        if self._bitable_sidebar_list.count() > 0:
            self._bitable_sidebar_list.setCurrentRow(0)

    # ──────────────────── JS 事件处理 ────────────────────

    def _on_bitable_js_action(self, action: str, payload_json: str):
        """分发 JS → Python 事件。"""
        if action == 'page_ready':
            self._bitable_page_is_ready = True
            if self._bitable_current_table:
                self._bitable_load_table(self._bitable_current_table)

        elif action == 'getRows':
            self._handle_get_rows(payload_json)

        elif action == 'cellValueChanged':
            self._handle_cell_edit(payload_json)

        elif action == 'sortChanged':
            self._bitable_save_view_state('sort', json.loads(payload_json))

        elif action == 'filterChanged':
            self._bitable_save_view_state('filter', json.loads(payload_json))

        elif action == 'columnMoved':
            data = json.loads(payload_json)
            self._bitable_save_view_state('column_order', data.get('columns', []))

        elif action == 'selectionChanged':
            data = json.loads(payload_json)
            count = data.get('count', 0)
            self._bitable_selection_label.setText(
                f"已选 {count} 行" if count else ""
            )

        elif action == 'columnResized':
            self._bitable_save_view_state('widths', json.loads(payload_json))

        # ── 新增：记录/字段操作 ──
        elif action == 'addRecord':
            self._handle_add_record()

        elif action == 'insertRecord':
            self._handle_add_record()  # 插入新行（简化：追加到末尾）

        elif action == 'deleteRecords':
            self._handle_delete_records(payload_json)

        elif action == 'hideColumn':
            data = json.loads(payload_json)
            field = data.get('field', '')
            if field and field in self._bitable_visible_columns:
                self._bitable_visible_columns.remove(field)
                new_defs = self._apply_column_visibility(self._bitable_current_columns, self._bitable_visible_columns)
                self._bitable_bridge.set_columns(new_defs)
                QTimer.singleShot(200, self._bitable_bridge.refresh_grid)
                self._bitable_save_view_state('visible_columns', self._bitable_visible_columns)

        elif action == 'addField':
            data = json.loads(payload_json)
            self._handle_add_field_dialog()

        elif action == 'dropColumn':
            data = json.loads(payload_json)
            field = data.get('field', '')
            if field:
                self._handle_drop_column(field)

    # ──────────────────── 查询处理 ────────────────────

    def _handle_get_rows(self, payload_json: str):
        """处理 AG Grid 的 getRows 请求。优先返回缓存数据（防止页面切换重载）。"""
        payload = json.loads(payload_json)
        start_row = payload.get('startRow', 0)
        end_row = payload.get('endRow', 100)
        sort_model = payload.get('sortModel', [])
        filter_model = payload.get('filterModel', {})

        # 缓存命中检查：相同查询参数 + 缓存版本一致 → 直接返回
        cache_key = (
            start_row, end_row,
            json.dumps(sort_model, sort_keys=True),
            json.dumps(filter_model, sort_keys=True),
            self._bitable_cache_version,
        )
        if cache_key in self._bitable_query_cache:
            rows, total = self._bitable_query_cache[cache_key]
            self._bitable_bridge.push_rows(rows, total)
            return

        mgr = getattr(self, '_report_manager', None)
        if not mgr or not mgr._db or not mgr._db.available:
            self._bitable_bridge.push_error("数据库不可用")
            return

        # 取消之前的查询
        if self._bitable_query_worker and self._bitable_query_worker.isRunning():
            try:
                self._bitable_query_worker.finished.disconnect()
                self._bitable_query_worker.error.disconnect()
            except Exception:
                pass
            self._bitable_query_worker.terminate()

        # 保存当前查询的缓存 key
        self._bitable_pending_cache_key = cache_key

        self._bitable_query_worker = _BitableQueryWorker(
            mgr._db, self._bitable_current_table, self._bitable_display_cols_str,
            start_row, end_row, sort_model, filter_model, parent=self,
        )
        self._bitable_query_worker.finished.connect(self._on_query_finished)
        self._bitable_query_worker.error.connect(self._on_query_error)
        self._bitable_query_worker.start()

    def _on_query_finished(self, rows, total):
        """查询成功，回传数据到 AG Grid 并缓存结果。"""
        # 缓存本次查询结果
        key = getattr(self, '_bitable_pending_cache_key', None)
        if key:
            self._bitable_query_cache[key] = (rows, total)
            # 限制缓存大小（保留最近 50 个分页查询）
            if len(self._bitable_query_cache) > 50:
                oldest = list(self._bitable_query_cache.keys())[:25]
                for k in oldest:
                    del self._bitable_query_cache[k]
        self._bitable_bridge.push_rows(rows, total)
        field_count = len(self._bitable_current_columns)
        self._bitable_status_label.setText(f"共 {total:,} 条记录，{field_count} 个字段")

    def _on_query_error(self, msg):
        """查询失败。"""
        self._bitable_bridge.push_error(msg)
        self._bitable_status_label.setText(f"❌ 查询失败: {msg}")

    # ──────────────────── 内联编辑 ────────────────────

    def _handle_cell_edit(self, payload_json: str):
        """处理 AG Grid 单元格编辑。"""
        data = json.loads(payload_json)
        row_id = data.get('row_id')
        field = data.get('field')
        new_value = data.get('newValue')

        if not self._bitable_current_table or not field:
            return
        if row_id is None:
            self._bitable_status_label.setText("⚠ 无法更新: 行缺少唯一标识")
            return

        mgr = getattr(self, '_report_manager', None)
        if not mgr or not mgr._db or not mgr._db.available:
            return

        # 空字符串转 NULL
        if new_value == '':
            new_value = None

        self._bitable_update_worker = _BitableUpdateWorker(
            mgr._db, self._bitable_current_table,
            self._bitable_current_row_id_field, row_id,
            field, new_value, parent=self,
        )
        self._bitable_update_worker.finished.connect(self._on_update_finished)
        self._bitable_update_worker.start()

    def _on_update_finished(self, ok, msg):
        """更新完成回调。"""
        if ok:
            self._bitable_status_label.setText("✅ 已保存")
            self._bitable_cache_version += 1
            self._bitable_query_cache.clear()
        else:
            self._bitable_status_label.setText(f"❌ 保存失败: {msg}")

    # ──────────────────── 记录操作 ────────────────────

    def _handle_add_record(self):
        """添加空记录。"""
        mgr = getattr(self, '_report_manager', None)
        if not mgr or not mgr._db or not mgr._db.available:
            return
        worker = _BitableInsertWorker(mgr._db, self._bitable_current_table, parent=self)
        worker.finished.connect(self._on_insert_finished)
        worker.start()
        self._bitable_insert_worker = worker

    def _on_insert_finished(self, ok, msg, new_id):
        if ok:
            self._bitable_cache_version += 1
            self._bitable_query_cache.clear()
            self._bitable_bridge.refresh_grid()
            self._bitable_status_label.setText(f"✅ 已添加记录 (ID: {new_id})")
        else:
            self._bitable_status_label.setText(f"❌ 添加失败: {msg}")

    def _handle_delete_records(self, payload_json):
        """删除记录。"""
        data = json.loads(payload_json)
        ids = data.get('ids', [])
        if not ids:
            return
        mgr = getattr(self, '_report_manager', None)
        if not mgr or not mgr._db or not mgr._db.available:
            return
        worker = _BitableDeleteWorker(
            mgr._db, self._bitable_current_table,
            self._bitable_current_row_id_field, ids, parent=self,
        )
        worker.finished.connect(self._on_delete_finished)
        worker.start()
        self._bitable_delete_worker = worker

    def _on_delete_finished(self, ok, msg, count):
        if ok:
            self._bitable_cache_version += 1
            self._bitable_query_cache.clear()
            self._bitable_bridge.refresh_grid()
            self._bitable_status_label.setText(f"✅ 已删除 {count} 条记录")
        else:
            self._bitable_status_label.setText(f"❌ 删除失败: {msg}")

    def _handle_add_field_dialog(self):
        """弹出添加字段对话框。"""
        name, ok = frameless_input_text(self, "添加字段", "字段名称:")
        if not ok or not name.strip():
            return
        type_items = ["文本 VARCHAR(500)", "长文本 TEXT", "整数 INT", "小数 DOUBLE", "日期 DATE", "日期时间 DATETIME"]
        type_map = {
            "文本 VARCHAR(500)": "VARCHAR(500)", "长文本 TEXT": "TEXT", "整数 INT": "INT",
            "小数 DOUBLE": "DOUBLE", "日期 DATE": "DATE", "日期时间 DATETIME": "DATETIME",
        }
        type_choice, ok2 = frameless_input_getitem(self, "字段类型", "选择类型:", type_items, 0, False)
        if not ok2:
            return
        mgr = getattr(self, '_report_manager', None)
        if not mgr or not mgr._db or not mgr._db.available:
            return
        worker = _BitableAlterWorker(
            mgr._db, self._bitable_current_table, 'add',
            name.strip(), type_map.get(type_choice, 'VARCHAR(500)'), parent=self,
        )
        worker.finished.connect(lambda ok, msg: self._on_alter_finished(ok, msg, '添加字段'))
        worker.start()
        self._bitable_alter_worker = worker

    def _handle_drop_column(self, field: str):
        """删除字段。"""
        reply = CustomMessageBox.question(
            self, "确认删除字段", f"确定删除字段「{field}」？此操作不可撤销。"
        )
        if reply != 'yes':
            return
        mgr = getattr(self, '_report_manager', None)
        if not mgr or not mgr._db or not mgr._db.available:
            return
        worker = _BitableAlterWorker(
            mgr._db, self._bitable_current_table, 'drop', field, parent=self,
        )
        worker.finished.connect(lambda ok, msg: self._on_alter_finished(ok, msg, '删除字段'))
        worker.start()
        self._bitable_alter_worker = worker

    def _on_alter_finished(self, ok, msg, action_name):
        if ok:
            self._bitable_cache_version += 1
            self._bitable_query_cache.clear()
            # 重新加载表（列定义可能已变化）
            if self._bitable_current_table:
                self._bitable_load_table(self._bitable_current_table)
            self._bitable_status_label.setText(f"✅ {action_name}成功")
        else:
            self._bitable_status_label.setText(f"❌ {action_name}失败: {msg}")

    # ──────────────────── 排序对话框 ────────────────────

    def _on_bitable_sort_dialog(self):
        """弹出排序配置对话框。"""
        if not self._bitable_current_columns:
            return
        dlg = _SortConfigDialog(self._bitable_current_columns, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            sort_state = dlg.get_sort_state()
            if sort_state:
                self._bitable_bridge.apply_sort_state(sort_state)

    # ──────────────────── 数据源管理 ────────────────────

    def _bitable_refresh_source_list(self):
        """从 ReportManager 加载数据源到左侧栏列表。"""
        self._bitable_sidebar_list.blockSignals(True)
        self._bitable_sidebar_list.clear()
        self._bitable_source_data = []

        mgr = getattr(self, '_report_manager', None)
        if not mgr:
            self._bitable_sidebar_list.blockSignals(False)
            return

        try:
            sources = mgr.get_available_data_sources()
            for src in sources.get('reports', []):
                name = src.get('name', '')
                table_name = src.get('table_name', '')
                row_count = src.get('row_count', 0) or 0
                item = QListWidgetItem(f"{name}  ({row_count:,})")
                item.setData(Qt.ItemDataRole.UserRole, table_name)
                self._bitable_sidebar_list.addItem(item)
                self._bitable_source_data.append(src)
        except Exception as e:
            logger.error(f"[Bitable] Failed to load sources: {e}")

        self._bitable_sidebar_list.blockSignals(False)

    def _on_sidebar_search_changed(self, text):
        """搜索框过滤左侧栏表列表。"""
        ft = text.lower()
        for i in range(self._bitable_sidebar_list.count()):
            item = self._bitable_sidebar_list.item(i)
            item.setHidden(ft != '' and ft not in item.text().lower())

    def _on_sidebar_item_changed(self, current, previous):
        """左侧栏选中表变化。"""
        if not current:
            return
        table_name = current.data(Qt.ItemDataRole.UserRole)
        if table_name and self._bitable_page_is_ready:
            self._bitable_load_table(table_name)

    def _bitable_load_table(self, table_name: str):
        """加载表到 AG Grid。"""
        self._bitable_current_table = table_name
        # 切换表时清空查询缓存
        self._bitable_cache_version += 1
        self._bitable_query_cache.clear()
        col_defs, row_id_field, cols_str = self._build_column_defs(table_name)
        if not col_defs:
            self._bitable_status_label.setText(f"❌ 无法加载表: {table_name}")
            return

        self._bitable_current_row_id_field = row_id_field
        self._bitable_current_columns = col_defs
        self._bitable_display_cols_str = cols_str

        # 应用已保存的列可见性
        visible = self._bitable_load_view_state().get('visible_columns')
        if visible:
            col_defs = self._apply_column_visibility(col_defs, visible)
        self._bitable_visible_columns = [c['field'] for c in col_defs if not c.get('hide')]

        # 应用已保存的列宽
        saved_widths = self._bitable_load_view_state().get('widths', {})
        for cd in col_defs:
            if cd['field'] in saved_widths:
                cd['width'] = saved_widths[cd['field']]

        # 设置列和数据源
        self._bitable_bridge.set_columns(col_defs)
        QTimer.singleShot(200, self._bitable_bridge.set_datasource)

        # 恢复排序和筛选
        saved = self._bitable_load_view_state()
        if saved.get('sort'):
            QTimer.singleShot(400, lambda: self._bitable_bridge.apply_sort_state(saved['sort']))
        if saved.get('filter'):
            QTimer.singleShot(400, lambda: self._bitable_bridge.apply_filter_model(saved['filter']))

        self._bitable_status_label.setText(f"已加载: {table_name}")

    # ──────────────────── 列定义构建 ────────────────────

    def _build_column_defs(self, table_name: str):
        """从 MySQL information_schema 构建 AG Grid 列定义。

        Returns:
            (col_defs, row_id_field, display_cols_sql_str)
        """
        mgr = getattr(self, '_report_manager', None)
        if not mgr or not mgr._db or not mgr._db.available:
            return [], 'id', ''

        try:
            cols = mgr._db.execute(
                "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION",
                (table_name,)
            )
        except Exception as e:
            logger.error(f"[Bitable] Schema query failed: {e}")
            return [], 'id', ''

        col_defs = []
        display_cols = []
        row_id_field = 'id'
        first_field = None

        for c in (cols or []):
            col_name = c['COLUMN_NAME']
            # 跳过内部字段
            if col_name in ('_hash', '_sync_time'):
                continue
            if col_name == '_id':
                row_id_field = '_id'
                continue

            data_type = (c.get('DATA_TYPE', '') or '').lower()
            comment = c.get('COLUMN_COMMENT', '') or col_name

            if first_field is None:
                first_field = col_name
            display_cols.append(col_name)

            # 类型映射
            if any(x in data_type for x in ('int', 'decimal', 'float', 'double', 'numeric')):
                filter_type = 'agNumberColumnFilter'
                value_formatter = "params.value != null ? Number(params.value).toLocaleString() : ''"
            else:
                filter_type = 'agTextColumnFilter'
                value_formatter = None

            cd = {
                'field': col_name,
                'headerName': comment if comment != col_name else col_name,
                'filter': filter_type,
                'sortable': True,
                'resizable': True,
                'editable': False,
                'minWidth': 80,
            }
            if value_formatter:
                cd['valueFormatter'] = value_formatter

            col_defs.append(cd)

        if row_id_field == 'id' and first_field:
            row_id_field = first_field

        cols_str = ', '.join(f'`{c}`' for c in display_cols) if display_cols else '*'
        return col_defs, row_id_field, cols_str

    # ──────────────────── 列可见性 ────────────────────

    def _on_bitable_columns_popup(self):
        """显示列可见性弹窗。"""
        if not self._bitable_current_columns:
            return

        all_fields = [c['field'] for c in self._bitable_current_columns]
        visible = self._bitable_visible_columns or all_fields

        popup = CheckableOptionPopup(self)
        popup.set_options(all_fields, visible, select_all_when_empty=True)

        def _on_apply():
            selected = popup.get_selected_options()
            if not selected:
                return
            self._bitable_visible_columns = selected
            new_defs = self._apply_column_visibility(
                self._bitable_current_columns, selected
            )
            self._bitable_bridge.set_columns(new_defs)
            QTimer.singleShot(200, self._bitable_bridge.refresh_grid)
            self._bitable_save_view_state('visible_columns', selected)

        popup.selection_changed.connect(_on_apply)

        btn = self._bitable_btn_columns
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        popup.move(pos.x(), pos.y() + 4)
        popup.show()

    def _apply_column_visibility(self, col_defs, visible_fields):
        """设置列的 hide 属性。"""
        visible_set = set(visible_fields)
        result = []
        for cd in col_defs:
            new_cd = dict(cd)
            new_cd['hide'] = cd['field'] not in visible_set
            result.append(new_cd)
        return result

    # ──────────────────── 编辑模式 ────────────────────

    def _on_bitable_toggle_edit(self, checked):
        """切换编辑模式。"""
        self._bitable_bridge.set_editable(checked)
        self._bitable_btn_edit.setText("编辑中" if checked else "编辑")

    # ──────────────────── 导出 / 刷新 ────────────────────

    def _on_bitable_export(self):
        """导出当前数据为 CSV。"""
        table = self._bitable_current_table or 'export'
        safe_name = re.sub(r'[^\w一-鿿-]', '_', table)
        self._bitable_bridge.export_csv(f'{safe_name}.csv')

    def _on_bitable_refresh(self):
        """刷新当前表数据。"""
        if self._bitable_current_table and self._bitable_page_is_ready:
            self._bitable_cache_version += 1
            self._bitable_query_cache.clear()
            self._bitable_bridge.refresh_grid()
            self._bitable_status_label.setText("已刷新")

    # ──────────────────── 视图切换 ────────────────────

    def _bitable_switch_view(self, view: str):
        """切换表格/图表/仪表盘视图。"""
        self._bitable_btn_grid.setChecked(view == 'grid')
        self._bitable_btn_chart.setChecked(view == 'chart')
        self._bitable_btn_dashboard.setChecked(view == 'dashboard')

        is_grid = (view == 'grid')
        is_chart = (view == 'chart')
        is_dash = (view == 'dashboard')

        # 图表配置面板仅图表模式可见
        self._bitable_chart_panel.setVisible(is_chart)

        # 表格专用按钮仅表格模式可见
        self._bitable_btn_columns.setVisible(is_grid)
        self._bitable_btn_sort.setVisible(is_grid)
        self._bitable_btn_search.setVisible(is_grid)
        self._bitable_row_height.setVisible(is_grid)
        self._bitable_btn_export.setVisible(is_grid)
        self._bitable_btn_refresh.setVisible(is_grid)

        # WebEngine 可见性：表格和图表模式显示，仪表盘模式隐藏
        self._bitable_webview.setVisible(not is_dash)

        # 仪表盘 widget 可见性
        if hasattr(self, '_bitable_dash_widget'):
            self._bitable_dash_widget.setVisible(is_dash)

        if not is_dash:
            self._bitable_bridge.switch_view('grid' if is_grid else 'chart')

        if is_chart:
            self._bitable_populate_chart_fields()

    def _bitable_populate_chart_fields(self):
        """填充图表配置的字段下拉框。"""
        if not self._bitable_current_columns:
            return

        # 保存当前选中值
        prev_x = self._bitable_chart_x.currentText()
        prev_y = self._bitable_chart_y.currentText()

        self._bitable_chart_x.blockSignals(True)
        self._bitable_chart_y.blockSignals(True)
        self._bitable_chart_group.blockSignals(True)

        self._bitable_chart_x.clear()
        self._bitable_chart_y.clear()
        self._bitable_chart_group.clear()
        self._bitable_chart_group.addItem("(无)", "")

        for cd in self._bitable_current_columns:
            field = cd['field']
            name = cd.get('headerName', field)
            self._bitable_chart_x.addItem(name, field)
            self._bitable_chart_y.addItem(name, field)
            self._bitable_chart_group.addItem(name, field)

        # 恢复之前选中
        if prev_x:
            idx = self._bitable_chart_x.findText(prev_x)
            if idx >= 0:
                self._bitable_chart_x.setCurrentIndex(idx)
        if prev_y:
            idx = self._bitable_chart_y.findText(prev_y)
            if idx >= 0:
                self._bitable_chart_y.setCurrentIndex(idx)

        self._bitable_chart_x.blockSignals(False)
        self._bitable_chart_y.blockSignals(False)
        self._bitable_chart_group.blockSignals(False)

    def _on_bitable_render_chart(self):
        """生成图表。"""
        if not self._bitable_current_table:
            self._bitable_status_label.setText("请先选择数据源")
            return

        mgr = getattr(self, '_report_manager', None)
        if not mgr or not mgr._db or not mgr._db.available:
            self._bitable_status_label.setText("数据库不可用")
            return

        # 获取配置
        chart_type_name = self._bitable_chart_type.currentText()
        chart_type = self._bitable_chart_type_map.get(chart_type_name, 'bar')
        x_field = self._bitable_chart_x.currentData()
        y_field = self._bitable_chart_y.currentData()
        agg_name = self._bitable_chart_agg.currentText()
        agg = self._bitable_chart_agg_map.get(agg_name, 'sum')
        group_field = self._bitable_chart_group.currentData() or None

        if not x_field or not y_field:
            self._bitable_status_label.setText("请选择 X 轴和 Y 轴字段")
            return

        self._bitable_status_label.setText("正在查询数据...")

        # 后台查询
        from chart_engine import ChartEngine
        engine = ChartEngine(mgr._db)

        try:
            data = engine.query_data(
                table=self._bitable_current_table,
                x_field=x_field,
                y_fields=[y_field],
                group_field=group_field,
                agg=agg,
            )
        except Exception as e:
            self._bitable_status_label.setText(f"查询失败: {e}")
            return

        if not data:
            self._bitable_status_label.setText("查询无数据")
            return

        # 生成 ECharts options
        title = f"{chart_type_name} — {self._bitable_current_table}"
        option = engine.build_option(
            chart_type=chart_type,
            data=data,
            x_field=x_field,
            y_fields=[y_field],
            group_field=group_field,
            title=title,
        )

        # 渲染图表
        self._bitable_bridge.render_chart(option)
        self._bitable_status_label.setText(
            f"图表已生成: {len(data)} 条数据, {chart_type_name}"
        )

    # ──────────────────── 视图持久化 ────────────────────

    def _bitable_save_view_state(self, key: str, value):
        """保存视图状态到 config。"""
        if not self._bitable_current_table:
            return
        try:
            cfg = load_config()
            views = cfg.setdefault('bitable_views', {})
            tbl_views = views.setdefault(self._bitable_current_table, {})
            tbl_views.setdefault('default', {})[key] = value
            save_config(cfg)
        except Exception as e:
            logger.error(f"[Bitable] Save view state failed: {e}")

    def _bitable_load_view_state(self) -> dict:
        """加载当前表的已保存视图状态。"""
        if not self._bitable_current_table:
            return {}
        try:
            cfg = load_config()
            return cfg.get('bitable_views', {}).get(
                self._bitable_current_table, {}
            ).get('default', {})
        except Exception:
            return {}


# ============================================================
# 排序配置对话框
# ============================================================

class _SortConfigDialog(CenteredPopupDialog):
    """多列排序配置对话框。"""

    def __init__(self, columns: list, parent=None):
        super().__init__(parent, title="排序配置")
        self._columns = columns  # [{'field': ..., 'headerName': ...}, ...]
        self._rows = []
        self._build_ui()

    def _build_ui(self):
        content = self.content_layout
        self._rows_layout = QVBoxLayout()
        content.addLayout(self._rows_layout)

        # 添加第一个排序行
        self._add_sort_row()

        btn_add = QPushButton("＋ 添加排序条件")
        btn_add.clicked.connect(self._add_sort_row)
        content.addWidget(btn_add)

    def _add_sort_row(self):
        row = QHBoxLayout()
        combo = QComboBox()
        for c in self._columns:
            combo.addItem(c.get('headerName', c['field']), c['field'])
        row.addWidget(combo, 1)

        direction = QComboBox()
        direction.addItems(["升序", "降序"])
        row.addWidget(direction)

        btn_del = QPushButton("✕")
        btn_del.setFixedWidth(28)
        row.addWidget(btn_del)

        self._rows_layout.addLayout(row)
        self._rows.append((combo, direction, row))
        btn_del.clicked.connect(lambda: self._remove_sort_row(combo, direction, row))

    def _remove_sort_row(self, combo, direction, row):
        if len(self._rows) <= 1:
            return
        self._rows = [(c, d, r) for c, d, r in self._rows if c is not combo]
        # 清理布局
        while row.count():
            item = row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows_layout.removeItem(row)

    def get_sort_state(self) -> list:
        """返回 AG Grid applyColumnState 格式的排序状态。"""
        state = []
        for combo, direction, _ in self._rows:
            field = combo.currentData()
            sort = 'asc' if direction.currentText() == '升序' else 'desc'
            if field:
                state.append({'colId': field, 'sort': sort})
        return state
