@echo off
REM S2T launcher - double-click to start local speech-to-text dictation.
REM Keeps this window open so you can see status/errors; close it to stop the app.

title S2T - Local Dictation
cd /d "%~dp0"

echo Starting S2T...
echo Wait for the tray microphone icon to turn GRAY, then hold Right Ctrl to dictate.
echo Close this window (or right-click the tray icon and choose Quit) to stop.
echo.

python main.py

echo.
echo S2T has stopped. Press any key to close this window.
pause >nul
