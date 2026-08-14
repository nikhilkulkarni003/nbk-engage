@echo off
rem Helper for "Start NBK Engage.bat": waits for the local server to
rem come up, then opens NBK Engage in a chromeless "app window" (Edge
rem --app mode) instead of a normal browser tab, so it looks and feels
rem like a native desktop app rather than a website.
rem
rem Opens the bare URL (no ?mode=host) so the local launcher lands on
rem the same participant-join screen as the deployed web URL, with
rem "Are you the trainer?" to get to the host console from there --
rem previously this went straight to ?mode=host, which also had the
rem side effect of making the in-app "Admin" button silently not work
rem (the URL's ?mode=host kept overriding the role on every rerun; see
rem app.py::_determine_role).
rem Budget is 120s (not the previous 30s) -- a genuinely COLD first run
rem (fresh venv, first-ever import of pandas/matplotlib/wordcloud/
rem sqlalchemy, often slowed further by antivirus real-time scanning
rem the just-installed packages) can comfortably take longer than 30s
rem to start listening, even though the polling logic itself was
rem already correct. This is what caused "works on the 2nd run" --
rem the 2nd run's imports are warm (compiled .pyc already cached), so
rem it starts fast enough to beat the old 30s budget, masking the
rem real problem on run 1.
setlocal
set count=0

:waitloop
curl -s -o nul -f http://localhost:8501
if %errorlevel%==0 goto ready
set /a count+=1
if %count% geq 120 goto giveup
timeout /t 1 /nobreak >nul
goto waitloop

:ready
start "" msedge --app=http://localhost:8501/ --window-size=1360,900
exit /b 0

:giveup
echo NBK Engage server did not respond within 120 seconds.
echo Open http://localhost:8501/ manually once it starts.
exit /b 1
