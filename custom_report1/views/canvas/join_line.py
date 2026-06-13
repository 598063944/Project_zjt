"""
连线

画布上两张表之间的贝塞尔连接线。
根据 JOIN 类型使用不同线型。
"""

from PyQt6.QtWidgets import (
    QGraphicsPathItem, QGraphicsSceneMouseEvent,
    QGraphicsSceneHoverEvent, QGraphicsSceneContextMenuEvent,
)
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QPainterPath, QFont, QPainterPathStroker,
)


class JoinLine(QGraphicsPathItem):
    """两张卡片之间的 JOIN 连线"""

    def __init__(self, left_card: "TableCard", right_card: "TableCard",
                 left_field: str = "", right_field: str = "",
                 join_type: str = "left"):
        super().__init__()
        self._left_card = left_card
        self._right_card = right_card
        self.left_field = left_field
        self.right_field = right_field
        self.join_type = join_type      # left / inner / one_to_one
        self._hovered = False

        self.setZValue(1)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable, True)

        self.update_path()

    @property
    def left_api(self) -> str:
        return self._left_card.object_api if self._left_card else ""

    @property
    def right_api(self) -> str:
        return self._right_card.object_api if self._right_card else ""

    def _get_anchor_points(self) -> tuple[QPointF, QPointF]:
        """计算连线两端在场景中的锚点"""
        left_card = self._left_card
        right_card = self._right_card
        if not left_card or not right_card:
            return QPointF(), QPointF()

        # 左卡片右侧中点
        left_rect = left_card.boundingRect()
        left_pos = left_card.scenePos()
        left_anchor = QPointF(
            left_pos.x() + left_rect.width(),
            left_pos.y() + left_rect.height() / 2,
        )

        # 右卡片左侧中点
        right_pos = right_card.scenePos()
        right_anchor = QPointF(
            right_pos.x(),
            right_pos.y() + right_card.boundingRect().height() / 2,
        )

        # 如果右卡在左卡左边，交换
        if right_anchor.x() < left_anchor.x():
            left_anchor = QPointF(left_pos.x(), left_pos.y() + left_rect.height() / 2)
            right_anchor = QPointF(
                right_pos.x() + right_card.boundingRect().width(),
                right_pos.y() + right_card.boundingRect().height() / 2,
            )

        return left_anchor, right_anchor

    def update_path(self):
        """更新贝塞尔曲线路径"""
        p1, p2 = self._get_anchor_points()
        if p1.isNull() and p2.isNull():
            return

        dx = abs(p2.x() - p1.x()) * 0.5
        dx = max(dx, 80)

        path = QPainterPath()
        path.moveTo(p1)
        path.cubicTo(
            QPointF(p1.x() + dx, p1.y()),
            QPointF(p2.x() - dx, p2.y()),
            p2,
        )
        self.setPath(path)

    def boundingRect(self):
        return super().boundingRect().adjusted(-15, -15, 15, 15)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 颜色和样式
        if self._hovered or self.isSelected():
            color = QColor("#FF8C00")
            width = 3
        elif self.join_type == 'inner':
            color = QColor("#52C41A")
            width = 2.5
        elif self.join_type == 'one_to_one':
            color = QColor("#1890FF")
            width = 2
        else:
            color = QColor("#999999")
            width = 2

        pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)

        # 虚线（one_to_one）
        if self.join_type == 'one_to_one':
            pen.setStyle(Qt.PenStyle.DashLine)

        painter.setPen(pen)
        painter.drawPath(self.path())

        # 箭头（终点）
        self._draw_arrow(painter, color)

        # 字段标签
        if self._hovered or self.isSelected():
            self._draw_label(painter)

    def _draw_arrow(self, painter: QPainter, color: QColor):
        """在终点绘制箭头"""
        path = self.path()
        if path.isEmpty():
            return
        end_point = path.pointAtPercent(1.0)
        # 终点前的点用于计算方向
        tan_point = path.pointAtPercent(0.97)
        dx = end_point.x() - tan_point.x()
        dy = end_point.y() - tan_point.y()
        length = (dx**2 + dy**2) ** 0.5
        if length < 1:
            return
        dx, dy = dx / length, dy / length

        arrow_size = 8
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)

        p1 = QPointF(
            end_point.x() - arrow_size * dx + arrow_size * 0.4 * dy,
            end_point.y() - arrow_size * dy - arrow_size * 0.4 * dx,
        )
        p2 = QPointF(
            end_point.x() - arrow_size * dx - arrow_size * 0.4 * dy,
            end_point.y() - arrow_size * dy + arrow_size * 0.4 * dx,
        )
        arrow = QPainterPath()
        arrow.moveTo(end_point)
        arrow.lineTo(p1)
        arrow.lineTo(p2)
        arrow.closeSubpath()
        painter.drawPath(arrow)

    def _draw_label(self, painter: QPainter):
        """在连线中点显示匹配字段信息"""
        path = self.path()
        if path.isEmpty():
            return
        mid = path.pointAtPercent(0.5)

        label = f"{self.left_field} = {self.right_field}"
        painter.setPen(QColor("#333333"))
        painter.setFont(QFont("Consolas", 9))
        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(label)
        text_height = fm.height()

        bg_rect = QRectF(
            mid.x() - text_width / 2 - 6,
            mid.y() - text_height / 2 - 3,
            text_width + 12,
            text_height + 6,
        )
        painter.fillRect(bg_rect, QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#E0E0E0"), 1))
        painter.drawRect(bg_rect)
        painter.setPen(QColor("#333333"))
        painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, label)

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()

    def contextMenuEvent(self, event):
        from PyQt6.QtWidgets import QMenu, QInputDialog

        menu = QMenu()

        # JOIN 类型子菜单
        join_menu = menu.addMenu("JOIN 类型")
        for jt, jt_label in [('left', '左连接 (LEFT)'), ('inner', '内连接 (INNER)'),
                               ('one_to_one', '一对一')]:
            action = join_menu.addAction(jt_label)
            action.setCheckable(True)
            action.setChecked(self.join_type == jt)
            action.triggered.connect(lambda checked, t=jt: self._set_join_type(t))

        menu.addSeparator()
        edit_action = menu.addAction("编辑匹配字段...")
        edit_action.triggered.connect(self._edit_match_fields)

        menu.addSeparator()
        delete_action = menu.addAction("删除连线")
        delete_action.triggered.connect(self._delete_self)

        menu.exec(event.screenPos())

    def _set_join_type(self, jt: str):
        self.join_type = jt
        self.update()
        if self.scene() and hasattr(self.scene(), 'sceneModified'):
            self.scene().sceneModified.emit()

    def _edit_match_fields(self):
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                      QComboBox, QPushButton, QCompleter)

        left_fields = self._left_card.get_all_fields() if self._left_card else []
        right_fields = self._right_card.get_all_fields() if self._right_card else []

        dlg = QDialog()
        dlg.setWindowTitle("编辑匹配字段")
        dlg.setMinimumWidth(440)
        dlg.setStyleSheet("""
            QDialog { background-color: #FAFAFA; }
            QLabel { color: #333333; font-size: 13px; }
            QComboBox { background-color: #FFFFFF; color: #333333;
                        border: 1px solid #D9D9D9; border-radius: 4px;
                        padding: 6px 10px; font-size: 13px; }
            QComboBox:hover { border-color: #FF8C00; }
            QComboBox QAbstractItemView { background-color: #FFFFFF; color: #333333;
                        selection-background-color: #FFF7E6; selection-color: #333333; }
            QPushButton { background-color: #FFFFFF; color: #333333;
                          border: 1px solid #D9D9D9; border-radius: 4px;
                          padding: 6px 16px; font-size: 13px; }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)

        # 左表字段
        left_name = self._left_card.display_name if self._left_card else "左表"
        layout.addWidget(QLabel(f"左表 ({left_name}) 字段:"))
        left_combo = QComboBox()
        left_combo.setEditable(True)
        left_labels = [f"{f['label']} ({f['key']})" for f in left_fields]
        for i, f in enumerate(left_fields):
            left_combo.addItem(left_labels[i], f['key'])
        # 模糊搜索
        left_completer = QCompleter(left_labels, dlg)
        left_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        left_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        left_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        left_combo.setCompleter(left_completer)
        # 恢复当前值
        if self.left_field:
            idx = left_combo.findData(self.left_field)
            if idx < 0:
                idx = left_combo.findText(self.left_field, Qt.MatchFlag.MatchContains)
            if idx >= 0:
                left_combo.setCurrentIndex(idx)
            else:
                left_combo.setEditText(self.left_field)
        layout.addWidget(left_combo)

        # 右表字段
        right_name = self._right_card.display_name if self._right_card else "右表"
        layout.addWidget(QLabel(f"右表 ({right_name}) 字段:"))
        right_combo = QComboBox()
        right_combo.setEditable(True)
        right_labels = [f"{f['label']} ({f['key']})" for f in right_fields]
        for i, f in enumerate(right_fields):
            right_combo.addItem(right_labels[i], f['key'])
        # 模糊搜索
        right_completer = QCompleter(right_labels, dlg)
        right_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        right_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        right_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        right_combo.setCompleter(right_completer)
        # 恢复当前值
        if self.right_field:
            idx = right_combo.findData(self.right_field)
            if idx < 0:
                idx = right_combo.findText(self.right_field, Qt.MatchFlag.MatchContains)
            if idx >= 0:
                right_combo.setCurrentIndex(idx)
            else:
                right_combo.setEditText(self.right_field)
        layout.addWidget(right_combo)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        ok_btn = QPushButton("✓ 确认")
        ok_btn.setStyleSheet("""
            QPushButton { background-color: #FF8C00; color: #FFFFFF; border: none;
                          border-radius: 4px; padding: 6px 20px; font-weight: 600; }
            QPushButton:hover { background-color: #E67A00; }
        """)
        ok_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # 获取选择的值（优先用 data，回退到输入文本）
        new_left = left_combo.currentData() or left_combo.currentText().strip()
        new_right = right_combo.currentData() or right_combo.currentText().strip()
        if not new_left or not new_right:
            return
        self.left_field = new_left
        self.right_field = new_right
        self.update()
        if self.scene() and hasattr(self.scene(), 'sceneModified'):
            self.scene().sceneModified.emit()

    def _delete_self(self):
        if self.scene() and hasattr(self.scene(), 'remove_line'):
            self.scene().remove_line(self)
        elif self.scene():
            self.scene().removeItem(self)
