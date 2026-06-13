# -*- coding: utf-8 -*-
"""自定义报表对话框组件"""

from PyQt6.QtCore import Qt, QEvent, QTimer, QObject
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QDialog, QApplication


# ---- 辅助函数 ----

def _get_screen_for_widget(widget=None):
    app = QApplication.instance()
    if widget is not None:
        try:
            screen = QApplication.screenAt(widget.mapToGlobal(widget.rect().center()))
            if screen is not None:
                return screen
        except Exception:
            pass
        if hasattr(widget, 'screen'):
            try:
                screen = widget.screen()
                if screen is not None:
                    return screen
            except Exception:
                pass
    return app.primaryScreen() if app is not None else None


def center_dialog(dialog, reference_widget=None):
    dialog.adjustSize()
    screen = _get_screen_for_widget(reference_widget or dialog.parentWidget() or dialog)
    if screen is None:
        return
    available_geometry = screen.availableGeometry()
    center_point = available_geometry.center()
    if reference_widget is not None:
        try:
            center_point = reference_widget.mapToGlobal(reference_widget.rect().center())
        except Exception:
            center_point = available_geometry.center()
    popup_width = dialog.width()
    popup_height = dialog.height()
    min_x = available_geometry.left()
    max_x = available_geometry.left() + max(0, available_geometry.width() - popup_width)
    min_y = available_geometry.top()
    max_y = available_geometry.top() + max(0, available_geometry.height() - popup_height)
    x = center_point.x() - popup_width // 2
    y = center_point.y() - popup_height // 2
    dialog.move(min(max(x, min_x), max_x), min(max(y, min_y), max_y))


def position_dialog_below_widget(dialog, anchor_widget, margin=6):
    if anchor_widget is None:
        center_dialog(dialog)
        return
    dialog.adjustSize()
    screen = _get_screen_for_widget(anchor_widget)
    if screen is None:
        center_dialog(dialog, anchor_widget)
        return
    available_geometry = screen.availableGeometry()
    popup_width = dialog.width()
    popup_height = dialog.height()
    anchor_rect = anchor_widget.rect()
    anchor_top_left = anchor_widget.mapToGlobal(anchor_rect.topLeft())
    anchor_bottom_left = anchor_widget.mapToGlobal(anchor_rect.bottomLeft())
    anchor_bottom_right = anchor_widget.mapToGlobal(anchor_rect.bottomRight())
    min_x = available_geometry.left()
    max_x = available_geometry.left() + max(0, available_geometry.width() - popup_width)
    min_y = available_geometry.top()
    max_y = available_geometry.top() + max(0, available_geometry.height() - popup_height)
    x = anchor_top_left.x()
    if x > max_x:
        x = anchor_bottom_right.x() - popup_width
    x = min(max(x, min_x), max_x)
    y = anchor_bottom_left.y() + margin
    if y > max_y:
        y = anchor_top_left.y() - popup_height - margin
    y = min(max(y, min_y), max_y)
    dialog.move(x, y)


# ---- 事件过滤器 ----

class _DialogOutsideCloseFilter(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, watched, event):
        dialog = self._dialog
        if dialog is None:
            return False
        try:
            if not dialog.isVisible() or not getattr(dialog, '_outside_close_armed', False):
                return False
        except RuntimeError:
            return False
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        active_modal = QApplication.activeModalWidget()
        active_popup = QApplication.activePopupWidget()
        if active_modal is not None and active_modal is not dialog:
            return False
        if active_popup is not None and active_popup is not dialog:
            return False
        watched_widget = watched if hasattr(watched, 'parentWidget') else None
        if watched_widget is dialog or (watched_widget is not None and dialog.isAncestorOf(watched_widget)):
            return False
        global_pos = None
        if hasattr(event, 'globalPosition'):
            global_pos = event.globalPosition().toPoint()
        elif hasattr(event, 'globalPos'):
            global_pos = event.globalPos()
        if global_pos is not None and dialog.frameGeometry().contains(global_pos):
            return False
        try:
            dialog.reject()
        except RuntimeError:
            pass
        return False


# ---- 基类 ----

class CenteredPopupDialog(QDialog):
    """统一处理居中显示和点外部关闭的弹窗基类。

    包含 _dialog_closed 标志位修复 accept/reject 竞态问题。
    强制浅色背景，避免被父窗口样式表或系统深色主题覆盖。
    """

    def __init__(self, parent=None, center_reference=None, close_on_outside=True):
        super().__init__(parent)
        self._center_reference_widget = center_reference or parent
        self._popup_anchor_widget = None
        self._popup_anchor_margin = 6
        self._close_on_outside = close_on_outside
        self._outside_close_armed = False
        self._outside_close_filter = _DialogOutsideCloseFilter(self) if close_on_outside else None
        self._outside_close_filter_installed = False
        self._dialog_closed = False

        # 强制浅色背景：同时设置调色板和样式表，防止被父窗口/系统主题覆盖
        light_palette = self.palette()
        light_palette.setColor(light_palette.Window, QColor('#FAFAFA'))
        light_palette.setColor(light_palette.WindowText, QColor('#333333'))
        light_palette.setColor(light_palette.Base, QColor('#FFFFFF'))
        light_palette.setColor(light_palette.AlternateBase, QColor('#F5F5F5'))
        light_palette.setColor(light_palette.Text, QColor('#333333'))
        light_palette.setColor(light_palette.Button, QColor('#FFFFFF'))
        light_palette.setColor(light_palette.ButtonText, QColor('#333333'))
        light_palette.setColor(light_palette.ToolTipBase, QColor('#FFFFFF'))
        light_palette.setColor(light_palette.ToolTipText, QColor('#333333'))
        self.setPalette(light_palette)

        # 使用对象名选择器提高优先级，防止父窗口 QDialog 规则覆盖
        self.setObjectName("centeredPopupDialog")
        self.setStyleSheet("""
            QDialog#centeredPopupDialog {
                background-color: #FAFAFA;
                color: #333333;
            }
        """)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def setCenterReferenceWidget(self, widget):
        self._center_reference_widget = widget

    def setPopupAnchorWidget(self, widget, margin=6):
        self._popup_anchor_widget = widget
        self._popup_anchor_margin = margin

    def showEvent(self, event):
        super().showEvent(event)
        if self._popup_anchor_widget is not None:
            position_dialog_below_widget(self, self._popup_anchor_widget, self._popup_anchor_margin)
        else:
            center_dialog(self, self._center_reference_widget or self.parentWidget())
        if self._close_on_outside:
            self._outside_close_armed = False
            self._install_outside_close_filter()
            QTimer.singleShot(0, self._arm_outside_close)

    def hideEvent(self, event):
        self._outside_close_armed = False
        self._remove_outside_close_filter()
        super().hideEvent(event)

    def event(self, event):
        if getattr(self, '_dialog_closed', False):
            return super().event(event)
        if (
            self._close_on_outside
            and self.isVisible()
            and self._outside_close_armed
            and event.type() == QEvent.Type.WindowDeactivate
        ):
            active_modal = QApplication.activeModalWidget()
            active_popup = QApplication.activePopupWidget()
            if active_modal is not None and active_modal is not self:
                return super().event(event)
            if active_popup is not None and active_popup is not self:
                return super().event(event)
            self._dialog_closed = True
            self.reject()
            return True
        return super().event(event)

    def accept(self):
        self._dialog_closed = True
        super().accept()

    def reject(self):
        self._dialog_closed = True
        super().reject()

    def _arm_outside_close(self):
        if self.isVisible():
            self._outside_close_armed = True

    def _install_outside_close_filter(self):
        app = QApplication.instance()
        if app is None or self._outside_close_filter is None or self._outside_close_filter_installed:
            return
        app.installEventFilter(self._outside_close_filter)
        self._outside_close_filter_installed = True

    def _remove_outside_close_filter(self):
        app = QApplication.instance()
        if app is None or self._outside_close_filter is None or not self._outside_close_filter_installed:
            return
        app.removeEventFilter(self._outside_close_filter)
        self._outside_close_filter_installed = False
