# 列表页面筛选器代码合并方案

## 一、现状分析

### 1.1 三类筛选器定义

| 类别 | 说明 | 涉及文件 |
|------|------|----------|
| **列表页面筛选器** | CRM订单、商机、对象查询页面的多条件筛选面板 + 搜索栏 | `order_to_contract.py`, `object_query.py` |
| **从CRM获取数据的筛选器** | 与第1类高度重叠，筛选数据来自CRM API | 同上 |
| **自定义报表筛选器** | 自定义报表编辑器中的筛选弹窗 | `Project_zjt_3.5.8.py`, `common.py` |

### 1.2 重复代码分布

| 文件:位置 | 类名/方法名 | 行数 | 类型 | 与谁重复 |
|-----------|-----------|------|------|---------|
| `common.py:5053-5325` | `CustomReportFilterDialog` | ~270 | 弹窗 | 与主文件**完全一致** |
| `Project_zjt_3.5.8.py:5217-5488` | `CustomReportFilterDialog` | ~270 | 弹窗 | 与common.py**完全一致** |
| `order_to_contract.py:5495-5684` | `_add_crm_condition_row` | ~190 | 行构建 | 与opp/obj_q 70%相同 |
| `order_to_contract.py:547-783` | `_add_opp_condition_row` | ~236 | 行构建 | 与crm/obj_q 70%相同 |
| `object_query.py:2279-2442` | `_add_obj_query_condition_row` | ~163 | 行构建 | 与crm/opp 70%相同 |
| `order_to_contract.py:5687-5827` | `_remove/clear/collect_crm` | ~140 | 辅助 | 逻辑相同 |
| `object_query.py:2572-2622` | `_remove/clear/collect_obj` | ~110 | 辅助 | 逻辑相同 |
| `order_to_contract.py:547-783` | `_remove/clear/collect_opp` | ~110 | 辅助 | 逻辑相同 |

**总计重复代码：约 800-1100 行**（排除差异化的搜索栏、预设管理等非重复部分）

### 1.3 各实现差异对比

| 差异维度 | CRM订单 | 商机 | 对象查询 | 自定义报表弹窗 | filter_bar.py(参考) |
|----------|---------|------|----------|--------------|-------------------|
| 字段来源 | `_build_crm_field_label_list()` | `_get_opp_filter_headers()` | `obj_query_search_field` combo | `fields` 参数 | `set_available_fields()` |
| 文本操作符 | ~18个 | ~6个 | ~9个 | 12个(类常量) | ~14个 |
| 日期操作符 | ~10个(含past_n) | ~7个 | ~10个(含past_n) | 无 | ~26个(含quarters) |
| value_stack页面 | 0:text,1:date,2:range,3:spin | 0:text,1:date,2:range | 0:text,1:date,2:range,3:spin | 0:text,1:date | 0:text,1:date,2:range,3:spin,4:multi |
| 外露checkbox | ✓ | ✓ | ✓ | ✗ | ✗ |
| 多选picker | ✗(CRM行无) | ✗ | config-based | parent-delegated | config+DB fallback |
| 防抖时间 | 200ms | 300ms共享 | 250ms共享 | 无 | 300ms/row |
| 面板模式 | 内嵌弹窗 | 内嵌弹窗 | 内嵌 | Dialog弹窗 | 内嵌 |
| 预设管理 | ✓(完整) | ✓(简单) | ✓ | ✗ | ✗ |
| api_key输出 | ✓ | ✗ | ✗ | ✗ | target_object_api |
| QCompleter | ✓ | ✗ | ✗ | ✗ | ✓ |

### 1.4 依赖关系

```
Project_zjt_3.5.8.py (主程序)
├── from common import *          ← 通过 core.py 间接导入（core.py:694 有字段定义）
├── from order_to_contract import *   ← Mixin，类MainFrame多重继承
├── from object_query import *        ← Mixin，类MainFrame多重继承

order_to_contract.py:
├── from common import *          ← 使用 CenteredPopupDialog, QuickDatePickerDialog 等公共组件
object_query.py:
├── from common import *          ← 使用 show_multi_select_dropdown, _DialogOutsideCloseFilter 等
```

**关键发现：**
- `common.py` 已被所有使用者导入（`from common import *`）
- `common.py` 的模块描述（第6行）已声明 `筛选器组件（FilterBar / 条件行 / 预设管理）` 是其职责之一
- `common.py:5053` 的 `CustomReportFilterDialog` 与 `Project_zjt_3.5.8.py:5217` 是完全重复
- 主程序不直接导入 `common`，但 Mixin 都导入了；主程序通过多重继承合并所有 Mixin

---

## 二、合并方案

### 2.1 总体策略

**在 `common.py` 中构建两个核心基类：**

1. **`FilterConditionRow`** — 单行筛选条件的构建与管理（最小复用单元）
2. **`FilterPanel`** — 多行筛选面板，基于 `FilterConditionRow` 组合

然后将现有的 5 个重复实现逐步替换为使用这两个基类。

### 2.2 模块架构

```
common.py
├── 基础层（已有，保留不变）
│   ├── CenteredPopupDialog       ← 弹窗基类
│   ├── _DialogOutsideCloseFilter ← 外部点击关闭
│   └── QuickDatePickerDialog     ← 日期范围选择
│
├── 【新增】FilterConditionRow(QFrame)     ← 单行筛选条件
│   ├── 可配置：字段列表、操作符列表、value_stack页面配置
│   ├── 公共信号：filtersChanged, rowRemoved
│   ├── 公共方法：set_field(), set_operator(), set_value(), get_condition()
│   └── 子组件：field_combo, op_combo, value_stack(含text/date/range/spin), picker_btn, expose_check
│
├── 【新增】FilterPanel(QWidget)           ← 多行筛选面板
│   ├── 管理多个 FilterConditionRow
│   ├── 公共信号：filtersChanged
│   ├── 公共方法：add_row(), remove_row(), clear_all(), get_conditions(), load_conditions()
│   ├── 可选功能：外露标签栏、预设管理、搜索栏联动
│   └── 面板模式：内嵌 / 弹窗
│
├── 【保留】CustomReportFilterDialog ← 修改为继承 FilterPanel 或组合使用
│
└── 【保留】FieldSettingsDialog ← 不受影响
```

### 2.3 详细设计

#### 2.3.1 `FilterConditionRow` — 单行筛选条件

```python
class FilterConditionRow(QFrame):
    """单行筛选条件：字段 + 操作符 + 值 + [外露复选框]
    
    所有可配置项通过构造函数参数或setter注入，消除子类化需求。
    """

    # 信号
    filtersChanged = pyqtSignal()      # 值变化时发射
    rowRemoveRequested = pyqtSignal()  # 删除按钮点击

    def __init__(self, parent=None, *,
                 # ── 字段配置 ──
                 field_options: list = None,        # [(label, key), ...]
                 field_placeholder: str = "选择字段",
                 field_width: int = 140,
                 
                 # ── 操作符配置 ──
                 text_operators: list = None,       # [(label, key), ...]
                 date_operators: list = None,       # [(label, key), ...]
                 op_width: int = 95,
                 default_operator: str = "contains",
                 
                 # ── 值输入配置 ──
                 value_pages: tuple = ("text", "date", "date_range", "spin"),
                 value_stretch: bool = True,
                 
                 # ── 可选组件 ──
                 show_expose: bool = True,           # 是否显示"外露"复选框
                 show_picker: bool = True,            # 是否显示多选按钮
                 show_remove: bool = True,            # 是否显示删除按钮
                 
                 # ── 行为配置 ──
                 debounce_ms: int = 250,              # 值变化防抖时间
                 is_date_field_callback: callable = None,  # 判断字段是否为日期的回调
                 picker_callback: callable = None,    # 多选按钮点击回调
                 
                 # ── 样式配置 ──
                 row_height: int = 32,
                 **kwargs):
        super().__init__(parent)
        self._init_configs(...)   # 存储所有配置
        self._build_ui()          # 构建 UI
        self._connect_signals()   # 连接信号
```

##### 配置注入点设计（解决各使用者差异）

| 配置项 | CRM订单 | 商机 | 对象查询 | 自定义报表 |
|--------|---------|------|----------|-----------|
| `field_options` | `_build_crm_field_label_list()` | `_get_opp_filter_headers()` | search_field combo items | `fields` 参数 |
| `text_operators` | `_get_crm_text_operators()` | 6个简化版 | 9个 | OPERATORS类常量 |
| `date_operators` | `_get_crm_date_operators()` | 7个 | 10个 | 无(不启用date页面) |
| `value_pages` | ("text", "date", "date_range", "spin") | ("text", "date", "date_range") | ("text", "date", "date_range", "spin") | ("text", "date") |
| `show_expose` | True | True | True | False |
| `show_picker` | False(CRM行) | False | True(config) | True(parent) |
| `debounce_ms` | 200 | 300 | 250 | 0(立即) |
| `is_date_field_callback` | `_is_crm_date_field()` | `_is_opp_date_field()` | `_get_obj_query_field_type()` | `self.date_fields` |
| `picker_callback` | None | None | `_on_obj_query_picker` | `_get_custom_report_field_value_options` |
| `field_width` | 150 | 140 | 140 | 180 |

##### 公共 API 方法

```python
    # ── 值存取 ──
    def get_condition(self) -> dict:
        """返回 {'field', 'operator', 'value', 'expose', 'is_date'}"""
        
    def set_condition(self, condition: dict):
        """从条件字典恢复UI状态"""
    
    def clear_value(self):
        """清空当前值（保留字段和操作符）"""
    
    # ── UI 更新 ──
    def set_field_options(self, options: list):
        """重新设置字段选项列表"""
    
    def update_input_mode(self):
        """根据当前字段类型自动切换输入模式（文本/日期/日期范围/数字）"""
    
    # ── 显示控制 ──
    def set_expose_visible(self, visible: bool):
    def set_picker_visible(self, visible: bool):
```

##### 内部实现要点

1. **value_stack 统一布局（索引规范）**：
   - 0 = 文本输入 (QLineEdit)
   - 1 = 单日期选择 (QDateEdit, CalendarPopup)
   - 2 = 日期范围按钮 (QPushButton, 打开日期范围对话框)
   - 3 = 数字微调 (QSpinBox, 用于N天/月等)
   - 4 = 多选下拉 (QComboBox, 可选)
   - `value_pages` 参数控制哪些页面被创建

2. **操作符切换逻辑统一化**：
   ```python
   def _on_operator_changed(self, idx):
       op = self.op_combo.currentData()
       # 统一的操作符→页面映射
       if op in ("empty", "not_empty"):
           self.value_stack.hide()
       elif op == "date_range":
           self.value_stack.setCurrentIndex(2)
           self.value_stack.show()
       elif op in self._N_TYPE_OPS:  # 过去/未来N天等
           self.value_stack.setCurrentIndex(3)
           self.value_stack.show()
       elif self._is_date_op():
           self.value_stack.setCurrentIndex(1)
           self.value_stack.show()
       else:
           self.value_stack.setCurrentIndex(0)
           self.value_stack.show()
   ```

3. **防抖机制统一化**：
   - 每个实例内部维护一个 `QTimer(singleShot=True, interval=debounce_ms)`
   - 输入变化 → `timer.start()` → timeout → emit `filtersChanged`
   - `debounce_ms=0` 时不创建timer，直接emit

4. **日期范围解析统一化**：
   ```python
   @staticmethod
   def parse_date_range(value: str) -> tuple:
       """'2024-01-01 ~ 2024-06-30' → (QDate, QDate) or (None, None)"""
   @staticmethod
   def format_date_range(start: QDate, end: QDate) -> str:
       """(QDate, QDate) → '2024-01-01 ~ 2024-06-30'"""
   ```

---

#### 2.3.2 `FilterPanel` — 多行筛选面板

```python
class FilterPanel(QWidget):
    """多行筛选条件面板：管理多个 FilterConditionRow，支持预设保存/加载"""

    filtersChanged = pyqtSignal()     # 任何行值变化时发射
    
    def __init__(self, parent=None, *,
                 # ── 面板模式 ──
                 mode: str = "inline",        # "inline" | "popup"
                 
                 # ── 条件行默认配置 ──
                 row_defaults: dict = None,    # 传给每个 FilterConditionRow 的默认参数
                 
                 # ── 面板 UI ──
                 title: str = "设置筛选",
                 show_add_btn: bool = True,
                 show_clear_btn: bool = True,
                 show_apply_btn: bool = True,
                 show_save_btn: bool = False,
                 show_exposed_tags: bool = False,  # 是否显示"外露"标签栏
                 max_condition_rows: int = 20,
                 
                 # ── 扩展回调 ──
                 on_save_preset: callable = None,   # 保存预设回调
                 on_load_preset: callable = None,   # 加载预设回调
                 **kwargs):
```

##### 三种面板模式

| 模式 | 说明 | 使用场景 |
|------|------|---------|
| `"inline"` | 内嵌面板，初始隐藏，toggle显示 | CRM订单、商机、对象查询的筛选面板 |
| `"embedded"` | 始终可见，如filter_bar.py作为编辑器的一部分 | 自定义报表编辑器 |
| `"popup"` | 独立弹窗，继承自CenteredPopupDialog | 自定义报表弹窗筛选（替代CustomReportFilterDialog） |

##### 公共 API

```python
    # ── 行管理 ──
    def add_row(self, condition: dict = None) -> FilterConditionRow:
        """添加一行筛选条件，返回行对象"""
    
    def remove_row(self, row: FilterConditionRow):
        """移除指定行"""
    
    def clear_all(self):
        """清除所有条件"""
    
    # ── 值存取 ──
    def get_all_conditions(self) -> list[dict]:
        """获取所有行的条件列表"""
    
    def load_conditions(self, conditions: list[dict]):
        """从条件列表恢复到面板"""
    
    # ── 行级配置 ──
    def set_row_field_options(self, options: list):
        """批量更新所有行的字段选项"""
    
    def for_each_row(self, callback: callable):
        """遍历所有行"""
    
    # ── 外露标签 ──
    def refresh_exposed_tags(self):
        """刷新外露标签栏"""
    
    # ── 预设管理 ──
    def get_preset_data(self) -> list[dict]:
        """获取当前面板状态的持久化数据"""
    def load_preset_data(self, data: list[dict]):
        """从持久化数据恢复面板状态"""
```

##### 外露标签栏（Exposed Tags）

作为 FilterPanel 的可选子组件，统一 CRM 订单和商机的标签 UI：

```python
class ExposedTagsBar(QFrame):
    """外露筛选条件标签栏"""
    tagClicked = pyqtSignal(dict)      # 标签被点击，传递条件dict
    tagRemoved = pyqtSignal(dict)      # 标签被移除
    
    def refresh_from_rows(self, rows: list[FilterConditionRow]):
        """从条件行列表刷新标签显示"""
```

##### 与搜索栏联动（保持各页面差异化）

搜索栏（搜索字段combo + 搜索输入 + 日期范围搜索）**不纳入公共模块**，因为差异过大：
- CRM订单：全字段搜索 + 格式选择 + 字段显示 + 刷新 + 生成合同按钮
- 商机：简化的搜索框
- 对象查询：对象选择 + 搜索 + 快捷筛选标签

各页面保持自己的搜索栏布局，通过信号与 FilterPanel 交互。

---

#### 2.3.3 重构现有代码的步骤

##### 第一阶段：新建公共组件（不影响现有功能）

**Step 1:** 在 `common.py` 中新增 `FilterConditionRow` 类
- 位置：`common.py`，放在 `CustomReportFilterDialog` 之前（约第 5000 行处）
- 暂时不被任何代码使用，纯新增，零风险
- 约 350-400 行

**Step 2:** 在 `common.py` 中新增 `FilterPanel` 类
- 位置：紧接 `FilterConditionRow` 之后
- 同样暂时不被使用，纯新增
- 约 300-400 行

**Step 3:** 在 `common.py` 中新增 `ExposedTagsBar` 类
- 约 150 行
- 纯新增

**估计新增总行数：~900 行**

##### 第二阶段：替换重复实现（逐个验证）

**Step 4:** 替换 `CustomReportFilterDialog`（风险最低，独立弹窗）
- 位置：`common.py` 和 `Project_zjt_3.5.8.py`
- 改造方式：`CustomReportFilterDialog` 改为继承 `FilterPanel`（popup模式），或内部组合 `FilterPanel`
- 删除重复代码：~270行 × 2 = ~540行
- 新增适配代码：~50行
- **净减少：~490行**

**Step 5:** 替换对象查询筛选面板
- 位置：`object_query.py`
- 改造方式：创建 `FilterPanel(mode="inline", show_exposed_tags=True)` 实例，替换当前的 `obj_query_filter_panel` + `_add_obj_query_condition_row` 等方法
- 保持：搜索栏（`obj_query_search_field` + `obj_query_search_input`）+ 快捷筛选标签不变
- 删除重复代码：~450行
- 新增适配代码：~120行
- **净减少：~330行**

**Step 6:** 替换 CRM 订单筛选面板
- 位置：`order_to_contract.py`
- 改造方式：`_build_crm_filter_bar` 中的筛选面板部分改用 `FilterPanel`，条件行构建逻辑删除
- 保持：搜索栏（字段选择 + 文本/日期搜索）+ 格式选择 + 操作按钮不变
- 删除重复代码：~400行
- 新增适配代码：~150行
- **净减少：~250行**

**Step 7:** 替换商机筛选面板
- 位置：`order_to_contract.py`
- 改造方式：与CRM订单类似，创建独立的 `FilterPanel` 实例
- 删除重复代码：~350行
- 新增适配代码：~100行
- **净减少：~250行**

##### 总净减少代码量估计

| 阶段 | 新增 | 删除 | 净变化 |
|------|------|------|--------|
| Step 1-3 (新建公共组件) | +900 | 0 | +900 |
| Step 4 (自定义报表弹窗) | +50 | -540 | -490 |
| Step 5 (对象查询) | +120 | -450 | -330 |
| Step 6 (CRM订单) | +150 | -400 | -250 |
| Step 7 (商机) | +100 | -350 | -250 |
| **合计** | **+1320** | **-1740** | **-420行** |

---

### 2.4 兼容性保障措施

#### 2.4.1 零破坏原则
- **纯新增阶段（Step 1-3）**：只添加类定义，不修改任何现有代码
- **逐个替换（Step 4-7）**：每次只替换一个页面，替换后完整回归测试
- **旧的 public API 保持**：如果外部代码依赖某些方法的签名，保留兼容层

#### 2.4.2 接口兼容层
对每个替换的页面，保留旧的方法签名作为 `FilterPanel` 的包装：

```python
# object_query.py 中的兼容层示例
def _add_obj_query_condition_row(self, condition=None):
    """[兼容] 委托给 FilterPanel"""
    return self._filter_panel.add_row(condition)

def _collect_obj_query_conditions(self):
    """[兼容] 委托给 FilterPanel"""
    return self._filter_panel.get_all_conditions()
```

#### 2.4.3 配置字典模式
使用配置字典而非固定参数，保证未来扩展性：

```python
CRM_FILTER_ROW_CONFIG = {
    "field_options": [],  # 由调用方动态设置
    "text_operators": _get_crm_text_operators(),
    "date_operators": _get_crm_date_operators(),
    "value_pages": ("text", "date", "date_range", "spin"),
    "show_expose": True,
    "show_picker": False,
    "debounce_ms": 200,
    "field_width": 150,
}
```

#### 2.4.4 分阶段开关
新增环境变量/配置项控制是否使用新组件，便于回退：

```python
# .config/app_settings.json
{
    "use_new_filter_panel": true  // false 时回退到旧代码
}
```

每个替换点：

```python
if self.config.get('app_settings', {}).get('use_new_filter_panel', True):
    self._init_new_filter_panel()
else:
    self._init_legacy_filter_panel()  # 保留旧代码作为回退
```

#### 2.4.5 测试验证清单
每阶段替换后需验证：

| 验证项 | Step4 | Step5 | Step6 | Step7 |
|--------|-------|-------|-------|-------|
| 添加筛选条件 | ✓ | ✓ | ✓ | ✓ |
| 删除单行条件 | ✓ | ✓ | ✓ | ✓ |
| 清除所有条件 | ✓ | ✓ | ✓ | ✓ |
| 文本操作符切换 | ✓ | ✓ | ✓ | ✓ |
| 日期操作符 + 日期选择器 | N/A | ✓ | ✓ | ✓ |
| 日期范围选择 | N/A | ✓ | ✓ | ✓ |
| N天/月/周 数字输入 | N/A | ✓ | ✓ | N/A |
| "外露"复选框 + 标签显示 | N/A | ✓ | ✓ | ✓ |
| 多选下拉 picker | ✓ | ✓ | N/A | N/A |
| 筛选结果正确性 | ✓ | ✓ | ✓ | ✓ |
| 预设保存/加载 | N/A | ✓ | ✓ | ✓ |
| 搜索栏联动 | N/A | ✓ | ✓ | ✓ |
| 输入法(IME)兼容性 | ✓ | ✓ | ✓ | ✓ |
| 点击外部关闭面板 | N/A | ✓ | ✓ | ✓ |
| 分页重置 | ✓ | ✓ | ✓ | ✓ |
| 数据刷新后筛选保持 | ✓ | ✓ | ✓ | ✓ |

---

### 2.5 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `common.py` | **新增大段** | 新增 `FilterConditionRow`(~400行)、`FilterPanel`(~400行)、`ExposedTagsBar`(~150行) |
| `common.py` | **修改** | `CustomReportFilterDialog` 改为继承/组合 `FilterPanel`(~50行变更) |
| `Project_zjt_3.5.8.py` | **删除** | 删除 `CustomReportFilterDialog`(~270行)，改为从 `common` 导入 |
| `order_to_contract.py` | **修改** | `_add_crm_condition_row` 等方法改为委托给 `FilterPanel`，保留搜索栏 |
| `order_to_contract.py` | **修改** | `_add_opp_condition_row` 等方法改为委托给 `FilterPanel` |
| `object_query.py` | **修改** | `_add_obj_query_condition_row` 等方法改为委托给 `FilterPanel` |
| `custom_report_backup/views/filter_bar.py` | **不变** | 作为参考实现的备份，暂不修改 |

### 2.6 不纳入统一模块的部分（保持差异化）

以下功能由于各页面差异过大，不纳入公共模块：

1. **搜索栏布局**（`_build_crm_filter_bar` 中的 top_row）：各页面按钮/控件组合差异大
2. **CRM API 过滤器构建**（`_build_obj_query_api_filters`、`_build_crm_api_filters`）：输出格式不同
3. **预设管理UI**（`_show_crm_filter_preset_popup`、`_save_crm_filter_preset`）：UI和存储方式不同
4. **机会特有逻辑**（`_adjust_opp_filter_panel_size`）：动态面板尺寸调整
5. **对象查询特有的快捷筛选标签**（`_rebuild_quick_filter_tags`）：与筛选面板不同体系

---

## 三、实施时间线与建议

### 建议实施顺序

```
Phase 1 ──── Phase 2 ──── Phase 3 ──── Phase 4
[公共组件]   [弹窗替换]   [内嵌面板]   [收尾清理]
  2-3天        1天         2-3天        1天
```

| 阶段 | 内容 | 风险 | 验收标准 |
|------|------|------|---------|
| Phase 1 | 在 `common.py` 新增三个类 | **极低**（纯新增） | 代码可正常 import |
| Phase 2 | 替换 `CustomReportFilterDialog` | **低**（独立弹窗） | 自定义报表筛选功能正常 |
| Phase 3 | 替换对象查询筛选面板 | **中**（涉及搜索联动） | 对象查询筛选正确 |
| Phase 4 | 替换CRM/商机筛选面板 | **中**（功能最复杂） | CRM订单、商机筛选正确 |
| Phase 5 | 删除旧代码，移除兼容开关 | **低** | 代码清洁，无死代码 |

---

## 四、风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|---------|
| 信号连接不完整，筛选不生效 | 中 | 高 | 每个替换阶段保留旧代码回退开关 |
| IME 输入法兼容性问题 | 中 | 中 | 保留 debounce 机制，PopupCompletion 模式 |
| 日期范围属性名冲突 | 低 | 低 | 统一使用 `date_range` 属性名 |
| 性能退化（信号过多） | 低 | 中 | 保留 debounce 机制，避免重复查询 |
| CRM API 过滤格式不兼容 | 中 | 高 | API 过滤器构建保留在各页面，仅 UI 层统一 |

---

## 五、总结

| 指标 | 数值 |
|------|------|
| 重复代码总量 | ~800-1100 行（分布5处） |
| 新增公共代码 | ~900 行（一次性） |
| 删除重复代码 | ~1740 行 |
| 净减少代码 | ~420 行 |
| 重复率降低 | 筛选器条件行代码从 ~85% 重复 → ~0% |
| 涉及文件 | 3 个（common.py, order_to_contract.py, object_query.py） |
| 预计工期 | 5-8 天 |
| 对现有功能影响 | 零（分阶段实施 + 回退开关） |

### 核心收益

1. **一处修改，全局生效**：后续修复 bug 或新增筛选操作符只需改 `common.py`
2. **新页面开发成本降低**：任何需要筛选面板的新页面，只需一行 `FilterPanel(...)`
3. **UI 一致性**：所有筛选面板的样式、行为、操作符统一
4. **可测试性提升**：公共组件可独立单元测试
 
 ## 更新说明（2026-06-13）
 
 **已完成的工作：**
 - Phase 1（新增公用组件 FilterConditionRow / FilterPanel / ExposedTagsBar）：已在 common.py 完成
 - 主程序与 common.py 类去重：17 个重复类已统一为 `from common import ...`
 - Mixin 方法去重：MainFrame 中 494 个重复方法已删除，依靠 MRO 继承使用模块版本
 - 死代码清理：简化版 ReportListPage 已删除（460 行）
 
 **仍需完成的后续工作：**
 - Phase 2-4（FilterPanel 替换现有实现）：object_query.py / order_to_contract.py / file_generation.py 中的条件行方法仍在使用自有实现，未迁移到 FilterPanel。这因测试复杂度较高而推迟。
