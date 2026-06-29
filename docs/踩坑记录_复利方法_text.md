# 踩坑记录 - 复利方法

---

## 2026-06-18 QTableWidget 列序号读反导致显示名称与API名称互换

### 背景

CRM设置 → 订单设置页，有一个字段映射列表表格 `crm_field_mapping_list_table`，两列：
- 列0 = **显示名称**（中文标签，如"订单产品类型"）
- 列1 = **API名称**（字段标识，如"field_jv2dq__c"）

### 踩坑经过

1. 用户反馈：切换地址Excel后，字段映射列表的"显示名称"和"API名称"两列内容互换了。
2. 排查发现：`save_settings` 函数（行24516）读取表格时，把列0当作`api_name`、列1当作`display_name`，与表头定义**完全相反**。
3. 切换地址Excel触发 `apply_settings_immediately({'crm'})`，会调用保存逻辑，此时写入配置文件的值就已经是反的了。
4. 下次加载时按正确列序读取，结果用户看到的就是两列内容互换。

### 根因

表头定义 `["显示名称", "API名称"]`（列0=显示名称，列1=API名称），但保存代码写反了：
```python
# ❌ 错误写法
api_item = table.item(row, 0)       # 实际读到的是显示名称
display_item = table.item(row, 1)   # 实际读到的是API名称

# ✅ 正确写法
display_item = table.item(row, 0)   # 列0 = 显示名称
api_item = table.item(row, 1)       # 列1 = API名称
```

### 同类排查

全量扫描了 `crm_field_mapping_list_table`（14处）和 `opp_field_mapping_list_table`（9处）共23处列读写，又发现 **1处同类问题**：

| 位置 | 函数 | 问题 |
|------|------|------|
| 行24516 | `save_settings` | `item(row, 0)`误读为api_name（本次触发bug的根源） |
| 行22095 | `_on_batch_paste_crm_field_values` | `item(current_row, 0)`误读为api_name，导致批量粘贴字段值时用显示名称做key查找配置 |

### 复利要点

> **凡是QTableWidget有多列的，写读取逻辑时必须核对列序号与表头的对应关系，不能凭变量名猜测列顺序。**

具体做法：
1. **写代码时**：在读取列的代码旁加注释标明该列对应的表头，如 `# 列0 = 显示名称`
2. **Code Review时**：对所有 `table.item(row, N)` 调用，逐一核对 N 是否与 `setHorizontalHeaderLabels` 的顺序一致
3. **排查此类bug时**：全文搜索所有对该表格的 `item(row, N)` 调用，逐一比对列号，防止遗漏

---

## 2026-06-18 商机筛选面板条件行不可见 + 搜索栏 NameError

### 背景

招投标授权页（商机页）有两个筛选功能：
- **工具栏搜索栏**：`opp_search_input` QLineEdit，输入文字后 300ms 防抖触发 `_apply_opp_filters()`
- **筛选条件面板**：点击"筛选"按钮弹出浮窗，内含多行条件（字段/操作符/值）

筛选面板的代码分布在三个文件：
- `pdf_watermark.py`：创建原始 QFrame（含按钮：另存为/添加条件/清除/筛选）
- `order_to_contract.py`：筛选逻辑方法 + FilterPanel 委托
- `Project_zjt_3.5.8.py`：防抖定时器接线

### 踩坑经过

**Bug 1 — 搜索栏 NameError：**
1. 用户在搜索栏输入文字，触发 `_apply_opp_filters()`
2. 方法内部引用了 `search_field` 变量（行713），但该变量从未定义
3. 原因：搜索字段下拉框在之前的重构中被移除（方法 `_refresh_opp_search_field_combo` 变为空壳），但 `_apply_opp_filters` 中的引用未清理
4. 结果：每次文本搜索都抛出 `NameError`，搜索栏完全失效

**Bug 2 — 筛选面板条件行不可见：**
1. 用户点击"筛选"按钮 → `_toggle_opportunity_filter_panel()` 把原始 QFrame 设为 `Qt.WindowType.Dialog` 弹窗并显示
2. 用户点击"+ 添加条件" → `_add_opp_condition_row()` 首次调用时创建 `FilterPanel`，然后用 `_panel_frame` **替换** `self.opp_filter_panel`
3. 替换后：原始 QFrame（含按钮）仍作为 Dialog 弹窗显示在屏幕上（孤立状态）；新的 `_panel_frame` 被添加到主窗口布局中，但不是弹窗，不可见
4. 条件行被添加到了不可见的新帧里，用户看到的弹窗（旧帧）里没有任何条件行
5. 后续点击"+ 添加条件"虽然不再创建新面板，但条件行仍然加到了看不见的帧里

### 根因

**Bug 1 — 未定义变量：**
```python
# ❌ search_field 从未定义，直接引用会 NameError
if search_text:
    if search_field:
        sf_idx = col_map.get(search_field, -1)
        ...
    else:
        if not any(search_text in str(v).lower() for v in row_vals):
            continue

# ✅ 修复：删除死代码分支，保留全字段搜索
if search_text:
    if not any(search_text in str(v).lower() for v in row_vals):
        continue
```

**Bug 2 — 双面板竞争（pdf_watermark.py 创建旧帧 vs order_to_contract.py 创建 FilterPanel）：**

CRM 订单的正确模式：
```python
# ✅ CRM 订单：FilterPanel 在初始化时创建，_panel_frame 直接作为弹窗
self._crm_filter_panel = FilterPanel(...)
self.crm_filter_panel = self._crm_filter_panel._panel_frame
# toggle 方法直接操作 _panel_frame
panel = self._crm_filter_panel._panel_frame
panel.setWindowFlags(Qt.WindowType.Popup | ...)
panel.setVisible(True)
```

商机页的错误模式：
```python
# ❌ pdf_watermark.py 创建旧 QFrame 作为 self.opp_filter_panel
self.opp_filter_panel = QFrame()  # 含按钮
# ❌ _toggle 方法把旧 QFrame 显示为 Dialog 弹窗
self.opp_filter_panel.setWindowFlags(Qt.WindowType.Dialog | ...)
self.opp_filter_panel.setVisible(True)
# ❌ _add_opp_condition_row 首次调用时替换 self.opp_filter_panel
self.opp_filter_panel = self._opp_filter_panel._panel_frame  # 旧弹窗变孤立！
```

### 同类排查

| 位置 | 问题 | 状态 |
|------|------|------|
| `order_to_contract.py` 行713 | `search_field` 未定义 → NameError | ✅ 已修复 |
| `order_to_contract.py` `_add_opp_condition_row` | 替换 `self.opp_filter_panel` 导致旧弹窗孤立 | ✅ 已修复 |
| `order_to_contract.py` `_toggle_opportunity_filter_panel` | 用旧 QFrame 而非 FilterPanel 的 `_panel_frame` 作为弹窗 | ✅ 已修复 |
| `order_to_contract.py` `_adjust_opp_filter_panel_size` | 引用 `self.opp_filter_panel` 而非 `_panel_frame` | ✅ 已修复 |
| `order_to_contract.py` `_apply_opp_filter_and_close` | 同上 | ✅ 已修复 |

### 复利要点

> **当存在两套 UI 组件（旧版 + 新版委托层）时，必须确保只有一套作为"权威源"，另一套要么完全删除，要么在初始化时显式隐藏/替换。懒初始化 + 替换引用 = 必然产生孤立组件。**

具体做法：
1. **委托模式重构时**：参照已验证的实现（如 CRM 订单）的初始化顺序，不要"先弹窗再创建组件"
2. **FilterPanel 使用规范**：必须在 UI 初始化阶段创建 FilterPanel 并将 `_panel_frame` 作为弹窗载体，而非在按钮回调中懒创建后替换
3. **变量清理**：移除 UI 组件（如下拉框）时，必须全文搜索所有引用该组件的方法，确保没有残留的未定义变量
4. **弹窗模式选择**：使用 `Qt.WindowType.Popup` 而非 `Qt.WindowType.Dialog`，Popup 失焦自动关闭，更简洁
