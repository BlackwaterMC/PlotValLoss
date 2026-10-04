@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:: ==========================================================================
::  PlotValLoss installer
::  Creates .\venv (git-ignored) and installs requirements.txt into it.
::  Safe to run again at any time: it detects a missing, partial or broken
::  install and repairs it, and does nothing if everything is already fine.
:: ==========================================================================

set "VENV_DIR=%~dp0venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "MARKER=%VENV_DIR%\.plotvalloss_installed"
set "REQS=%~dp0requirements.txt"
set "PY_CMD="
set "PIP_EXTRA="

echo.
echo  ========================================
echo   PlotValLoss - Installer
echo  ========================================
echo.

:: ---- 1. Is the project folder what we expect? ----------------------------
if not exist "%REQS%" (
    echo  [!] I can't find requirements.txt next to this installer.
    echo.
    echo      Expected it here: %REQS%
    echo.
    echo      What to try: make sure you extracted / cloned the WHOLE project
    echo      folder, and that Install.bat is still inside it.
    goto :fail
)

:: ---- 2. Is the existing venv (if any) healthy? ---------------------------
if not exist "%VENV_DIR%" goto :need_python
echo  Found an existing venv folder. Checking that it is complete...

if not exist "%VENV_PY%" (
    echo  [!] The venv folder exists but has no python.exe inside.
    echo      That usually means an earlier install was interrupted.
    goto :rebuild
)

"%VENV_PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo  [!] The venv's python.exe won't start.
    echo      This happens when Python was uninstalled or upgraded after the
    echo      venv was made, or when the folder was copied from another PC.
    goto :rebuild
)

"%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo  [!] The venv has no working pip, so packages can't be installed.
    goto :rebuild
)

"%VENV_PY%" -c "import flask, pytest" >nul 2>&1
if errorlevel 1 (
    echo  [!] The venv is missing some required packages.
    echo      I'll install them into the existing venv - no need to start over.
    goto :install_packages
)

if not exist "%MARKER%" (
    echo  [!] The packages are there, but I never recorded a finished install.
    echo      I'll re-run the package install to be sure.
    goto :install_packages
)

echo.
echo  [OK] Everything is already installed and working. Nothing to do.
goto :configure_aitk

:: ---- 3. Rebuild a broken venv --------------------------------------------
:rebuild
echo.
echo  I'll delete the broken venv folder and make a fresh one.
echo  (It only contains downloaded packages - none of your data or settings.)
echo.
rmdir /s /q "%VENV_DIR%" >nul 2>&1
if exist "%VENV_DIR%" (
    echo  [X] I couldn't delete the old venv folder:
    echo      %VENV_DIR%
    echo.
    echo      What to try:
    echo        - Close PlotValLoss if it's running, and any terminal or editor
    echo          that has the venv open, then run this installer again.
    echo        - Or delete the "venv" folder yourself in File Explorer.
    goto :fail
)

:: ---- 4. Find a usable Python ---------------------------------------------
:need_python
echo  Looking for Python 3.10 or newer...
call :try_python py -3
if not defined PY_CMD call :try_python python
if not defined PY_CMD call :try_python python3
if not defined PY_CMD goto :no_python
echo  Using: %PY_CMD%
echo.

:: ---- 5. Create the venv --------------------------------------------------
echo  Creating the virtual environment in "venv" (a few seconds)...
%PY_CMD% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo.
    echo  [X] Python couldn't create the virtual environment.
    echo.
    echo      What to try:
    echo        - Make sure this folder isn't read-only or inside a protected
    echo          location - try somewhere like C:\GitProjects instead.
    echo        - Check your antivirus isn't blocking Python.
    echo        - If Python came from the Microsoft Store, try the installer
    echo          from https://www.python.org/downloads/ instead.
    goto :fail
)
if not exist "%VENV_PY%" (
    echo.
    echo  [X] The venv was created but python.exe is missing from it.
    echo      Your Python install may be damaged. Reinstalling Python from
    echo      https://www.python.org/downloads/ usually fixes this.
    goto :fail
)

:: ---- 6. Install packages -------------------------------------------------
:install_packages
:: Remove the "finished" marker first so an interrupted install is detectable.
if exist "%MARKER%" del /q "%MARKER%" >nul 2>&1

echo.
echo  Installing packages from requirements.txt...
echo  (This needs an internet connection and can take a minute.)
echo.
"%VENV_PY%" -m pip install --disable-pip-version-check %PIP_EXTRA% -r "%REQS%"
if errorlevel 1 (
    echo.
    echo  [X] Installing the packages failed. Scroll up for pip's own message.
    echo.
    echo      Common causes:
    echo        - No internet connection, or a VPN / proxy / firewall blocking
    echo          pypi.org. Check you can open https://pypi.org in a browser.
    echo        - Your Python is too old for the pinned versions
    echo          ^(3.10 or newer is needed^).
    echo        - A package download was cut off. Just run this installer again;
    echo          it will pick up where it left off.
    goto :fail
)

:: ---- 7. Verify, then record success --------------------------------------
echo.
echo  Checking that the install actually works...
"%VENV_PY%" -c "import flask, pytest" >nul 2>&1
if errorlevel 1 (
    if not defined PIP_EXTRA (
        echo.
        echo  [!] Some package files look damaged or half-written.
        echo      Reinstalling everything from scratch ^(one more try^)...
        set "PIP_EXTRA=--force-reinstall"
        goto :install_packages
    )
    echo.
    echo  [X] Even after a forced reinstall, Flask / pytest can't be imported.
    echo      Delete the "venv" folder and run this installer once more for a
    echo      clean start. If it still fails, check your antivirus isn't
    echo      quarantining files.
    goto :fail
)
> "%MARKER%" echo ok
if errorlevel 1 (
    echo  [!] Installed fine, but I couldn't write my "finished" note.
    echo      Harmless - I'll just re-check next time.
)

:: ---- 8. Tell the app where AI-Toolkit lives ------------------------------
:configure_aitk
set "PYTHONPATH=%~dp0"
if defined AITK_ROOT goto :aitk_done
"%VENV_PY%" -c "import sys, loss_reader; sys.exit(0 if loss_reader.resolve_aitk_root() else 1)" >nul 2>&1
if not errorlevel 1 goto :aitk_done
if /i "%~1"=="/nopause" goto :aitk_skipped

echo.
echo  ----------------------------------------
echo   Where is AI-Toolkit?
echo  ----------------------------------------
echo  PlotValLoss reads your training runs from AI-Toolkit's "output" folder.
echo  Enter the AI-Toolkit folder (the one that contains "output"),
echo  for example  C:\AI-Toolkit
echo  Or just press Enter to skip - you can set it later.
:aitk_ask
echo.
set "PVL_ROOT="
set /p "PVL_ROOT=  AI-Toolkit folder: "
if not defined PVL_ROOT goto :aitk_skipped
set "PVL_ROOT=%PVL_ROOT:"=%"
if not exist "%PVL_ROOT%\" goto :aitk_not_found
if not exist "%PVL_ROOT%\output\" goto :aitk_no_output
"%VENV_PY%" -c "import os, config_store as c; p = c.config_path_for('plotvalloss'); d = c.load_config(p); d['aitk_root'] = os.environ['PVL_ROOT']; c.save_config(p, d)" >nul 2>&1
if errorlevel 1 goto :aitk_write_failed
echo.
echo  [OK] Saved to plotvalloss_config.json (git-ignored, specific to this PC).
goto :aitk_done

:aitk_not_found
echo.
echo  [!] I can't find that folder. Check the spelling and try again,
echo      or press Enter to skip.
goto :aitk_ask

:aitk_no_output
echo.
echo  [!] That folder exists, but it has no "output" folder inside it.
echo      Make sure you gave the AI-Toolkit folder itself, not a sub-folder.
echo      Try again, or press Enter to skip.
goto :aitk_ask

:aitk_write_failed
echo.
echo  [!] I couldn't save that setting. Not a big deal - you can add it by hand:
echo      create plotvalloss_config.json in this folder containing
echo          {"aitk_root": "C:/AI-Toolkit"}
echo      ^(forward slashes work fine in the path^).
goto :aitk_done

:aitk_skipped
echo.
echo  Skipped. Before using the app, tell it where AI-Toolkit is by either:
echo    - running Install.bat again, or
echo    - creating plotvalloss_config.json here with {"aitk_root": "C:/AI-Toolkit"}
echo    - or setting the AITK_ROOT environment variable.

:aitk_done

:success
echo.
echo  ========================================
echo   All done!
echo  ========================================
echo.
echo   Start the app by double-clicking PlotValLoss.bat
echo.
if /i not "%~1"=="/nopause" pause
exit /b 0

:: ---- Python not found ----------------------------------------------------
:no_python
echo.
echo  [X] I couldn't find Python 3.10 or newer on this computer.
echo.
echo      What to do:
echo        1. Download Python from https://www.python.org/downloads/
echo        2. Run its installer and TICK "Add python.exe to PATH" on the
echo           first screen.
echo        3. Close this window and run Install.bat again.
echo.
echo      Already installed it? Windows may be intercepting "python" with a
echo      Microsoft Store shortcut. Turn it off under Settings ^> Apps ^>
echo      Advanced app settings ^> App execution aliases.
goto :fail

:: ---- Shared failure exit -------------------------------------------------
:fail
echo.
echo  The install did NOT finish. Nothing is lost - fix the problem above and
echo  run Install.bat again. It will pick up from wherever it stopped.
echo.
if /i not "%~1"=="/nopause" pause
exit /b 1

:: ---- Subroutine: try_python <command...> ---------------------------------
:: Sets PY_CMD if the command runs Python 3.10+. Ignores the Microsoft Store
:: stub, which exists on PATH but fails when run.
:try_python
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=%*"
exit /b 0
