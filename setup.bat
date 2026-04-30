@echo off
cd /d "%~dp0"
echo =======================================
echo   Bank Statement DB - Setup
echo =======================================
echo.

REM -- Check Python
set PYEXE=
py --version >nul 2>&1
if not errorlevel 1 ( set PYEXE=py& goto :HAVE_PYTHON )
python --version >nul 2>&1
if not errorlevel 1 ( set PYEXE=python& goto :HAVE_PYTHON )

REM -- Python not found, download and install automatically
echo Python not found. Downloading Python 3.12.10...
echo (Internet connection required)
echo.

set PY_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe
set PY_INST=%TEMP%\python_setup_312.exe

powershell -NoProfile -Command "Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_INST%' -UseBasicParsing"

if not exist "%PY_INST%" (
    echo [ERROR] Download failed. Please install Python manually:
    echo   https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installing Python 3.12.10 (this may take a moment)...
"%PY_INST%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1

timeout /t 5 >nul
del "%PY_INST%" >nul 2>&1

REM -- Find newly installed Python
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe
py --version >nul 2>&1
if not errorlevel 1 ( set PYEXE=py )

if "%PYEXE%"=="" (
    echo.
    echo [ERROR] Python installation failed.
    echo   Please close this window, reopen setup.bat and try again.
    echo   Or install manually: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Python installed successfully!
echo.

:HAVE_PYTHON
for /f "tokens=*" %%v in ('"%PYEXE%" --version 2^>^&1') do echo Found: %%v
echo.
echo Installing required libraries...
echo.

"%PYEXE%" -m pip install --upgrade pip --quiet 2>nul
"%PYEXE%" -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [ERROR] Library installation failed.
    echo   Please check your internet connection and run setup.bat again.
    pause
    exit /b 1
)

echo.
echo =======================================
echo   Setup complete!
echo   Double-click run.bat to start.
echo =======================================
echo.
pause