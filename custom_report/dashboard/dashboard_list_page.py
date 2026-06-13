"""
仪表盘列表页

显示所有已保存的仪表盘，支持搜索、CRUD、导入/导出 JSON。
"""

import json
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QLineEdit,
    QLabel, QComboBox, QMenu, QFileDialog, QMessageBox,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont

from .models import DashboardDefinition

PAGE_SIZES = [20, 50, 100]


class DashboardListPage(QWidget):
    """仪表盘列表管理页"""

    viewRequested = pyqtSignal(str)      # dashboard_id
    editRequested = pyqtSignal(str)      # dashboard_id
    newDashboard = pyqtSignal()          # 新建空白仪表盘

    def __init__(self, repo, parent=None):
        """
        Args:
            repo: DashboardRepository 实例
        """
        super().__init__(parent)
        self._repo = repo
        self._all_dashboards: list[DashboardDefinition] = []
        self._current_page = 1
        self._page_size = 20
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # 标题组
        group = QGroupBox("BI 仪表盘")
        group.setStyleSheet("QGroupBox { font-size: 16px; font-weight: bold; border: none; }")
        gl = QVBoxLayout(group)

        # 操作栏
        action_bar = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 搜索仪表盘名称...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setFixedWidth(260)
        self._search_input.returnPressed.connect(self._on_search)
        action_bar.addWidget(self._search_input)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh)
        refresh_btn.setFixedHeight(28)
        action_bar.addWidget(refresh_btn)

        action_bar.addStretch()

        import_btn = QPushButton("📤 导入 JSON / PBIX")
        import_btn.clicked.connect(self._on_import_file)
        import_btn.setFixedHeight(28)
        action_bar.addWidget(import_btn)

        export_btn = QPushButton("📥 导出 JSON")
        export_btn.clicked.connect(self._on_export_selected)
        export_btn.setFixedHeight(28)
        action_bar.addWidget(export_btn)

        new_btn = QPushButton("+ 新建仪表盘")
        new_btn.clicked.connect(self.newDashboard.emit)
        new_btn.setFixedHeight(28)
        new_btn.setStyleSheet("QPushButton { background: #FF8C00; color: #FFF; border-radius: 4px; font-weight: bold; } QPushButton:hover { background: #FFA940; }")
        action_bar.addWidget(new_btn)
        gl.addLayout(action_bar)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["名称", "图表数", "数据源", "修改时间", "操作"])
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(30)
        # 所有列设为 Interactive：用户可拖拽调整，不强制拉伸铺满表格
        for c in range(5):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        # 默认列宽（总宽约 700px；超出部分留白，不强制铺满）
        self._table.setColumnWidth(0, 200)
        self._table.setColumnWidth(1, 60)
        self._table.setColumnWidth(2, 180)
        self._table.setColumnWidth(3, 140)
        self._table.setColumnWidth(4, 160)
        # 不自动调整大小以适应内容，让用户自定义的列宽始终生效
        self._table.setSizeAdjustPolicy(
            self._table.sizeAdjustPolicy().AdjustToContentsOnFirstShow
        )
        # 显式启用水平滚动条（列宽总和超出视口时出现）
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.setStyleSheet("""
            QTableWidget { border: 1px solid #E8E8E8; font-size: 13px; }
            QTableWidget::item { padding: 6px 8px; }
            QTableWidget::item:hover { background: #FFF7E6; }
            QHeaderView::section { background: #FAFAFA; padding: 6px 8px; font-weight: bold; }
        """)
        gl.addWidget(self._table)

        # 分页栏
        page_bar = QHBoxLayout()
        self._record_label = QLabel("共 0 个仪表盘")
        page_bar.addWidget(self._record_label)
        page_bar.addStretch()

        page_bar.addWidget(QLabel("每页:"))
        page_size_combo = QComboBox()
        page_size_combo.addItems([str(s) for s in PAGE_SIZES])
        page_size_combo.setCurrentText("20")
        page_size_combo.setFixedWidth(65)
        page_size_combo.currentTextChanged.connect(self._on_page_size_changed)
        page_bar.addWidget(page_size_combo)

        prev_btn = QPushButton("◀")
        prev_btn.setFixedSize(32, 28)
        prev_btn.clicked.connect(self._prev_page)
        page_bar.addWidget(prev_btn)

        self._page_label = QLabel("1")
        page_bar.addWidget(self._page_label)

        next_btn = QPushButton("▶")
        next_btn.setFixedSize(32, 28)
        next_btn.clicked.connect(self._next_page)
        page_bar.addWidget(next_btn)
        gl.addLayout(page_bar)

        layout.addWidget(group)

    def refresh(self, search: str = None):
        """刷新列表"""
        self._all_dashboards = self._repo.list_all(search=search)
        self._current_page = 1
        self._populate()

    def _populate(self):
        """填充表格"""
        total = len(self._all_dashboards)
        start = (self._current_page - 1) * self._page_size
        end = start + self._page_size
        page_items = self._all_dashboards[start:end]

        self._table.setRowCount(len(page_items))
        for i, dashboard in enumerate(page_items):
            self._table.setRowHeight(i, 40)

            # 名称
            name_item = QTableWidgetItem(dashboard.name)
            name_item.setData(Qt.ItemDataRole.UserRole, dashboard.id)
            self._table.setItem(i, 0, name_item)

            # 图表数
            chart_count = len(dashboard.charts) if dashboard.charts else 0
            self._table.setItem(i, 1, QTableWidgetItem(str(chart_count)))

            # 数据源（汇总）
            sources = set()
            for chart in (dashboard.charts or []):
                if chart.data_source_name:
                    sources.add(chart.data_source_name)
            self._table.setItem(i, 2, QTableWidgetItem("、".join(sources) if sources else "—"))

            # 修改时间
            self._table.setItem(i, 3, QTableWidgetItem(dashboard.modified_at or "—"))

            # 操作按钮
            op_widget = QWidget()
            op_layout = QHBoxLayout(op_widget)
            op_layout.setContentsMargins(2, 2, 2, 2)
            op_layout.setSpacing(4)

            view_btn = QPushButton("👁 查看")
            view_btn.setFixedHeight(24)
            view_btn.clicked.connect(lambda checked, did=dashboard.id: self.viewRequested.emit(did))
            op_layout.addWidget(view_btn)

            edit_btn = QPushButton("✏️ 编辑")
            edit_btn.setFixedHeight(24)
            edit_btn.clicked.connect(lambda checked, did=dashboard.id: self.editRequested.emit(did))
            op_layout.addWidget(edit_btn)
            self._table.setCellWidget(i, 4, op_widget)

        self._record_label.setText(f"共 {total} 个仪表盘")
        total_pages = max(1, (total + self._page_size - 1) // self._page_size)
        self._page_label.setText(f"{self._current_page} / {total_pages}")

    def _on_search(self):
        text = self._search_input.text()
        self.refresh(search=text if text else None)

    def _on_double_click(self, index):
        item = self._table.item(index.row(), 0)
        if item:
            dashboard_id = item.data(Qt.ItemDataRole.UserRole)
            self.viewRequested.emit(dashboard_id)

    def _on_context_menu(self, pos):
        """右键菜单"""
        item = self._table.itemAt(pos)
        if not item:
            return
        row = item.row()
        name_item = self._table.item(row, 0)
        if not name_item:
            return
        dashboard_id = name_item.data(Qt.ItemDataRole.UserRole)
        if not dashboard_id:
            return

        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #FFF; border: 1px solid #D9D9D9; } QMenu::item { padding: 6px 24px; } QMenu::item:hover { background: #FFF7E6; }")

        menu.addAction("👁 查看", lambda: self.viewRequested.emit(dashboard_id))
        menu.addAction("✏️ 编辑", lambda: self.editRequested.emit(dashboard_id))
        menu.addSeparator()
        menu.addAction("📋 复制", lambda: self._on_duplicate(dashboard_id))
        menu.addAction("✏️ 重命名", lambda: self._on_rename(dashboard_id))
        menu.addAction("📥 导出 JSON", lambda: self._export_dashboard(dashboard_id))
        menu.addSeparator()
        delete_action = QAction("🗑 删除")
        delete_action.triggered.connect(lambda: self._on_delete(dashboard_id))
        menu.addAction(delete_action)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _on_import_file(self):
        """统一导入：JSON 仪表盘 / PBIX 元数据 / PBIT 模板"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入文件", "",
            "支持格式 (*.json *.pbix *.pbit);;JSON 文件 (*.json);;Power BI (*.pbix *.pbit);;所有文件 (*.*)"
        )
        if not file_path:
            return
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ('.pbix', '.pbit'):
            self._do_import_pbix(file_path)
        else:
            self._do_import_json(file_path)

    def _do_import_json(self, file_path: str):
        """导入 JSON 仪表盘"""
        try:
            # 先读字节，自动处理 UTF-8 BOM
            with open(file_path, 'rb') as f:
                raw = f.read()
            if raw.startswith(b'\xef\xbb\xbf'):
                raw = raw[3:]  # 去掉 UTF-8 BOM
            data = json.loads(raw.decode('utf-8'))
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if 'dashboards' in data:
                    items = list(data['dashboards'].values()) if isinstance(data['dashboards'], dict) else data['dashboards']
                elif 'charts' in data or 'name' in data:
                    items = [data]
            if not items:
                print("[BI 报表] 导入失败: JSON 格式不正确")
                return
            count = 0
            for ddata in items:
                if not isinstance(ddata, dict):
                    continue
                dashboard = DashboardDefinition.from_dict(ddata)
                if not dashboard.name.endswith(" (导入)"):
                    dashboard.name += " (导入)"
                from .models import _new_id
                dashboard.id = _new_id(12)
                self._repo.save(dashboard)
                count += 1
            self.refresh()
            print(f"[BI 报表] 成功导入 {count} 个仪表盘")
        except Exception as e:
            print(f"[BI 报表] JSON 导入失败: {e}")

    def _do_import_pbix(self, file_path: str):
        """导入 .pbix / .pbit 文件，直接生成仪表盘图表"""
        try:
            from .pbix_extractor import extract_to_dashboard, extract_metadata
            ext = os.path.splitext(file_path)[1].lower()
            kind = 'PBIT 模板' if ext == '.pbit' else 'PBIX'
            print(f"[BI 报表] 正在导入 {kind}: {file_path}")
            result = extract_to_dashboard(file_path)
            if not result['success'] or not result.get('dashboard') or not result['dashboard'].charts:
                print(f"[BI 报表] 生成仪表盘失败: {result.get('error', '无图表')}，回退到元数据提取")
                meta = extract_metadata(file_path)
                if meta['success']:
                    _print_pbix_meta(meta)
                    _show_pbix_meta_panel(meta)
                return
            dashboard = result['dashboard']
            self._repo.save(dashboard)
            self.refresh()
            print(f"[BI 报表] 已生成仪表盘「{dashboard.name}」({len(dashboard.charts)} 个图表)")
            print("[BI 报表] 💡 提示: 每个图表需手动选择数据源（字段映射已自动填充）")
            # 打开仪表盘编辑
            self.editRequested.emit(dashboard.id)
        except Exception as e:
            print(f"[BI 报表] PBIX/PBIT 导入失败: {e}")

    def _on_export_selected(self):
        selected = self._get_selected_id()
        if not selected:
            QMessageBox.information(self, "提示", "请先在表格中单击选中一个仪表盘")
            return
        dashboard = self._repo.get(selected)
        if not dashboard:
            QMessageBox.warning(self, "导出失败", "未找到该仪表盘")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出仪表盘 JSON", f"{dashboard.name}.json",
            "JSON 文件 (*.json);;所有文件 (*.*)"
        )
        if not file_path:
            return
        try:
            export_data = {'dashboards': {dashboard.id: dashboard.to_dict()}}
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            print(f"[BI 报表] 已导出: {file_path}")
            QMessageBox.information(self, "导出成功", f"仪表盘已导出到:\n{file_path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))
            print(f"[BI 报表] 导出失败: {e}")

    def _export_dashboard(self, dashboard_id: str):
        """导出指定仪表盘为 JSON 文件"""
        dashboard = self._repo.get(dashboard_id)
        if not dashboard:
            QMessageBox.warning(self, "导出失败", "未找到该仪表盘")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出仪表盘 JSON", f"{dashboard.name}.json",
            "JSON 文件 (*.json);;所有文件 (*.*)"
        )
        if not file_path:
            return
        try:
            export_data = {'dashboards': {dashboard.id: dashboard.to_dict()}}
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            print(f"[BI 报表] 已导出: {file_path}")
            QMessageBox.information(self, "导出成功", f"仪表盘已导出到:\n{file_path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))
            print(f"[BI 报表] 导出失败: {e}")

    def _on_duplicate(self, dashboard_id: str):
        dashboard = self._repo.get(dashboard_id)
        if dashboard:
            new_name = f"{dashboard.name} (副本)"
            new_db = self._repo.duplicate(dashboard_id, new_name)
            if new_db:
                self.refresh()
                print(f"[BI 报表] 已创建副本: {new_name}")

    def _on_rename(self, dashboard_id: str):
        dashboard = self._repo.get(dashboard_id)
        if dashboard:
            from PyQt6.QtWidgets import QInputDialog
            new_name, ok = QInputDialog.getText(
                self, "重命名", "新名称:", text=dashboard.name
            )
            if ok and new_name.strip():
                dashboard.name = new_name.strip()
                self._repo.save(dashboard)
                self.refresh()

    def _on_delete(self, dashboard_id: str):
        dashboard = self._repo.get(dashboard_id)
        if dashboard:
            self._repo.delete(dashboard_id)
            self.refresh()
            print(f"[BI 报表] 仪表盘已删除: {dashboard.name}")

    def _get_selected_id(self) -> str:
        rows = self._table.selectionModel().selectedRows()
        if rows:
            item = self._table.item(rows[0].row(), 0)
            if item:
                return item.data(Qt.ItemDataRole.UserRole)
        return ""

    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._populate()

    def _next_page(self):
        total = len(self._all_dashboards)
        total_pages = max(1, (total + self._page_size - 1) // self._page_size)
        if self._current_page < total_pages:
            self._current_page += 1
            self._populate()

    def _on_page_size_changed(self, text: str):
        self._page_size = int(text)
        self._current_page = 1
        self._populate()

    def set_repo(self, repo):
        """更新 repo 引用"""
        self._repo = repo


def _save_meta_txt(meta: dict, file_path: str):
    """保存 PBIX 元数据到 txt 文件"""
    lines = [f"PBIX 元数据: {meta['report_name']}", f"页面数: {len(meta.get('pages', []))}  |  字段: {len(meta.get('fields', []))} 个  |  表: {len(meta.get('tables', []))} 个", ""]
    if meta.get('tables'):
        lines.append(f"数据表: {', '.join(meta['tables'])}")
        lines.append("")
    for page in meta.get('pages', []):
        lines.append(f"{'='*60}")
        lines.append(f"📄 {page['name']} ({len(page['visuals'])} 个图表)")
        lines.append(f"{'='*60}")
        for v in page['visuals']:
            fields_str = f" [{', '.join(v['fields'])}]" if v.get('fields') else ''
            lines.append(f"  📊 {v['name']}  →  {v['type']}{fields_str}")
        lines.append("")
    if meta.get('fields'):
        lines.append(f"所有引用字段 ({len(meta['fields'])} 个):")
        for f in meta['fields']:
            lines.append(f"  • {f}")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def _print_pbix_meta(meta: dict):
    """输出 PBIX 元数据到运行时窗口"""
    lines = [f"[BI 报表] ====== PBIX 元数据: {meta['report_name']} ======"]
    lines.append(f"[BI 报表] 页面数: {len(meta.get('pages', []))}  |  字段: {len(meta.get('fields', []))} 个  |  表: {len(meta.get('tables', []))} 个")
    if meta.get('tables'):
        lines.append(f"[BI 报表] 数据表: {', '.join(meta['tables'][:15])}")
    for page in meta.get('pages', []):
        lines.append(f"[BI 报表] --- 📄 {page['name']} ({len(page['visuals'])} 个图表) ---")
        for v in page['visuals']:
            fields_str = f" [{', '.join(v['fields'])}]" if v.get('fields') else ''
            lines.append(f"[BI 报表]   📊 {v['name']}  →  {v['type']}{fields_str}")
    lines.append("[BI 报表] ====== PBIX 提取完成，可在悬浮窗口查看详情 ======")
    for line in lines:
        print(line)


def _show_pbix_meta_panel(meta: dict):
    """小型非模态悬浮窗口显示 PBIX 元数据"""
    from PyQt6.QtWidgets import QFrame, QTextEdit
    from PyQt6.QtCore import Qt as QtCore
    from PyQt6.QtGui import QFont

    panel = QFrame(None, QtCore.WindowType.Tool | QtCore.WindowType.WindowStaysOnTopHint)
    panel.setWindowTitle(f"📊 PBIX: {meta['report_name']}")
    panel.setMinimumSize(420, 360)
    panel.resize(460, 420)
    panel.setStyleSheet("QFrame { background: #FFF; border: 1px solid #D9D9D9; }")

    layout = QVBoxLayout(panel)
    layout.setContentsMargins(8, 8, 8, 8)

    info = QLabel(f"<b>{meta['report_name']}</b> — {len(meta.get('pages',[]))}页 {len(meta.get('fields',[]))}字段 "
                  f"{'| 表: '+', '.join(meta.get('tables',[])[:8]) if meta.get('tables') else ''}")
    info.setWordWrap(True)
    info.setStyleSheet("color:#666;font-size:12px;padding:4px;")
    layout.addWidget(info)

    edit = QTextEdit()
    edit.setReadOnly(True)
    edit.setFont(QFont("Microsoft YaHei", 11))
    edit.setStyleSheet("QTextEdit { background: #FAFAFA; border: 1px solid #E8E8E8; border-radius: 4px; }")

    text_lines = []
    for page in meta.get('pages', []):
        text_lines.append(f"\n{'─'*50}")
        text_lines.append(f"📄 {page['name']}  ({len(page['visuals'])} 个图表)")
        text_lines.append(f"{'─'*50}")
        for v in page['visuals']:
            text_lines.append(f"  📊 {v['name']}")
            text_lines.append(f"     类型: {v['type']}")
            if v.get('fields'):
                text_lines.append(f"     字段: {', '.join(v['fields'])}")
            text_lines.append("")
    edit.setPlainText('\n'.join(text_lines))
    layout.addWidget(edit)

    panel.show()
