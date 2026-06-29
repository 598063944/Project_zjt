
### 2026-07-04: 对象查询 contains/not_contains 传值加 % 通配符修复

**问题**: 对象查询页面 → 设置筛选条件 → "包含"/"不包含"操作符传值到 CRM API 时缺少 % 通配符，退化为精确匹配，导致查询返回 0 条数据。

**根因**:
1. `_build_obj_query_api_filters()` (对象查询UI筛选面板) 发送 contains/not_contains 值时没有加 % 包裹
2. `_build_api_filters_from_settings()` (设置页默认筛选) 相同问题
3. 2026-07-01 已在 settings 路径修复过此问题，但在后续代码重构中丢失，且 UI 路径一直未修复

**修改**（object_query.py，2 处）:
- L741: `_build_api_filters_from_settings` 中 contains/not_contains 值包裹 `%{value_text}%`
- L2800: `_build_obj_query_api_filters` 中 contains/not_contains 值包裹 `%{value_text}%`

**验证**: `python -m py_compile object_query.py` 通过
