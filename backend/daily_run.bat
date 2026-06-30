@echo off
chcp 65001 >nul
setlocal

for /f "tokens=*" %%a in ('powershell -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%a

echo [%date% %time%] Starting daily collection...

cd /d c:\Users\baiwan\christian-intel-v2\backend

if not exist ..\logs mkdir ..\logs

echo [%date% %time%] Starting RSS collection...
python -c "from services.rss_collector import collect_rss; collect_rss()" 1>> ..\logs\rss_%TODAY%.log 2>&1
echo [%date% %time%] RSS collection finished

echo [%date% %time%] Starting NewsAPI batch collection...
python data\batch_collect.py --source newsapi --delay 5 --limit 30 1>> ..\logs\batch_%TODAY%.log 2>&1
echo [%date% %time%] NewsAPI batch collection finished

echo [%date% %time%] All collection finished
