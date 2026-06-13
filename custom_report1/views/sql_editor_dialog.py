"""
SQL 代码编辑弹窗

用于在报表编辑器中直接编辑和预览拼表 SQL。
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit,
    QLabel, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QPalette


# 浅色 QMessageBox 样式
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


class SQLEditorDialog(QDialog):
    """SQL 代码编辑弹窗"""

    def __init__(self, parent, sql: str, report, db, repo):
        super().__init__(parent)
        self._report = report
        self._db = db
        self._repo = repo
        self._custom_sql = ""

        self.setWindowTitle("MySQL 代码编辑")
        self.resize(900, 650)
        self.setMinimumSize(700, 500)

        # 浅色调色板
        light_palette = self.palette()
        light_palette.setColor(QPalette.ColorRole.Window, QColor('#FAFAFA'))
        light_palette.setColor(QPalette.ColorRole.WindowText, QColor('#333333'))
        light_palette.setColor(QPalette.ColorRole.Base, QColor('#FFFFFF'))
        light_palette.setColor(QPalette.ColorRole.Text, QColor('#333333'))
        light_palette.setColor(QPalette.ColorRole.Button, QColor('#FFFFFF'))
        light_palette.setColor(QPalette.ColorRole.ButtonText, QColor('#333333'))
        self.setPalette(light_palette)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- 顶部栏 ----
        top_bar = QFrame()
        top_bar.setStyleSheet("""
            QFrame { background-color: #FAFAFA; border-bottom: 1px solid #E0E0E0; }
        """)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 10, 16, 10)
        top_layout.setSpacing(12)

        title = QLabel("📝 MySQL 拼表 SQL 编辑")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #333;")
        top_layout.addWidget(title)
        top_layout.addStretch()

        # 生成默认 SQL 按钮
        regen_btn = QPushButton("重新生成 SQL")
        regen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        regen_btn.setStyleSheet("""
            QPushButton { border: 1px solid #D9D9D9; border-radius: 4px;
                          padding: 6px 14px; font-size: 13px; background: #FFFFFF; color: #333; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        top_layout.addWidget(regen_btn)

        layout.addWidget(top_bar)

        # ---- SQL 编辑区 ----
        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Consolas", 12))
        self._editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #FFFFFF; color: #333333;
                border: none; padding: 16px; font-family: 'Consolas', 'Courier New', monospace;
                font-size: 13px; line-height: 1.6;
                selection-background-color: #FFE7BA;
            }
        """)
        # 设置 Tab 宽度
        self._editor.setTabStopDistance(32)
        self._editor.setPlainText(sql)

        # 重置 SQL 为当前生成结果
        regen_btn.clicked.connect(lambda: self._editor.setPlainText(sql))

        layout.addWidget(self._editor, 1)

        # ---- 底部按钮栏 ----
        bottom_bar = QFrame()
        bottom_bar.setStyleSheet("""
            QFrame { background-color: #FAFAFA; border-top: 1px solid #E0E0E0; }
        """)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(16, 10, 16, 10)
        bottom_layout.setSpacing(12)

        hint = QLabel("编辑上方 SQL 后，点击「执行 SQL」直接在 MySQL 中运行并刷新预览。")
        hint.setStyleSheet("font-size: 12px; color: #999;")
        bottom_layout.addWidget(hint)
        bottom_layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("""
            QPushButton { border: 1px solid #D9D9D9; border-radius: 4px;
                          padding: 8px 20px; font-size: 14px; background: #FFFFFF; color: #333; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        cancel_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(cancel_btn)

        exec_btn = QPushButton("⚡ 执行 SQL")
        exec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exec_btn.setStyleSheet("""
            QPushButton { background-color: #FF8C00; color: #FFFFFF; border: none;
                          border-radius: 4px; padding: 8px 24px; font-size: 14px; font-weight: 600; }
            QPushButton:hover { background-color: #E67A00; }
        """)
        exec_btn.clicked.connect(self._on_execute)
        bottom_layout.addWidget(exec_btn)

        layout.addWidget(bottom_bar)

    def get_sql(self) -> str:
        """获取编辑后的 SQL"""
        return self._editor.toPlainText().strip()

    def _on_execute(self):
        """执行 SQL 并关闭"""
        self._custom_sql = self.get_sql()
        if not self._custom_sql:
            return
        self.accept()
