@echo off
setlocal
title NBK Engage
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ============================================================
    echo  First-time setup - installing NBK Engage, please wait...
    echo  This only happens once and may take a few minutes.
    echo ============================================================
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Python was not found. Please install Python 3.10+
        echo from https://www.python.org/downloads/ and make sure
        echo "Add python.exe to PATH" is checked during install.
        echo.
        pause
        exit /b 1
    )
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip >nul
    pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo.
    echo ============================================================
    echo  A .env file has been created for you at:
    echo  %cd%\.env
    echo.
    echo  Before continuing, open it and set:
    echo    DATABASE_URL   - your Supabase Postgres connection string
    echo    ADMIN_PASSWORD - a password for the trainer/host login
    echo.
    echo  See README.md sections 3 and 4 for step-by-step instructions.
    echo ============================================================
    echo.
    pause
    exit /b 0
)

echo.
echo Starting NBK Engage...
echo The Trainer Console will open automatically in its own app
echo window (not a browser tab). Participants join separately from
echo their own phone using the QR code / link shown in that window -
echo this launcher is only for YOUR screen.
echo.
echo Closing THIS window stops the server and ends the session.
echo.
echo If phones on the same Wi-Fi can't connect, allow Python through
echo Windows Defender Firewall when prompted, or see README.md
echo section 5 (Network access) for internet-wide access options.
echo.

start "" /min "%~dp0_open_app_window.bat"
streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless=true

pause
