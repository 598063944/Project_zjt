 # Codex 项目记忆中枢 — Project_001_数据批量文档处理工具
 
 ## 🚨 最高优先级指令
 
 ### 必须遵守的四步预检规则
 
 **在任何新项目任务开始之前，Codex 必须先按顺序完成以下全部操作：**
 
 1. **读取** `D:\Workspace\全局工作台.md` — 确认命名规范、行为规则、文档体系
 2. **读取** `D:\Workspace\全局复利与踩坑日志.md` — 回顾全局历史教训，避免重复犯错
 3. **读取** `D:\Workspace\新项目SOP.md` — 确认标准操作流程
 4. **读取项目 docs/ 文件夹下的所有文档** — 包括但不限于：
    - `docs/踩坑记录_复利方法.md` — 本项目的踩坑历史
    - `docs/修改日志.md` — 本项目的修改历史
    - `docs/SOP_项目文件指南.md` — 项目文档体系与操作流程
 5. **只有确认以上所有文档已完整阅读后，才允许开始执行新项目任务**
 
 **违反此规则将导致项目文件散落、命名混乱、行为不一致等严重问题。**
 
 ---
 
 
## 核心规则（追加）

### UI 设计规则
- **禁止使用黑色（#000000）作为任何背景色**，所有界面背景必须使用浅色
- 推荐背景色：白色、极浅灰色（#FAFAFA/#F5F5F5）、白色（#FFFFFF）
- Tooltip 背景统一使用 #FFF7E6（暖浅色），配合 #D9D9D9 边框
- 新增 UI 组件必须与现有设计风格一致（浅色背景、圆角边框、中灰分割线）

### 弹窗无边框规则（2026-06-21 新增）
- **所有弹窗、对话框、消息框必须使用 `FramelessWindowHint`，禁止显示系统标题栏**
- 继承 `CenteredPopupDialog` 的弹窗已自动无边框（基类已设置），无需额外处理
- 原生 `QDialog` 实例必须在创建后立即添加：
  ```python
  dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.FramelessWindowHint)
  ```
- 禁止直接使用 `QMessageBox.warning/information/question/critical()` 和 `QInputDialog.getText/getItem()`，必须使用 `common.py` 中的无边框替代函数：
  ```python
  from common import frameless_input_text, frameless_input_getitem, frameless_message_box
  # 替代 QInputDialog.getText
  text, ok = frameless_input_text(parent, '标题', '提示文字')
  # 替代 QInputDialog.getItem
  item, ok = frameless_input_getitem(parent, '标题', '提示文字', items)
  # 替代 QMessageBox
  frameless_message_box(parent, '标题', '内容')
  result = frameless_message_box(parent, '确认', '内容',
      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
      QMessageBox.StandardButton.No)
  ```
- 违反此规则 = 必须修复，不允许合并

## 项目信息
 
 | 字段 | 内容 |
 |------|------|
 | 项目编号 | Project_001 |
 | 项目名称 | 数据批量文档处理工具 |
 | 项目路径 | `D:\Workspace\Project_001_数据批量文档处理工具` |
 | 创建日期 | 2026-06-12 |
 
 ---
 
 ## 修订历史
 
 | 日期 | 版本 | 修改内容 | 修改人 |
 |-----|------|---------|-------|
 | 2026-06-12 | v1.0 | 初始版本，建立四步预检规则和项目文档体系 | Codex |
 | 2026-06-21 | v1.1 | 新增"弹窗无边框规则"，要求所有弹窗使用 FramelessWindowHint，禁止原生标题栏 | Codex |
