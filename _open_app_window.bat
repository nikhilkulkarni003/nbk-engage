@echo off
rem Helper for "Start NBK Engage.bat": waits for the local server to
rem come up, then opens the Trainer Console in a chromeless "app
rem window" (Edge --app mode) instead of a normal browser tab, so it
rem looks and feels like a native desktop app rather than a website.
setlocal
set count=0

:waitloop
curl -s -o nul -f http://localhost:8501
if %errorlevel%==0 goto ready
set /a count+=1
if %count% geq 30 goto giveup
timeout /t 1 /nobreak >nul
goto waitloop

:ready
start "" msedge --app=http://localhost:8501/?mode=host --window-size=1360,900
exit /b 0

:giveup
echo NBK Engage server did not respond within 30 seconds.
echo Open http://localhost:8501/?mode=host manually once it starts.
exit /b 1
