# SOP & 项目文件指南 — Project_001
#
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
 
 ﻿## 附录 A：项目代码结构与模块职责总览

### A.1 项目概览

| 项目属性 | 值 |
|---------|-----|
| **主入口文件** | Project_zjt_3.5.8.py（约 25415 行） |
| **Python 版本** | 3.13.10 |
| **GUI 框架** | PyQt6 |
| **虚拟环境** | .venv\Scripts\python.exe |
| **配置文件目录** | .config/ |
| **用户运行状态** | User/RuntimeState/ |

### A.2 应用启动流程

程序从 Project_zjt_3.5.8.py 的 __main__ 块启动（L25408），执行顺序如下：

`
__main__ 块 (L25408)
  │
  ├── 1. 检查用户登录状态
  │   ├─ current_user 已缓存 → 跳过登录窗口
  │   └─ 无缓存 → 弹出 LoginRegisterDialog → 写入 user_cache.json
  │
  ├── 2. 确保个人配置文件存在 → User/RuntimeState/{user_id}.json
  │
  ├── 3. 延迟导入 PyQt6 模块
  │
  ├── 4. ensure_qapplication() — 创建 QApplication 实例
  │
  ├── 5. MainFrame() — 创建主窗口
  │   ├─ __init__ → 加载配置 → 创建布局
  │   ├─ create_*_page() → 创建 9 个页面加入 content_stack
  │   └─ restore_user_runtime_state() → 恢复窗口状态
  │
  ├── 6. main_window.show() — 显示主窗口
  │
  └── 7. app.exec() — 进入 Qt 事件主循环
`

### A.3 MainFrame 类继承链

MainFrame 通过 Python MRO 继承 QMainWindow + 8 个 Mixin：

`python
class MainFrame(
    QMainWindow,              # Qt 主窗口基类
    file_generationMixin,     # 页面0: 文件生成
    order_to_contractMixin,   # 页面1: CRM订单转换
    file_moverMixin,          # 页面3: 文件移动
    pdf_watermarkMixin,       # 页面4: PDF水印
    object_queryMixin,        # 页面5: 对象查询
    bi_dashboardMixin,        # 页面7: BI报表
    departmentMixin,          # 页面8: 部门员工
    custom_report_pageMixin,  # 页面2: 自定义报表（放最后覆盖同名方法）
):
`

Mixin 模式要点：
- 每个 Mixin 定义一组页面相关方法（create_*_page、on_*、_*）
- custom_report_pageMixin 放最后确保其方法优先级最高
- Mixin 内部调用其他 Mixin 方法时通过 MRO 查找

### A.4 页面导航与权限控制

switch_to_page(index) 控制页面切换：

| 页面 | 名称 | Mixin 源文件 | 创建方法 |
|------|------|-------------|---------|
| 0 | 文件生成 | file_generation.py | create_excel_to_pdf_page() |
| 1 | CRM订单 | order_to_contract.py | create_crm_order_page() |
| 2 | 自定义报表 | custom_report.py | create_custom_report_page() |
| 3 | 文件移动 | file_mover.py | create_file_organize_page() |
| 4 | PDF水印 | pdf_watermark.py | create_pdf_watermark_page() |
| 5 | 对象查询 | object_query.py | create_object_query_page() |
| 6 | 设置 | Project_zjt_3.5.8.py（主文件内） | create_settings_page() |
| 7 | BI报表 | bi_dashboard.py | create_bi_dashboard_page() |
| 8 | 部门员工 | department.py | create_department_page() |

权限限制：页面 2/5/7/8 仅管理员用户可访问。

### A.5 布局架构

`
main_horizontal_layout (QHBoxLayout)
  +- left_panel (QFrame) [固定宽度，由 nav_expanded 控制]
  |   +- nav_panel           — 导航按钮列表
  |   +- task_status_bar     — 后台任务状态栏
  |   +- toggle_nav_btn      — 导航折叠/展开
  |   +- nav_btn_row:        — 隐藏/清除/透明度按钮
  |
  +- right_layout (QVBoxLayout) [stretch=1]
      +- content_stack (QStackedWidget) [stretch=8]
          +- 页面0-8
`

导航栏宽：展开 160px / 折叠 60px。输出窗口为独立弹窗（无边框/圆角/阴影/可调透明度/点击外部隐藏）。

### A.6 模块职责详解

#### A.6.1 页面模块（Mixin 模式）

##### file_generation.py — 页面0: 文件生成

| 属性 | 内容 |
|------|------|
| Mixin 类 | ile_generationMixin（L70） |
| 创建方法 | create_excel_to_pdf_page() |
| 依赖 | core.py / common.py |
| 核心功能 | Excel 数据处理 → Word 模板填充 → PDF 转换 |

操作逻辑：
1. 选择 Excel 数据源，数据展示在表格（筛选/排序/分页/搜索）
2. 选择合同 Word 模板（占位符变量替换）
3. 逐行/选中行处理：读取模板 → 替换字段 → 生成 Word 合同
4. 可选 Word → PDF 转换（WordPdfConverterSession）
5. 输出到指定目录

##### order_to_contract.py — 页面1: CRM订单转换

| 属性 | 内容 |
|------|------|
| Mixin 类 | order_to_contractMixin（L69） |
| 创建方法 | create_crm_order_page() |
| 依赖 | core.py / common.py / network.py |
| 核心功能 | CRM 订单处理、产品匹配、商机管理、合同生成 |

操作逻辑：
1. 从 CRM API 拉取订单列表
2. 配置字段映射（CRM 字段 ↔ 模板字段）
3. 产品匹配（CRM 产品名 → 本地产品列表，支持模糊匹配）
4. 价格计算/匹配
5. 选择订单 → 填充模板 → 批量生成合同
6. 商机管理子模块：商机 → 模板匹配 → 资格文件生成 → SVN 提交

##### custom_report.py — 页面2: 自定义报表（最复杂模块）

| 属性 | 内容 |
|------|------|
| Mixin 类 | custom_report_pageMixin |
| 创建方法 | create_custom_report_page() |
| 依赖 | core.py / common.py / network.py |
| 核心功能 | 可视化拼表设计器、MySQL 持久化、仪表板、AI 助手 |

子页面结构（QStackedWidget 切换）：
`
custom_report 主容器
  +- 列表页: ReportListPage（报表列表 + 复选框 + 批量刷新）
  +- 编辑器: ReportEditorPage（拼表画布 + 字段配置 + 预览 + 同步）
  +- 详情页: ReportDetailPage（数据查看 + 搜索 + 筛选）
  +- 仪表板设计器: DashboardDesigner（拖拽图表 + AI 生成）
`

报表创建操作逻辑：
1. 新建报表 → ReportEditorPage
2. 选择数据源（CRM 对象表 sr_* / Excel 导入表 ex_* / 普通 MySQL 表）
3. 添加字段列（字段提取/公式计算/日期成分提取）
4. 配置表关联（JoinDefinition）
5. 预览 → 确认拼表结果
6. 保存定义（JSON / MySQL）
7. 同步到 MySQL：CREATE TABLE AS SELECT ... JOIN → cr_*

> 编辑器完整数据流水线（7 步）：详见附录 E

批量刷新操作逻辑：详见附录 D

关键类：

| 类 | 行号(约) | 职责 |
|------|----------|------|
| ReportListPage | ~2461 / ~25695 | 报表列表（复选框 + 批量刷新 + 右键菜单） |
| ReportDefinition | ~2894 | 报表定义数据模型 |
| ReportRepository | ~3419 | 报表 CRUD（JSON / MySQL 双存储） |
| JoinSQLBuilder | ~3905 | 拼表 SQL 生成器 |
| DataFetcher | ~822 | CRM 数据拉取 |
| PreviewQueryBuilder | ~5145 | 预览 SQL 构建 |
| SourceTableSyncer | ~5223 | CRM → sr_* 表同步 |
| ReportRefreshWorker | ~5382 | 报表刷新核心（拼表/地址提取/公式回填） |
| ReportDatabase | ~23870 | MySQL 底层操作 |
| ReportManager | ~23095 | 报表管理器（CRUD + 刷新控制器） |
| DashboardDesigner | ~7783 | 仪表板设计器 |
| ChartConfigPanel | ~6687 | 图表配置面板 |
| AIAssistant | ~6224 | AI 助手（自然语言→图表） |

##### file_mover.py — 页面3: 文件移动

| 属性 | 内容 |
|------|------|
| Mixin 类 | ile_moverMixin（L67） |
| 创建方法 | create_file_organize_page() |
| 依赖 | core.py / common.py |
| 核心功能 | 按规则扫描文件并移动到分类文件夹 |

操作逻辑：
1. 选择源文件夹和目标根文件夹
2. 设置日期过滤范围
3. 扫描文件列表（递归/非递归）
4. 按文件名模式关键词自动分组
5. 执行 move_files_to_new_folders() → 创建分类子文件夹并移动

##### pdf_watermark.py — 页面4: PDF水印

| 属性 | 内容 |
|------|------|
| Mixin 类 | pdf_watermarkMixin（L68） |
| 创建方法 | create_pdf_watermark_page() |
| 依赖 | core.py / common.py |
| 核心功能 | PDF 文件添加水印/加密 |

操作逻辑：
1. 选择源 PDF 文件（单个或批量）
2. 配置水印参数：文字/图片、位置、透明度、旋转、字号、颜色、每页/仅首页
3. 可选 PDF 加密（设置密码）
4. 执行 process_pdf_watermark() → 生成加印版本
5. 输出到指定目录

##### object_query.py — 页面5: 对象查询

| 属性 | 内容 |
|------|------|
| Mixin 类 | object_queryMixin（L69） |
| 创建方法 | create_object_query_page() |
| 依赖 | core.py / common.py / network.py |
| 核心功能 | CRM 对象通用查询、字段配置、数据同步到 MySQL |

操作逻辑：
1. 选择 CRM 对象类型（客户/联系人/订单/产品等）
2. 自动获取字段列表（etch_object_fields）
3. 配置查询字段和筛选条件
4. 调用 FXiaokeCRM.query_data_object() 拉取数据
5. 表格展示（排序/筛选/导出）
6. 可选同步到 MySQL → 创建 对象-{name} 表

##### bi_dashboard.py — 页面7: BI报表

| 属性 | 内容 |
|------|------|
| Mixin 类 | i_dashboardMixin（L66） |
| 创建方法 | create_bi_dashboard_page() |
| 依赖 | core.py / common.py / custom_report |
| 核心功能 | ECharts 仪表板查看与数据刷新 |

操作逻辑：
1. 选择已有仪表板或创建新的
2. 查看模式：展示 ECharts 图表（折线/柱状/饼图/地图/词云）
3. 数据刷新：_refresh_dashboard / _prewarm_dashboard
4. 使用本地 ECharts 离线资源（echarts/ 目录）
5. 与 custom_report.py 的 DashboardDesigner 通信（DashboardBridge）

##### department.py — 页面8: 部门员工

| 属性 | 内容 |
|------|------|
| Mixin 类 | departmentMixin（L69） |
| 创建方法 | create_department_page() |
| 依赖 | core.py / common.py / network.py |
| 核心功能 | 企业微信/CRM 部门与员工管理 |

操作逻辑：
1. 显示部门树结构（从 CRM API 获取）
2. 选择部门 → 显示员工列表（姓名/手机/邮箱/职位/状态）
3. 配置显示字段
4. 同步到 MySQL：_do_usergroup_sync_to_mysql() → 对象-员工 / 对象-部门 表

#### A.6.2 基础设施模块

##### Project_zjt_3.5.8.py — 主程序

定位：应用入口 + 全局基础设施。约 25415 行（经去重优化）。

主要类：

| 类 | 行号(约) | 职责 |
|------|----------|------|
| FXiaokeCRM | L86 | CRM API 客户端（token/数据对象/用户/部门） |
| BackgroundTaskManager | L371 | 后台任务调度（超时/状态跟踪） |
| MysqlCache | L448 | MySQL 连接池与缓存（sr_* 表操作） |
| CRMCache | L744 | CRM 本地缓存（JSON + MySQL 双写） |
| WordPdfConverterSession | L1070 | Word→PDF 转换 |
| SSLContextAdapter | L1415 | SSL 适配（HTTPS 证书兼容） |
| ImportantOperationLogFilter | L2171 | 日志过滤（抑制噪声） |
| AppConfig | L4424 | 配置管理（字段映射/特征开关） |
| MainFrame | L5569 | 主窗口（+8 Mixin，见 A.3） |
| SettingsDialog | L12453 | 设置对话框（8+ 选项卡） |

设置页选项卡：

| 选项卡 | 创建方法 | 内容 |
|--------|---------|------|
| 通用设置 | create_general_settings_tab() | 输出窗口透明度/大小、导航栏位置、缩放 |
| 路径设置 | create_path_tab() | 模板目录、缓存目录、CRM 缓存目录 |
| 字段映射 | create_field_mapping_tab() | CRM 字段 ↔ 模板字段映射表 |
| CRM对象管理 | create_crm_object_management_tab() | 仅管理员可见 |
| CRM设置 | create_crm_settings_tab() | 连接参数、缓存策略 |
| 模板管理 | create_template_tab() | 合同模板列表/上传 |
| 产品管理 | create_product_list_tab() | 产品列表 |
| 功能选择 | create_feature_selection_tab() | 功能开关 |
| 用户设置 | create_user_dependent_tabs() | 用户专属配置 |

##### core.py — 核心工具（延迟代理）

设计模式：延迟代理（Lazy Proxy），从 __main__ 重新导出核心函数。

解决的问题：rom __main__ import * 在模块加载阶段有时序问题。core.py 定义本地延迟代理，运行时从 sys.modules["__main__"] 获取真实函数。

导出函数：load_config / save_config / load_user_runtime_state / save_user_runtime_state / resolve_app_path / deep_merge_dict / append_user_operation_record / flush_pending_config / perform_requests_request

##### common.py — 通用 UI 组件库（约 6600 行）

关键组件：

| 组件 | 职责 |
|------|------|
| FilterPanel | 通用筛选器面板（多条件/预设/标签栏） |
| FilterConditionRow | 筛选条件行（字段/运算符/值） |
| ExposedTagsBar | 活动筛选条件标签 |
| CustomReportFilterDialog | 报表筛选对话框 |
| CheckBoxHeader | 表头复选框（全选/全不选/部分选中） |
| TableRowCheckBox | 行复选框（紧凑嵌入表格单元格） |
| CenteredPopupDialog | 居中弹窗基类（模态/遮罩/关闭过滤） |
| CustomMessageBox | 自定义消息框 |
| UIToolkit | UI 工具集（按钮/缩放/玻璃效果） |
| QuickDatePickerDialog | 快速日期选择器 |
| DatePartPickerDialog | 日期成分提取对话框 |
| ExcelFieldSettingsDialog | Excel 字段设置 |
| CRMInlineComboDelegate | 表格内联下拉框委托 |
| TableCellEditMenu | 单元格右键菜单 |
| BrowseLineEdit | 路径浏览输入框 |

##### network.py — 数据访问层

主要类：

| 类 | 行号(约) | 职责 |
|------|----------|------|
| FXiaokeCRM | L60 | CRM API 封装（分页拉取/字段查询/用户部门接口） |
| BackgroundTaskManager | L344 | 后台任务管理（线程池/超时/状态） |
| MysqlCache | L421 | MySQL 缓存层（sr_* 表 CRUD） |
| CRMCache | L734 | 本地缓存（文件 + MySQL 双写） |

##### auth.py — 用户认证

| 功能 | 说明 |
|------|------|
| 密码验证 | verify_login() |
| 用户缓存 | user_cache.json 读写 |
| 登录状态持久化 | 自动保存/恢复 |
| 用户 CRUD | 增删改查 users.json |
| 权限判断 | 获取 user_type |

### A.7 配置文件详解

| 文件 | 路径 | 用途 | 更新方式 |
|------|------|------|---------|
| admin.json | .config/ | 管理员配置（功能选项/路径/字段映射） | 设置页保存 |
| shared_settings.json | .config/ | 共享设置（CRM 选项映射/业务规则/输出窗口偏好） | 设置页/运行时 |
| users.json | .config/ | 登录用户列表 | 注册/管理 |
| custom_reports_v2.json | .config/ | 报表定义全集 | 编辑保存 |
| dashboards.json | .config/ | 仪表板定义列表 | 管理操作 |
| deleted_user_ids.json | .config/ | 已删除用户 ID | 用户删除时写入 |
| excel_datasets.json | .config/ | Excel 数据集配置 | 导入配置 |
| user_cache.json | .config/ | 登录缓存（current_user / user_type） | 登录/登出 |
| {user_id}.json | User/RuntimeState/ | 个人运行状态（窗口位置/大小/输出窗口） | 关闭/切换页面 |

### A.8 关键目录

| 目录 | 用途 |
|------|------|
| .config/ | 配置文件（8 个 JSON） |
| User/RuntimeState/ | 用户运行状态 + 操作日志 |
| echarts/ | ECharts 离线资源（echarts.min.js / china.json / 扩展插件） |
| template/ | Word/Excel 合同模板文件 |
| log/ | 操作日志 operation_{date}.log |
| docs/ | 项目文档（踩坑/修改日志/SOP） |
| .venv/ | Python 虚拟环境 |
| .vscode/ | VS Code 配置（解释器/调试） |
| .github/agents/ | Copilot Agent 指令文件 |

### A.9 打印输出分层过滤

应用实现三层过滤确保运行窗口不被噪声淹没：

第1层 — 全局 print 统配：uiltins.print = 统配版，所有模块的 print() 经过同一过滤器

第2层 — _should_suppress_runtime_print：返回 False（正常显示）/ "ui_only"（仅写日志不显示）

第3层 — append_output 入口过滤：前缀/子串匹配 → 直接 return

过滤前缀列表：[DEBUG-]、[RuntimeState]、→ 窗口居中、[operation]、[root] INFO、✓、保存页面顺序到配置

### A.10 关键代码位置

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
| 主文件启动入口 | Project_zjt_3.5.8.py | __main__ 块 (L25408) |


---

## 修订历史
| 日期 | 修改内容 | 修改人 |
|-----|---------|-------|
| 2026-06-21 | 新增附录 E：自定义报表编辑器完整数据流水线（7 步：选取→拼表→字段→筛选→排序→公式→预览） | Codex |
| 2026-06-21 | 附录 C 新增"禁止直接使用原生 Qt 对话框"规则，要求使用 frameless_message_box / frameless_input_text / frameless_input_getitem 替代 | Codex |
| 2026-06-20 | 重写附录 C：完整 UI 窗口统一风格规范（背景色体系、窗口标志速查、圆角/阴影/Tooltip/QSS 模板、新增窗口检查清单） | Codex |
| 2026-06-14 | 重写附录 A：加入应用启动流程、Mixin 继承链、8 个页面模块职责与操作逻辑、基础设施模块详解、配置文件/目录总览、打印过滤机制 | Codex |
| 2026-06-14 | 合并项目文档/SOP_项目文件指南.md：加入代码结构/布局架构/启动方式附录 | Codex |
| 2026-06-14 | 新增附录C：UI设计规范（浅色背景、Tooltip规范、修改/新增规范） | Codex |
| 2026-06-12 | 初始版本，建立项目文档体系和预检流程 | Codex |

## 附录 D：批量刷新完整技术流程

### D.1 流程概述

从用户点击批量刷新到结果表写入 MySQL 的完整数据链路：

`
用户点击 [批量刷新]
  │
  ▼
ReportListPage._on_batch_refresh()
  │  显示 QProgressBar, range(0, total)
  │  调用 _batch_refresh_fn(to_refresh, progress_cb, done_cb)
  │
  ▼
ReportManager._on_batch_refresh_reports()
  │  取消旧 worker
  │  创建 BatchRefreshWorker
  │  worker.progress_updated → progress_cb (QueuedConnection)
  │  worker.all_done → _on_all_done (QueuedConnection)
  │  threading.Thread(target=worker.run, daemon=True).start()
  │  ──── 至此主线程返回，不阻塞 UI ────
  │
  ▼
BatchRefreshWorker.run()
  │  ThreadPoolExecutor(max_workers=3)
  │  for each report: executor.submit(_refresh_one)
  │
  ▼  (每个报表独立执行)
_refresh_one(rid, idx)
  │
  └─ ReportRefreshWorker.full_refresh(report)
       │
       ├── [Phase 1] SourceTableSyncer.sync_all_for_report()
       │   │  从 CRM 拉取 → 写入 MySQL source 表
       │   │
       │   ├── DataFetcher.fetch_object(api)
       │   │   └─ crm.fetch_all_data_object(...)  ← CRM API 分页拉取
       │   │      返回: (rows, total_count, error)
       │   │
       │   ├── ReportDatabase.ensure_source_table(api, sample_row)
       │   │   │  CREATE TABLE IF NOT EXISTS sr_{api}
       │   │   │  (_id PK, _sync_time, _hash, {fields} LONGTEXT...)
       │   │   └─ 新字段自动 ADD COLUMN
       │   │
       │   └── ReportDatabase.upsert_rows(api, rows)
       │       │  Python hashlib.md5 计算 _hash
       │       └─ INSERT ON DUPLICATE KEY UPDATE (hash变更检测)
       │
       ├── [Phase 2] ReportRefreshWorker.refresh()
       │   │  拼表 → 写入 MySQL 结果表
       │   │
       │   ├── JoinSQLBuilder(report, db).build_create_sql()
       │   │   │  解析 columns(FieldColumn/FormulaColumn...)
       │   │   │  解析 joins(对象间关联)
       │   │   │  解析 calculated_fields
       │   │   └─ 生成完整 SELECT FROM t0 LEFT JOIN t1 ON ...
       │   │
       │   ├── ReportDatabase.create_result_table_as()
       │   │   │  write_mode 决定策略:
       │   │   │
       │   │   ├─ incremental (默认):
       │   │   │   _upsert_result_table()
       │   │   │     ├─ CREATE TABLE cr_{id}_incr AS {SELECT}
       │   │   │     ├─ _add_hash_to_temp_table (Python hashlib)
       │   │   │     ├─ 补全新列 + 建 _id 唯一索引
       │   │   │     └─ INSERT ON DUPLICATE KEY UPDATE
       │   │   │
       │   │   └─ overwrite (增量失败回退):
       │   │       DROP + CREATE TABLE AS SELECT
       │   │       → _add_row_id → _ensure_result_hash_column
       │   │
       │   ├── _run_address_extraction()
       │   │   └─ 读取结果表 → ChinaCitys.json 匹配 → UPDATE 写回
       │   │
       │   └── _run_formula_backfill()
       │       └─ pandas 计算 → UPDATE 写回结果表
       │
       └── 返回 {success, row_count, error, duration}
`

### D.2 关键类与位置

| 类 | 文件 | 行号 |
|-----|------|------|
| ReportListPage | custom_report.py | ~25650 |
| ReportManager | custom_report.py | ~23061 |
| BatchRefreshWorker | custom_report.py | ~26738 |
| ReportRefreshWorker | custom_report.py | ~5382 |
| SourceTableSyncer | custom_report.py | ~5223 |
| DataFetcher | custom_report.py | ~822 |
| ReportDatabase | custom_report.py | ~23845 |
| JoinSQLBuilder | custom_report.py | ~3905 |

### D.3 线程安全设计

1. **BatchRefreshWorker** 不 moveToThread，留在主线程 → pyqtSignal 跨线程 emit 自动 QueuedConnection
2. **_on_all_done completion guard**: if self._batch_worker is not worker: return 防止旧 worker 覆盖新 worker
3. **cancel() 机制**: 设置 _cancelled=True，_refresh_one 检测后尽早返回
4. **daemon=True**: 进程退出时自动清理后台线程
5. **QApplication.processEvents()**: 进度回调中调用，确保 UI 在后台计算期间保持响应

---

## 附录 E：自定义报表编辑器完整数据流水线

### E.1 流程概述

从用户进入编辑器到最终看到预览数据，共 7 个环节：

```
选取报表 → 拼表（选表+连线） → 选取字段 → 筛选过滤 → 排序 → 公式计算 → 预览显示
```

编辑器 UI 为三栏布局（`ReportEditorPage._setup_ui()`）：

```
┌─────────────────────────────────────────────────────────────────────┐
│  ReportEditorPage                                                   │
│                                                                     │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────────────────┐  │
│  │ 左: 可用表 │  │ 中: 拼图画布  │  │ 右: 字段面板 + 筛选栏 + 预览表 │  │
│  │ TableSel..│  │ JoinCanvas   │  │ FieldConfig + FilterBar      │  │
│  │           │  │              │  │           + PreviewTable      │  │
│  └──────────┘  └──────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### E.2 Step 1 · 选取报表

| 动作 | 代码位置 |
|------|----------|
| 报表列表页 | `ReportListPage` ~L24513 |
| 点击编辑 → 进入编辑器 | `ReportEditorPage` L20706 |
| 加载报表定义 | `ReportDefinition` L3412 |

编辑器加载 `ReportDefinition` 对象，它包含整份报表的全部配置：

```
@dataclass
class ReportDefinition:
    main_object_api: str     # 主表 API 名
    joins: list              # 拼表关系 (list[JoinDefinition])
    columns: list            # 显示列 (list[FieldColumn])
    filters: list            # 筛选条件 (list[FilterCondition])
    sort_config: list        # 排序配置
    group_by_fields: list    # 分组字段
    show_summary_row: bool   # 汇总行开关
    write_mode: str          # "overwrite" | "incremental"
    canvas_positions: dict   # 画布卡片位置
    ...
```

### E.3 Step 2 · 拼表（选表 + 连线）

#### 左栏：可用表面板

| 组件 | 代码位置 | 职责 |
|------|----------|------|
| `TableSelectorPanel` | L26995 | 列出 MySQL 中所有可用表 |
| `importExcelRequested` 信号 | — | 导入 Excel 数据集 |
| `addMySQLRequested` 信号 | — | 添加外部 MySQL 表 |

表来源分三类：
- `sr_{api_name}` — CRM 对象同步表（由对象查询页面同步）
- `ex_{name}` — Excel 导入表
- 普通 MySQL 表 — 外部直连

#### 中栏：拼图画布

| 组件 | 代码位置 | 职责 |
|------|----------|------|
| `JoinCanvas` | L27645 | 拼图画布主控件 |
| `JoinCanvasScene` | L27381 | 画布场景（管理卡片和连线） |
| `JoinLine` | L28075 | 表间连线（代表 JOIN 关系） |

操作流程：

```
双击左侧面板的表
  → _on_table_selected_from_panel() [L22457]
  → canvas.add_table_card() 添加卡片到画布
  → 第一张表自动设为主表（橙色标题栏 + ★ 标记）

拖拽连线两张表的卡片
  → 生成 JoinDefinition（左表、右表、连接键、JOIN 类型）
  → join_type: "left" | "inner" | "one_to_one"
  → multi_match: "expand" | "first" | "concat" | "count" | "sum" | "avg"
```

`JoinDefinition` 数据结构（L3358）：

```
class JoinDefinition:
    left_object_api: str     # 左表对象 API 名
    right_object_api: str    # 右表对象 API 名
    match_keys: list         # 连接键 [(左字段, 右字段)]
    join_type: str           # "left" | "inner" | "one_to_one"
    multi_match: str         # "expand" | "first" | "concat" | "count" | "sum" | "avg"
    concat_separator: str    # concat 模式分隔符，默认 "、"
```

### E.4 Step 3 · 选取字段

字段有两种添加方式：

**方式 A — 画布卡片勾选**（推荐）

```
卡片上勾选字段复选框
  → card.fieldToggled 信号
  → _on_card_field_toggled() [L22503]
  → field_panel.add_column(label, object_api, field_key)
```

**方式 B — 字段面板直接管理**

`FieldConfigPanel`（L15496）支持：拖拽排序、删除、编辑公式/聚合/地址提取/日期成分。

`FieldColumn` 数据结构（L3375）：

```
class FieldColumn:
    display_name: str          # 列显示名（中文表头）
    source_object_api: str     # 来源对象 API 名
    source_field: str          # 字段 API 名
    visible: bool              # 是否在结果表中显示
    sort_order: int            # 列顺序
    computation_type: str      # "direct" | "aggregate" | "formula" | "address_extract" | "date_part"
    formula_expression: str    # 公式表达式，如 "=单价*数量"
    aggregate_func: str        # 聚合函数 "SUM" | "AVG" | "COUNT" | "MAX" | "MIN"
    field_format: str          # 显示格式 "text" | "integer" | "float" | "currency" | "date_ymd" | ...
    address_source_fields: list  # 地址提取源字段
    address_target_level: str    # "province" | "city_full" | "city_short" | ...
    date_part_source_field: str  # 日期成分提取源字段
    date_part_unit: str          # "year" | "month" | "week" | "quarter"
```

### E.5 Step 4 · 筛选过滤（两层筛选）

`FilterBar`（L17941）管理筛选条件。筛选在**两个阶段**分别起作用：

#### 阶段 A — 拼表时筛选（写入 MySQL 结果表）

```
用户点击"刷新数据"
  → _refresh_data() [L22068]
  → ReportRefreshWorker.refresh() [L6110]
  → JoinSQLBuilder.build_create_sql() [L4658]
  → _split_filter_conditions() [L5359]
```

筛选条件被拆分（L5399）：
- **主表条件** → SQL `WHERE` 子句
- **JOIN 表条件** → SQL `ON` 子句（避免 LEFT JOIN 退化为 INNER JOIN）

生成的 SQL 结构：

```sql
CREATE TABLE cr_xxx AS
SELECT _base.*, 公式列...
FROM (
  SELECT t0.`字段1`, t1.`字段2`, ...
  FROM `sr_主表` t0
  LEFT JOIN `sr_关联表` t1 ON t0.`键` = t1.`键` AND t1.`筛选条件`  -- ON 子句
  WHERE t0.`主表筛选条件`                                          -- WHERE 子句
  GROUP BY ...                                                     -- 如有聚合列
) _base
```

#### 阶段 B — 预览时筛选（仅影响显示，不改结果表）

```
筛选条件变更
  → _on_filter_changed() [L22650]
  → 防抖 300ms（_filter_change_timer）
  → _apply_filter_to_preview() [L22655]
  → preview.set_filter_conditions(conditions)
  → refresh() → query_result(filters=conditions)
```

预览时筛选直接在 `SELECT ... WHERE` 中追加条件（`query_result()` L30326），不修改 MySQL 结果表。

### E.6 Step 5 · 排序

| 组件 | 代码位置 | 职责 |
|------|----------|------|
| "排序" 按钮 | `FieldConfigPanel` L15622 | 点击弹出排序配置 |
| `SortConfigDialog` | L19236 | 多字段排序配置弹窗 |
| `PreviewTable.set_sort_config()` | L19762 | 接收排序配置 |

操作流程：

```
用户点击"排序"按钮
  → _on_sort_clicked() [L15685]
  → SortConfigDialog 弹出（支持多字段排序）
  → 用户配置: [{field: "列显示名", direction: "asc"|"desc"}, ...]
  → sortConfigChanged 信号
  → _on_sort_config_changed() [L22640]
      ├─ report.sort_config = config（持久化）
      ├─ preview.set_sort_config(config)
      └─ preview.refresh()（触发数据重载）
```

排序在 **MySQL 查询层**执行（`ORDER BY` 子句），不在内存排序：

```python
# PreviewTable.refresh() [L19774]
for sc in self._sort_config:
    field = sc.get('field', '')
    direction = 'ASC' if sc.get('direction') == 'asc' else 'DESC'
    parts.append(f"`{field}` {direction}")
order_by = ', '.join(parts)
# → SQL: ORDER BY `列名` ASC, `列名2` DESC
```

### E.7 Step 6 · 公式计算（三层兜底）

公式在**三个阶段**分别计算，确保最大程度覆盖：

#### 层级 A — 拼表 SQL 翻译（优先，性能最好）

```
JoinSQLBuilder.build_create_sql() [L4658]
  → _get_formula_columns() 提取所有 formula 类型列
  → translate_formula_to_sql(expr, base_names) 公式 → SQL 表达式
  → 外层子查询: SELECT _base.*, (SQL表达式) AS '计算列' FROM (内层) _base
```

能翻译为 SQL 的公式直接写入 MySQL 结果表，查询时零开销。

#### 层级 B — pandas 回填（SQL 无法翻译时兜底）

```
ReportRefreshWorker.refresh() [L6110]
  → _run_formula_backfill() [L6208]
  # 对 SQL 翻译失败的公式列，用 pandas 计算后 UPDATE 写回 MySQL
```

#### 层级 C — 预览时实时计算（最终兜底）

```
PreviewTable._populate_table() [L19802]
  → df = pd.DataFrame(rows)
  → df = eval_formula_columns(df, report_def.columns) [L2775]
  → 即使 MySQL 中没有的公式列，预览也能正确显示
```

公式引擎还支持以下特殊计算类型：

| computation_type | 说明 | 示例 |
|-----------------|------|------|
| `direct` | 直接字段映射 | 普通列 |
| `aggregate` | 聚合函数 | SUM、AVG、COUNT、MAX、MIN |
| `formula` | 公式计算 | `=单价*数量`、`=IF(金额>1000, '大额', '小额')` |
| `address_extract` | 地址提取 | 从详细地址提取省/市 |
| `date_part` | 日期成分 | 从日期提取年/月/周/季度 |

### E.8 Step 7 · 预览界面显示

`PreviewTable`（L19495）负责最终数据展示：

```
PreviewTable.refresh() [L19768]
  │
  ├─ 1. 构建 ORDER BY（来自 sort_config）
  │
  ├─ 2. 调用 db.query_result() [L30285]
  │     SQL: SELECT 列1, 列2, ... FROM cr_xxx
  │          WHERE (预览筛选条件)
  │          ORDER BY (排序配置)
  │          LIMIT 50 OFFSET (分页)
  │
  ├─ 3. _populate_table(rows) [L19802]
  │     ├─ pd.DataFrame(rows)
  │     ├─ eval_formula_columns(df, columns)  ← 公式兜底计算
  │     ├─ 按 visible_fields 过滤列
  │     ├─ 填充 QTableWidget
  │     └─ _add_summary_row(df, cols)         ← 汇总行（如启用）
  │
  └─ 4. 恢复列宽/列顺序/分页状态
```

分页参数：每页 50 行，支持上一页/下一页导航。

### E.9 完整数据流图

```
CRM API / Excel / MySQL 外部表
        │
        ▼ (Phase 1: 同步 — 仅完整刷新时)
   ┌─────────────┐
   │ sr_主表      │  Source 表（原始数据）
   │ sr_关联表    │
   └──────┬──────┘
          │
          ▼ (Phase 2: 拼表 SQL)
   ┌──────────────────────────────────────────┐
   │ JoinSQLBuilder                           │
   │  ├─ 拓扑排序确定 JOIN 顺序               │
   │  ├─ 别名分配 (t0, t1, ...)               │
   │  ├─ SELECT 子句（直接列 + 聚合列）        │
   │  ├─ FROM + JOIN（含 ON 筛选条件）         │
   │  ├─ WHERE（主表筛选条件）                 │
   │  ├─ GROUP BY（如有聚合列）                │
   │  └─ 外层子查询（SQL 可翻译的公式列）      │
   └──────────────────┬───────────────────────┘
                      │
                      ▼ (CREATE TABLE AS SELECT)
               ┌──────────────┐
               │ cr_xxx       │  结果表（MySQL）
               │ (中间状态)    │
               └──────┬───────┘
                      │
                      ▼ (Phase 2.5~2.7: 后处理)
   ┌──────────────────────────────────────┐
   │ 地址提取后处理 → UPDATE MySQL        │
   │ 时间成分后处理 → UPDATE MySQL        │
   │ 公式列 pandas 回填 → UPDATE MySQL    │
   └──────────────────┬───────────────────┘
                      │
                      ▼ (Phase 3: 预览查询)
   ┌──────────────────────────────────────┐
   │ SELECT ... FROM cr_xxx               │
   │   WHERE (预览筛选)                    │
   │   ORDER BY (排序配置)                 │
   │   LIMIT/OFFSET (分页)                │
   └──────────────────┬───────────────────┘
                      │
                      ▼
   ┌──────────────────────────────────────┐
   │ PreviewTable._populate_table()       │
   │  ├─ 公式列兜底计算 (pandas)          │
   │  ├─ 汇总行（如启用）                 │
   │  └─ QTableWidget 显示               │
   └──────────────────────────────────────┘
```

### E.10 关键类速查

| 类 | 行号(约) | 职责 |
|------|----------|------|
| `ReportEditorPage` | L20706 | 编辑器主页面（三栏布局） |
| `ReportDefinition` | L3412 | 报表定义数据模型 |
| `FieldColumn` | L3375 | 显示列定义 |
| `JoinDefinition` | L3358 | 拼表关系定义 |
| `TableSelectorPanel` | L26995 | 左栏可用表面板 |
| `JoinCanvas` | L27645 | 中栏拼图画布 |
| `FieldConfigPanel` | L15496 | 右栏字段配置面板 |
| `FilterBar` | L17941 | 筛选条件栏 |
| `SortConfigDialog` | L19236 | 排序配置弹窗 |
| `PreviewTable` | L19495 | 预览表格（分页+公式+汇总） |
| `JoinSQLBuilder` | L4477 | 拼表 SQL 生成器 |
| `ReportRefreshWorker` | L6046 | 报表刷新编排器 |
| `ReportDatabase` | ~L30000 | MySQL 底层操作（query_result 等） |

### E.11 修订历史（附录 E）

| 日期 | 修改内容 | 修改人 |
|-----|---------|-------|
| 2026-06-21 | 初版：自定义报表编辑器完整 7 步数据流水线（选取→拼表→字段→筛选→排序→公式→预览），含数据结构、SQL 生成、三层公式兜底机制 | Codex |

---

## 附录 C：UI 窗口统一风格规范

> **铁律：所有窗口、弹窗、悬浮窗、提示框，背景必须用浅色，禁止深色背景。**

### C.1 背景色体系

| 颜色 | 用途 |
|------|------|
| `#FAFAFA` | 弹窗基类背景（CenteredPopupDialog）、工具栏、对话框主体 |
| `#F7F8FA` | 子面板标题栏 |
| `#F5F5F5` | 底部信息栏、隔行交替背景 |
| `#F0F2F5` | WebEngineView 预览区 |
| `#F8F8F8` | 条件行背景 |
| `#FFFFFF` | 输入框、搜索框、按钮、弹出菜单内部 |
| `transparent` | 搜索输入框、标签栏、滚动区域 |
| **禁止** | 任何 `#333` / `#222` / `#000` / `dark` / `#1a1a1a` 等深色背景 |

### C.2 文字色体系

| 颜色 | 用途 |
|------|------|
| `#333333` | 正文/标签/默认文字 |
| `#666666` | 次要说明文字 |
| `#999999` | 占位符/禁用状态 |
| `#1890FF` | 链接/主操作 hover |

### C.3 窗口标志组合速查表

| 标志组合 | 用途 | 何时使用 |
|---------|------|---------|
| `Popup \| FramelessWindowHint` | 下拉菜单、预设弹出 | 失焦自动关闭的轻量弹窗 |
| `Dialog \| FramelessWindowHint` | 筛选面板 | 需要保持打开、不 grab 鼠标的面板 |
| `Dialog \| FramelessWindowHint \| WindowStaysOnTopHint` | CheckablePopup | 需要置顶、避免鼠标 grab 的多选弹窗 |
| `Tool \| FramelessWindowHint` | 浮动工具窗口 | 自动补全列表 |
| `Tool \| FramelessWindowHint \| WindowStaysOnTopHint` | Tooltip | 提示信息 |
| `Window \| FramelessWindowHint` | 顶层输出弹窗 | 可调大小、可调透明度的常驻弹窗 |
| `FramelessWindowHint`（仅此） | CenteredPopupDialog | 居中模态/非模态弹窗 |

**禁止：** `Dialog` 不加 `FramelessWindowHint`（显示系统标题栏）；`Dialog` 不加 `NonModal`（默认模态冻结 UI）。

**禁止直接使用原生 Qt 对话框**（2026-06-21 新增）：
```python
# ❌ 禁止
QMessageBox.warning(self, "提示", "内容")
QMessageBox.information(self, "标题", "内容")
QMessageBox.question(self, "确认", "内容")
QInputDialog.getText(self, "标题", "提示")
QInputDialog.getItem(self, "标题", "提示", items)

# ✅ 必须使用 common.py 中的无边框替代函数
from common import frameless_input_text, frameless_input_getitem, frameless_message_box
frameless_message_box(self, "提示", "内容")                    # 替代 QMessageBox.warning/information
frameless_message_box(self, "确认", "内容",                     # 替代 QMessageBox.question
    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    QMessageBox.StandardButton.No)
text, ok = frameless_input_text(self, "标题", "提示")           # 替代 QInputDialog.getText
item, ok = frameless_input_getitem(self, "标题", "提示", items) # 替代 QInputDialog.getItem
```

### C.4 QDialog 模态规则

所有 QDialog 必须显式设置模态：
```python
self.setWindowModality(Qt.WindowModality.NonModal)  # 绝大多数弹窗
# 仅真正需要阻塞用户操作时才用 ApplicationModal
```

### C.5 圆角规范

| 圆角值 | 用途 |
|--------|------|
| `2px` | 小型按钮（预设方案默认/删除） |
| `4px` | 按钮、输入框、下拉框、搜索框、弹出菜单边框 |
| `6px` | 筛选面板外框 |
| `8px` | 大面板、WebEngineView 内容区 |

### C.6 阴影规范

```python
# 项目自定义弹窗标准阴影
shadow = QGraphicsDropShadowEffect()
shadow.setBlurRadius(24)
shadow.setOffset(0, 4)
shadow.setColor(QColor(0, 0, 0, 60))
```

### C.7 Tooltip 规范

```python
palette = QPalette()
palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFDF7"))  # 浅黄底
palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#333333"))
QToolTip.setPalette(palette)
```

### C.8 通用控件 QSS 模板

```
/* 普通按钮 */
QPushButton { border: 1px solid #D9D9D9; border-radius: 4px; padding: 4px 12px; font-size: 12px; background: #FFF; color: #333; }
QPushButton:hover { border-color: #1890FF; color: #1890FF; }

/* 主按钮 */
QPushButton#primary { background: #1890FF; color: #FFF; border: none; }
QPushButton#primary:hover { background: #40A9FF; }

/* 弹出菜单 */
QFrame { border: 1px solid #D9D9D9; border-radius: 4px; background: #FFF; }

/* 筛选面板 */
QFrame { border: 1px solid #E8E8E8; border-radius: 6px; background: #FFF; }
```

### C.9 新增窗口检查清单

- [ ] 背景色在浅色体系内？（`#FAFAFA` ~ `#FFFFFF`）
- [ ] 用了 `FramelessWindowHint`？
- [ ] QDialog 设置了 `setWindowModality`？
- [ ] 圆角、阴影、边框符合上述规范？
- [ ] 文字色用 `#333` 而非黑色？
- [ ] hover/active 状态颜色符合规范？

### C.10 修订历史（附录 C）

| 日期 | 修改内容 | 修改人 |
|-----|---------|-------|
| 2026-06-20 | 初版：从项目已有实现中提炼完整的 UI 窗口风格规范，含背景色体系、窗口标志速查、圆角/阴影/Tooltip/QSS 模板、检查清单 | Codex |
