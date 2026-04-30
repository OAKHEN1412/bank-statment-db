@echo off
cd /d "%~dp0"
echo =======================================
echo   Bank Statement DB
echo =======================================
echo.

REM -- Find Python
set PYEXE=
py --version >nul 2>&1
if not errorlevel 1 ( set PYEXE=py& goto :CHECK_DEPS )
python --version >nul 2>&1
if not errorlevel 1 ( set PYEXE=python& goto :CHECK_DEPS )

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe
if not "%PYEXE%"=="" goto :CHECK_DEPS

echo [ERROR] Python not found. Please run setup.bat first.
pause
exit /b 1

:CHECK_DEPS
"%PYEXE%" -c "import flask, pdfplumber, openpyxl" >nul 2>&1
if errorlevel 1 (
    echo [!] Library not installed. Please run setup.bat first.
    pause
    exit /b 1
)

echo Starting server...
echo Opening browser at http://127.0.0.1:5000
echo Press Ctrl+C to stop.
echo.

start "" cmd /c "timeout /t 2 >nul && start http://127.0.0.1:5000"

"%PYEXE%" app.py
pause