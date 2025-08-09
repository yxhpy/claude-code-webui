@echo off
echo ========================================
echo Claude Code 环境验证工具
echo ========================================
echo.

echo 1. 检查 claude 命令...
claude --version >nul 2>&1
if %errorlevel%==0 (
    echo ✓ claude 命令可用
    claude --version
) else (
    echo ✗ claude 命令不可用
    echo   请确保 npm 全局路径在 PATH 中
)

echo.
echo 2. 检查 ccui 命令...
ccui --version >nul 2>&1
if %errorlevel%==0 (
    echo ✓ ccui 命令可用
    ccui --version
) else (
    echo ✗ ccui 命令不可用
    echo   尝试使用完整路径...
    "%USERPROFILE%\AppData\Local\bin\ccui.bat" --version >nul 2>&1
    if %errorlevel%==0 (
        echo ✓ ccui.bat 文件存在并可执行
        "%USERPROFILE%\AppData\Local\bin\ccui.bat" --version
    ) else (
        echo ✗ ccui.bat 无法执行
    )
)

echo.
echo 3. 检查环境文件...
if exist "%USERPROFILE%\.claude-code-env.bat" (
    echo ✓ 环境文件存在: %USERPROFILE%\.claude-code-env.bat
    echo 内容:
    type "%USERPROFILE%\.claude-code-env.bat"
) else (
    echo ✗ 环境文件不存在
)

echo.
echo 4. 当前 PATH 变量包含的关键路径:
echo %PATH% | findstr /i "npm" && echo ✓ 包含 npm 路径 || echo ✗ 不包含 npm 路径
echo %PATH% | findstr /i "AppData\\Local\\bin" && echo ✓ 包含 AppData\Local\bin 路径 || echo ✗ 不包含 AppData\Local\bin 路径

echo.
echo ========================================
echo 如果命令不可用，请:
echo 1. 关闭此窗口
echo 2. 重新打开新的命令提示符
echo 3. 重新运行此脚本
echo ========================================
pause