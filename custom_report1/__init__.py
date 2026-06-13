"""
自定义报表模块 - 可视化拼表 + MySQL 持久化

提供:
- 可视化画布：拖拽数据对象卡片、连线定义匹配关系
- 拼表引擎：自动生成 CREATE TABLE AS SELECT ... JOIN ... SQL
- MySQL 持久化：Source 表 (sr_*) → 拼表 → Result 表 (cr_*)

入口:
    from custom_report.manager import ReportManager
    mgr = ReportManager(mysql_config, crm_client)
    mgr.initialize()
    list_page = mgr.get_list_page()
    editor_page = mgr.get_editor_page()
"""

import logging
import sys


class UILogHandler(logging.Handler):
    """将日志同时输出到主程序运行时窗口"""

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            main_mod = sys.modules.get('__main__')
            if main_mod:
                mf = getattr(main_mod, 'MainFrame', None)
                if mf and hasattr(mf, 'instance') and mf.instance:
                    mf.instance.append_output(msg)
                    return
        except Exception:
            pass
        # 回退：打印到 stdout
        print(self.format(record))


def setup_ui_logging():
    """为所有 logger 添加 UI 日志处理器（输出到主程序运行时窗口）"""
    ui_handler = UILogHandler()
    ui_handler.setLevel(logging.INFO)
    ui_handler.setFormatter(logging.Formatter('[%(name)s] %(levelname)s - %(message)s'))

    # 避免重复添加
    existing = [h for h in logging.root.handlers if isinstance(h, UILogHandler)]
    if existing:
        return

    # 添加到 root logger → 捕获所有模块的日志
    logging.root.addHandler(ui_handler)
    logging.root.setLevel(logging.INFO)

    # 同时添加到 custom_report logger
    cr_logger = logging.getLogger('custom_report')
    cr_logger.addHandler(ui_handler)
    cr_logger.setLevel(logging.INFO)


from .models import (
    ReportDefinition,
    JoinDefinition,
    MatchKey,
    FieldColumn,
    FilterCondition,
    JoinType,
    MultiMatchStrategy,
    FilterOperator,
)

from .manager import ReportManager

__all__ = [
    'ReportManager',
    'ReportDefinition',
    'JoinDefinition',
    'MatchKey',
    'FieldColumn',
    'FilterCondition',
    'JoinType',
    'MultiMatchStrategy',
    'FilterOperator',
]
