@echo off
echo ============================================================
echo  CopyForge — Install Dependencies
echo ============================================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if %errorlevel% == 0 (
    echo.
    echo  All dependencies installed successfully.
    echo  Run CopyForge with:  python main.py
    echo  Or double-click:     run.bat
) else (
    echo.
    echo  Some packages failed to install.
    echo  blake3 is optional — the app will fall back to SHA256 if not available.
)

echo.
pause
