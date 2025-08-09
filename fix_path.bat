@echo off
echo 修复Windows PATH环境变量以包含npm全局包路径

REM 获取当前用户PATH
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set CURRENT_PATH=%%B

REM 检查是否已经包含npm路径
echo %CURRENT_PATH% | find "AppData\Roaming\npm" >nul
if %errorlevel%==0 (
    echo npm路径已经在PATH中
) else (
    echo 添加npm路径到PATH...
    setx PATH "%CURRENT_PATH%;%USERPROFILE%\AppData\Roaming\npm"
    echo 完成！请重新打开命令提示符窗口。
)

echo.
echo 测试命令：claude --version
pause