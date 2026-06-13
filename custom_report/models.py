"""
自定义报表数据模型

ReportDefinition 是一份报表的完整定义，包含:
- 基本信息 (名称、主表)
- JOIN 关系 (哪些表、怎么连)
- 显示列 (哪些字段、显示名)
- 筛选条件
- 画布布局
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import uuid
import json


# ==================== 枚举 ====================

class JoinType(Enum):
    """两张表之间的 JOIN 方式"""
    LEFT_JOIN = "left"           # 保留左表所有行，匹配不到填 NULL
    INNER_JOIN = "inner"         # 只保留两表都匹配成功的行
    ONE_TO_ONE = "one_to_one"    # 一对一：匹配到多行时只取第一条（不膨胀）

    @classmethod
    def from_str(cls, s: str):
        for m in cls:
            if m.value == s:
                return m
        return cls.LEFT_JOIN


class MultiMatchStrategy(Enum):
    """当关联表匹配到多行时的处理策略"""
    EXPAND = "expand"      # 展开为多行（默认，类似 SQL JOIN）
    FIRST = "first"        # 只取第一条匹配
    CONCAT = "concat"      # 拼接为字符串（用分隔符连接）
    COUNT = "count"        # 计数
    SUM = "sum"            # 求和（仅数字字段）
    AVG = "avg"            # 平均值（仅数字字段）

    @classmethod
    def from_str(cls, s: str):
        for m in cls:
            if m.value == s:
                return m
        return cls.EXPAND


class FilterOperator(Enum):
    # 文本操作符
    EQ = "EQ"
    NEQ = "NEQ"
    CONTAINS = "CONTAINS"
    NOT_CONTAINS = "NOT_CONTAINS"
    IN = "IN"
    NOT_IN = "NOT_IN"
    GT = "GT"
    LT = "LT"
    GTE = "GTE"
    LTE = "LTE"
    EMPTY = "EMPTY"
    NOT_EMPTY = "NOT_EMPTY"
    STARTS_WITH = "STARTS_WITH"
    ENDS_WITH = "ENDS_WITH"
    # 日期操作符
    DATE_BEFORE = "DATE_BEFORE"
    DATE_AFTER = "DATE_AFTER"
    DATE_BEFORE_EQ = "DATE_BEFORE_EQ"
    DATE_AFTER_EQ = "DATE_AFTER_EQ"
    DATE_RANGE = "DATE_RANGE"
    PAST_N_DAYS_EXCLUSIVE = "PAST_N_DAYS_EXCLUSIVE"
    PAST_N_DAYS_INCLUSIVE = "PAST_N_DAYS_INCLUSIVE"
    FUTURE_N_DAYS_EXCLUSIVE = "FUTURE_N_DAYS_EXCLUSIVE"
    FUTURE_N_DAYS_INCLUSIVE = "FUTURE_N_DAYS_INCLUSIVE"
    PAST_N_WEEKS_EXCLUSIVE = "PAST_N_WEEKS_EXCLUSIVE"
    PAST_N_WEEKS_INCLUSIVE = "PAST_N_WEEKS_INCLUSIVE"
    FUTURE_N_WEEKS_EXCLUSIVE = "FUTURE_N_WEEKS_EXCLUSIVE"
    FUTURE_N_WEEKS_INCLUSIVE = "FUTURE_N_WEEKS_INCLUSIVE"
    PAST_N_MONTHS_EXCLUSIVE = "PAST_N_MONTHS_EXCLUSIVE"
    PAST_N_MONTHS_INCLUSIVE = "PAST_N_MONTHS_INCLUSIVE"
    FUTURE_N_MONTHS_EXCLUSIVE = "FUTURE_N_MONTHS_EXCLUSIVE"
    FUTURE_N_MONTHS_INCLUSIVE = "FUTURE_N_MONTHS_INCLUSIVE"
    PAST_N_QUARTERS_INCLUSIVE = "PAST_N_QUARTERS_INCLUSIVE"
    N_DAYS_AGO = "N_DAYS_AGO"
    N_DAYS_LATER = "N_DAYS_LATER"
    N_WEEKS_AGO = "N_WEEKS_AGO"
    N_WEEKS_LATER = "N_WEEKS_LATER"

    @classmethod
    def from_str(cls, s: str):
        for m in cls:
            if m.value == s:
                return m
        return cls.EQ


# ==================== 核心数据模型 ====================

@dataclass
class MatchKey:
    """单个匹配键：两表之间一对字段的关联"""
    left_field: str          # 左表字段 API 名（如 sales_order_id）
    right_field: str         # 右表字段 API 名（如 order_id）


@dataclass
class JoinDefinition:
    """两张表之间的拼表关系"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    left_object_api: str = ""          # 左表对象 API 名
    right_object_api: str = ""         # 右表对象 API 名
    match_keys: list = field(default_factory=list)    # list[MatchKey]
    join_type: str = "left"            # left / inner / one_to_one
    multi_match: str = "expand"        # expand / first / concat / count / sum / avg
    concat_separator: str = "、"

    def __post_init__(self):
        # 反序列化时 match_keys 可能是 dict 列表，转为 MatchKey 对象
        if self.match_keys and isinstance(self.match_keys[0], dict):
            self.match_keys = [MatchKey(**m) if isinstance(m, dict) else m for m in self.match_keys]


@dataclass
class FieldColumn:
    """报表中的一个显示列"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    display_name: str = ""             # 列显示名（中文表头）
    source_object_api: str = ""        # 字段来源对象 API 名
    source_field: str = ""             # 字段 API 名
    visible: bool = True               # 是否在预览/结果表中显示
    sort_order: int = 0                # 列顺序
    column_width: Optional[int] = None
    # 计算字段（Excel 风格）
    computation_type: str = "direct"   # "direct" | "aggregate" | "formula" | "address_extract" | "date_part"
    aggregate_func: str = ""           # "SUM" | "AVG" | "COUNT" | "MAX" | "MIN"
    formula_expression: str = ""       # 如 "=单价*数量", "=IF(金额>1000, '大额', '小额')"
    # 字段格式（MySQL 存储类型），默认文本
    field_format: str = "text"         # "text" | "integer" | "float" | "currency" | "date_ymd" | "date_ymd_cn" | "datetime" | "time"
    # 地址提取字段
    address_source_fields: list = field(default_factory=list)
    # 候选列显示名列表，最多 5 个，按优先级排列
    address_target_level: str = ""     # "province" | "province_short" | "city" | "area"
    # 日期成分提取字段
    date_part_source_field: str = ""   # 源日期字段 API 名（如 create_time）
    date_part_unit: str = ""           # "year" | "month" | "week" | "quarter"


@dataclass
class FilterCondition:
    """行级筛选条件"""
    field_api: str = ""                # 筛选字段 API 名
    operator: str = "EQ"              # 操作符（支持文字和日期操作符）
    value: str = ""
    target_object_api: str = ""       # 筛选字段所属对象（默认主表）
    field_label: str = ""             # 字段中文显示名
    expose: bool = False              # "外露"标记
    is_date_field: bool = False       # 是否为日期字段


@dataclass
class ReportDefinition:
    """一份报表的完整定义"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "未命名报表"
    description: str = ""

    # 拼表定义
    main_object_api: str = ""
    joins: list = field(default_factory=list)          # list[JoinDefinition]

    # 显示列
    columns: list = field(default_factory=list)         # list[FieldColumn]

    # 筛选
    filters: list = field(default_factory=list)         # list[FilterCondition]
    date_range_enabled: bool = False
    date_field: str = "create_time"
    date_start: str = ""
    date_end: str = ""

    # 画布布局（记录每张卡片的位置，用于还原）
    canvas_positions: dict = field(default_factory=dict)
    # {"NewOpportunityObj": (100.0, 200.0), "DeliveryNoteObj": (450.0, 200.0)}

    # 分组与汇总（Excel 风格聚合）
    group_by_fields: list = field(default_factory=list)   # ["field_api_1", ...]
    show_summary_row: bool = False                         # 预览表底部显示汇总行

    # 文件夹（报表分类管理）
    folder_path: str = ""              # 文件夹路径，如 ""（根目录）、"销售报表"、"销售/月度"

    # 元信息
    created_at: str = ""
    modified_at: str = ""
    version: int = 1

    # 结果表信息
    result_table_name: str = ""        # cr_{id}
    result_row_count: int = 0
    last_refresh_time: str = ""

    # 写入方式
    write_mode: str = "overwrite"      # "overwrite" (覆盖) | "incremental" (增量)

    # 同步主键配置（多字段拼接）
    sync_id_fields: list = field(default_factory=list)   # 列显示名列表，如 ["销售订单号", "发货单号"]
    sync_id_separator: str = "_"                          # 拼接分隔符

    def __post_init__(self):
        # 反序列化时修复嵌套对象类型
        if self.joins and isinstance(self.joins[0], dict):
            self.joins = [JoinDefinition(**j) if isinstance(j, dict) else j for j in self.joins]
        if self.columns and isinstance(self.columns[0], dict):
            self.columns = [FieldColumn(**c) if isinstance(c, dict) else c for c in self.columns]
        if self.filters and isinstance(self.filters[0], dict):
            self.filters = [FilterCondition(**f) if isinstance(f, dict) else f for f in self.filters]

    def to_dict(self) -> dict:
        """序列化为可 JSON 存储的 dict"""
        return _serialize(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ReportDefinition":
        """从 dict 反序列化"""
        return cls(**_deserialize_report(data))

    @property
    def source_table_name(self) -> str:
        """主表对应的 MySQL source 表名"""
        return f"sr_{self.main_object_api}"

    @property
    def result_table(self) -> str:
        """结果表名"""
        return self.result_table_name or f"cr_{self.id}"

    def get_object_apis(self) -> list[str]:
        """获取报表涉及的所有对象 API 名"""
        apis = [self.main_object_api] if self.main_object_api else []
        for j in self.joins:
            jd = j if isinstance(j, JoinDefinition) else JoinDefinition(**j)
            for api in (jd.left_object_api, jd.right_object_api):
                if api and api not in apis:
                    apis.append(api)
        return apis


# ==================== 序列化辅助 ====================

def _serialize(obj):
    """递归转换 dataclass/dict/list 为纯 dict"""
    if isinstance(obj, list):
        return [_serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if hasattr(obj, '__dataclass_fields__'):
        result = {}
        for k, v in asdict(obj).items():
            vv = getattr(obj, k, None)
            if isinstance(vv, list):
                result[k] = [_serialize(item) for item in vv]
            elif isinstance(vv, dict):
                result[k] = {kk: _serialize(vv) for kk, vv in vv.items()}
            elif hasattr(vv, '__dataclass_fields__'):
                result[k] = _serialize(vv)
            else:
                result[k] = v
        return result
    return obj


def _deserialize_report(data: dict) -> dict:
    """将 dict 转为 ReportDefinition 构造函数参数"""
    result = {}
    for k, v in data.items():
        if k == 'joins':
            result[k] = [JoinDefinition(**j) if isinstance(j, dict) else j for j in (v or [])]
        elif k == 'columns':
            result[k] = [FieldColumn(**c) if isinstance(c, dict) else c for c in (v or [])]
        elif k == 'filters':
            result[k] = [FilterCondition(**f) if isinstance(f, dict) else f for f in (v or [])]
        else:
            result[k] = v
    return result
