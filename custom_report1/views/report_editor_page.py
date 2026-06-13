"""
报表编辑器主页面

组装表选择器、画布、字段面板、筛选栏、预览面板为完整的编辑器界面。

布局:
  ┌──────────────────────────────────────────────────────────┐
  │ [←返回] 报表名称: [____]  [保存] [刷新数据]               │
  ├────────┬───────────────────────────┬─────────────────────┤
  │ ① 表   │   ② 画布区域              │  ③ 字段配置 (右上)   │
  │   选择 │   (QGraphicsView)        ├─────────────────────┤
  │   面板 │                          │  ④ 筛选栏            │
  │        │                          ├─────────────────────┤
  │        │                          │  ⑤ 预览 (右下)       │
  └────────┴───────────────────────────┴─────────────────────┘
"""

import logging
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QFrame,
    QPushButton, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QApplication, QComboBox, QDialog, QGroupBox, QRadioButton,
    QListWidget, QListWidgetItem, QDialogButtonBox, QButtonGroup,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, QTimer
from PyQt6.QtGui import QColor

from .canvas.join_canvas import JoinCanvas
from .canvas.table_card import TableCard
from .field_config_panel import FieldConfigPanel
from .preview_table import PreviewTable
from .filter_bar import FilterBar
from .table_selector_panel import TableSelectorPanel
from .sql_editor_dialog import SQLEditorDialog

from ..models import ReportDefinition, FieldColumn, FilterCondition, JoinDefinition, MatchKey
from ..repository import ReportRepository
from ..db_manager import ReportDatabase
from ..syncer import ReportRefreshWorker, SourceTableSyncer
from ..fetcher import DataFetcher

# 浅色 QMessageBox 样式（覆盖系统深色主题）
_MSGBOX_STYLE = """
    QMessageBox { background-color: #FAFAFA; color: #333333; }
    QLabel { color: #333333; font-size: 13px; }
    QPushButton {
        background-color: #FFFFFF; color: #333333;
        border: 1px solid #D9D9D9; border-radius: 4px;
        padding: 6px 20px; font-size: 13px; min-width: 80px;
    }
    QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
"""

def _light_msgbox(parent, icon, title, text):
    """显示浅色背景的消息弹窗（避免系统深色主题导致黑底）。"""
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(icon)
    msg.setStyleSheet(_MSGBOX_STYLE)
    return msg.exec()


class RefreshThread(QThread):
    """后台刷新线程"""
    progress = pyqtSignal(str, str, int)  # phase, message, percent
    finished = pyqtSignal(dict)           # result dict

    def __init__(self, worker: ReportRefreshWorker, report: ReportDefinition):
        super().__init__()
        self._worker = worker
        self._report = report

    def run(self):
        result = self._worker.refresh(
            self._report,
            progress_callback=lambda p, m, pc: self.progress.emit(p, m, pc),
        )
        self.finished.emit(result)


class ReportEditorPage(QWidget):
    """报表编辑器"""

    # 信号
    backRequested = pyqtSignal()                        # 返回列表
    reportSaved = pyqtSignal(str)                       # report_id

    def __init__(self, repo: ReportRepository = None,
                 db: ReportDatabase = None,
                 fetcher: DataFetcher = None,
                 app_config: dict = None,
                 save_config_fn=None,
                 load_config_fn=None,
                 save_filters_fn=None,
                 excel_repo=None,
                 parent=None):
        super().__init__(parent)
        self._repo = repo or ReportRepository()
        self._db = db
        self._fetcher = fetcher or DataFetcher()
        self._syncer = SourceTableSyncer(self._db, self._fetcher) if self._db else None
        self._refresh_worker = ReportRefreshWorker(self._db, self._syncer) if self._db else None

        self._report: ReportDefinition = None
        self._object_meta: dict[str, dict] = {}  # {api_name: {name, fields: [(key, label)]}}
        self._refresh_thread: RefreshThread = None
        self._table_selector: TableSelectorPanel = None  # created in _setup_ui
        self._app_config = app_config or {}
        self._save_config_fn = save_config_fn
        self._load_config_fn = load_config_fn
        self._save_filters_fn = save_filters_fn
        self._excel_repo = excel_repo
        self._splitter: QSplitter = None  # created in _setup_ui
        self._filter_change_timer = QTimer()
        self._filter_change_timer.setSingleShot(True)
        self._filter_change_timer.setInterval(300)
        self._filter_change_timer.timeout.connect(self._apply_filter_to_preview)

        self._setup_ui()

    def set_object_meta(self, meta: dict[str, dict]):
        """
        设置可用对象元数据

        Args:
            meta: {api_name: {name: "中文名", fields: [(key, label, is_time), ...]}}
                  兼容旧格式 [(key, label), ...]
        """
        self._object_meta = meta
        self._update_refresh_button_state()
        # 同步更新表选择器的名称映射并刷新列表
        if hasattr(self, '_table_selector') and self._table_selector:
            name_map = {}
            for api, m in meta.items():
                name = m.get('name', api)
                name_map[f'对象-{name}'] = name
                name_map[f'sr_{api}'] = name
            self._table_selector.set_name_mapping(name_map)
            self._table_selector.refresh()
        # 同步更新筛选栏可用字段
        self._update_filter_bar_fields()

    # ==================== UI 构建 ====================

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 强制浅色调色板，防止系统深色主题影响
        light_palette = self.palette()
        light_palette.setColor(light_palette.Window, QColor('#FAFAFA'))
        light_palette.setColor(light_palette.WindowText, QColor('#333333'))
        light_palette.setColor(light_palette.Base, QColor('#FFFFFF'))
        light_palette.setColor(light_palette.AlternateBase, QColor('#F5F5F5'))
        light_palette.setColor(light_palette.Text, QColor('#333333'))
        light_palette.setColor(light_palette.Button, QColor('#FFFFFF'))
        light_palette.setColor(light_palette.ButtonText, QColor('#333333'))
        self.setPalette(light_palette)
        self.setStyleSheet("""
            QWidget { color: #333333; }
            QComboBox {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 4px 10px; font-size: 13px;
            }
            QComboBox:hover { border-color: #FF8C00; }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF; color: #333333;
                selection-background-color: #FFF7E6; selection-color: #333333;
            }
            QLineEdit {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 4px 10px; font-size: 13px;
            }
            QLineEdit:focus { border-color: #FF8C00; }
            QDateEdit {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 4px 10px; font-size: 13px;
            }
            QCheckBox { color: #333333; }
            QLabel { color: #333333; }
            QTableWidget {
                background-color: #FFFFFF; color: #333333;
                gridline-color: #F0F0F0; border: 1px solid #E0E0E0;
            }
            QHeaderView::section {
                background-color: #FAFAFA; color: #333333;
                border: none; border-bottom: 2px solid #E0E0E0;
                padding: 8px; font-weight: 500;
            }
            QListWidget {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #E0E0E0;
            }
            QGraphicsView { background-color: #F5F5F5; border: none; }
            QMenu {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #E0E0E0; border-radius: 4px;
            }
            QMenu::item { padding: 8px 20px; background-color: #FFFFFF; color: #333333; }
            QMenu::item:selected { background-color: #FFF7E6; color: #FF8C00; }
            QScrollBar:vertical {
                background-color: #F5F5F5; width: 10px;
            }
            QScrollBar::handle:vertical {
                background-color: #D0D0D0; border-radius: 5px; min-height: 24px;
            }
            QScrollBar::handle:vertical:hover { background-color: #B0B0B0; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QCalendarWidget {
                background-color: #FFFFFF; color: #333333;
            }
            QCalendarWidget QToolButton {
                color: #333333; background-color: #FFFFFF;
                border: 1px solid #D9D9D9; border-radius: 3px;
            }
            QToolTip {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #D9D9D9; padding: 4px;
            }
        """)

        # ---- 顶部操作栏 ----
        toolbar = QFrame()
        toolbar.setStyleSheet("""
            QFrame { background-color: #FAFAFA; border-bottom: 1px solid #E0E0E0; padding: 10px 16px; }
        """)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 10, 16, 10)
        toolbar_layout.setSpacing(12)

        back_btn = QPushButton("← 返回列表")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton { background: transparent; border: none; color: #1890FF;
                          font-size: 14px; text-decoration: underline; padding: 4px 10px; }
            QPushButton:hover { color: #FF8C00; }
        """)
        back_btn.clicked.connect(self.backRequested.emit)
        toolbar_layout.addWidget(back_btn)

        toolbar_layout.addWidget(QLabel("报表名称:"))

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("输入报表名称...")
        self._name_input.setFixedWidth(260)
        self._name_input.setFixedHeight(30)
        self._name_input.setStyleSheet("""
            QLineEdit { border: 1px solid #D9D9D9; border-radius: 4px;
                        padding: 4px 12px; font-size: 14px; }
            QLineEdit:focus { border-color: #FF8C00; }
        """)
        toolbar_layout.addWidget(self._name_input)

        toolbar_layout.addStretch()

        # 进度条（刷新时显示）
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(200)
        self._progress_bar.setFixedHeight(22)
        self._progress_bar.setVisible(False)
        self._progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #D9D9D9; border-radius: 3px; text-align: center; }
            QProgressBar::chunk { background-color: #FF8C00; border-radius: 2px; }
        """)
        toolbar_layout.addWidget(self._progress_bar)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 12px; color: #666;")
        toolbar_layout.addWidget(self._status_label)

        # SQL 编辑按钮（在刷新按钮之前）
        sql_edit_btn = QPushButton("📝 SQL编辑")
        sql_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sql_edit_btn.setMinimumWidth(110)
        sql_edit_btn.setStyleSheet("""
            QPushButton { background-color: #FFFFFF; color: #333; border: 1px solid #D9D9D9;
                          border-radius: 4px; padding: 6px 14px; font-size: 13px; }
            QPushButton:hover { border-color: #1890FF; color: #1890FF; }
        """)
        sql_edit_btn.clicked.connect(self._show_sql_editor)
        toolbar_layout.addWidget(sql_edit_btn)

        import_btn = QPushButton("📥 导入")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.setMinimumWidth(80)
        import_btn.setStyleSheet("""
            QPushButton { background-color: #FFFFFF; color: #333; border: 1px solid #D9D9D9;
                          border-radius: 4px; padding: 6px 14px; font-size: 13px; }
            QPushButton:hover { border-color: #52C41A; color: #52C41A; }
        """)
        import_btn.clicked.connect(self._import_report)
        toolbar_layout.addWidget(import_btn)

        export_btn = QPushButton("📤 导出")
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.setMinimumWidth(80)
        export_btn.setStyleSheet("""
            QPushButton { background-color: #FFFFFF; color: #333; border: 1px solid #D9D9D9;
                          border-radius: 4px; padding: 6px 14px; font-size: 13px; }
            QPushButton:hover { border-color: #1890FF; color: #1890FF; }
        """)
        export_btn.clicked.connect(self._export_report)
        toolbar_layout.addWidget(export_btn)

        save_btn = QPushButton("💾 保存配置")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setMinimumWidth(110)
        save_btn.setStyleSheet("""
            QPushButton { background-color: #FFFFFF; color: #333; border: 1px solid #D9D9D9;
                          border-radius: 4px; padding: 6px 14px; font-size: 13px; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        save_btn.clicked.connect(self._save_report)
        toolbar_layout.addWidget(save_btn)

        # 写入方式选择
        self._write_mode_combo = QComboBox()
        self._write_mode_combo.addItems(["覆盖 (DROP+CREATE)", "增量 (INSERT UPDATE)"])
        self._write_mode_combo.setCurrentIndex(0)
        self._write_mode_combo.setFixedWidth(175)
        self._write_mode_combo.setFixedHeight(30)
        self._write_mode_combo.setToolTip("刷新数据时的 MySQL 写入方式\n覆盖：删表重建 | 增量：按ID插入/更新")
        toolbar_layout.addWidget(self._write_mode_combo)

        # 同步配置按钮
        sync_cfg_btn = QPushButton("⚙")
        sync_cfg_btn.setFixedSize(30, 30)
        sync_cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sync_cfg_btn.setToolTip("同步 MySQL 配置（主键字段、写入方式）")
        sync_cfg_btn.setStyleSheet("""
            QPushButton { background-color: #FFFFFF; color: #333; border: 1px solid #D9D9D9;
                          border-radius: 4px; font-size: 16px; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        sync_cfg_btn.clicked.connect(self._show_sync_config_dialog)
        toolbar_layout.addWidget(sync_cfg_btn)

        # 同步MySQL 按钮
        self._sync_mysql_btn = QPushButton("📤 同步MySQL")
        self._sync_mysql_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_mysql_btn.setMinimumWidth(130)
        self._sync_mysql_btn.setStyleSheet("""
            QPushButton { background-color: #00A854; color: #FFFFFF; border: none;
                          border-radius: 4px; padding: 8px 18px; font-size: 14px; font-weight: 600; }
            QPushButton:hover { background-color: #008C44; }
            QPushButton:disabled { background-color: #B0B0B0; color: #E0E0E0; }
        """)
        self._sync_mysql_btn.setToolTip("将当前结果表数据同步到展示用 MySQL 表\n"
                                        "写入方式来自左侧下拉选择：覆盖=删表重建 | 增量=按ID插入/更新")
        self._sync_mysql_btn.clicked.connect(self._on_sync_mysql)
        toolbar_layout.addWidget(self._sync_mysql_btn)

        self._refresh_btn = QPushButton("🔄 刷新数据")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setMinimumWidth(130)
        self._refresh_btn.setStyleSheet("""
            QPushButton { background-color: #FF8C00; color: #FFFFFF; border: none;
                          border-radius: 4px; padding: 8px 18px; font-size: 14px; font-weight: 600; }
            QPushButton:hover { background-color: #E67A00; }
            QPushButton:disabled { background-color: #CCC; }
        """)
        self._refresh_btn.clicked.connect(self._refresh_data)
        toolbar_layout.addWidget(self._refresh_btn)

        layout.addWidget(toolbar)

        # ---- 主区域 (水平分割，三栏) ----
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # ① 左侧：可用表选择面板
        self._table_selector = TableSelectorPanel(self._db, excel_repo=self._excel_repo)
        self._table_selector.tableSelected.connect(self._on_table_selected_from_panel)
        self._table_selector.importExcelRequested.connect(self._on_import_excel)
        self._table_selector.addMySQLRequested.connect(self._on_add_mysql_table)
        self._table_selector.refreshExcelRequested.connect(self._on_refresh_excel_table)
        # 设置表名映射（MySQL表名 → 中文显示名）
        name_map = {}
        for api, meta in self._object_meta.items():
            name = meta.get('name', api)
            name_map[f'对象-{name}'] = name
            name_map[f'sr_{api}'] = name
        self._table_selector.set_name_mapping(name_map)
        self._splitter.addWidget(self._table_selector)
        self._splitter.setStretchFactor(0, 1)

        # ② 中间：画布
        self._canvas = JoinCanvas()
        self._splitter.addWidget(self._canvas)
        self._splitter.setStretchFactor(1, 3)

        # ③ 右侧：面板区 (垂直分割)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        # 字段配置面板
        self._field_panel = FieldConfigPanel()
        self._field_panel.set_config_callbacks(self._save_config_fn, self._load_config_fn)
        right_layout.addWidget(self._field_panel, 1)

        # 筛选栏
        self._filter_bar = FilterBar()
        if self._db:
            self._filter_bar.set_database(self._db)
        right_layout.addWidget(self._filter_bar)

        # 预览面板
        self._preview = PreviewTable(self._db)
        self._preview.set_config_callbacks(self._save_config_fn, self._load_config_fn)
        right_layout.addWidget(self._preview, 2)

        # 将筛选按钮桥接到筛选栏：预览表格的筛选按钮 → 筛选栏的展开/收起
        filter_btn = self._preview.get_filter_toggle_button()
        if filter_btn:
            self._filter_bar.set_toggle_button(filter_btn)
        self._preview.filterToggleRequested.connect(self._filter_bar.toggle_filter_panel)

        self._splitter.addWidget(right_panel)
        self._splitter.setStretchFactor(2, 2)

        # 恢复用户之前保存的画布宽度（个人配置），无保存记录时使用默认值
        saved_sizes = self._load_splitter_sizes()
        if saved_sizes and len(saved_sizes) == 3:
            self._splitter.setSizes(saved_sizes)
        else:
            self._splitter.setSizes([220, 650, 500])

        # 用户拖动分割条后自动保存到个人配置文件
        self._splitter.splitterMoved.connect(self._on_splitter_moved)

        layout.addWidget(self._splitter, 1)

        # 底部状态
        status_bar = QFrame()
        status_bar.setStyleSheet("""
            QFrame { background-color: #FAFAFA; border-top: 1px solid #E0E0E0; padding: 4px 12px; }
        """)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(12, 4, 12, 4)
        self._bottom_status = QLabel("就绪 — 请从左侧面板双击添加数据表")
        self._bottom_status.setStyleSheet("font-size: 11px; color: #999;")
        status_layout.addWidget(self._bottom_status)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("font-size: 11px; color: #999; min-width: 36px;")
        status_layout.addWidget(self._zoom_label)

        zoom_in_btn = QPushButton("🔍+")
        zoom_in_btn.setFixedSize(30, 24)
        zoom_in_btn.clicked.connect(self._canvas.zoom_in)
        status_layout.addWidget(zoom_in_btn)

        zoom_out_btn = QPushButton("🔍-")
        zoom_out_btn.setFixedSize(30, 24)
        zoom_out_btn.clicked.connect(self._canvas.zoom_out)
        status_layout.addWidget(zoom_out_btn)

        zoom_reset_btn = QPushButton("1:1")
        zoom_reset_btn.setFixedSize(30, 24)
        zoom_reset_btn.clicked.connect(self._canvas.zoom_reset)
        status_layout.addWidget(zoom_reset_btn)

        auto_layout_btn = QPushButton("自动布局")
        auto_layout_btn.setFixedSize(72, 26)
        auto_layout_btn.setStyleSheet("font-size: 12px; padding: 2px 6px;")
        auto_layout_btn.clicked.connect(self._canvas.auto_layout)
        status_layout.addWidget(auto_layout_btn)

        # 画布显示/隐藏按钮
        self._canvas_visible = True
        self._toggle_canvas_btn = QPushButton("隐藏画布")
        self._toggle_canvas_btn.setFixedSize(72, 26)
        self._toggle_canvas_btn.setStyleSheet("font-size: 12px; padding: 2px 6px;")
        self._toggle_canvas_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_canvas_btn.clicked.connect(self._toggle_canvas_visibility)
        status_layout.addWidget(self._toggle_canvas_btn)

        layout.addWidget(status_bar)

        # 信号连接
        self._canvas.canvasModified.connect(self._on_canvas_modified)
        self._canvas.zoomChanged.connect(
            lambda z: self._zoom_label.setText(f"{int(z * 100)}%")
        )
        self._field_panel.columnsChanged.connect(self._on_field_panel_changed)
        self._preview.columnOrderChanged.connect(self._on_preview_column_order_changed)
        self._filter_bar.filtersChanged.connect(self._on_filter_changed)

        # 初始加载表列表
        self._table_selector.refresh()

    # ==================== 画布宽度持久化（保存到用户个人配置文件） ====================

    def _load_splitter_sizes(self):
        """从用户个人配置文件恢复分割条宽度，无记录时返回 None。"""
        try:
            cfg = None
            if self._load_config_fn:
                cfg = self._load_config_fn()
            if not cfg:
                cfg = self._app_config or {}
            cr = cfg.get('custom_reports', {}) if isinstance(cfg, dict) else {}
            sizes = cr.get('editor_splitter_sizes')
            if isinstance(sizes, list) and len(sizes) == 3 and all(isinstance(s, int) and s > 0 for s in sizes):
                return sizes
        except Exception:
            pass
        return None

    def _on_splitter_moved(self, pos, index):
        """分割条拖动后防抖保存宽度到个人配置文件。"""
        if not self._save_config_fn:
            return
        if not self._splitter:
            return
        # 使用 QTimer 防抖，避免拖动过程中频繁写入磁盘
        if hasattr(self, '_splitter_save_timer'):
            self._splitter_save_timer.stop()
        else:
            self._splitter_save_timer = QTimer()
            self._splitter_save_timer.setSingleShot(True)
            self._splitter_save_timer.timeout.connect(self._do_save_splitter_sizes)
        self._splitter_save_timer.start(800)  # 800ms 防抖

    def _do_save_splitter_sizes(self):
        """执行分割条宽度保存（使用最新配置避免覆盖并发修改）。"""
        try:
            sizes = self._splitter.sizes()
            if len(sizes) != 3:
                return
            # 优先使用 load_config_fn 获取最新配置，避免覆盖其他模块的并发修改
            cfg = None
            if self._load_config_fn:
                try:
                    cfg = self._load_config_fn()
                except Exception:
                    pass
            if not cfg:
                cfg = self._app_config or {}
            if not isinstance(cfg, dict):
                return
            cfg.setdefault('custom_reports', {})
            old_sizes = cfg['custom_reports'].get('editor_splitter_sizes')
            if old_sizes == sizes:
                return  # 未变化，跳过写入
            cfg['custom_reports']['editor_splitter_sizes'] = list(sizes)
            self._save_config_fn(cfg)
        except Exception:
            pass

    # ==================== 报表加载/保存 ====================

    def new_report(self, main_object_api: str = ""):
        """创建新报表"""
        self._report = ReportDefinition(main_object_api=main_object_api)
        self._name_input.setText("")
        # 新报表：如果指定了主表则只显示该表，否则显示所有可用对象
        self._load_to_ui(show_all=not bool(main_object_api))

    def load_report(self, report: ReportDefinition):
        """加载已有报表"""
        self._report = report
        self._name_input.setText(report.name)
        self._load_to_ui()

    def _load_to_ui(self, show_all: bool = False):
        """将 ReportDefinition 加载到 UI

        Args:
            show_all: True = 新建空白报表（画布保持空白），
                      False = 只显示已关联的对象（编辑已有报表时）
        """
        if not self._report:
            return

        # 画布：创建卡片
        scene = self._canvas.canvas_scene
        # 清除现有
        for card in list(scene.get_all_cards()):
            scene.remove_card(card.object_api)

        # 确定要显示的对象列表
        if show_all:
            # 新建报表：画布保持空白，不自动添加任何表
            display_apis = []
        else:
            display_apis = self._report.get_object_apis()
            if not display_apis and self._object_meta:
                # 空报表回退：显示所有对象（兼容旧流程）
                display_apis = list(self._object_meta.keys())

        for api in display_apis:
            # 获取显示名和字段：优先从 _object_meta，其次从 MySQL 清洗表
            name, field_meta = self._resolve_table_info(api)

            # 收集该对象已选字段的 key 和 label
            # source_object_api 可能为空（旧数据），此时全匹配
            selected_keys = set()
            selected_labels = set()
            for c in self._report.columns:
                if isinstance(c, FieldColumn):
                    src_api = c.source_object_api
                elif isinstance(c, dict):
                    src_api = c.get('source_object_api', '')
                else:
                    continue
                # 指定对象匹配 或 未指定对象时全匹配
                if src_api and src_api != api:
                    continue
                sf = c.source_field if isinstance(c, FieldColumn) else c.get('source_field', '')
                dn = c.display_name if isinstance(c, FieldColumn) else c.get('display_name', '')
                if sf:
                    selected_keys.add(sf)
                if dn:
                    selected_labels.add(dn)
            fields = []
            for item in field_meta:
                key = item[0]
                label = item[1] if len(item) >= 2 else key
                checked = key in selected_keys or label in selected_labels
                fields.append((key, label, checked))

            pos = self._report.canvas_positions.get(api)
            pos = (pos[0], pos[1]) if pos else None
            is_main = (api == self._report.main_object_api)

            card = TableCard(api, name, fields, is_main=is_main)
            if pos:
                card.setPos(*pos)
            scene.add_card(card)

            # 字段勾选同步
            card.fieldToggled.connect(
                lambda api_name=api, field_key=None, checked=None:
                    self._on_card_field_toggled(api_name, field_key, checked)
            )

        # 还原连线
        scene.from_report_joins(self._report.joins)

        # 字段面板
        columns = []
        sorted_cols = sorted(
            self._report.columns,
            key=lambda c: c.sort_order if isinstance(c, FieldColumn) else (c.get('sort_order', 0) if isinstance(c, dict) else 0)
        )
        for col in sorted_cols:
            if isinstance(col, FieldColumn):
                src_field = self._normalize_field_key(col.source_object_api, col.source_field)
                columns.append({
                    'display_name': col.display_name,
                    'source_object': col.source_object_api,
                    'source_field': src_field,
                    'visible': col.visible,
                    'computation_type': getattr(col, 'computation_type', 'direct'),
                    'aggregate_func': getattr(col, 'aggregate_func', ''),
                    'formula_expression': getattr(col, 'formula_expression', ''),
                    'address_source_fields': getattr(col, 'address_source_fields', []) or [],
                    'address_target_level': getattr(col, 'address_target_level', '') or '',
                    'date_part_source_field': getattr(col, 'date_part_source_field', '') or '',
                    'date_part_unit': getattr(col, 'date_part_unit', '') or '',
                    'field_format': getattr(col, 'field_format', 'text') or 'text',
                })
            elif isinstance(col, dict):
                src_api = col.get('source_object_api', '')
                src_field = self._normalize_field_key(src_api, col.get('source_field', ''))
                columns.append({
                    'display_name': col.get('display_name', ''),
                    'source_object': src_api,
                    'source_field': src_field,
                    'visible': col.get('visible', True),
                    'computation_type': col.get('computation_type', 'direct'),
                    'aggregate_func': col.get('aggregate_func', ''),
                    'formula_expression': col.get('formula_expression', ''),
                    'address_source_fields': col.get('address_source_fields', []) or [],
                    'address_target_level': col.get('address_target_level', '') or '',
                    'date_part_source_field': col.get('date_part_source_field', '') or '',
                    'date_part_unit': col.get('date_part_unit', '') or '',
                    'field_format': col.get('field_format', 'text') or 'text',
                })
        self._field_panel.set_columns(columns)

        # 恢复分组与汇总设置
        self._field_panel.set_group_by_fields(
            getattr(self._report, 'group_by_fields', []) or []
        )
        self._field_panel.set_show_summary_row(
            getattr(self._report, 'show_summary_row', False)
        )

        # 筛选栏
        self._update_filter_bar_fields()
        # 构建筛选条件（含字段标签解析）
        restored_conditions = []
        for f in self._report.filters:
            if isinstance(f, FilterCondition):
                api = f.field_api
                op = f.operator
                val = f.value
                target = f.target_object_api
                fl = f.field_label
                exp = f.expose
                is_dt = f.is_date_field
            elif isinstance(f, dict):
                api = f.get('field_api', '')
                op = f.get('operator', 'EQ')
                val = f.get('value', '')
                target = f.get('target_object_api', '')
                fl = f.get('field_label', '')
                exp = f.get('expose', False)
                is_dt = f.get('is_date_field', False)
            else:
                continue
            # 解析字段标签（若未存储）
            if not fl:
                fl = self._resolve_field_label(target or self._report.main_object_api, api)
            restored_conditions.append({
                'field': api,
                'field_label': fl,
                'target_object_api': target,
                'operator': op,
                'value': val,
                'expose': exp,
                'is_date': is_dt,
            })
        self._filter_bar.set_conditions(restored_conditions)

        # 预览
        if self._db:
            self._filter_bar.set_database(self._db)
        if self._db and self._db.result_table_exists(self._report.id):
            self._preview.set_report(self._report.id)
            self._preview.set_report_definition(self._report)
            self._filter_bar.set_result_table(ReportDatabase.result_table_name(self._report.id))
            self._sync_field_order_to_preview()
            # 加载时立即应用已保存的筛选条件（修复重启后筛选不生效）
            conditions = self._filter_bar.get_conditions()
            if conditions:
                self._preview.set_filter_conditions(conditions)
        elif self._db:
            self._preview.show_status("暂无数据 — 请配置字段后点击「🔄 刷新数据」")
        else:
            self._preview.show_status("数据库未连接 — 请先在设置中配置 MySQL")

        # 最终同步：从字段面板内部数据勾选画布卡片字段
        for col_dict in self._field_panel._columns:
            api = col_dict.get('source_object', '')
            sf = col_dict.get('source_field', '')
            dn = col_dict.get('display_name', '')
            if not sf:
                continue
            for card in scene.get_all_cards():
                if api and card.object_api != api:
                    continue
                for f in card.get_all_fields():
                    if f['checked']:
                        continue
                    if f['key'] == sf or f['label'] == sf or f['label'] == dn or f['key'] == dn:
                        card.update_field_checked(f['key'], True)
                        break

        # 自动布局（新报表时）
        if not self._report.canvas_positions:
            self._canvas.auto_layout()

        # 恢复写入方式选择
        wm = getattr(self._report, 'write_mode', 'overwrite')
        self._write_mode_combo.setCurrentIndex(0 if wm == 'overwrite' else 1)

        self._update_status()
        self._update_refresh_button_state()

    def _save_report(self):
        """保存报表配置"""
        if not self._report:
            return

        name = self._name_input.text().strip()
        if not name:
            _light_msgbox(self, QMessageBox.Icon.Warning, "提示", "请输入报表名称。")
            return

        self._report.name = name

        # 从 UI 收集配置
        self._collect_from_ui()

        # 应用待定的文件夹路径（从列表页新建时传入）
        pending_folder = getattr(self, '_pending_folder_path', '')
        if pending_folder:
            self._report.folder_path = pending_folder
            self._pending_folder_path = ''  # 仅首次保存时应用

        self._repo.save(self._report)
        self.reportSaved.emit(self._report.id)
        self._bottom_status.setText(f"✅ 已保存: {name}")
        _light_msgbox(self, QMessageBox.Icon.Information, "保存成功", f"报表 \"{name}\" 已保存。")

    def _export_report(self):
        """导出报表定义为 .crpt 文件"""
        if not self._report:
            _light_msgbox(self, QMessageBox.Icon.Warning, "提示", "请先创建或打开报表。")
            return

        # 先收集最新配置
        name = self._name_input.text().strip()
        if name:
            self._report.name = name
        self._collect_from_ui()

        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出报表定义", f"{self._report.name}.crpt",
            "报表定义文件 (*.crpt);;JSON 文件 (*.json)"
        )
        if not path:
            return

        try:
            import json
            data = self._report.to_dict()
            # 清除结果表信息（导入后需要重新刷新）
            data.pop('result_table_name', None)
            data.pop('result_row_count', None)
            data.pop('last_refresh_time', None)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _light_msgbox(self, QMessageBox.Icon.Information, "导出成功",
                          f"报表定义已导出到:\n{path}")
        except Exception as e:
            _light_msgbox(self, QMessageBox.Icon.Warning, "导出失败", str(e))

    def _import_report(self):
        """从 .crpt 文件导入报表定义"""
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

            # 验证必要字段
            if not data.get('name'):
                _light_msgbox(self, QMessageBox.Icon.Warning, "导入失败", "无效的报表定义文件：缺少名称。")
                return

            # 生成新 ID 避免冲突
            data['id'] = uuid.uuid4().hex[:12]
            data['name'] = data['name'] + " (导入)"
            # 清除运行状态
            data.pop('result_table_name', None)
            data.pop('result_row_count', None)
            data.pop('last_refresh_time', None)
            data.pop('created_at', None)
            data.pop('modified_at', None)

            report = ReportDefinition.from_dict(data)
            self._repo.save(report)

            # 加载到当前编辑器
            self._report = report
            self._name_input.setText(report.name)

            # 清理旧画布
            scene = self._canvas.canvas_scene
            for card in list(scene.get_all_cards()):
                scene.remove_card(card.object_api)

            self._load_to_ui()
            self.reportSaved.emit(report.id)
            self._bottom_status.setText(f"✅ 已导入: {report.name}")
            _light_msgbox(self, QMessageBox.Icon.Information, "导入成功",
                          f"报表 \"{report.name}\" 已导入。\n请配置数据源后点击「刷新数据」。")
        except Exception as e:
            _light_msgbox(self, QMessageBox.Icon.Warning, "导入失败", str(e))

    # ==================== 数据导入 ====================

    def _on_import_excel(self):
        """导入 Excel/CSV 文件为数据源"""
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 Excel/CSV 文件", "",
            "表格文件 (*.xlsx *.xls *.csv);;所有文件 (*)"
        )
        if not path:
            return
        try:
            from ..dashboard.excel_importer import ExcelImporter
            importer = ExcelImporter(self._db)
            dataset = importer.import_file(
                path,
                progress_callback=lambda pct, msg: self._bottom_status.setText(
                    f"导入中 ({pct}%): {msg}")
            )
            if self._excel_repo:
                self._excel_repo.save(dataset)
            self._table_selector.refresh()
            self._bottom_status.setText(
                f"✅ 已导入: {dataset.name} ({dataset.row_count} 行)")
            _light_msgbox(self, QMessageBox.Icon.Information, "导入成功",
                         f"文件已导入为数据表:\n名称: {dataset.name}\n"
                         f"表名: {dataset.mysql_table}\n行数: {dataset.row_count}")
        except Exception as e:
            _light_msgbox(self, QMessageBox.Icon.Warning, "导入失败", str(e))

    def _on_refresh_excel_table(self, table_name: str):
        """右键刷新 Excel 表：从原始文件重新导入数据"""
        if not self._excel_repo:
            _light_msgbox(self, QMessageBox.Icon.Warning, "刷新失败", "数据仓库不可用")
            return
        # 查找数据集
        dataset = None
        for ds in self._excel_repo.list_all():
            if ds.mysql_table == table_name:
                dataset = ds
                break
        if not dataset:
            _light_msgbox(self, QMessageBox.Icon.Warning, "刷新失败", f"未找到表 {table_name} 的数据集记录")
            return
        source = dataset.source_file
        if not source or not os.path.exists(source):
            _light_msgbox(self, QMessageBox.Icon.Warning, "刷新失败",
                         f"原始文件不存在:\n{source}\n\n请重新导入。")
            return
        try:
            from ..dashboard.excel_importer import ExcelImporter
            importer = ExcelImporter(self._db)
            # 删旧表
            if self._db and self._db.available:
                try:
                    self._db.execute(f"DROP TABLE IF EXISTS `{table_name}`")
                except Exception:
                    pass
            new_dataset = importer.import_file(
                source,
                progress_callback=lambda pct, msg: self._bottom_status.setText(
                    f"刷新中 ({pct}%): {msg}")
            )
            # 将新表重命名为旧表名，保持引用一致
            new_table = new_dataset.mysql_table
            if new_table != table_name and self._db and self._db.available:
                try:
                    self._db.execute(f"RENAME TABLE `{new_table}` TO `{table_name}`")
                except Exception as e:
                    _light_msgbox(self, QMessageBox.Icon.Warning, "刷新失败", f"重命名表失败: {e}")
                    return
            # 保留原 ID 和表名，更新其他数据
            new_dataset.id = dataset.id
            new_dataset.mysql_table = table_name
            self._excel_repo.save(new_dataset)
            self._table_selector.refresh()
            self._bottom_status.setText(
                f"✅ 已刷新: {new_dataset.name} ({new_dataset.row_count} 行)")
        except Exception as e:
            _light_msgbox(self, QMessageBox.Icon.Warning, "刷新失败", str(e))

    def _on_add_mysql_table(self):
        """弹出 MySQL 表选择对话框，将选中的表添加到左侧面板。"""
        if not self._db or not self._db.available:
            _light_msgbox(self, QMessageBox.Icon.Warning, "数据库未连接",
                         "请先在设置中配置 MySQL 连接。")
            return
        from .table_selector_panel import _MySQLTableDialog
        dlg = _MySQLTableDialog(self._db, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            table_name = dlg.selected_table
            if table_name:
                if self._table_selector.add_mysql_table(table_name):
                    self._bottom_status.setText(f"✅ 已添加: {table_name}")
                else:
                    self._bottom_status.setText(f"表 {table_name} 已在列表中")
        else:
            self._bottom_status.setText("已取消")

    # ==================== 表名翻译 ====================

    def _is_non_crm_table(self, table_name: str) -> bool:
        """判断表名是否为非 CRM 数据源（Excel 导入 / 直连 MySQL 表）。"""
        if not table_name:
            return False
        if table_name.startswith('ex_'):
            return True
        # 检查 Excel repo
        if self._excel_repo:
            for ds in self._excel_repo.list_all():
                if ds.mysql_table == table_name:
                    return True
        # 不在 _object_meta 中 → 非 CRM 直连表
        if table_name not in self._object_meta:
            # 进一步检查：是否匹配 CRM 命名模式
            from ..db_manager import ReportDatabase
            try:
                sr_name = ReportDatabase.source_table_name(table_name)
            except Exception:
                sr_name = f"sr_{table_name}"
            if not self._db or not self._db.available:
                return True
            # 如果能通过 resolve_existing_table 转为「对象-」或「sr_」表 → CRM
            if hasattr(self._db, 'resolve_existing_table'):
                resolved = self._db.resolve_existing_table(table_name)
                if resolved != sr_name and resolved != table_name:
                    return False  # resolved to CRM table
            # 直接检查表名是否以对象-或sr_开头
            if table_name.startswith('对象-') or table_name.startswith('sr_'):
                return False
            return True
        return False

    def _to_crm_api_name(self, table_name: str) -> str:
        """将 MySQL 清洗表名（如 '对象-商机'）转换为 CRM API 名（如 'NewOpportunityObj'）。
        如果已是 CRM API 名则直接返回。非 CRM 表直接返回原表名。
        """
        if not table_name:
            return table_name
        # 直接匹配 _object_meta 的 key（CRM API 名）
        if table_name in self._object_meta:
            return table_name
        # 反向映射：MySQL 表名 → CRM API 名
        mapping = self._build_display_to_api_map()
        if table_name in mapping:
            return mapping[table_name]
        # 从裸名（去「对象-」前缀）查找
        raw_name = table_name[3:] if table_name.startswith('对象-') else table_name
        if raw_name in mapping:
            return mapping[raw_name]
        # 按 _object_meta 的 name 值反查（兜底：table_name 可能是中文显示名）
        for api, meta in self._object_meta.items():
            if isinstance(meta, dict) and meta.get('name', '') == raw_name:
                return api
        # 通过数据库管理器反查（解析 sr_xxx / 对象-xxx → CRM API 名）
        if self._db and hasattr(self._db, 'resolve_existing_table'):
            try:
                resolved = self._db.resolve_existing_table(table_name)
                # 如果 resolve 返回了不同于 table_name 的 sr_xxx，尝试反向映射
                if resolved and resolved != table_name:
                    if resolved.startswith('sr_'):
                        sr_name = resolved[3:]  # 去 sr_ 前缀
                        if sr_name in self._object_meta:
                            return sr_name
            except Exception:
                pass
        # 最后回退：从配置文件直接加载（_object_meta 可能尚未注入）
        try:
            import sys
            main = sys.modules.get('__main__')
            if main and hasattr(main, 'load_config'):
                cfg = main.load_config()
                crm_objs = cfg.get('fxiaoke', {}).get('crm_objects', [])
                for obj in crm_objs:
                    if isinstance(obj, dict):
                        api = obj.get('api_name', '')
                        name = obj.get('name', '')
                        if name and (table_name == f'对象-{name}' or table_name == name or raw_name == name):
                            return api
        except Exception:
            pass

        # 最终回退：非 CRM 表（Excel / MySQL 直连）静默返回原表名
        if table_name.startswith('ex_') or not (table_name.startswith('sr_') or table_name.startswith('对象-')):
            return table_name
        logger = logging.getLogger(__name__)
        logger.warning(
            f"[ReportEditor] 无法将表名 '{table_name}' 转换为 CRM API 名，"
            f"_object_meta 中有 {len(self._object_meta)} 个对象"
        )
        return table_name

    def _collect_from_ui(self):
        """从 UI 收集配置到 ReportDefinition（自动翻译 MySQL 表名为 CRM API 名）。"""
        rpt = self._report

        # 主表 → 翻译为 CRM API 名
        main_card = self._canvas.canvas_scene.get_main_card()
        if main_card:
            rpt.main_object_api = self._to_crm_api_name(main_card.object_api)

        # JOIN 关系 → 先翻译主表，再收集 JOIN
        rpt.joins = self._canvas.canvas_scene.to_report_joins(rpt.main_object_api)
        # 翻译 JOIN 中的表名
        translated_joins = []
        for j in rpt.joins:
            jd = j if isinstance(j, JoinDefinition) else JoinDefinition(**j) if isinstance(j, dict) else j
            jd.left_object_api = self._to_crm_api_name(jd.left_object_api)
            jd.right_object_api = self._to_crm_api_name(jd.right_object_api)
            translated_joins.append(jd)
        rpt.joins = translated_joins

        # 显示列 → 翻译 source_object，并标准化 source_field 为 API key
        columns = self._field_panel.get_columns()
        rpt.columns = []
        for i, c in enumerate(columns):
            comp_type = c.get('computation_type', 'direct')
            src_field = c.get('source_field', '')

            # 安全检查：如果 source_field 以 = 开头，自动识别为公式列
            if comp_type == 'direct' and src_field and str(src_field).startswith('='):
                comp_type = 'formula'
                c['formula_expression'] = str(src_field)

            # 公式列：不需要 source_field 验证
            if comp_type == 'formula':
                if not c['display_name']:
                    continue
                rpt.columns.append(FieldColumn(
                    display_name=c['display_name'],
                    source_object_api='',
                    source_field='',
                    visible=c['visible'],
                    sort_order=i,
                    computation_type='formula',
                    formula_expression=c.get('formula_expression', ''),
                    field_format=c.get('field_format', 'text') or 'text',
                ))
                continue
            # 地址提取列：不需要 source_field，使用 address_source_fields
            if comp_type == 'address_extract':
                if not c['display_name']:
                    continue
                rpt.columns.append(FieldColumn(
                    display_name=c['display_name'],
                    source_object_api='',
                    source_field='',
                    visible=c['visible'],
                    sort_order=i,
                    computation_type='address_extract',
                    address_source_fields=c.get('address_source_fields', []),
                    address_target_level=c.get('address_target_level', 'city'),
                    field_format=c.get('field_format', 'text') or 'text',
                ))
                continue
            # 时间成分列：不需要 source_field，使用 date_part_source_field
            if comp_type == 'date_part':
                if not c['display_name']:
                    continue
                rpt.columns.append(FieldColumn(
                    display_name=c['display_name'],
                    source_object_api='',
                    source_field='',
                    visible=c['visible'],
                    sort_order=i,
                    computation_type='date_part',
                    date_part_source_field=c.get('date_part_source_field', ''),
                    date_part_unit=c.get('date_part_unit', 'year'),
                    field_format=c.get('field_format', 'text') or 'text',
                ))
                continue
            # 聚合列 / 直接列
            if not (c['display_name'] and src_field):
                continue
            src_api = self._to_crm_api_name(c['source_object'])
            src_field_normalized = self._normalize_field_key(src_api, src_field)
            rpt.columns.append(FieldColumn(
                display_name=c['display_name'],
                source_object_api=src_api,
                source_field=src_field_normalized,
                visible=c['visible'],
                sort_order=i,
                computation_type=c.get('computation_type', 'direct'),
                aggregate_func=c.get('aggregate_func', ''),
                formula_expression=c.get('formula_expression', ''),
                field_format=c.get('field_format', 'text') or 'text',
            ))

        # 分组与汇总设置
        rpt.group_by_fields = self._field_panel.get_group_by_fields()
        rpt.show_summary_row = self._field_panel.get_show_summary_row()

        # 筛选
        rpt.filters = [
            FilterCondition(
                field_api=c['field'],
                operator=c['operator'],
                value=c.get('value', ''),
                target_object_api=c.get('target_object_api', ''),
                field_label=c.get('field_label', ''),
                expose=c.get('expose', False),
                is_date_field=c.get('is_date', False),
            )
            for c in self._filter_bar.get_conditions()
        ]

        # 画布位置
        positions = {}
        for card in self._canvas.canvas_scene.get_all_cards():
            pos = card.scenePos()
            positions[card.object_api] = (pos.x(), pos.y())
        rpt.canvas_positions = positions

        # 写入方式
        if self._write_mode_combo.currentIndex() == 0:
            rpt.write_mode = "overwrite"
        else:
            rpt.write_mode = "incremental"

    # ==================== 数据刷新 ====================

    def _update_refresh_button_state(self):
        """根据数据库状态更新刷新按钮和同步MySQL按钮"""
        db_connected = self._db and self._db.available
        if db_connected:
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setToolTip("从 CRM 拉取数据并执行拼表，结果写入 MySQL")
            self._sync_mysql_btn.setEnabled(True)
            self._sync_mysql_btn.setToolTip("将当前结果表数据同步到展示用 MySQL 表\n"
                                            "写入方式来自左侧下拉选择：覆盖=删表重建 | 增量=按ID插入/更新")
        else:
            self._refresh_btn.setEnabled(False)
            self._refresh_btn.setStyleSheet("""
                QPushButton { background-color: #CCC; color: #999; border: none;
                              border-radius: 4px; padding: 8px 20px; font-size: 14px; font-weight: 600; }
            """)
            self._refresh_btn.setToolTip("数据库未连接，请先在 设置→MySQL配置 中启用并测试连接")
            self._sync_mysql_btn.setEnabled(False)
            self._sync_mysql_btn.setToolTip("数据库未连接，请先在 设置→MySQL配置 中启用并测试连接")

    def _show_sync_config_dialog(self):
        """弹出同步 MySQL 配置对话框（主键字段选择 + 写入方式）。"""
        if not self._report:
            _light_msgbox(self, QMessageBox.Icon.Warning, "提示", "请先创建或打开报表。")
            return

        # 收集画布上所有表的所有字段（区分所属表），额外补上 _id
        # format: [(display_label, unique_key, field_label), ...]
        available_fields = []
        seen_keys = set()
        for card in self._canvas.canvas_scene.get_all_cards():
            # 优先使用画布卡片上已确认的显示名（绕过 _object_meta 中的潜在名称错误）
            obj_name = card.display_name or self._resolve_table_display_name(card.object_api)
            # 画布卡片字段（不含 _id）
            for f in card.get_all_fields():
                label = f.get('label', f['key'])
                key = (card.object_api, label)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                display_label = f"[{obj_name}] {label}"
                unique_key = f"{card.object_api}|{label}"
                available_fields.append((display_label, unique_key, label))
            # 补上 _id（每张表都有，但卡片上不显示）
            id_key = (card.object_api, '_id')
            if id_key not in seen_keys:
                seen_keys.add(id_key)
                available_fields.append((f"[{obj_name}] _id", f"{card.object_api}|_id", '_id'))
        if not available_fields:
            _light_msgbox(self, QMessageBox.Icon.Warning, "提示", "画布上没有可选的字段，请先添加数据表。")
            return

        # 恢复已保存的选择：用 exact unique_key 匹配
        saved_fields = getattr(self._report, 'sync_id_fields', None)
        import sys
        print(f"[SyncConfig] 打开对话框: saved_fields={saved_fields}", file=sys.stderr, flush=True)
        saved_set = set(saved_fields or [])
        selected_keys = []
        for _, unique_key, label in available_fields:
            if unique_key in saved_set:
                selected_keys.append(unique_key)
        print(f"[SyncConfig] 恢复选中: selected_keys={selected_keys}", file=sys.stderr, flush=True)

        # 转为对话框需要的 [(display, key), ...] 格式
        dlg_fields = [(dl, uk) for dl, uk, lb in available_fields]
        dlg = _SyncConfigDialog(
            self,
            dlg_fields,
            selected_keys,
            getattr(self._report, 'sync_id_separator', '_') or '_',
            getattr(self._report, 'write_mode', 'overwrite') or 'overwrite',
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            import sys
            print(f"[SyncConfig] 对话框确定: {result}", file=sys.stderr, flush=True)
            self._report.sync_id_fields = result['sync_id_fields']
            self._report.sync_id_separator = result['sync_id_separator']
            self._report.write_mode = result['write_mode']
            self._write_mode_combo.setCurrentIndex(0 if result['write_mode'] == 'overwrite' else 1)
            # 自动保存，避免重启丢失
            sync_before = self._report.sync_id_fields
            self._collect_from_ui()
            sync_after = self._report.sync_id_fields
            if sync_before != sync_after:
                print(f"[SyncConfig] ⚠ _collect_from_ui 清空了 sync_id_fields! {sync_before} → {sync_after}", file=sys.stderr, flush=True)
            self._repo.save(self._report)
            print(f"[SyncConfig] 保存后: sync_id_fields={self._report.sync_id_fields}", file=sys.stderr, flush=True)

    def _resolve_table_display_name(self, object_api: str) -> str:
        """解析表的中文显示名（优先使用 MySQL 实际表名，回退到 _object_meta）"""
        db_name = self._resolve_name_from_mysql_table(object_api)
        if db_name:
            return db_name
        meta = self._object_meta.get(object_api, {})
        if meta:
            return meta.get('name', object_api)
        return self._extract_display_name(object_api)

    def _on_sync_mysql(self):
        """将当前结果表数据同步到展示用的 MySQL 表（带中文表头）。

        写入方式来自左侧下拉选择：
          - 覆盖: DROP+CREATE 目标表，全量插入
          - 增量: INSERT ... ON DUPLICATE KEY UPDATE
        """
        if not self._report:
            _light_msgbox(self, QMessageBox.Icon.Warning, "提示", "请先创建或打开报表。")
            return

        if not self._db or not self._db.available:
            _light_msgbox(self, QMessageBox.Icon.Warning, "数据库未连接",
                         "无法同步：MySQL 数据库未连接。")
            return

        if not self._db.result_table_exists(self._report.id):
            _light_msgbox(self, QMessageBox.Icon.Warning, "无数据",
                         "结果表不存在，请先点击「刷新数据」生成报表数据。")
            return

        write_mode = "overwrite" if self._write_mode_combo.currentIndex() == 0 else "incremental"

        report_name = self._report.name or self._name_input.text().strip() or "未命名报表"
        table_name = f"报表-{report_name}"

        filters = self._filter_bar.get_conditions()
        # 从字段面板取列顺序（比从预览表取更可靠，不受数据加载状态影响）
        field_cols = self._field_panel.get_columns()
        column_order = [c['display_name'] for c in field_cols if c.get('display_name', '').strip()]

        # 收集字段格式配置
        columns = self._field_panel.get_columns()
        field_formats = {}
        if columns:
            for c in columns:
                name = c.get('display_name', '')
                fmt = c.get('field_format', 'text') or 'text'
                if name:
                    field_formats[name] = fmt

        # sync_id_fields 存的是字段中文标签 = 结果表列名，可直接使用
        sync_id_fields = getattr(self._report, 'sync_id_fields', None) or None

        self._sync_mysql_btn.setEnabled(False)
        self._sync_mysql_btn.setText("⏳ 同步中...")

        try:
            ok, msg, stats = self._db.sync_filtered_to_mysql(
                self._report.id, table_name,
                filters=filters, search=None, search_columns=None,
                id_column='_id',
                column_order=column_order,
                write_mode=write_mode,
                field_formats=field_formats,
                sync_id_fields=sync_id_fields if sync_id_fields else None,
                sync_id_separator=getattr(self._report, 'sync_id_separator', '_') or '_',
            )
            if ok:
                _light_msgbox(self, QMessageBox.Icon.Information,
                             "同步完成", f"已同步到 MySQL 表:\n{table_name}\n\n{msg}")
            else:
                _light_msgbox(self, QMessageBox.Icon.Warning, "同步失败", msg)
        except Exception as e:
            _light_msgbox(self, QMessageBox.Icon.Warning, "同步异常", str(e))
        finally:
            self._sync_mysql_btn.setText("📤 同步MySQL")
            self._sync_mysql_btn.setEnabled(True)

    def _refresh_data(self):
        """执行完整的数据刷新流程（不带筛选条件，筛选仅用于预览过滤）"""
        if not self._report:
            return

        # 先保存配置
        self._collect_from_ui()

        # 检查主表是否设置
        if not self._report.main_object_api:
            _light_msgbox(self, QMessageBox.Icon.Warning, "提示",
                "请先在画布上选择主表。\n\n"
                "操作：右键点击要作为主数据源的对象卡片 → 选择「设为主表」。\n"
                "主表将显示橙色标题栏和 ★ 标记。")
            return

        # 检查字段是否配置
        if not self._field_panel.get_columns():
            _light_msgbox(self, QMessageBox.Icon.Warning, "提示",
                "请先选择要显示的字段。\n\n"
                "操作：在画布卡片上勾选需要的字段，勾选后字段自动添加到右侧面板。")
            return

        # 检查数据库连接
        if not self._db or not self._refresh_worker:
            if self._db:
                self._update_refresh_button_state()
            _light_msgbox(self, QMessageBox.Icon.Warning, "数据库未连接",
                "无法刷新数据：MySQL 数据库未连接。\n\n"
                "请按以下步骤配置：\n"
                "1. 点击导航栏「设 置」\n"
                "2. 选择「MySQL 配置」\n"
                "3. 填入数据库连接信息并测试\n"
                "4. 确保已启用 MySQL 缓存\n\n"
                "配置完成后，刷新按钮将变为可用状态。")
            return

        # 检测是否已在刷新中，防止快速连续点击导致 _pending_filters 被覆盖
        if self._refresh_thread is not None and self._refresh_thread.isRunning():
            _light_msgbox(self, QMessageBox.Icon.Information, "刷新中",
                          "数据刷新正在进行中，请等待完成后再试。")
            return

        # 暂存筛选条件，刷新时清空以拉取全量数据（筛选仅对最终预览做过滤）
        # 注意：此处只清空内存中的 filters，不写入磁盘，避免刷新期间程序退出导致筛选条件永久丢失
        saved_filters = list(self._report.filters)
        self._report.filters = []

        self._refresh_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._status_label.setText("正在同步...")

        # 将暂存的筛选条件挂到线程上，刷新完成后恢复
        self._pending_filters = saved_filters

        # deepcopy 报告对象传给后台线程，避免主线程和后台线程共享可变对象导致竞态
        import copy
        report_copy = copy.deepcopy(self._report)
        self._refresh_thread = RefreshThread(self._refresh_worker, report_copy)
        self._refresh_thread.progress.connect(self._on_refresh_progress)
        self._refresh_thread.finished.connect(self._on_refresh_finished)
        self._refresh_thread.start()

    def _on_refresh_progress(self, phase: str, message: str, percent: int):
        self._progress_bar.setValue(percent)
        self._status_label.setText(message)
        self._bottom_status.setText(f"[{phase.upper()}] {message}")

    def _on_refresh_finished(self, result: dict):
        self._refresh_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._status_label.setText("")

        # 恢复刷新前暂存的筛选条件
        saved_filters = getattr(self, '_pending_filters', None)
        self._pending_filters = None

        if result['success']:
            # 恢复筛选条件 + 写入结果元数据
            if saved_filters:
                self._report.filters = saved_filters
            self._report.result_row_count = result['row_count']
            self._report.last_refresh_time = result.get('refresh_time', '')
            self._report.result_table_name = ReportDatabase.result_table_name(self._report.id)
            self._repo.save(self._report)

            self._bottom_status.setText(
                f"✅ 刷新完成: {result['row_count']} 条记录 (耗时 {result['duration']:.1f}s)")
            import sys
            print(f"[刷新完成] 结果表: {self._report.result_table_name} | "
                  f"记录数: {result['row_count']} | 耗时: {result['duration']:.1f}s",
                  file=sys.stderr, flush=True)

            # 预览 + 重新应用筛选条件
            self._preview.set_report(self._report.id)
            self._preview.set_report_definition(self._report)
            self._filter_bar.set_result_table(ReportDatabase.result_table_name(self._report.id))
            self._sync_field_order_to_preview()
            conditions = self._filter_bar.get_conditions()
            self._preview.set_filter_conditions(conditions)
        else:
            if saved_filters:
                self._report.filters = saved_filters
                self._repo.save(self._report)
            self._bottom_status.setText(f"❌ 刷新失败: {result.get('error', '')}")
            import sys
            print(f"[刷新失败] {result.get('error', '未知错误')}", file=sys.stderr, flush=True)

    # ==================== SQL 编辑 ====================

    def _show_sql_editor(self):
        """打开 MySQL SQL 代码编辑界面。"""
        if not self._report:
            _light_msgbox(self, QMessageBox.Icon.Warning, "提示", "请先配置报表对象和字段。")
            return

        # 先从 UI 收集最新配置
        self._collect_from_ui()

        # 生成当前拼表 SQL
        from ..sql_builder import JoinSQLBuilder
        try:
            builder = JoinSQLBuilder(self._report, db=self._db)
            select_sql = builder.build_create_sql()
            result_table = self._report.result_table_name or f"cr_{self._report.id}"
            full_sql = f"-- 结果表: {result_table}\n"
            full_sql += f"-- 主表: {self._report.main_object_api}\n"
            if self._report.joins:
                for j in self._report.joins:
                    jd = j if hasattr(j, 'left_object_api') else None
                    if jd:
                        full_sql += f"-- JOIN: {jd.left_object_api} ↔ {jd.right_object_api}\n"
            full_sql += f"\n-- 以下 SQL 可直接编辑后执行\n{select_sql}"
        except Exception as e:
            full_sql = f"-- SQL 生成失败: {e}\n\n-- 请检查报表配置"

        # 显示编辑对话框
        dialog = SQLEditorDialog(self, full_sql, self._report, self._db, self._repo)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 用户保存了自定义 SQL
            custom_sql = dialog.get_sql()
            if custom_sql:
                self._execute_custom_sql(custom_sql)

    def _execute_custom_sql(self, sql: str):
        """在 MySQL 中执行用户编辑的 SQL。"""
        if not self._db or not self._db.available:
            _light_msgbox(self, QMessageBox.Icon.Warning, "数据库未连接",
                         "请先在设置中配置 MySQL 连接。")
            return
        try:
            # 先删除旧结果表
            self._db.drop_result_table(self._report.id)
            # 执行用户编辑的 SQL（通常为 CREATE TABLE AS SELECT）
            self._db.execute(sql)
            # 更新报表状态
            table_name = ReportDatabase.result_table_name(self._report.id)
            self._report.result_table_name = table_name
            row_count = self._db.get_result_count(self._report.id)
            self._report.result_row_count = row_count
            self._report.last_refresh_time = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self._repo.save(self._report)
            # 刷新预览
            self._preview.set_report(self._report.id)
            self._preview.set_report_definition(self._report)
            self._sync_field_order_to_preview()
            self._bottom_status.setText(f"✅ SQL 已执行: {row_count} 条记录")
            _light_msgbox(self, QMessageBox.Icon.Information, "执行成功",
                         f"SQL 已成功执行。\n结果表: {table_name}\n记录数: {row_count}")
        except Exception as e:
            _light_msgbox(self, QMessageBox.Icon.Critical, "SQL 执行失败", str(e))

    # ==================== 表信息解析 ====================

    def _build_display_to_api_map(self) -> dict[str, str]:
        """构建 MySQL 清洗表名 → CRM API 名的反向映射。

        例如: {'对象-商机': 'NewOpportunityObj', ...}
        用于从 TableSelectorPanel 添加表时解析字段中文名。
        """
        mapping = {}
        for api, meta in self._object_meta.items():
            name = meta.get('name', api)
            table_name = f'对象-{name}'
            mapping[table_name] = api
            mapping[name] = api  # 也支持不带「对象-」前缀的
        return mapping

    def _resolve_field_label(self, object_api: str, field_key: str) -> str:
        """将字段 key 解析为中文显示名。

        优先从 _object_meta 查找，其次尝试通过反向映射查找，
        最后使用 field_key 本身作为标签。
        """
        # 非 CRM 表：从 Excel repo 或直接返回字段名
        if self._is_non_crm_table(object_api):
            if self._excel_repo:
                for ds in self._excel_repo.list_all():
                    if ds.mysql_table == object_api:
                        for c in (ds.columns or []):
                            if c.get('key') == field_key:
                                return c.get('label', field_key)
            return field_key

        # 直接查找
        meta = self._object_meta.get(object_api)
        if not meta:
            # 尝试反向映射（MySQL 表名 → API 名）
            mapping = self._build_display_to_api_map()
            resolved_api = mapping.get(object_api, object_api)
            meta = self._object_meta.get(resolved_api)
        if meta:
            for item in meta.get('fields', []):
                k = item[0]
                lbl = item[1] if len(item) >= 2 else k
                if k == field_key:
                    return lbl or field_key
        return field_key

    def _normalize_field_key(self, object_api: str, source_field: str) -> str:
        """将 source_field 标准化为 API field key。

        如果 source_field 是中文标签，尝试从 _object_meta 查找对应的 API key；
        如果已是 API key 则直接返回。找不到映射时返回原值。

        这解决了旧数据中 source_field 存储中文标签而非 API key 的问题。
        """
        if not source_field or not object_api:
            return source_field
        # 非 CRM 表：不需要 normalize，字段名即列名
        if self._is_non_crm_table(object_api):
            return source_field
        meta = self._object_meta.get(object_api)
        if not meta:
            mapping = self._build_display_to_api_map()
            resolved_api = mapping.get(object_api, object_api)
            meta = self._object_meta.get(resolved_api)
        if not meta:
            return source_field
        # 先检查是否已是有效的 API key（直接命中）
        for item in meta.get('fields', []):
            k = item[0]
            if k == source_field:
                return source_field  # 已是 API key
        # 再尝试标签反查
        for item in meta.get('fields', []):
            k = item[0]
            lbl = item[1] if len(item) >= 2 else k
            if lbl == source_field:
                return k
        return source_field

    def _resolve_table_info(self, api: str) -> tuple[str, list]:
        """解析表的显示名和字段列表

        优先从 _object_meta (CRM API 名) 查找，
        其次从配置文件直接加载（_object_meta 可能尚未注入），
        最后从 MySQL 清洗表或 TableSelectorPanel 缓存查找。
        """
        # 非 CRM 表（Excel 导入 / 直连 MySQL 表）
        if self._is_non_crm_table(api):
            display_name = api
            # Excel 表：从 repo 读显示名和字段标签
            if api.startswith('ex_') and self._excel_repo:
                for ds in self._excel_repo.list_all():
                    if ds.mysql_table == api:
                        display_name = ds.name
                        fields = [(c.get('key', ''), c.get('label', ''), False)
                                  for c in (ds.columns or [])]
                        return display_name, fields
            # 直连 MySQL 表：读 SHOW COLUMNS
            fields = self._get_cleaned_table_fields(api)
            return display_name, [(f, f, False) for f in fields]

        meta = self._object_meta.get(api)
        if meta:
            # _object_meta 中的 name 可能因配置错误而不可信。
            # 优先使用 MySQL 中实际存在的表名推断中文名，确保与用户看到的表一致。
            meta_name = meta.get('name', api)
            db_name = self._resolve_name_from_mysql_table(api)
            if db_name and db_name != meta_name:
                return db_name, meta.get('fields', [])
            return meta_name, meta.get('fields', [])
        # 回退：从配置查找
        try:
            import sys
            main = sys.modules.get('__main__')
            if main and hasattr(main, 'load_config'):
                cfg = main.load_config()
                crm_objs = cfg.get('fxiaoke', {}).get('crm_objects', [])
                for obj in crm_objs:
                    if isinstance(obj, dict) and obj.get('api_name') == api:
                        name = obj.get('name', api)
                        field_cfg = cfg.get('fxiaoke', {}).get('crm_object_fields', {}).get(api, {})
                        fields = [(k, v.get('label', k) if isinstance(v, dict) else str(v))
                                  for k, v in field_cfg.items()
                                  if isinstance(v, dict) and v.get('enabled', True)]
                        return name, fields
        except Exception:
            pass
        # 最终回退：MySQL 表名

        # 清洗表名（对象-xxx）或已有缓存
        name = self._extract_display_name(api)
        fields = self._get_cleaned_table_fields(api)
        field_tuples = [(f, f) for f in fields]  # key=label (中文列名)
        return name, field_tuples

    def _resolve_name_from_mysql_table(self, api: str) -> str | None:
        """通过 MySQL 实际表名推断中文显示名（比 _object_meta 更可信）。

        例如 api='NewOpportunityObj' → MySQL 表 '对象-商机' → 返回 '商机'
        """
        if not self._db or not self._db.available:
            return None
        try:
            if hasattr(self._db, 'resolve_existing_table'):
                table_name = self._db.resolve_existing_table(api)
            else:
                return None
            if table_name and table_name.startswith('对象-'):
                return table_name[3:]
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_display_name(table_name: str) -> str:
        """从 MySQL 清洗表名提取中文显示名"""
        if table_name.startswith('对象-'):
            return table_name[3:]
        return table_name

    def _get_cleaned_table_fields(self, table_name: str) -> list[str]:
        """获取清洗表的列名列表（排除 _id）"""
        # 优先从 TableSelectorPanel 缓存获取
        if self._table_selector:
            cached = self._table_selector.get_cached_fields(table_name)
            if cached:
                return cached

        # 回退：直接查 MySQL
        if self._db and self._db.available:
            try:
                cols = self._db.execute(f"SHOW COLUMNS FROM `{table_name}`")
                if cols:
                    return [r['Field'] for r in cols if r['Field'] != '_id']
            except Exception:
                pass
        return []

    # ==================== 回调 ====================

    def _on_table_selected_from_panel(self, table_name: str, display_name: str,
                                       fields: list, source_type: str = ''):
        """用户从左侧面板双击选择了一张表 → 添加到画布"""
        # 非 CRM 表直接用表名作为标识，CRM 表翻译为 API 名
        if source_type in ('excel', 'mysql'):
            object_api = table_name
        else:
            object_api = self._to_crm_api_name(table_name)

        # 优先使用面板传入的 display_name（面板直接来自 MySQL 表名，是用户看到并确认的名称）
        card_display = display_name

        # 检查是否已在画布上
        existing = self._canvas.canvas_scene.get_card(object_api)
        if existing:
            self._canvas.centerOn(existing)
            existing.setSelected(True)
            return

        # 构建字段数据：[(key, label, checked), ...]，使用中文显示名
        field_data = []
        for col in fields:
            label = self._resolve_field_label(object_api, col)
            field_data.append((col, label, False))

        # 通过 JoinCanvas 添加到画布
        card = self._canvas.add_table_card(
            object_api=object_api,
            display_name=card_display,
            fields=field_data,
            is_main=False,
        )

        # 连接字段切换信号
        card.fieldToggled.connect(
            lambda api_name=object_api, field_key=None, checked=None:
                self._on_card_field_toggled(api_name, field_key, checked)
        )

        # 首张表自动设为主表
        if self._canvas.canvas_scene.card_count == 1:
            self._canvas.canvas_scene.set_main_card(object_api)
            self._canvas.auto_layout()

        self._update_status()

    def _on_card_field_toggled(self, object_api: str, field_key: str, checked: bool):
        """画布上字段勾选状态变化 → 同步到字段面板"""
        field_label = self._resolve_field_label(object_api, field_key)
        if checked:
            self._field_panel.add_column(field_label, object_api, field_key)
        else:
            self._field_panel.remove_column_by_field(field_key, object_api)

    def _on_canvas_modified(self):
        self._update_status()
        self._update_filter_bar_fields()

    def _on_preview_column_order_changed(self, order: list[str]):
        """用户拖拽预览表格列头 → 同步到字段面板排序"""
        if getattr(self, '_field_preview_syncing', False):
            return
        if not self._field_panel._columns:
            return
        self._field_panel.reorder_by_display_names(order)

    def _on_field_panel_changed(self):
        try:
            self._field_preview_syncing = True
            self.__on_field_panel_changed_impl()
        finally:
            self._field_preview_syncing = False

    def __on_field_panel_changed_impl(self):
        # 同步画布卡片上的勾选状态
        # update_field_checked 只做视觉重绘，不会重发 fieldToggled 信号，因此不会产生循环
        columns = self._field_panel.get_columns()
        selected_with_api = set()
        selected_no_api = set()
        for col in columns:
            api = col.get('source_object', '')
            sf = col.get('source_field', '')
            if not sf:
                continue
            if api:
                selected_with_api.add((api, sf))
            else:
                selected_no_api.add(sf)

        for card in self._canvas.canvas_scene.get_all_cards():
            for f in card.get_all_fields():
                is_selected = (
                    (card.object_api, f['key']) in selected_with_api
                    or (card.object_api, f['label']) in selected_with_api
                    or f['key'] in selected_no_api
                    or f['label'] in selected_no_api
                )
                if f['checked'] != is_selected:
                    card.update_field_checked(f['key'], is_selected)

        # 同步预览表格可见字段（仅显示「显示」勾选的列）
        # 使用 display_name 匹配，因为数据库结果表的列名是中文标签
        visible_fields = {col['display_name'] for col in columns if col.get('visible', True)}
        self._preview.set_visible_fields(visible_fields if visible_fields else None)
        # 同步列顺序到预览表格（字段面板变更 → 预览表拖着列头同步）
        self._sync_field_order_to_preview()
        # 同步筛选栏字段（只跟随当前报表列）
        self._update_filter_bar_fields()

    def _sync_field_order_to_preview(self):
        """将字段面板当前的列顺序同步到预览表（字段变更 / 刷新数据后均调用）。"""
        columns = self._field_panel.get_columns()
        field_order = [col['display_name'] for col in columns if col.get('display_name', '').strip()]
        if field_order:
            self._preview.set_column_order(field_order)

    def _update_filter_bar_fields(self):
        """筛选栏可选字段：仅包含已加入报表列中的字段。"""
        if not hasattr(self, '_filter_bar') or not self._filter_bar:
            return
        field_list = []

        columns = self._field_panel.get_columns()
        seen_fields = set()

        # 辅助函数：添加单个字段到列表
        def _add_field(source_obj_api, field_key, display_name, is_time=False):
            nonlocal seen_fields
            if not field_key or not source_obj_api:
                return
            unique_key = (source_obj_api, field_key)
            if unique_key in seen_fields:
                return
            seen_fields.add(unique_key)

            if not display_name:
                display_name = self._resolve_field_label(source_obj_api, field_key)

            # 优先从 MySQL 实际表名推断对象中文名（避免 _object_meta 配置错误）
            obj_name = ''
            if source_obj_api:
                obj_name = self._resolve_table_display_name(source_obj_api)
                if obj_name == source_obj_api:
                    obj_name = self._extract_display_name(source_obj_api)

            if not is_time:
                date_keywords = ('时间', '日期', '创建', '修改', '提交', 'date', 'time')
                lower_display = (display_name or '').lower()
                lower_key = (field_key or '').lower()
                if any(kw in lower_display for kw in date_keywords) or any(kw in lower_key for kw in date_keywords):
                    is_time = True

            display = f"[{obj_name}] {display_name}" if obj_name else display_name
            field_list.append((display, field_key, is_time, source_obj_api))

        # 仅遍历报表列中的字段
        for c in columns:
            field_key = str(c.get('source_field', '')).strip()
            if not field_key:
                continue
            source_obj_api = self._to_crm_api_name(str(c.get('source_object', '')).strip())
            if not source_obj_api and self._report:
                source_obj_api = self._report.main_object_api
            display_name = str(c.get('display_name', '')).strip()

            # 推断 is_time
            is_time = False
            obj_meta = self._object_meta.get(source_obj_api, {}) if source_obj_api else {}
            if obj_meta:
                for item in obj_meta.get('fields', []):
                    key = item[0]
                    label = item[1] if len(item) >= 2 else key
                    if key == field_key or label == display_name:
                        if len(item) >= 3:
                            is_time = bool(item[2])
                        break

            _add_field(source_obj_api, field_key, display_name, is_time)

        self._filter_bar.set_available_fields(field_list)

    def _on_filter_changed(self):
        self._update_status()
        # 防抖：避免筛选条件快速变化时频繁触发 DB 刷新（尤其是在 IME 输入过程中）
        self._filter_change_timer.start()

    def _apply_filter_to_preview(self):
        """将筛选条件同步到预览表格（由防抖定时器触发），并自动持久化到 report。"""
        if self._preview and self._report:
            conditions = self._filter_bar.get_conditions()
            self._preview.set_filter_conditions(conditions)
            # 自动保存筛选条件，确保重启后不清空，且与详情页同步
            if self._save_filters_fn:
                self._save_filters_fn(self._report.id, conditions)

    def _update_status(self):
        """更新底部状态"""
        cards = self._canvas.canvas_scene.get_all_cards()
        lines = self._canvas.canvas_scene.get_all_lines()
        cols = self._field_panel.get_columns()
        visible_cols = len([c for c in cols if c['visible']])

        if not cards:
            hint = "👈 从左侧「可用数据表」双击添加表到画布"
        elif not cols:
            hint = "☑ 勾选卡片上的字段复选框，添加到报表列"
        elif visible_cols == 0:
            hint = "👁 在右侧「报表列」面板中勾选「显示」列"
        else:
            hint = f"对象: {len(cards)} 张表 | 连线: {len(lines)} 条 | 字段: {len(cols)} 列 | {visible_cols} 可见"

        self._bottom_status.setText(hint)

    def _toggle_canvas_visibility(self):
        """切换画布（含左侧表选择面板）的显示/隐藏状态。"""
        self._canvas_visible = not self._canvas_visible
        visible = self._canvas_visible
        self._canvas.setVisible(visible)
        self._table_selector.setVisible(visible)
        self._toggle_canvas_btn.setText("隐藏画布" if visible else "显示画布")


class _SyncConfigDialog(QDialog):
    """同步 MySQL 配置对话框 — 选择主键字段 + 写入方式

    available_fields: [(display_label, unique_value), ...]
      如 ("[销售订单] 订单号", "SalesOrderObj|order_no")
    selected_fields: 已选中的 unique_value 列表
    """

    def __init__(self, parent=None, available_fields=None,
                 selected_fields=None, separator='_', write_mode='overwrite'):
        super().__init__(parent)
        self.setWindowTitle("同步 MySQL 配置")
        self.setMinimumWidth(620)
        self._available_fields = available_fields or []
        self._selected_fields = list(selected_fields or [])
        self._separator = separator
        self._write_mode = write_mode
        self.setStyleSheet("""
            QDialog { background-color: #FAFAFA; color: #333333; }
            QGroupBox { background-color: #FAFAFA; color: #333333; font-weight: 500;
                        border: 1px solid #E0E0E0; border-radius: 6px; margin-top: 10px; padding-top: 14px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QLabel { color: #333333; font-size: 13px; }
            QRadioButton { color: #333333; font-size: 13px; }
            QLineEdit {
                border: 1px solid #D9D9D9; border-radius: 3px;
                padding: 4px 8px; font-size: 13px; background: #FFFFFF; color: #333333;
            }
            QLineEdit:focus { border-color: #FF8C00; }
            QListWidget {
                border: 1px solid #D9D9D9; border-radius: 4px;
                background-color: #FFFFFF; color: #333333; font-size: 13px;
            }
            QListWidget::item { padding: 6px 8px; }
            QListWidget::item:selected { background-color: #FFF7E6; color: #333333; }
            QPushButton {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 6px 20px; font-size: 13px; min-width: 80px;
            }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 写入方式
        wm_group = QGroupBox("写入方式")
        wm_layout = QVBoxLayout(wm_group)
        self._rb_overwrite = QRadioButton("覆盖 (DROP + CREATE) — 每次全量重建")
        self._rb_incremental = QRadioButton("增量 (INSERT ON DUPLICATE KEY UPDATE) — 按主键匹配更新")
        self._rb_overwrite.setChecked(self._write_mode == 'overwrite')
        self._rb_incremental.setChecked(self._write_mode == 'incremental')
        wm_layout.addWidget(self._rb_overwrite)
        wm_layout.addWidget(self._rb_incremental)
        layout.addWidget(wm_group)

        # 主键字段选择 — 双栏布局
        pk_group = QGroupBox("主键字段（拼接顺序 = 右栏从上到下）")
        pk_layout = QVBoxLayout(pk_group)

        fields_row = QHBoxLayout()
        fields_row.setSpacing(8)

        # 左栏：可选字段
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("可选字段"))
        self._available_list = QListWidget()
        self._available_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._available_list.setMaximumHeight(200)
        for display_label, unique_value in self._available_fields:
            item = QListWidgetItem(display_label)
            item.setData(Qt.ItemDataRole.UserRole, unique_value)
            self._available_list.addItem(item)
        left_layout.addWidget(self._available_list)
        fields_row.addLayout(left_layout, 1)

        # 中间按钮
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        btn_col.addStretch()

        add_btn = QPushButton("→")
        add_btn.setFixedSize(32, 28)
        add_btn.setToolTip("添加选中字段")
        add_btn.clicked.connect(self._add_selected)
        btn_col.addWidget(add_btn)

        remove_btn = QPushButton("←")
        remove_btn.setFixedSize(32, 28)
        remove_btn.setToolTip("移除选中字段")
        remove_btn.clicked.connect(self._remove_selected)
        btn_col.addWidget(remove_btn)

        btn_col.addSpacing(8)

        up_btn = QPushButton("↑")
        up_btn.setFixedSize(32, 28)
        up_btn.setToolTip("上移")
        up_btn.clicked.connect(self._move_selected_up)
        btn_col.addWidget(up_btn)

        down_btn = QPushButton("↓")
        down_btn.setFixedSize(32, 28)
        down_btn.setToolTip("下移")
        down_btn.clicked.connect(self._move_selected_down)
        btn_col.addWidget(down_btn)

        btn_col.addStretch()
        fields_row.addLayout(btn_col)

        # 右栏：已选字段（顺序 = 拼接顺序）
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("已选字段（拼接顺序）"))
        self._selected_list = QListWidget()
        self._selected_list.setMaximumHeight(200)
        self._selected_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._selected_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        right_layout.addWidget(self._selected_list)
        fields_row.addLayout(right_layout, 1)

        pk_layout.addLayout(fields_row)

        # 恢复已保存的选择 → 填充右栏
        for uk in self._selected_fields:
            self._move_to_selected(uk)

        # 拼接分隔符
        sep_row = QHBoxLayout()
        sep_row.addWidget(QLabel("拼接分隔符:"))
        self._sep_edit = QLineEdit(self._separator)
        self._sep_edit.setFixedWidth(60)
        self._sep_edit.setPlaceholderText("_")
        self._sep_edit.textChanged.connect(self._update_preview)
        sep_row.addWidget(self._sep_edit)

        sep_row.addSpacing(16)
        sep_row.addWidget(QLabel("预览:"))
        self._preview_label = QLabel("")
        self._preview_label.setStyleSheet("font-weight: bold; color: #FF8C00;")
        sep_row.addWidget(self._preview_label)
        sep_row.addStretch()
        pk_layout.addLayout(sep_row)

        self._selected_list.model().rowsMoved.connect(self._update_preview)
        self._update_preview()

        layout.addWidget(pk_group)

        # 提示
        note = QLabel("⚠ 增量模式下，拼接后 ID 重复的行将被跳过。\n"
                      "  若任一 ID 字段为空，该行将被跳过。")
        note.setStyleSheet("font-size: 11px; color: #999;")
        layout.addWidget(note)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _move_to_selected(self, unique_key: str):
        """将指定 unique_key 从左栏移到右栏"""
        # 查找匹配项的 display_label
        for display_label, uv in self._available_fields:
            if uv == unique_key:
                # 从右栏检查是否已存在
                for i in range(self._selected_list.count()):
                    if self._selected_list.item(i).data(Qt.ItemDataRole.UserRole) == unique_key:
                        return  # 已存在，跳过
                item = QListWidgetItem(display_label)
                item.setData(Qt.ItemDataRole.UserRole, unique_key)
                self._selected_list.addItem(item)
                return

    def _add_selected(self):
        """将左栏选中项移到右栏"""
        for item in self._available_list.selectedItems():
            uk = item.data(Qt.ItemDataRole.UserRole)
            # 检查右栏是否已存在
            already = False
            for i in range(self._selected_list.count()):
                if self._selected_list.item(i).data(Qt.ItemDataRole.UserRole) == uk:
                    already = True
                    break
            if not already:
                new_item = QListWidgetItem(item.text())
                new_item.setData(Qt.ItemDataRole.UserRole, uk)
                self._selected_list.addItem(new_item)
        self._update_preview()

    def _remove_selected(self):
        """移除右栏选中项"""
        for item in self._selected_list.selectedItems():
            row = self._selected_list.row(item)
            self._selected_list.takeItem(row)
        self._update_preview()

    def _move_selected_up(self):
        """右栏选中项上移"""
        row = self._selected_list.currentRow()
        if row > 0:
            item = self._selected_list.takeItem(row)
            self._selected_list.insertItem(row - 1, item)
            self._selected_list.setCurrentRow(row - 1)
            self._update_preview()

    def _move_selected_down(self):
        """右栏选中项下移"""
        row = self._selected_list.currentRow()
        if row < self._selected_list.count() - 1:
            item = self._selected_list.takeItem(row)
            self._selected_list.insertItem(row + 1, item)
            self._selected_list.setCurrentRow(row + 1)
            self._update_preview()

    def _update_preview(self, *args):
        selected = self._get_selected_fields()
        sep = self._sep_edit.text() or '_'
        if selected:
            labels = [k.split('|', 1)[1] if '|' in k else k for k in selected]
            self._preview_label.setText(sep.join(labels))
        else:
            self._preview_label.setText("(未选择)")

    def _get_selected_fields(self):
        """返回右栏中的 unique_value 列表（保持右栏从上到下顺序 = 拼接顺序）"""
        result = []
        for i in range(self._selected_list.count()):
            item = self._selected_list.item(i)
            result.append(item.data(Qt.ItemDataRole.UserRole))
        import sys
        print(f"[SyncDialog] _get_selected_fields: {result} (count={len(result)})", file=sys.stderr, flush=True)
        return result

    def get_result(self):
        # 直接用 unique_key（"api|label"）存储，保证精确恢复
        return {
            'sync_id_fields': self._get_selected_fields(),
            'sync_id_separator': self._sep_edit.text() or '_',
            'write_mode': 'overwrite' if self._rb_overwrite.isChecked() else 'incremental',
        }
