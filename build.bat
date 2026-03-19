@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Always run from the folder containing this script
cd /d "%~dp0"

echo ==========================================
echo   BUILDING PDFRECON
echo ==========================================
echo Working directory: %CD%

REM 0. Quick sanity checks
if not exist PDFRecon.spec (
    echo ERROR: PDFRecon.spec not found in %CD%
    pause
    exit /b 1
)
if not exist src\config.py (
    echo ERROR: src\config.py not found in %CD%
    pause
    exit /b 1
)

REM 1. Show version being built (prevents building from wrong folder)
REM Parse APP_VERSION directly from src\config.py (avoid cmd parsing issues with python -c)
echo Detecting APP_VERSION from src\config.py...
set "APP_VERSION="
for /f "usebackq tokens=1,2 delims==" %%a in (`findstr /b /c:"APP_VERSION" "src\config.py"`) do (
    set "APP_VERSION=%%b"
)
REM Trim spaces and surrounding quotes
if defined APP_VERSION (
    set "APP_VERSION=!APP_VERSION: =!"
    set "APP_VERSION=!APP_VERSION:"=!"
    echo Building version: !APP_VERSION!
) else (
    echo WARNING: Could not read APP_VERSION from src\config.py. Continuing...
)

REM 2. Check if PDFRecon.exe is running and close it
echo Checking if PDFRecon.exe is running...
tasklist /FI "IMAGENAME eq PDFRecon.exe" 2>NUL | find /I /N "PDFRecon.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo PDFRecon.exe is running. Attempting to close it...
    taskkill /F /IM PDFRecon.exe >NUL 2>&1
    timeout /t 2 /nobreak >NUL
)

REM 3. Clean previous builds + caches
echo Cleaning previous builds and caches...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist "__pycache__" rmdir /s /q "__pycache__"
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
for %%f in (*.pyc) do @del /f /q "%%f" >NUL 2>&1

REM 4. Install/upgrade requirements
echo Installing requirements...
python -m pip install -r requirements.txt
python -m pip install pyinstaller

REM 5. Build the Executable using the spec file (clean build)
echo Compiling with PyInstaller...
python -m PyInstaller --noconfirm --clean PDFRecon.spec

REM 6. Copy additional files to dist if needed
if exist exiftool.exe (
    echo Copying exiftool.exe to dist...
    copy /Y exiftool.exe dist\ >nul 2>&1
)

if exist exiftool_files (
    echo Copying exiftool_files to dist...
    xcopy /E /I /Y exiftool_files dist\exiftool_files\ >nul 2>&1
)

if exist config.ini (
    echo Copying config.ini to dist...
    copy /Y config.ini dist\ >nul 2>&1
)

echo ==========================================
echo      BUILD COMPLETE
echo ==========================================
echo Your executable is located in the 'dist' folder.
echo.
pause
