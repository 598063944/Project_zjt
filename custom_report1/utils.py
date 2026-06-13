"""
工具函数

字段标签映射、类型推断、名称清理等
"""

import re
import json
from decimal import Decimal
from datetime import datetime, date
from typing import Optional


# ==================== JSON 序列化辅助 ====================

def json_dumps_safe(obj, **kwargs) -> str:
    """安全的 json.dumps，自动转换 Decimal/datetime 等非标准类型"""
    def _default(o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime, date)):
            return str(o)
        if isinstance(o, bytes):
            return o.decode('utf-8', errors='replace')
        raise TypeError(f'Object of type {o.__class__.__name__} is not JSON serializable')
    return json.dumps(obj, default=_default, **kwargs)


# ==================== 字段标签映射 ====================

_COMMON_FIELD_LABELS = {
    '_id': '数据ID',
    'id': 'ID',
    'name': '名称',
    'create_time': '创建时间',
    'submit_time': '提交时间',
    'last_modified_time': '最后修改时间',
    'created_by': '创建人ID',
    'created_by__r': '创建人',
    'created_by_name': '创建人',
    'owner': '负责人ID',
    'owner__r': '负责人',
    'owner_name': '负责人',
    'account_id': '客户ID',
    'account_id__r': '客户名称',
    'contact_id': '联系人ID',
    'contact_id__r': '客户联系人',
    'record_type': '业务类型',
    'life_status': '生命状态',
    'remark': '备注',
    'description': '描述',
    'amount': '金额',
    'price': '单价',
    'quantity': '数量',
    'status': '状态',
    'stage': '阶段',
    'source': '来源',
    'mobile': '手机',
    'phone': '电话',
    'address': '地址',
    'code': '编码',
    'number': '编号',
    'date': '日期',
    'time': '时间',
    'type': '类型',
}


def guess_field_label(field_name: str) -> str:
    """根据 API 字段名猜测中文显示名"""
    field_name = str(field_name or '').strip()
    if not field_name:
        return ''

    # 精确匹配
    if field_name in _COMMON_FIELD_LABELS:
        return _COMMON_FIELD_LABELS[field_name]

    # 去掉后缀
    normalized = field_name
    for suffix in ('__r', '__c'):
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]

    # 关键词匹配
    keyword_map = [
        ('create', '创建'), ('modified', '修改'), ('submit', '提交'),
        ('owner', '负责人'), ('account', '客户'), ('customer', '客户'),
        ('contact', '联系人'), ('mobile', '手机'), ('phone', '电话'),
        ('address', '地址'), ('amount', '金额'), ('price', '价格'),
        ('quantity', '数量'), ('status', '状态'), ('stage', '阶段'),
        ('source', '来源'), ('remark', '备注'), ('description', '描述'),
        ('date', '日期'), ('time', '时间'), ('type', '类型'), ('name', '名称'),
        ('code', '编码'), ('number', '编号'), ('delivery', '发货'),
        ('product', '产品'), ('order', '订单'), ('project', '项目'),
    ]
    lower = normalized.lower()
    for kw, label in keyword_map:
        if kw in lower:
            return label

    if field_name.startswith('field_'):
        return f"自定义字段({field_name})"

    return field_name


def build_field_labels(field_names: list[str],
                       object_labels: dict = None,
                       custom_config: dict = None) -> dict[str, str]:
    """
    为一组字段名构建中文标签映射

    Args:
        field_names: API 字段名列表
        object_labels: 对象特定的标签映射 {(key: label)}
        custom_config: 用户自定义的标签映射

    Returns:
        {field_name: display_label}
    """
    result = {}
    label_usage = {}  # 检测重复标签

    for key in field_names:
        # 优先级: 自定义 > 对象特定 > 通用猜测
        if custom_config and key in custom_config:
            label = custom_config[key]
        elif object_labels and key in object_labels:
            label = object_labels[key]
        else:
            label = guess_field_label(key)

        # 去重处理
        if label in label_usage:
            label_usage[label] += 1
            result[key] = f"{label}({key})"
        else:
            label_usage[label] = 1
            result[key] = label

    return result


# ==================== 名称清理 ====================

_SAFE_IDENT_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def safe_sql_ident(name: str) -> str:
    """检查 SQL 标识符是否安全"""
    if not _SAFE_IDENT_RE.match(name):
        raise ValueError(f"非法的 SQL 标识符: {name}")
    return name


def safe_table_name(name: str) -> str:
    """清理表名，只保留安全字符"""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name)


# ==================== 时间戳转换 ====================

def ts_to_datetime(ts_value) -> Optional[str]:
    """Unix 毫秒时间戳 → yyyy-mm-dd HH:MM:SS"""
    if ts_value is None:
        return None
    try:
        from datetime import datetime
        ts = float(ts_value)
        if ts <= 0:
            return str(ts_value)
        if ts > 1e14:
            ts = ts / 1000000
        elif ts > 1e11:
            ts = ts / 1000
        dt = datetime.fromtimestamp(ts)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, OSError, OverflowError):
        return str(ts_value)


def date_str_to_ts(date_str: str, end_of_day: bool = False) -> int:
    """yyyy-mm-dd → Unix 毫秒时间戳"""
    from datetime import datetime
    try:
        dt = datetime.strptime(date_str.strip(), '%Y-%m-%d')
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0
