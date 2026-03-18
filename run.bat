@echo off
cd /d C:\DEV\discord-bot
call .venv\Scripts\activate

:: 로그 폴더 생성
if not exist logs mkdir logs

:: 날짜별 로그 파일
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set dt=%%I
set LOGFILE=logs\bot_%dt:~0,4%-%dt:~4,2%-%dt:~6,2%.txt

echo [%date% %time%] 봇 시작 >> "%LOGFILE%"
set PYTHONIOENCODING=utf-8
python bot.py 2>&1 | powershell -Command "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; $input | Tee-Object -Append -FilePath \"%LOGFILE%\""
echo [%date% %time%] 봇 종료 >> "%LOGFILE%"

pause
