"""HIBURI営業自動化システム - 統合dry_runスクリプト

全パイプラインをdry_run=Trueで順番に実行し、
本番運用前の動作確認を行う。

実行順序:
  1. 厚生局スクレイピング (medical_scraper)
  2. メールテンプレート生成 (email_generator)
  3. ナビタパイプライン (navita_pipeline)
  4. 送信スケジューラー状態確認 (scheduler)

使い方:
  python run_all_dry.py
"""

import json
import logging
import sys
from datetime import date
from pathlib import Path

# ログ設定
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"dry_run_{date.today().isoformat()}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def section(title: str):
    border = "=" * 60
    logger.info("")
    logger.info(border)
    logger.info(f"  {title}")
    logger.info(border)


def dump(label: str, data: dict):
    logger.info(f"\n--- {label} ---")
    for line in json.dumps(data, ensure_ascii=False, indent=2).split("\n"):
        logger.info(line)


def step1_medical_scraper() -> dict:
    """Step 1: 厚生局スクレイピング (dry_run)"""
    section("Step 1: 厚生局スクレイピング")

    from src.medical_scraper import MedicalScraper

    scraper = MedicalScraper(dry_run=True)

    # 関東信越厚生局のみでテスト
    result = scraper.run(bureaus=["関東信越"])

    dump("厚生局スクレイピング結果", result)

    logger.info(f"取得件数: {result['total_scraped']}件")
    logger.info(f"CRM登録: {result['registration']['registered']}件")
    for cat, count in result.get("by_category", {}).items():
        logger.info(f"  {cat}: {count}件")

    return result


def step2_email_generator(scraper_result: dict) -> dict:
    """Step 2: 診療科別メールテンプレート生成"""
    section("Step 2: 診療科別メールテンプレート生成")

    from src.email_generator import EmailGenerator

    gen = EmailGenerator()

    categories = ["内科", "歯科", "薬局", "整形外科", "皮膚科"]
    results = {}

    for cat in categories:
        email = gen.generate({
            "name": f"サンプル{cat}クリニック",
            "category": cat,
        })
        results[cat] = email
        logger.info(f"\n[{cat}]")
        logger.info(f"  件名: {email['subject']}")
        logger.info(f"  本文: {email['body'][:100]}...")

    logger.info(f"\n生成完了: {len(results)}診療科のテンプレート")

    return {"categories_generated": len(results), "categories": list(results.keys())}


def step3_navita_pipeline() -> dict:
    """Step 3: ナビタパイプライン (dry_run)"""
    section("Step 3: ナビタパイプライン")

    from src.navita_pipeline import NavitaPipeline

    pipeline = NavitaPipeline(dry_run=True)
    result = pipeline.run()

    dump("ナビタパイプライン結果", result)

    logger.info(f"対象駅: {result.get('target_stations', 0)}/{result.get('total_stations', 0)}駅")
    logger.info(f"事業者検出: {result.get('businesses_found', 0)}件")
    logger.info(f"重複除外後: {result.get('after_dedup', 0)}件")
    for cat, count in result.get("by_category", {}).items():
        logger.info(f"  {cat}: {count}件")

    return result


def step4_scheduler_status() -> dict:
    """Step 4: 送信スケジューラー状態確認"""
    section("Step 4: 送信スケジューラー状態")

    from src.scheduler import SendScheduler

    scheduler = SendScheduler(dry_run=True)
    status = scheduler.status()

    dump("スケジューラー状態", status)

    can_send = status["can_send_now"]
    logger.info(f"現在時刻: {status['current_time']}")
    logger.info(f"送信可否: {'可能' if can_send else '不可'} ({status['reason']})")
    if not can_send:
        logger.info(f"次回送信可能: {status['next_available']}")
    logger.info(f"開業医パイプライン: 送信済{status['clinic']['sent_today']}/{status['clinic']['limit']}件")
    logger.info(f"ナビタパイプライン: 送信済{status['navita']['sent_today']}/{status['navita']['limit']}件")

    return status


def main():
    logger.info("=" * 60)
    logger.info("  HIBURI営業自動化システム - 統合dry_run")
    logger.info(f"  実行日: {date.today().isoformat()}")
    logger.info(f"  ログ: {log_file}")
    logger.info("=" * 60)

    all_results = {}

    try:
        # Step 1
        all_results["medical_scraper"] = step1_medical_scraper()

        # Step 2
        all_results["email_generator"] = step2_email_generator(all_results["medical_scraper"])

        # Step 3
        all_results["navita_pipeline"] = step3_navita_pipeline()

        # Step 4
        all_results["scheduler"] = step4_scheduler_status()

    except Exception as e:
        logger.error(f"エラーが発生しました: {e}", exc_info=True)
        all_results["error"] = str(e)

    # 最終サマリ
    section("最終サマリ")

    summary = {
        "date": date.today().isoformat(),
        "mode": "DRY_RUN",
        "log_file": str(log_file),
        "results": {
            "medical_scraper": {
                "scraped": all_results.get("medical_scraper", {}).get("total_scraped", 0),
                "registered": all_results.get("medical_scraper", {}).get("registration", {}).get("registered", 0),
            },
            "email_generator": {
                "templates": all_results.get("email_generator", {}).get("categories_generated", 0),
            },
            "navita_pipeline": {
                "stations": all_results.get("navita_pipeline", {}).get("target_stations", 0),
                "businesses": all_results.get("navita_pipeline", {}).get("after_dedup", 0),
            },
            "scheduler": {
                "can_send": all_results.get("scheduler", {}).get("can_send_now", False),
                "clinic_remaining": all_results.get("scheduler", {}).get("clinic", {}).get("remaining", 0),
                "navita_remaining": all_results.get("scheduler", {}).get("navita", {}).get("remaining", 0),
            },
        },
    }

    dump("統合dry_run結果", summary)

    if "error" in all_results:
        logger.error("dry_runでエラーが発生しました。上記のログを確認してください。")
        return 1

    logger.info("")
    logger.info("全パイプラインのdry_runが正常に完了しました。")
    logger.info("本番運用に移行するには、各モジュールの dry_run=False に変更してください。")
    logger.info("")

    return 0


if __name__ == "__main__":
    sys.exit(main())
