@echo off
setlocal
echo.
echo  ========================================
echo   Training Loss Explorer - Starting...
echo  ========================================
echo.

:: ==========================================
:: CONFIGURATION
:: ==========================================
set PORT=5006
:: Optional: where AI-Toolkit lives (or set "aitk_root" in plotvalloss_config.json)
:: set AITK_ROOT=C:\AI-Toolkit
:: ==========================================

:: Check for any process using the port and kill it safely
echo Checking for existing process on port %PORT%...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORT%"') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: Launch the browser with a 2-second delay to give Flask time to boot
echo Opening browser to http://127.0.0.1:%PORT%...
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:%PORT%"

:: Activate virtual environment and start app
echo Activating virtual environment and starting app...
if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
)

set PYTHONPATH=%~dp0
python "%~dp0plot_val_loss.py" --port %PORT% %*

if errorlevel 1 pause
