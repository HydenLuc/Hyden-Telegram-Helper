@echo off
REM 桌面控制面板入口（Windows）：
REM 用 Edge/Chrome app 模式打开 dashboard —— 无地址栏独立窗口，体验等同桌面应用。
REM 用法：panel.bat [端口]   （默认 8090）
setlocal
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8090"
set "URL=http://localhost:%PORT%"

REM 先确认服务在跑（Windows 10 起自带 curl）。提示用英文：cmd 默认代码页下中文会乱码
where curl >nul 2>nul
if not errorlevel 1 (
    curl -s -m 2 -o NUL "%URL%"
    if errorlevel 1 (
        echo Dashboard is not responding at %URL%
        echo Start it first:  docker compose up -d
        pause
        exit /b 1
    )
)

set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if exist "%EDGE%" (
    start "" "%EDGE%" --app=%URL%
) else if exist "%CHROME%" (
    start "" "%CHROME%" --app=%URL%
) else (
    start "" %URL%
)
endlocal
