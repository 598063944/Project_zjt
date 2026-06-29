# 2026-07-01 修改 - 对象查询 CONTAINS 操作符修复（API端处理）

## 修改摘要
**问题**: "产品 包含 13.012"筛选获取不到数据  
**根因**: op_map 中 contains 错误映射为 LIKE（字符串匹配），而应该是 CONTAINS（数组包含）  
**方案**: 修改 op_map 映射，让 contains 直接通过 API 发送，使用正确的 CONTAINS 操作符  
**类型**: Bug Fix - API操作符映射纠正

## 修改文件
- `object_query.py`

## 具体修改

### 修改1：L666 (_build_api_filters_from_settings)
```python
# 修改前：
'contains': 'LIKE',
'not_contains': 'NLIKE',

# 修改后：
'contains': 'CONTAINS',    # ✅ 数组包含操作符
'not_contains': 'NIN',      # ✅ 不属于操作符
```

### 修改2：L2601 (_build_obj_query_api_filters)
```python
# 修改前：
'contains': 'LIKE',
'not_contains': 'NLIKE',

# 修改后：
'contains': 'CONTAINS',
'not_contains': 'NIN',
```

### 修改3：删除特殊处理（L720-731）
```python
# 修改前：
elif op == 'contains':
    # CRM API: CONTAINS 无效，退回到客户端过滤
    c_lst = getattr(self, '_obj_query_client_filters', [])
    c_lst.append(cond)
    self._obj_query_client_filters = c_lst
elif op == 'not_contains':
    # CRM API 没有"不包含"的原生操作符，退回到客户端过滤
    c_lst = getattr(self, '_obj_query_client_filters', [])
    c_lst.append(cond)
    self._obj_query_client_filters = c_lst
elif op in op_map:

# 修改后：
elif op in op_map:  # contains 通过 op_map 正常处理
```

## 验证信息
- ✅ 编译通过：`python -m py_compile object_query.py`
- ✅ 两处 op_map 均已修正
- ✅ 逻辑清晰，无重复代码块

## 工作原理

### CRM API 操作符定义
| 操作符 | 用途 | 例子 |
|-------|------|------|
| **CONTAINS** | 数组/多选字段包含判断 | Product 包含 "13.012" |
| **LIKE** | 字符串模糊匹配 | Name LIKE "%张%" |
| **IN** | 属于某个集合 | Status IN ['已完成', '已关闭'] |
| **NIN** | 不属于某个集合 | Status NOT IN ['草稿'] |

### 修复后的执行流程
```
用户配置: 字段=产品, 操作符=包含, 值=13.012
    ↓
前端转换:
  操作符 "包含" → "contains"（UI层）
    ↓
后端映射:
  "contains" → op_map.get('contains') = "CONTAINS"（API层）
    ↓
API请求:
  {'field_name': 'product', 'operator': 'CONTAINS', 'field_values': ['13.012']}
    ↓
CRM服务器:
  检查 Product 数组字段是否包含 '13.012'
    ↓
返回结果: 所有产品包含"13.012"的记录
```

## 测试方法

### 功能测试
1. 启动应用
2. 进入 设置→CRM设置→对象查询
3. 选择包含"产品"字段的对象
4. 添加筛选条件：
   - 字段：产品
   - 操作符：包含
   - 值：13.012（或任意产品值的部分）
5. 点击"刷新"或"应用筛选"
6. **预期**: 表格显示所有产品包含"13.012"的记录 ✅

### 日志验证
在调试输出中应该看到：
```
[DEBUG-API筛选] api=Product, filters=[...operator='CONTAINS'...]
```

## 影响范围
- ✅ 对象查询所有"包含"操作符筛选
- ✅ 适用于所有数组/多选类型字段
- ✅ 不影响其他操作符（EQ、LT、LIKE、IN 等）

## 相关参考
- CRM API 文档：CONTAINS 用于数组包含判断
- 用户参数表：CONTAINS = Array 包含
