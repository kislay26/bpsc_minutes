@echo off
setlocal
cd /d "%~dp0"
set "PATH=%ProgramFiles%\Tesseract-OCR;%PATH%"
"%~dp0.venv\Scripts\python.exe" -X utf8 "%~dp0bot.py" %*
exit /b %errorlevel%
