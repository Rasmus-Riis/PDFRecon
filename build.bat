@echo off
echo ==========================================
echo   BUILDING PDFRECON
echo ==========================================

REM 1. Check if PDFRecon.exe is running and close it
echo Checking if PDFRecon is running...
tasklist /FI "IMAGENAME eq PDFRecon.exe" 2>NUL | find /I /N "PDFRecon.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo PDFRecon.exe is running. Attempting to close it...
    taskkill /F /IM PDFRecon.exe >NUL 2>&1
    timeout /t 2 /nobreak >NUL
)

REM 2. Clean previous builds
echo Cleaning previous builds...
if exist dist\PDFRecon.exe (
    echo Removing existing PDFRecon.exe...
    del /F /Q dist\PDFRecon.exe >NUL 2>&1
    if exist dist\PDFRecon.exe (
        echo ERROR: Cannot delete PDFRecon.exe. Please close it manually and try again.
        pause
        exit /b 1
    )
)
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM 2. Install/upgrade requirements
echo Installing requirements...
pip install -r requirements.txt
pip install pyinstaller

REM 3. Build the Executable using the spec file
echo Compiling with PyInstaller...
pyinstaller PDFRecon.spec

REM 4. Copy additional files to dist if needed
if exist exiftool.exe (
    echo Copying exiftool.exe to dist...
    copy exiftool.exe dist\ >nul 2>&1
)

if exist exiftool_files (
    echo Copying exiftool_files to dist...
    xcopy /E /I /Y exiftool_files dist\exiftool_files\ >nul 2>&1
)

if exist config.ini (
    echo Copying config.ini to dist...
    copy config.ini dist\ >nul 2>&1
)

echo ==========================================
echo      BUILD COMPLETE
echo ==========================================
echo Your executable is located in the 'dist' folder.
echo.
pause
