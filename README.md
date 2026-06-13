 # Project_001_数据批量文档处理工具

 ## 项目概述
 基于 PyQt6 构建的桌面级数据批量文档处理工具，集数据处理、文档生成、PDF 水印、BI 报表等功能于一体。

 ## 核心功能
 - **数据处理** — 订单转合同、业务查询、部门管理等数据流程处理
 - **批量文档生成** — 基于模板批量生成 Word 文档（含自定义报表）
 - **PDF 处理** — 批量 PDF 文件生成与加水印
 - **BI 报表** — 数据可视化与业务智能图表展示
 - **文件管理** — 文件整理与自动移动工具
 - **网络与认证** — 网络请求封装与用户认证模块

 ## 技术栈
 - **界面框架**：PyQt6 / PyQt6-WebEngine
 - **语言**：Python 3.x
 - **依赖管理**：`requirements.txt`

 ## 项目结构
 ```
 Project_001_数据批量文档处理工具\
 ├── Project\               # 子项目模块目录
 │   ├── app\               # 应用主逻辑
 │   ├── docs\              # 文档模板
 │   ├── template\          # 通用模板
 │   ├── User\              # 用户模块
 │   ├── Profiles\          # 配置方案
 │   ├── examples\          # 示例文件
 │   ├── echarts\           # ECharts 图表集成
 │   └── Cache\             # 缓存
 ├── auth.py                # 认证模块
 ├── bi_dashboard.py        # BI 仪表盘
 ├── common.py              # 公共工具函数
 ├── core.py                # 核心逻辑
 ├── custom_report.py       # 自定义报表
 ├── department.py          # 部门管理
 ├── file_generation.py     # 文件生成（Word/PDF）
 ├── file_mover.py          # 文件移动工具
 ├── network.py             # 网络请求封装
 ├── object_query.py        # 对象查询模块
 ├── order_to_contract.py   # 订单转合同
 ├── pdf_watermark.py       # PDF 水印处理
 ├── Project_zjt_3.5.8.py   # 主程序入口
 └── requirements.txt       # Python 依赖
 ```

 ## 快速开始
 ```bash
 pip install -r requirements.txt
 python Project_zjt_3.5.8.py
 ```

 ## 源项目
 从 `D:\Project` 迁移至此，按 Codex 项目命名规范整理。
