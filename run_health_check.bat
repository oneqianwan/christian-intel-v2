@echo off
chcp 65001 >nul
cd /d C:\Users\baiwan\christian-intel-v2\backend
python cron_health_check.py
echo.
echo 健康巡检完成，按任意键关闭...
pause >nul
