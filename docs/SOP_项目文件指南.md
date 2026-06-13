# SOP & 项目文件指南 — Project_001
 
 ## 用途说明
 本文档定义本项目的文档体系结构、文件用途、以及每次操作前必须遵守的预检流程。
 
 ---
 
 ## 项目文档体系
 
 ### 文档总览
 
 | 文件 | 路径 | 用途 |
 |------|------|------|
 | 踩坑记录_复利方法.md | `docs/踩坑记录_复利方法.md` | 记录本项目的 bug、踩坑、可复用方法，防止重复犯错 |
 | 修改日志.md | `docs/修改日志.md` | 记录每次代码变更的明细，修改前读、修改后写 |
 | SOP_项目文件指南.md（本文档） | `docs/SOP_项目文件指南.md` | 项目文档体系说明与预检流程 |
 | AGENTS.md | `./AGENTS.md` | 项目记忆中枢，包含 Codex 的最高优先级行为指令 |
 
 ---
 
 ## 预检流程（每次操作前必须执行）
 
 ### Step 1：读取 3 份全局文档
 1. `D:\Workspace\全局工作台.md` — 命名规范、行为规则、文档体系
 2. `D:\Workspace\全局复利与踩坑日志.md` — 历史教训，避免重复踩坑
 3. `D:\Workspace\新项目SOP.md` — 标准操作流程
 
 ### Step 2：读取项目文档文件夹（docs/）下的所有文件
 1. `docs/踩坑记录_复利方法.md` — 了解本项目已踩过的坑
 2. `docs/修改日志.md` — 了解本项目已做过的修改
 3. `docs/SOP_项目文件指南.md`（本文档） — 了解项目文档体系
 
 ### Step 3：确认以上阅读完成后，再执行新任务
 
 ---
 
 ## 操作守则
 
 - **修改前** — 先读全部 3 份全局文档 + 项目 docs/ 下全部文件
 - **修改后** — 立即更新 `docs/修改日志.md`；如有踩坑则更新 `docs/踩坑记录_复利方法.md`
 - **所有文件** — 必须存放在项目文件夹内，禁止散落到其他位置
 
 ---
 
 ## 附录 A：项目代码结构 SOP
 
 ### 项目概览
 
 - **主入口文件**: Project_zjt_3.5.8.py（约 25415 行）
 - **虚拟环境**: .venv\Scripts\python.exe
 - **Python版本**: 3.13.10
 - **GUI框架**: PyQt6
 - **配置文件目录**: .config/
 - **用户运行状态**: User/RuntimeState/
 
 ### 文件结构总览
 
 #### 主程序 + 页面模块（Mixin 模式）
 
 MainFrame 继承 QMainWindow + 以下 Mixin，每个 Mixin 提供一页功能：
 
 | 文件 | Mixin 类 | 对应页面 |
 |------|----------|----------|
 | file_generation.py | file_generationMixin | 页面0: 文件生成 |
 | order_to_contract.py | order_to_contractMixin | 页面1: CRM订单转换 |
 | custom_report.py | custom_report_pageMixin | 页面2: 自定义报表(v2) |
 | file_mover.py | file_moverMixin | 页面3: 文件移动 |
 | pdf_watermark.py | pdf_watermarkMixin | 页面4: PDF水印 |
 | object_query.py | object_queryMixin | 页面5: 对象查询 |
 | bi_dashboard.py | bi_dashboardMixin | 页面7: BI报表 |
 | department.py | departmentMixin | 页面8: 部门员工 |
 
 #### 基础设施模块
 
 | 文件 | 用途 |
 |------|------|
 | core.py | 配置加载/保存、日志、路径、工具函数 |
 | common.py | 共享UI组件、通用样式函数 |
 | network.py | 网络请求封装、CRM API、SSL适配 |
 | auth.py | 登录认证相关 |
 
 #### 配置相关文件
 
 | 文件 | 用途 | 位置 |
 |------|------|------|
 | admin.json | 管理员配置（功能选项、路径、字段映射） | .config/ |
 | shared_settings.json | 共享设置 | .config/ |
 | users.json | 用户列表 | .config/ |
 | custom_reports_v2.json | 自定义报表配置 | .config/ |
 | 001.json | 用户运行状态（窗口大小、output_visible 等） | User/RuntimeState/ |
 | saas_contract_config_2026.json | 默认配置模板 | Project/Profiles/ |
 
 #### 主文件内主要类（Project_zjt_3.5.8.py）
 
 | 类名 | 行号(约) | 用途 |
 |------|----------|------|
 | MainFrame | ~8800 | 主窗口，__init__ 负责布局 |
 | SettingsDialog | ~31550 | 设置对话框 |
 | LoginRegisterDialog | ~5065 | 登录/注册窗口 |
 | CenteredPopupDialog | ~3831 | 通用居中弹窗基类 |
 | UIToolkit | ~4157 | UI工具集 |
 | AppConfig | ~5365 | 应用配置类 |
 
 ### 布局架构（当前）
 
 main_horizontal_layout (QHBoxLayout)
   ├─ left_panel (QFrame) [固定宽度，由 nav_expanded 控制]
   │   ├─ nav_panel — 导航按钮列表
   │   ├─ task_status_bar — 后台任务状态栏
   │   ├─ toggle_nav_btn — 导航折叠/展开按钮
   │   └─ nav_btn_row: toggle_output_btn + clear_btn + toggle_opacity_btn
   └─ right_layout (QVBoxLayout) [stretch=1]
       └─ content_stack (QStackedWidget) [stretch=8]
 
 导航栏宽: 展开160px / 折叠60px（按 UI 缩放比例调整）
 
 #### 输出窗口（独立弹出窗口）
 
 _output_dialog (QDialog) — 不嵌入主布局，独立的顶层窗口
   - 窗口标志: CustomizeWindowHint | FramelessWindowHint（无边框筛选器式弹窗）
   - 圆角白色容器（border-radius: 8px）+ QGraphicsDropShadowEffect 阴影
   - 可调整大小: setSizeGripEnabled(True) + 边缘自定义拉伸（右/上/右上）
   - 非模态: setWindowModality(NonModal)
   - 透明度: 循环切换（100% → 80% → 60% → 40%）
   - 定位: 导航栏"隐藏"按钮正上方（_position_output_dialog()）
   - 随主窗口移动/缩放：moveEvent + resizeEvent
   - 点击弹窗外区域自动隐藏（全局事件过滤器）
   - 内容: _output_label + _output_text（QTextEdit，只读）
 
 ### 关键代码位置
 
 | 功能点 | 文件 | 位置（行号约） |
 |--------|------|----------------|
 | 主布局创建 | Project_zjt_3.5.8.py | MainFrame.__init__ (~8970-9220) |
 | 输出窗口创建 | Project_zjt_3.5.8.py | MainFrame.__init__ (~9180-9210) |
 | 导航栏创建 | Project_zjt_3.5.8.py | MainFrame.__init__ (~9025-9145) |
 | 输出窗口切换 | Project_zjt_3.5.8.py | on_toggle_output (~28820) |
 | 输出文本追加 | Project_zjt_3.5.8.py | append_output (~28680) |
 | 输出窗口定位 | Project_zjt_3.5.8.py | _position_output_dialog (~28700) |
 | 恢复运行状态 | Project_zjt_3.5.8.py | restore_user_runtime_state (~9470) |
 | 导航折叠展开 | Project_zjt_3.5.8.py | toggle_navigation (~26680) |
 | 设置对话框 | Project_zjt_3.5.8.py | SettingsDialog.__init__ (~31550) |
 | 通用设置页 | Project_zjt_3.5.8.py | create_general_settings_tab (~32150) |
 
 ### 启动方式
 
 1. **VS Code**: 打开项目文件夹，按 Ctrl+F5（.vscode 已配置好，自动用 .venv）
 2. **命令行**: .venv\Scripts\python Project_zjt_3.5.8.py
 3. **双击**: 启动程序.bat（自动调用 python）
 
 注意：不要用 & file.py 运行，PowerShell 对 .py 文件处理不稳定。
 
 ---
 
 ## 修订历史
 | 日期 | 修改内容 | 修改人 |
 |-----|---------|-------|
 | 2026-06-14 | 合并项目文档/SOP_项目文件指南.md：加入代码结构/布局架构/启动方式附录 | Codex |
 | 2026-06-12 | 初始版本，建立项目文档体系和预检流程 | Codex |
