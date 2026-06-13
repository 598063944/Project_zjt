# -*- coding: utf-8 -*-
"""自定义报表模块常量定义"""

# 默认 CRM 数据源（显示名 → API 名）
DEFAULT_SOURCES = [
    {'name': '商机', 'api_name': 'NewOpportunityObj'},
    {'name': '销售订单', 'api_name': 'SalesOrderObj'},
    {'name': '发货单', 'api_name': 'DeliveryNoteObj'},
    {'name': '发货单产品', 'api_name': 'DeliveryNoteProductObj'},
    {'name': '公立项目授权', 'api_name': 'public_project_authorizati__c'},
]

# CRM API 筛选操作符
OPERATOR_MAP = {
    '等于': 'EQ',
    '不等于': 'NEQ',
    '包含': 'LIKE',
    '不包含': 'NOT_LIKE',
    '大于': 'GT',
    '小于': 'LT',
    '大于等于': 'GTE',
    '小于等于': 'LTE',
    '为空': 'IS_NULL',
    '不为空': 'IS_NOT_NULL',
}

# 本地筛选弹窗操作符
FILTER_DIALOG_OPERATORS = [
    ("包含", "contains"),
    ("不包含", "not_contains"),
    ("属于", "in"),
    ("不属于", "not_in"),
    ("等于", "eq"),
    ("不等于", "ne"),
    ("为空（未填写）", "empty"),
    ("不为空", "not_empty"),
    ("开始于", "starts_with"),
    ("结束于", "ends_with"),
    ("大于", "gt"),
    ("小于", "lt"),
]

# 快捷筛选操作符
QUICK_OPERATORS = ["包含", "等于", "不等于", "大于", "小于", "属于", "不属于", "为空"]

# 分页选项
DEFAULT_PAGE_SIZES = [20, 50, 100, 200]

# 报表预设类型
PRESET_TYPE_REPORT = 'report'
PRESET_TYPE_FOLDER = 'folder'
PRESET_TYPE_DASHBOARD = 'dashboard'

# MySQL 表名
MYSQL_REPORTS_TABLE = 'custom_reports'

# 报表预设状态
PRESET_STATUS_ENABLED = 'enabled'
PRESET_STATUS_DISABLED = 'disabled'


# ---- 字段格式枚举（用户可在报表编辑器中为每列指定） ----

# (value, label) 对，用于 UI 下拉框
FIELD_FORMATS = [
    ("text",        "文本"),
    ("integer",     "整数"),
    ("float",       "浮点数"),
    ("currency",    "金额"),
    ("date_ymd",    "日期(yyyy-MM-dd)"),
    ("date_ymd_cn", "日期(yyyy年MM月dd日)"),
    ("datetime",    "日期时间"),
    ("time",        "时间"),
]

# field_format → MySQL 列类型
FIELD_FORMAT_MYSQL_TYPE = {
    "text":         "LONGTEXT",
    "integer":      "BIGINT",
    "float":        "DOUBLE",
    "currency":     "DECIMAL(18,2)",
    "date_ymd":     "DATE",
    "date_ymd_cn":  "VARCHAR(32)",
    "datetime":     "DATETIME",
    "time":         "TIME",
}


def get_mysql_type_for_format(field_format: str) -> str:
    """根据字段格式返回 MySQL 列类型。默认 LONGTEXT。"""
    if not field_format:
        return "LONGTEXT"
    return FIELD_FORMAT_MYSQL_TYPE.get(field_format, "LONGTEXT")


def is_numeric_format(field_format: str) -> bool:
    """判断字段格式是否为数值类型（整数/浮点数/金额）。"""
    return field_format in ("integer", "float", "currency")


def safe_value_by_format(val, field_format: str = "text"):
    """根据字段格式将值安全转为对应类型，用于写入 MySQL。

    Returns:
        对应类型的值，或 None（空值），或原字符串（无法转换时）
    """
    if val is None or val == '':
        return None

    fmt = field_format or "text"

    if fmt == "text":
        return str(val) if val is not None else ''

    if fmt in ("integer", "float", "currency"):
        try:
            if isinstance(val, (int, float)):
                return int(float(val)) if fmt == "integer" else float(val)
            if isinstance(val, str):
                stripped = val.strip()
                if not stripped:
                    return None
                num = float(stripped)
                return int(num) if fmt == "integer" else num
            num = float(val)
            return int(num) if fmt == "integer" else num
        except (ValueError, TypeError):
            return str(val) if val is not None else ''

    # 日期/时间格式 — 保持字符串原值
    return str(val) if val is not None else ''


# ---- 字段类型判断工具（基于 CRM 字段类型） ----

def is_numeric_field_type(ftype: str) -> bool:
    """判断 CRM 字段类型是否为数值类型。"""
    if not ftype:
        return False
    t = str(ftype).lower().strip()
    return t in (
        'number', 'int', 'integer', 'float', 'double', 'decimal',
        'currency', 'percent', 'bigint', 'smallint', 'tinyint',
        'numeric', 'real', 'long',
    )


def get_mysql_type_for_field(ftype: str) -> str:
    """根据 CRM 字段类型返回 MySQL 列类型。数值 → DOUBLE，其余 → LONGTEXT。"""
    if is_numeric_field_type(ftype):
        return 'DOUBLE'
    return 'LONGTEXT'


def safe_numeric_value(val, ftype: str = ''):
    """将值安全转为数值类型用于写入 MySQL。非数值类型或无法转换时返回原值。

    Returns:
        float/int/None — 数值；str — 无法转换时的原字符串；None — 空值
    """
    if val is None or val == '':
        return None
    if not is_numeric_field_type(ftype):
        return str(val) if val is not None else ''
    try:
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            stripped = val.strip()
            if not stripped:
                return None
            return float(stripped)
        return float(val)
    except (ValueError, TypeError):
        return str(val) if val is not None else ''
