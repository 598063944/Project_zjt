"""
对象卡片

画布上的可拖拽卡片，代表一个 CRM 数据对象。
内部显示对象名称、字段列表（带勾选框和连接点）。
"""

from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsObject, QGraphicsProxyWidget,
    QGraphicsSceneMouseEvent, QGraphicsSceneHoverEvent,
    QGraphicsSceneDragDropEvent,
    QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QFrame, QWidget,
    QPushButton, QLineEdit,
)
from PyQt6.QtCore import (
    Qt, QRectF, QPointF, pyqtSignal, QObject,
)
from PyQt6.QtGui import (
    QPainter, QBrush, QPen, QColor, QFont, QPainterPath,
    QLinearGradient, QFontMetrics,
)

# 卡片常量
CARD_WIDTH = 260
CARD_HEADER_HEIGHT = 36
FIELD_ROW_HEIGHT = 26
SEARCH_BAR_HEIGHT = 30
CARD_MIN_HEIGHT = 120
CARD_RADIUS = 10
CONNECTOR_RADIUS = 5


class FieldConnectorDot(QGraphicsItem):
    """字段旁的连接点（小圆点，可拖拽拉出连线）。

    使用回调函数（非 PyQt 信号）来通知拖拽事件，
    避免 QObject + QGraphicsItem 多重继承的初始化冲突。
    """

    def __init__(self, object_api: str, field_name: str, parent=None):
        super().__init__(parent)
        self.object_api = object_api
        self.field_name = field_name
        self._hovered = False
        self._dragging = False
        self._on_drag_started = None  # callable(api, field, scene_pos)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(10)

    def set_drag_callback(self, callback):
        """设置拖拽开始回调: callback(object_api, field_name, scene_pos)"""
        self._on_drag_started = callback

    def boundingRect(self):
        r = CONNECTOR_RADIUS + 3
        return QRectF(-r, -r, r * 2, r * 2)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hovered or self._dragging:
            painter.setBrush(QBrush(QColor("#FF8C00")))
            painter.setPen(QPen(QColor("#FF8C00"), 2))
            painter.drawEllipse(QPointF(0, 0), CONNECTOR_RADIUS + 1, CONNECTOR_RADIUS + 1)
        else:
            painter.setBrush(QBrush(QColor("#1890FF")))
            painter.setPen(QPen(QColor("#FFFFFF"), 1))
        painter.drawEllipse(QPointF(0, 0), CONNECTOR_RADIUS, CONNECTOR_RADIUS)

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and self._on_drag_started:
            scene_pos = self.mapToScene(event.pos())
            self._on_drag_started(self.object_api, self.field_name, scene_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.update()
            event.accept()


class TableCard(QGraphicsObject):
    """数据对象卡片"""

    # 信号
    positionChanged = pyqtSignal(str, QPointF)          # api_name, new_pos
    fieldToggled = pyqtSignal(str, str, bool)            # api_name, field_name, checked
    fieldConnectionRequested = pyqtSignal(str, str, str, str)  # from_api, from_field, to_api, to_field
    cardRemoveRequested = pyqtSignal(str)                # api_name

    def __init__(self, object_api: str, display_name: str,
                 fields: list[tuple] = None, is_main: bool = False):
        """
        Args:
            object_api: CRM 对象 API 名
            display_name: 显示名（中文）
            fields: [(field_key, field_label, checked), ...]
            is_main: 是否为主表
        """
        super().__init__()
        self.object_api = object_api
        self.display_name = display_name
        self.is_main = is_main
        self._fields: list[dict] = []          # [{key, label, checked, connector}]
        self._connectors: list[FieldConnectorDot] = []
        self._search_text = ""
        self._search_active = False               # whether a search filter is currently applied
        self._filtered_indices: list[int] = []    # visible field indices after search filter
        self._search_input = None
        self._search_proxy = None

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(5)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        # 构建字段
        self._header_height = CARD_HEADER_HEIGHT
        self._fields_offset = CARD_HEADER_HEIGHT + SEARCH_BAR_HEIGHT
        self.set_fields(fields or [])
        self._setup_search_input()

    # ==================== 尺寸计算 ====================

    def _calc_height(self) -> float:
        if self._search_active:
            rows = max(len(self._filtered_indices), 1)
        else:
            rows = max(len(self._fields), 1)
        return self._fields_offset + rows * FIELD_ROW_HEIGHT + 12

    def boundingRect(self):
        return QRectF(0, 0, CARD_WIDTH, self._calc_height())

    # ==================== 字段管理 ====================

    def set_fields(self, fields: list[tuple]):
        """
        设置字段列表

        Args:
            fields: [(field_key, field_label, checked), ...]
        """
        # 清除旧连接点
        for c in self._connectors:
            if c.scene():
                c.scene().removeItem(c)
        self._connectors.clear()

        self._fields = []
        for key, label, checked in fields:
            self._fields.append({
                'key': key,
                'label': label or key,
                'checked': checked,
            })

        # 创建连接点
        for i, f in enumerate(self._fields):
            dot = FieldConnectorDot(self.object_api, f['key'], self)
            dot.setPos(CARD_WIDTH - 20, self._fields_offset + i * FIELD_ROW_HEIGHT + FIELD_ROW_HEIGHT / 2 + 6)
            dot.set_drag_callback(self._on_dot_drag_started)
            self._connectors.append(dot)

        self._search_text = ""
        self._search_active = False
        self._filtered_indices = list(range(len(self._fields)))
        # 清空搜索输入框（如果存在）
        if self._search_input:
            self._search_input.blockSignals(True)
            self._search_input.clear()
            self._search_input.blockSignals(False)
        self.prepareGeometryChange()
        self.update()

    def _setup_search_input(self):
        """Add a search QLineEdit below the card header to filter fields."""
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索字段...")
        self._search_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D9D9D9; border-radius: 3px;
                padding: 2px 8px; font-size: 11px;
                background: #FFFFFF;
            }
            QLineEdit:focus { border-color: #FF8C00; }
        """)
        self._search_input.textChanged.connect(self.set_search_text)
        self._search_proxy = QGraphicsProxyWidget(self)
        self._search_proxy.setWidget(self._search_input)
        self._search_proxy.setPos(10, CARD_HEADER_HEIGHT + 5)
        self._search_proxy.setZValue(100)
        self._search_input.setFixedWidth(int(CARD_WIDTH - 20))

    def set_search_text(self, text: str):
        """Filter displayed fields by search text (matches label or key)."""
        self.prepareGeometryChange()
        self._search_text = text.lower().strip()
        self._search_active = bool(self._search_text)
        if not self._search_active:
            self._filtered_indices = list(range(len(self._fields)))
        else:
            self._filtered_indices = [
                i for i, f in enumerate(self._fields)
                if self._search_text in f['label'].lower() or self._search_text in f['key'].lower()
            ]
        # Update connector dot visibility and positions
        for i, dot in enumerate(self._connectors):
            if i in self._filtered_indices:
                new_row = self._filtered_indices.index(i)
                dot.setPos(CARD_WIDTH - 20,
                           self._fields_offset + new_row * FIELD_ROW_HEIGHT + FIELD_ROW_HEIGHT / 2 + 6)
                dot.setVisible(True)
            else:
                dot.setVisible(False)
        self.update()

    def update_field_checked(self, field_key: str, checked: bool):
        """更新字段勾选状态"""
        for f in self._fields:
            if f['key'] == field_key:
                f['checked'] = checked
                break
        self.update()

    def get_checked_fields(self) -> list[dict]:
        """获取已勾选的字段"""
        return [f for f in self._fields if f['checked']]

    def get_all_fields(self) -> list[dict]:
        return list(self._fields)

    def get_field_keys(self) -> list[str]:
        return [f['key'] for f in self._fields]

    # ==================== 交互 ====================

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            y = event.pos().y()
            if y < self._header_height:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                # 头部区域：开始拖拽
                pass
            elif y >= self._fields_offset:
                # 字段区域：检查是否点击了勾选框
                row = int((y - self._fields_offset) / FIELD_ROW_HEIGHT)
                indices = self._filtered_indices if self._search_active else list(range(len(self._fields)))
                if 0 <= row < len(indices):
                    real_idx = indices[row]
                    x = event.pos().x()
                    if 12 <= x <= 32:  # 勾选框区域
                        f = self._fields[real_idx]
                        f['checked'] = not f['checked']
                        self.fieldToggled.emit(self.object_api, f['key'], f['checked'])
                        self.update()
                        event.accept()
                        return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.positionChanged.emit(self.object_api, self.pos())
            # 同步更新连接点位置
            indices = self._filtered_indices if self._search_active else list(range(len(self._fields)))
            for display_i, real_i in enumerate(indices):
                if real_i < len(self._connectors):
                    self._connectors[real_i].setPos(
                        CARD_WIDTH - 20,
                        self._fields_offset + display_i * FIELD_ROW_HEIGHT + FIELD_ROW_HEIGHT / 2 + 6)
        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        """右键菜单"""
        from PyQt6.QtWidgets import QMenu
        menu = QMenu()
        if not self.is_main:
            set_main_action = menu.addAction("设为主表")
            set_main_action.triggered.connect(
                lambda: self.scene().set_main_card(self.object_api) if self.scene() else None
            )
        menu.addSeparator()
        remove_action = menu.addAction("删除此表")
        remove_action.triggered.connect(lambda: self.cardRemoveRequested.emit(self.object_api))
        menu.exec(event.screenPos())

    # ==================== 连线拖拽 ====================

    def _on_dot_drag_started(self, object_api: str, field_name: str, scene_pos: QPointF):
        """连接点被拖拽 —— 由 CanvasView 处理拖拽线"""
        if hasattr(self.scene(), 'views') and self.scene().views():
            view = self.scene().views()[0]
            if hasattr(view, 'start_connection_drag'):
                view.start_connection_drag(object_api, field_name, scene_pos)

    # ==================== 绘制 ====================

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.boundingRect()
        h = self._calc_height()

        # 阴影
        shadow_path = QPainterPath()
        shadow_rect = QRectF(3, 3, rect.width(), rect.height())
        shadow_path.addRoundedRect(shadow_rect, CARD_RADIUS, CARD_RADIUS)
        painter.fillPath(shadow_path, QColor(0, 0, 0, 30))

        # 卡片背景
        body_path = QPainterPath()
        body_path.addRoundedRect(QRectF(0, 0, CARD_WIDTH, h), CARD_RADIUS, CARD_RADIUS)
        painter.fillPath(body_path, QColor("#FFFFFF"))

        # 边框
        border_color = QColor("#FF8C00") if self.is_main else QColor("#D9D9D9")
        if self.isSelected():
            border_color = QColor("#1890FF")
        painter.setPen(QPen(border_color, 2))
        painter.drawRoundedRect(QRectF(1, 1, CARD_WIDTH - 2, h - 2), CARD_RADIUS, CARD_RADIUS)

        # 头部
        header_rect = QRectF(0, 0, CARD_WIDTH, self._header_height)
        header_path = QPainterPath()
        header_path.addRoundedRect(header_rect, CARD_RADIUS, CARD_RADIUS)
        # 底部直角
        header_path.addRect(QRectF(0, CARD_RADIUS, CARD_WIDTH, self._header_height - CARD_RADIUS))
        header_gradient = QLinearGradient(0, 0, CARD_WIDTH, 0)
        if self.is_main:
            header_gradient.setColorAt(0, QColor("#FF8C00"))
            header_gradient.setColorAt(1, QColor("#FFB84D"))
        else:
            header_gradient.setColorAt(0, QColor("#666666"))
            header_gradient.setColorAt(1, QColor("#888888"))
        painter.fillPath(header_path, QBrush(header_gradient))

        # 头部文本
        painter.setPen(QColor("#FFFFFF"))
        font = QFont("Microsoft YaHei", 12, QFont.Weight.Bold)
        painter.setFont(font)
        label = f"{'★ ' if self.is_main else ''}{self.display_name}"
        painter.drawText(QRectF(14, 0, CARD_WIDTH - 30, self._header_height),
                        Qt.AlignmentFlag.AlignVCenter, label)

        # 数据源（灰色小字，显示中文名 + API 名）
        painter.setPen(QColor("#999999"))
        painter.setFont(QFont("Microsoft YaHei", 8))
        subtitle = f"{self.display_name}  [{self.object_api}]"
        fm = QFontMetrics(painter.font())
        elided_sub = fm.elidedText(subtitle, Qt.TextElideMode.ElideRight, CARD_WIDTH - 30)
        painter.drawText(QRectF(14, self._header_height - 12, CARD_WIDTH - 30, 12),
                        Qt.AlignmentFlag.AlignLeft, elided_sub)

        # 搜索栏区域背景
        search_bg = QRectF(0, self._header_height, CARD_WIDTH, SEARCH_BAR_HEIGHT)
        painter.fillRect(search_bg, QColor("#F8F8F8"))
        # 搜索栏底部分割线
        painter.setPen(QPen(QColor("#E8E8E8"), 1))
        painter.drawLine(QPointF(10, self._fields_offset - 2),
                        QPointF(CARD_WIDTH - 10, self._fields_offset - 2))

        # 字段列表
        if self._search_active:
            if not self._filtered_indices:
                # 搜索无结果提示
                y = self._fields_offset + 10
                painter.setPen(QColor("#999999"))
                painter.setFont(QFont("Microsoft YaHei", 11))
                painter.drawText(QRectF(14, y, CARD_WIDTH - 28, 20),
                               Qt.AlignmentFlag.AlignCenter, "无匹配字段")
            else:
                for display_i, real_i in enumerate(self._filtered_indices):
                    self._draw_field_row(painter, display_i, self._fields[real_i])
        else:
            for i, f in enumerate(self._fields):
                self._draw_field_row(painter, i, f)

    def _draw_field_row(self, painter: QPainter, display_i: int, f: dict):
        """Draw a single field row at the given display index."""
        y = self._fields_offset + display_i * FIELD_ROW_HEIGHT + 6
        row_rect = QRectF(0, y, CARD_WIDTH, FIELD_ROW_HEIGHT)

        # 隔行背景
        if display_i % 2 == 0:
            painter.fillRect(row_rect, QColor("#FAFAFA"))

        # 勾选框
        check_rect = QRectF(12, y + 5, 16, 16)
        if f['checked']:
            painter.setPen(QPen(QColor("#FF8C00"), 2))
            painter.setBrush(QBrush(QColor("#FF8C00")))
        else:
            painter.setPen(QPen(QColor("#BFBFBF"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(check_rect, 3, 3)
        if f['checked']:
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.drawLine(QPointF(16, y + 13), QPointF(19, y + 16))
            painter.drawLine(QPointF(19, y + 16), QPointF(25, y + 9))

        # 字段名
        painter.setPen(QColor("#333333"))
        painter.setFont(QFont("Microsoft YaHei", 10))
        label = f['label']
        fm = QFontMetrics(painter.font())
        elided = fm.elidedText(label, Qt.TextElideMode.ElideRight, CARD_WIDTH - 60)
        painter.drawText(QRectF(38, y, CARD_WIDTH - 60, FIELD_ROW_HEIGHT),
                       Qt.AlignmentFlag.AlignVCenter, elided)

        # 底部分割线
        painter.setPen(QPen(QColor("#F0F0F0"), 1))
        painter.drawLine(QPointF(14, y + FIELD_ROW_HEIGHT),
                       QPointF(CARD_WIDTH - 14, y + FIELD_ROW_HEIGHT))

    def update_visual(self):
        """更新视觉样式（如主表切换）"""
        self.prepareGeometryChange()
        self.update()
