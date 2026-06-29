@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo ============================================
echo   精简版 EXE 打包脚本
echo   保留模块：文件生成、订单转合同、文件移动、设置
echo ============================================
echo.

:: 切换到脚本所在目录
cd /d "%~dp0"

:: 检查虚拟环境
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv\Scripts\python.exe
    echo 请先创建虚拟环境并安装依赖：python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

:: 检查 PyInstaller
".venv\Scripts\pip.exe" show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装 PyInstaller...
    ".venv\Scripts\pip.exe" install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)

echo [1/3] 清理旧的构建文件...
if exist "build" rmdir /s /q "build"
if exist "dist\数据批量处理工具" rmdir /s /q "dist\数据批量处理工具"

echo [2/3] 运行 PyInstaller 打包...
".venv\Scripts\pyinstaller.exe" build_lite.spec --noconfirm
if errorlevel 1 (
    echo [错误] PyInstaller 打包失败
    pause
    exit /b 1
)

echo [3/3] 复制外部资源文件...
:: 复制配置文件（覆盖 PyInstaller 打包的，确保是最新的）
if exist ".config" (
    xcopy /E /I /Y ".config\*.json" "dist\数据批量处理工具\.config\" >nul
    echo   - .config/*.json
)
:: 复制模板文件
if exist "template" (
    xcopy /E /I /Y "template\*.docx" "dist\数据批量处理工具\template\" >nul
    xcopy /E /I /Y "template\*.doc"  "dist\数据批量处理工具\template\" >nul 2>&1
    xcopy /E /I /Y "template\*.xlsx" "dist\数据批量处理工具\template\" >nul 2>&1
    xcopy /E /I /Y "template\*.XLS"  "dist\数据批量处理工具\template\" >nul 2>&1
    echo   - template/
)
:: 复制城市数据
if exist "ChinaCitys.json" (
    copy /Y "ChinaCitys.json" "dist\数据批量处理工具\" >nul
    echo   - ChinaCitys.json
)

echo.
echo ============================================
echo   打包完成！
echo   输出目录：dist\数据批量处理工具\
echo   主程序：  dist\数据批量处理工具\数据批量处理工具.exe
echo ============================================
echo.
echo 使用方法：
echo   将 dist\数据批量处理工具 整个文件夹复制到目标电脑即可运行
echo   配置文件 .config 可在外部编辑，无需重新打包
echo.
pause
