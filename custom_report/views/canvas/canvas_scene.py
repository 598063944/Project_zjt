"""
画布场景管理器

管理所有 TableCard 和 JoinLine 的集合。
处理卡片添加/删除、连线建立/删除、数据模型同步。
"""

from PyQt6.QtWidgets import QGraphicsScene
from PyQt6.QtCore import pyqtSignal, QObject


class CanvasScene(QGraphicsScene):
    """拼表画布场景"""

    # 信号
    cardAdded = pyqtSignal(str)             # object_api
    cardRemoved = pyqtSignal(str)           # object_api
    joinCreated = pyqtSignal(str, str)      # (left_api, right_api)
    joinRemoved = pyqtSignal(str, str)      # (left_api, right_api)
    sceneModified = pyqtSignal()            # 任何变更

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self._cards: dict[str, "TableCard"] = {}      # {api_name: card}
        self._lines: list["JoinLine"] = []

    # ==================== 卡片管理 ====================

    def add_card(self, card: "TableCard"):
        """添加对象卡片到场景"""
        if card.object_api in self._cards:
            return
        self._cards[card.object_api] = card
        self.addItem(card)
        card.positionChanged.connect(self._on_card_moved)
        card.fieldConnectionRequested.connect(self._on_field_connection_request)
        card.cardRemoveRequested.connect(self._on_card_remove_request)
        self.cardAdded.emit(card.object_api)
        self.sceneModified.emit()

    def remove_card(self, object_api: str):
        """移除对象卡片（同时删除关联连线）"""
        card = self._cards.pop(object_api, None)
        if not card:
            return

        # 删除与此卡相关的所有连线
        lines_to_remove = []
        for line in self._lines:
            if object_api in (line.left_api, line.right_api):
                lines_to_remove.append(line)

        for line in lines_to_remove:
            self.removeItem(line)
            self._lines.remove(line)
            self.joinRemoved.emit(line.left_api, line.right_api)

        self.removeItem(card)
        self.cardRemoved.emit(object_api)
        self.sceneModified.emit()

    def get_card(self, object_api: str) -> "TableCard":
        return self._cards.get(object_api)

    @property
    def card_count(self) -> int:
        return len(self._cards)

    def get_all_cards(self) -> list["TableCard"]:
        return list(self._cards.values())

    def get_main_card(self) -> "TableCard":
        """获取主表卡片"""
        for card in self._cards.values():
            if card.is_main:
                return card
        return list(self._cards.values())[0] if self._cards else None

    def set_main_card(self, object_api: str):
        """设置主表"""
        for api, card in self._cards.items():
            card.is_main = (api == object_api)
            card.update_visual()
        self.sceneModified.emit()

    # ==================== 连线管理 ====================

    def add_line(self, line: "JoinLine"):
        """添加连线"""
        # 检查是否已存在相同连线
        for existing in self._lines:
            if (existing.left_api == line.left_api and
                existing.right_api == line.right_api and
                existing.left_field == line.left_field and
                existing.right_field == line.right_field):
                return  # 已存在
        self._lines.append(line)
        self.addItem(line)
        self.joinCreated.emit(line.left_api, line.right_api)
        self.sceneModified.emit()

    def remove_line(self, line: "JoinLine"):
        """移除连线"""
        if line in self._lines:
            self._lines.remove(line)
            self.removeItem(line)
            self.joinRemoved.emit(line.left_api, line.right_api)
            self.sceneModified.emit()

    def get_lines_for_card(self, object_api: str) -> list["JoinLine"]:
        """获取与指定卡片相关的所有连线"""
        return [l for l in self._lines if object_api in (l.left_api, l.right_api)]

    def get_all_lines(self) -> list["JoinLine"]:
        return list(self._lines)

    def get_line_between(self, api1: str, api2: str) -> "JoinLine":
        """获取两张表之间的连线"""
        for line in self._lines:
            if {line.left_api, line.right_api} == {api1, api2}:
                return line
        return None

    def remove_line_between(self, api1: str, api2: str):
        """移除两张表之间的连线"""
        for line in list(self._lines):
            if {line.left_api, line.right_api} == {api1, api2}:
                self.remove_line(line)

    # ==================== 内部回调 ====================

    def _on_card_moved(self, api: str, pos):
        """卡片移动后更新相关连线"""
        for line in self._lines:
            if api in (line.left_api, line.right_api):
                line.update_path()

    def _on_field_connection_request(self, from_api: str, from_field: str,
                                      to_api: str, to_field: str):
        """字段连线请求（从 TableCard 发出）"""
        from .join_line import JoinLine
        left_card = self._cards.get(from_api)
        right_card = self._cards.get(to_api)
        if not left_card or not right_card:
            return

        line = JoinLine(
            left_card, right_card,
            left_field=from_field,
            right_field=to_field,
        )
        self.add_line(line)

    def _on_card_remove_request(self, object_api: str):
        """卡片删除请求"""
        self.remove_card(object_api)

    # ==================== 序列化 ====================

    def to_report_joins(self, main_api: str) -> list:
        """将场景中的连线导出为 JoinDefinition 列表"""
        from ...models import JoinDefinition, MatchKey

        joins = []
        for line in self._lines:
            left_api = line.left_api
            right_api = line.right_api
            joins.append(JoinDefinition(
                left_object_api=left_api,
                right_object_api=right_api,
                match_keys=[MatchKey(
                    left_field=line.left_field,
                    right_field=line.right_field,
                )],
                join_type=line.join_type,
            ))
        return joins

    def from_report_joins(self, joins: list):
        """从 JoinDefinition 列表还原连线"""
        from .join_line import JoinLine

        # 清除现有连线
        for line in list(self._lines):
            self.removeItem(line)
        self._lines.clear()

        for jd in joins:
            if not isinstance(jd, dict) and hasattr(jd, 'left_object_api'):
                left_api = jd.left_object_api
                right_api = jd.right_object_api
                join_type = jd.join_type
                keys = jd.match_keys
            else:
                left_api = jd.get('left_object_api', '')
                right_api = jd.get('right_object_api', '')
                join_type = jd.get('join_type', 'left')
                keys = jd.get('match_keys', [])

            left_card = self._cards.get(left_api)
            right_card = self._cards.get(right_api)
            if not left_card or not right_card:
                continue

            for mk in keys:
                if isinstance(mk, dict):
                    left_field = mk.get('left_field', '')
                    right_field = mk.get('right_field', '')
                else:
                    left_field = mk.left_field
                    right_field = mk.right_field

                if left_field and right_field:
                    line = JoinLine(
                        left_card, right_card,
                        left_field=left_field,
                        right_field=right_field,
                        join_type=join_type,
                    )
                    self._lines.append(line)
                    self.addItem(line)

    def auto_layout(self):
        """自动布局所有卡片"""
        cards = list(self._cards.values())
        if not cards:
            return

        # 主表居中
        main = self.get_main_card()
        if not main:
            main = cards[0]

        cx, cy = 0, 0
        main.setPos(cx - main.boundingRect().width() / 2, cy - main.boundingRect().height() / 2)

        # 关联表围绕主表排列
        other = [c for c in cards if c != main]
        import math
        radius = 450
        for i, card in enumerate(other):
            angle = (2 * math.pi * i) / max(len(other), 1) - math.pi / 2
            x = cx + radius * math.cos(angle) - card.boundingRect().width() / 2
            y = cy + radius * math.sin(angle) - card.boundingRect().height() / 2
            card.setPos(x, y)

        # 更新连线
        for line in self._lines:
            line.update_path()
