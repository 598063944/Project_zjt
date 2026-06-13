"""
拼表画布主控件

QGraphicsView 包装器，提供:
- 缩放（滚轮）
- 平移（左键拖拽空白区域 / 中键拖拽 / 空格+左键）
- 拖拽连线（从连接点拉到目标卡片）
- 自动布局
- 迷你地图
"""

from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QSlider,
    QRubberBand,
)
from PyQt6.QtCore import (
    Qt, QPointF, QRectF, pyqtSignal, QTimer, QLineF,
)
from PyQt6.QtGui import (
    QPainter, QBrush, QColor, QPen, QWheelEvent, QMouseEvent,
    QPainterPath, QFont, QTransform,
)

from .canvas_scene import CanvasScene
from .table_card import TableCard
from .join_line import JoinLine


class JoinCanvas(QGraphicsView):
    """拼表画布"""

    # 信号
    connectionRequested = pyqtSignal(str, str, str, str)  # from_api, from_field, to_api, to_field
    canvasModified = pyqtSignal()
    zoomChanged = pyqtSignal(float)  # 当前缩放比例

    def __init__(self, parent=None):
        self._scene = CanvasScene()
        super().__init__(self._scene, parent)

        self._setup_view()
        self._setup_state()

        # 场景变更时通知外部
        self._scene.sceneModified.connect(self.canvasModified.emit)

    def _setup_view(self):
        """视图基础设置"""
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        # 背景色：浅色画布
        bg_color = QColor("#F5F5F5")
        self._scene.setBackgroundBrush(QBrush(bg_color))
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), bg_color)
        self.setPalette(pal)
        self.setStyleSheet("QGraphicsView { background-color: #F5F5F5; border: none; }")

    def _setup_state(self):
        """状态变量"""
        self._zoom = 1.0
        self._panning = False
        self._pan_start = QPointF()
        self._connecting = False                      # 正在拖拽连线
        self._connect_from_api = ""
        self._connect_from_field = ""
        self._connect_temp_line: QLineF = None        # 临时连线
        self._space_held = False

    # ==================== 场景访问 ====================

    @property
    def canvas_scene(self) -> CanvasScene:
        return self._scene

    def add_table_card(self, object_api: str, display_name: str,
                       fields: list[tuple] = None, is_main: bool = False,
                       position: QPointF = None) -> TableCard:
        """添加对象卡片"""
        card = TableCard(object_api, display_name, fields, is_main)
        if position:
            card.setPos(position)
        else:
            # 默认位置：在已有卡片旁边
            existing = self._scene.get_all_cards()
            if existing:
                last = existing[-1]
                card.setPos(last.pos().x() + 320, last.pos().y())
            else:
                card.setPos(100, 100)
        self._scene.add_card(card)
        return card

    def remove_table_card(self, object_api: str):
        self._scene.remove_card(object_api)

    def get_card(self, object_api: str) -> TableCard:
        return self._scene.get_card(object_api)

    # ==================== 连线拖拽 ====================

    def start_connection_drag(self, from_api: str, from_field: str, scene_pos: QPointF):
        """开始连线拖拽（由 FieldConnectorDot 触发）"""
        self._connecting = True
        self._connect_from_api = from_api
        self._connect_from_field = from_field
        self._connect_start_pos = scene_pos
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _end_connection_drag(self, scene_pos: QPointF):
        """结束连线拖拽"""
        self._connecting = False
        self._connect_temp_line = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # 查找目标卡片
        target_item = self._scene.itemAt(scene_pos, QTransform())
        target_card = self._find_parent_card(target_item)

        if target_card and target_card.object_api != self._connect_from_api:
            # 找到目标：弹窗选择目标字段
            self._show_connection_dialog(target_card)

        self.update()

    def _find_parent_card(self, item) -> TableCard:
        """递归查找 item 所属的 TableCard"""
        while item:
            if isinstance(item, TableCard):
                return item
            item = item.parentItem()
        return None

    def _show_connection_dialog(self, target_card: TableCard):
        """显示连线配置弹窗"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QButtonGroup, QRadioButton, QCompleter

        dialog = QDialog(self)
        dialog.setWindowTitle("设置匹配关系")
        dialog.setMinimumWidth(420)
        dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 强制浅色调色板，防止被系统深色主题影响
        light_palette = dialog.palette()
        light_palette.setColor(light_palette.Window, QColor('#FAFAFA'))
        light_palette.setColor(light_palette.WindowText, QColor('#333333'))
        light_palette.setColor(light_palette.Base, QColor('#FFFFFF'))
        light_palette.setColor(light_palette.AlternateBase, QColor('#F5F5F5'))
        light_palette.setColor(light_palette.Text, QColor('#333333'))
        light_palette.setColor(light_palette.Button, QColor('#FFFFFF'))
        light_palette.setColor(light_palette.ButtonText, QColor('#333333'))
        dialog.setPalette(light_palette)
        dialog.setStyleSheet("""
            QDialog { background-color: #FAFAFA; }
            QLabel { color: #333333; font-size: 13px; }
            QComboBox {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 6px 12px; font-size: 13px;
            }
            QComboBox:hover { border-color: #FF8C00; }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF; color: #333333;
                selection-background-color: #FFF7E6; selection-color: #333333;
                border: 1px solid #E0E0E0;
            }
            QRadioButton { color: #333333; font-size: 13px; spacing: 4px; }
            QRadioButton::indicator { width: 16px; height: 16px; }
            QPushButton {
                background-color: #FFFFFF; color: #333333;
                border: 1px solid #D9D9D9; border-radius: 4px;
                padding: 6px 16px; font-size: 13px;
            }
            QPushButton:hover { border-color: #FF8C00; color: #FF8C00; }
        """)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        from_card = self._scene.get_card(self._connect_from_api)
        layout.addWidget(QLabel(
            f"<b>{from_card.display_name if from_card else self._connect_from_api}</b>"
            f".{self._connect_from_field}  ←→  "
            f"<b>{target_card.display_name}</b>.___"
        ))

        # 目标字段选择
        layout.addWidget(QLabel("选择目标匹配字段:"))
        target_combo = QComboBox()
        target_combo.setEditable(True)
        target_fields = target_card.get_all_fields()
        target_labels = [f"{f['label']} ({f['key']})" for f in target_fields]
        for i, f in enumerate(target_fields):
            target_combo.addItem(target_labels[i], f['key'])
        # 模糊搜索补全
        target_completer = QCompleter(target_labels, dialog)
        target_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        target_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        target_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        target_combo.setCompleter(target_completer)
        layout.addWidget(target_combo)

        # JOIN 类型
        layout.addWidget(QLabel("JOIN 类型:"))
        join_group = QButtonGroup(dialog)
        join_row = QHBoxLayout()
        for jt, jt_label in [('left', '左连接'), ('inner', '内连接'), ('one_to_one', '一对一')]:
            rb = QRadioButton(jt_label)
            rb.setProperty('join_type', jt)
            if jt == 'left':
                rb.setChecked(True)
            join_group.addButton(rb)
            join_row.addWidget(rb)
        layout.addLayout(join_row)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_row.addWidget(cancel_btn)
        ok_btn = QPushButton("✓ 确认连线")
        ok_btn.setStyleSheet("""
            QPushButton { background-color: #FF8C00; color: #FFFFFF; border: none;
                          border-radius: 4px; padding: 6px 16px; font-weight: 600; }
            QPushButton:hover { background-color: #E67A00; }
        """)
        ok_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        target_field = target_combo.currentData()
        if not target_field:
            return

        join_type = 'left'
        checked = join_group.checkedButton()
        if checked:
            join_type = checked.property('join_type') or 'left'

        # 检查是否已存在连线
        existing = self._scene.get_line_between(self._connect_from_api, target_card.object_api)
        if existing:
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "连线已存在",
                f"两表之间已有连线 ({existing.left_field} = {existing.right_field})。\n是否替换？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._scene.remove_line(existing)

        line = JoinLine(
            from_card, target_card,
            left_field=self._connect_from_field,
            right_field=target_field,
            join_type=join_type,
        )
        self._scene.add_line(line)
        self.connectionRequested.emit(
            self._connect_from_api, self._connect_from_field,
            target_card.object_api, target_field,
        )
        self.canvasModified.emit()

    # ==================== 鼠标/键盘事件 ====================

    def wheelEvent(self, event: QWheelEvent):
        """滚轮缩放"""
        factor = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
        new_zoom = self._zoom * factor
        if 0.2 <= new_zoom <= 3.0:
            self._zoom = new_zoom
            self.scale(factor, factor)
            self.zoomChanged.emit(self._zoom)

    def mousePressEvent(self, event: QMouseEvent):
        if self._connecting and event.button() == Qt.MouseButton.LeftButton:
            # 结束连线拖拽
            scene_pos = self.mapToScene(event.pos())
            self._end_connection_drag(scene_pos)
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self._space_held:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        # 左键拖拽空白区域平移画布
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if item is None or isinstance(item, QGraphicsScene):
                self._panning = True
                self._pan_start = event.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._connecting:
            # 画临时连线
            scene_pos = self.mapToScene(event.pos())
            self._connect_temp_line = QLineF(self._connect_start_pos, scene_pos)
            self.update()
            return

        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_held = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif event.key() == Qt.Key.Key_Delete:
            # Delete 键删除选中的连线/卡片（不用 Backspace，因为 Backspace
            # 在卡片搜索框等文本输入场景中会冒泡过来导致误删）
            for item in self._scene.selectedItems():
                if isinstance(item, JoinLine):
                    self._scene.remove_line(item)
                elif isinstance(item, TableCard):
                    self._scene.remove_card(item.object_api)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_held = False
            if not self._panning:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().keyReleaseEvent(event)

    # ==================== 绘制覆盖层 ====================

    def drawForeground(self, painter: QPainter, rect: QRectF):
        """绘制临时连线"""
        super().drawForeground(painter, rect)
        if self._connecting and self._connect_temp_line:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor("#FF8C00"), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(self._connect_temp_line)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """绘制网格背景"""
        painter.fillRect(rect, QColor("#F5F5F5"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        grid_size = 30
        pen = QPen(QColor("#E0E0E0"), 0.5)
        painter.setPen(pen)

        left = int(rect.left()) - (int(rect.left()) % grid_size)
        top = int(rect.top()) - (int(rect.top()) % grid_size)

        x = left
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            x += grid_size

        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            y += grid_size

    # ==================== 公共方法 ====================

    def auto_layout(self):
        self._scene.auto_layout()
        self._fit_to_content()

    def _fit_to_content(self):
        """自适应显示所有卡片"""
        items = self._scene.get_all_cards()
        if not items:
            return
        rect = QRectF()
        for item in items:
            rect = rect.united(item.sceneBoundingRect())
        rect.adjust(-50, -50, 50, 50)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def zoom_in(self):
        if self._zoom >= 3.0:
            return
        self.scale(1.15, 1.15)
        self._zoom = min(self._zoom * 1.15, 3.0)
        self.zoomChanged.emit(self._zoom)

    def zoom_out(self):
        if self._zoom <= 0.2:
            return
        self.scale(1 / 1.15, 1 / 1.15)
        self._zoom = max(self._zoom / 1.15, 0.2)
        self.zoomChanged.emit(self._zoom)

    def zoom_reset(self):
        self.resetTransform()
        self._zoom = 1.0
        self._fit_to_content()
        self.zoomChanged.emit(self._zoom)
