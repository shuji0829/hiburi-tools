"""
定期実行スケジューラ
厚生局スクレイピング・Notion同期・営業パイプラインを自動実行

使い方:
  常駐実行:  python scheduler.py
  cron生成:  python scheduler.py --generate-cron
  単発実行:  python scheduler.py --run-now scraper|sync|pipeline|all
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime

try:
    import schedule
    import time as _time
except ImportError:
    schedule = None

from config import (
    SCHEDULE_SCRAPER_DAY, SCHEDULE_SCRAPER_TIME,
    SCHEDULE_SYNC_TIME, SCHEDULE_PIPELINE_TIME,
    SCHEDULE_HP_SEARCH_TIME, HP_SEARCH_DAILY_LIMIT, HP_SEARCH_EXCEL,
)

# ログ設定
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(LOG_DIR, f"scheduler_{datetime.now():%Y%m}.log"),
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# 各タスクのコマンド定義
PYTHON = sys.executable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TASKS = {
    "hp_search": {
        "name": "HP・メール検索",
        "command": [PYTHON, os.path.join(BASE_DIR, "hp_search.py"),
                    "--input", os.path.join(BASE_DIR, HP_SEARCH_EXCEL),
                    "--resume", "--limit", str(HP_SEARCH_DAILY_LIMIT)],
        "schedule": f"毎日 {SCHEDULE_HP_SEARCH_TIME}",
        "timeout": 3600,  # 1時間
    },
    "scraper": {
        "name": "厚生局スクレイパー",
        "command": [PYTHON, os.path.join(BASE_DIR, "厚生局スクレイパー.py"),
                    "--to-notion"],
        "schedule": f"毎月1日 {SCHEDULE_SCRAPER_TIME}",
    },
    "sync": {
        "name": "Excel→Notion同期",
        "command": [PYTHON, os.path.join(BASE_DIR, "notion_sync.py"),
                    "--excel", os.path.join(BASE_DIR, HP_SEARCH_EXCEL),
                    "--sheet", "新規指定一覧"],
        "schedule": f"毎日 {SCHEDULE_SYNC_TIME}",
    },
    "reverse_sync": {
        "name": "Notion→Excel逆同期",
        "command": [PYTHON, os.path.join(BASE_DIR, "notion_sync.py"),
                    "--excel", os.path.join(BASE_DIR, HP_SEARCH_EXCEL),
                    "--sheet", "新規指定一覧", "--reverse"],
        "schedule": f"毎日 {SCHEDULE_SYNC_TIME} (同期後)",
    },
    "pipeline": {
        "name": "営業メール一斉送信",
        "command": [PYTHON, os.path.join(BASE_DIR, "営業自動化パイプライン.py"),
                    "--stage", "新規"],
        "schedule": f"毎日 {SCHEDULE_PIPELINE_TIME}",
    },
}


def run_task(task_key):
    """タスクを実行"""
    task = TASKS.get(task_key)
    if not task:
        logger.error(f"不明なタスク: {task_key}")
        return False

    logger.info(f"=== {task['name']} 開始 ===")
    try:
        task_timeout = task.get("timeout", 600)
        result = subprocess.run(
            task["command"],
            capture_output=True,
            text=True,
            timeout=task_timeout,
            cwd=BASE_DIR,
        )
        if result.stdout:
            logger.info(result.stdout)
        if result.stderr:
            logger.warning(result.stderr)
        if result.returncode == 0:
            logger.info(f"=== {task['name']} 完了 ===")
            return True
        else:
            logger.error(f"=== {task['name']} 失敗 (code={result.returncode}) ===")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"=== {task['name']} タイムアウト ===")
        return False
    except Exception as e:
        logger.error(f"=== {task['name']} エラー: {e} ===")
        return False


def run_all():
    """全タスクを順次実行"""
    logger.info(f"===== 全タスク実行開始 ({datetime.now():%Y-%m-%d %H:%M}) =====")
    results = {}
    for key in ["hp_search", "scraper", "sync", "pipeline", "reverse_sync"]:
        results[key] = run_task(key)

    logger.info("===== 実行結果サマリー =====")
    for key, success in results.items():
        status = "成功" if success else "失敗"
        logger.info(f"  {TASKS[key]['name']}: {status}")
    return all(results.values())


def run_daily():
    """日次タスク: HP検索 → Notion同期 → メール送信 → 逆同期"""
    logger.info(f"===== 日次タスク開始 ({datetime.now():%Y-%m-%d %H:%M}) =====")
    for key in ["hp_search", "sync", "pipeline", "reverse_sync"]:
        run_task(key)


def run_monthly():
    """月次タスク（スクレイパー）"""
    logger.info(f"===== 月次タスク開始 ({datetime.now():%Y-%m-%d %H:%M}) =====")
    run_task("scraper")


def start_scheduler():
    """スケジューラを常駐実行"""
    if schedule is None:
        print("エラー: schedule ライブラリが必要です: pip install schedule")
        sys.exit(1)

    logger.info("スケジューラ起動")
    logger.info("スケジュール:")
    for key, task in TASKS.items():
        logger.info(f"  {task['name']}: {task['schedule']}")

    # HP検索（夜間20:00）
    schedule.every().day.at(SCHEDULE_HP_SEARCH_TIME).do(
        lambda: run_task("hp_search"))

    # Notion同期（深夜0:00）
    schedule.every().day.at(SCHEDULE_SYNC_TIME).do(
        lambda: [run_task("sync"), run_task("reverse_sync")])

    # メール送信（朝9:00）
    schedule.every().day.at(SCHEDULE_PIPELINE_TIME).do(
        lambda: run_task("pipeline"))

    # 月次タスク（毎月1日）
    def monthly_check():
        if datetime.now().day == 1:
            run_monthly()
    schedule.every().day.at(SCHEDULE_SCRAPER_TIME).do(monthly_check)

    logger.info("スケジューラ待機中... (Ctrl+C で停止)")
    try:
        while True:
            schedule.run_pending()
            _time.sleep(60)
    except KeyboardInterrupt:
        logger.info("スケジューラ停止")


def generate_cron():
    """crontab エントリを生成"""
    sync_h, sync_m = SCHEDULE_SYNC_TIME.split(":")
    pipe_h, pipe_m = SCHEDULE_PIPELINE_TIME.split(":")
    scrap_h, scrap_m = SCHEDULE_SCRAPER_TIME.split(":")

    print("# HIBURI Tools - 自動実行スケジュール")
    print("# 以下を crontab -e で追加してください")
    print()
    print(f"# 日次: Excel→Notion同期")
    print(f"{sync_m} {sync_h} * * * cd {BASE_DIR} && {PYTHON} notion_sync.py "
          f"--excel 営業リスト_sample.xlsx --sheet Sheet1 >> {LOG_DIR}/cron.log 2>&1")
    print()
    print(f"# 日次: 営業パイプライン")
    print(f"{pipe_m} {pipe_h} * * * cd {BASE_DIR} && {PYTHON} 営業自動化パイプライン.py "
          f">> {LOG_DIR}/cron.log 2>&1")
    print()
    print(f"# 日次: Notion→Excel逆同期 (パイプライン後)")
    rev_h = str(int(pipe_h) + 1).zfill(2)
    print(f"{pipe_m} {rev_h} * * * cd {BASE_DIR} && {PYTHON} notion_sync.py "
          f"--excel 営業リスト_sample.xlsx --sheet Sheet1 --reverse >> {LOG_DIR}/cron.log 2>&1")
    print()
    print(f"# 月次(1日): 厚生局スクレイパー")
    print(f"{scrap_m} {scrap_h} 1 * * cd {BASE_DIR} && {PYTHON} 厚生局スクレイパー.py "
          f"--to-notion >> {LOG_DIR}/cron.log 2>&1")


def generate_windows_tasks():
    """Windows タスクスケジューラ用コマンドを生成"""
    print("# HIBURI Tools - Windows タスクスケジューラ設定")
    print("# 以下を管理者権限のコマンドプロンプトで実行してください")
    print()
    for key, task in TASKS.items():
        cmd = " ".join(task["command"])
        sched_type = "/SC MONTHLY /D 1" if key == "scraper" else "/SC DAILY"
        time_val = SCHEDULE_SCRAPER_TIME if key == "scraper" else SCHEDULE_SYNC_TIME
        if key == "pipeline":
            time_val = SCHEDULE_PIPELINE_TIME
        print(f'schtasks /Create /TN "HIBURI_{key}" {sched_type} '
              f'/ST {time_val} /TR "{cmd}" /F')
    print()
    print("# 削除する場合:")
    for key in TASKS:
        print(f'schtasks /Delete /TN "HIBURI_{key}" /F')


def main():
    parser = argparse.ArgumentParser(description="HIBURI Tools スケジューラ")
    parser.add_argument("--run-now", choices=list(TASKS.keys()) + ["all", "daily", "monthly"],
                        help="指定タスクを即時実行")
    parser.add_argument("--generate-cron", action="store_true",
                        help="crontab エントリを生成")
    parser.add_argument("--generate-windows", action="store_true",
                        help="Windows タスクスケジューラ用コマンドを生成")
    args = parser.parse_args()

    if args.generate_cron:
        generate_cron()
    elif args.generate_windows:
        generate_windows_tasks()
    elif args.run_now:
        if args.run_now == "all":
            run_all()
        elif args.run_now == "daily":
            run_daily()
        elif args.run_now == "monthly":
            run_monthly()
        else:
            run_task(args.run_now)
    else:
        start_scheduler()


if __name__ == "__main__":
    main()
