"""
Windows每日定时采集脚本
用法：python schedule_daily.py
"""

import os

PROJECT_ROOT = r"c:\Users\baiwan\christian-intel-v2"
BACKEND_ROOT = rf"{PROJECT_ROOT}\backend"
LOG_ROOT = rf"{PROJECT_ROOT}\logs"

SCRIPT = rf"""
@echo off
echo [%date% %time%] 启动每日定时采集...

cd /d {BACKEND_ROOT}

if not exist ..\logs mkdir ..\logs

python -c "from services.rss_collector import collect_rss; collect_rss()" >> ..\logs\rss_%date:~-4,4%%date:~-10,2%%date:~-7,2%.log 2>&1
python data\batch_collect.py --source newsapi --delay 5 >> ..\logs\batch_%date:~-4,4%%date:~-10,2%%date:~-7,2%.log 2>&1

echo [%date% %time%] 采集完成
"""

SCHEDULE_CMD = rf"""
schtasks /create /tn "CIO-Daily-Collection" /tr "{BACKEND_ROOT}\daily_run.bat" /sc daily /st 02:00 /f
"""


def setup():
    """创建定时任务"""
    os.makedirs(LOG_ROOT, exist_ok=True)

    bat_path = rf"{BACKEND_ROOT}\daily_run.bat"
    with open(bat_path, "w", encoding="utf-8") as handle:
        handle.write(SCRIPT.strip() + "\n")

    print(f"✅ 已创建: {bat_path}")
    print("\n请用管理员权限运行以下命令创建定时任务:")
    print(f"  {SCHEDULE_CMD.strip()}")
    print("\n或手动操作:")
    print("  1. 打开 任务计划程序")
    print("  2. 创建基本任务 → 名称: CIO-Daily-Collection")
    print("  3. 触发器: 每天 2:00")
    print("  4. 操作: 启动程序 → daily_run.bat")
    print(f"\n日志目录: {LOG_ROOT}")


if __name__ == "__main__":
    setup()
