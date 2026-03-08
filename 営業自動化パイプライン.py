"""
営業自動化パイプライン
Notionのパイプラインステージに応じて自動メール送信・ステータス更新を行う

パイプラインステージ:
  新規 → 連絡済み → フォローアップ → 商談中 → 成約 / 休止

処理フロー:
  1. Notionから対象レコードを取得
  2. メールアドレスがある宛先に営業メール送信
  3. ステータスを更新

使い方:
  確認のみ:  python 営業自動化パイプライン.py --dry-run
  新規のみ:  python 営業自動化パイプライン.py --stage 新規 --limit 50
  本番実行:  python 営業自動化パイプライン.py --stage 新規
"""

import argparse
import csv
import os
import smtplib
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID, PROPERTY_TYPES,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    FROM_EMAIL, FROM_NAME,
    EMAIL_BATCH_SIZE, EMAIL_DELAY_SECONDS,
)
from notion_client import query_all_pages, update_page


# 送信ログファイル
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
SEND_LOG_FILE = os.path.join(
    LOG_DIR, f"email_send_{datetime.now():%Y%m%d}.csv"
)

# パイプライン定義
PIPELINE_STAGES = {
    "新規": {
        "action": "initial_outreach",
        "next_stage": "連絡済み",
        "description": "初回営業メール送信",
    },
    "連絡済み": {
        "action": "followup",
        "next_stage": "フォローアップ",
        "description": "フォローアップメール送信",
    },
    "フォローアップ": {
        "action": "final_followup",
        "next_stage": "休止",
        "description": "最終フォローアップ → 休止",
    },
}

# カテゴリ別メールテンプレート
# {カテゴリキーワード: テンプレートセット名}
CATEGORY_TEMPLATES = {
    "歯科": "dental",
    "薬局": "pharmacy",
    "薬": "pharmacy",
    "調剤": "pharmacy",
    "ドラッグ": "pharmacy",
}

# デフォルト + カテゴリ別テンプレート
EMAIL_TEMPLATES = {
    # === 初回営業メール ===
    "initial_outreach": {
        "subject": "【ご挨拶】{事業者名}様へのご案内 - HIBURI株式会社",
        "body": """{事業者名} 御中

はじめまして。HIBURI株式会社の富高修司と申します。

この度、新規ご開業おめでとうございます。

弊社では医療機関様向けに、業務効率化・集患支援のサービスを
ご提供しております。

ご多忙のところ恐れ入りますが、もしご興味がございましたら
お気軽にご返信ください。

━━━━━━━━━━━━━━━━━━━━━━━━━━
HIBURI株式会社
富高修司（とみたか しゅうじ）
Email: shuji.tomitaka@hiburi.co.jp
━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    },
    "initial_outreach_dental": {
        "subject": "【ご挨拶】{事業者名}様へのご案内 - HIBURI株式会社",
        "body": """{事業者名} 御中

はじめまして。HIBURI株式会社の富高修司と申します。

この度、新規ご開業おめでとうございます。

弊社では歯科医院様向けに、Web集患・予約システム・
業務効率化のサービスをご提供しております。

開業初期は特に集患が重要かと存じます。
もしよろしければ、事例を含めた資料をお送りいたします。

━━━━━━━━━━━━━━━━━━━━━━━━━━
HIBURI株式会社
富高修司（とみたか しゅうじ）
Email: shuji.tomitaka@hiburi.co.jp
━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    },
    "initial_outreach_pharmacy": {
        "subject": "【ご挨拶】{事業者名}様へのご案内 - HIBURI株式会社",
        "body": """{事業者名} 御中

はじめまして。HIBURI株式会社の富高修司と申します。

この度、新規ご開局おめでとうございます。

弊社では薬局様向けに、オンライン服薬指導対応・
業務効率化のサービスをご提供しております。

ご興味がございましたら、お気軽にご返信ください。

━━━━━━━━━━━━━━━━━━━━━━━━━━
HIBURI株式会社
富高修司（とみたか しゅうじ）
Email: shuji.tomitaka@hiburi.co.jp
━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    },
    # === フォローアップメール ===
    "followup": {
        "subject": "【再度のご案内】{事業者名}様 - HIBURI株式会社",
        "body": """{事業者名} 御中

先日はご挨拶のメールをお送りさせていただきました。
HIBURI株式会社の富高です。

ご多忙のところ恐れ入りますが、改めてご案内申し上げます。

弊社サービスについてご不明点がございましたら、
お気軽にお問い合わせください。

━━━━━━━━━━━━━━━━━━━━━━━━━━
HIBURI株式会社
富高修司（とみたか しゅうじ）
Email: shuji.tomitaka@hiburi.co.jp
━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    },
    # === 最終フォローアップ ===
    "final_followup": {
        "subject": "【最終ご案内】{事業者名}様 - HIBURI株式会社",
        "body": """{事業者名} 御中

数回にわたりご連絡をさせていただきましたが、
お忙しいところ恐縮です。

本メールをもちまして一旦ご案内を控えさせていただきます。
ご興味をお持ちの際は、いつでもお気軽にご連絡ください。

━━━━━━━━━━━━━━━━━━━━━━━━━━
HIBURI株式会社
富高修司（とみたか しゅうじ）
Email: shuji.tomitaka@hiburi.co.jp
━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    },
}


def get_template_key(action, category):
    """カテゴリに応じたテンプレートキーを返す"""
    if category:
        for keyword, template_suffix in CATEGORY_TEMPLATES.items():
            if keyword in category:
                specific_key = f"{action}_{template_suffix}"
                if specific_key in EMAIL_TEMPLATES:
                    return specific_key
    return action


def send_email(to_email, subject, body):
    """メール送信"""
    if not SMTP_USER or not SMTP_PASSWORD:
        raise ValueError("SMTP_USER / SMTP_PASSWORD 環境変数が未設定")

    msg = MIMEMultipart()
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


def log_send(name, email, stage, action, status, error_msg=""):
    """送信ログをCSVに記録"""
    file_exists = os.path.exists(SEND_LOG_FILE)
    with open(SEND_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["datetime", "name", "email", "stage", "action", "status", "error"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name, email, stage, action, status, error_msg
        ])


def process_stage(page, stage_config, dry_run=False):
    """1レコードのパイプライン処理"""
    name = page.get("事業者名", "不明")
    email = page.get("メールアドレス", "")
    category = page.get("カテゴリ", "")
    page_id = page["_page_id"]
    action = stage_config["action"]
    next_stage = stage_config["next_stage"]
    current_stage = [k for k, v in PIPELINE_STAGES.items() if v == stage_config][0]

    # メールアドレスがない場合はスキップ（送信しない）
    if not email:
        print(f"  [{name}] メールアドレスなし → スキップ")
        log_send(name, "", current_stage, action, "skipped_no_email")
        return "no_email"

    # カテゴリに応じたテンプレート選択
    template_key = get_template_key(action, category)
    template = EMAIL_TEMPLATES.get(template_key)
    if not template:
        print(f"  [{name}] テンプレートなし: {template_key}")
        return "no_template"

    subject = template["subject"].format(事業者名=name)
    body = template["body"].format(事業者名=name)

    if dry_run:
        print(f"  [{name}] → {email} (テンプレート: {template_key})")
        print(f"    件名: {subject}")
        print(f"    → 次ステージ: {next_stage}")
        return "dry_run"

    try:
        send_email(email, subject, body)
        print(f"  [{name}] 送信完了 → {email}")

        # Notionステータス更新
        properties = {"パイプライン": {"select": {"name": next_stage}}}
        update_page(page_id, properties)

        log_send(name, email, current_stage, action, "success")
        return "success"
    except Exception as e:
        print(f"  [{name}] エラー: {e}")
        log_send(name, email, current_stage, action, "error", str(e))
        return "error"


def run_pipeline(target_stage=None, dry_run=False, limit=None):
    """パイプライン実行"""
    print(f"=== 営業自動化パイプライン ===")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"送信元: {FROM_NAME} <{FROM_EMAIL}>")
    print(f"モード: {'DRY-RUN（送信なし）' if dry_run else '本番'}")
    if limit:
        print(f"送信上限: {limit} 件")
    else:
        limit = EMAIL_BATCH_SIZE
        print(f"バッチ上限: {limit} 件")
    print()

    # Notionから全ページ取得
    print("Notionページ取得中...")
    pages = query_all_pages()
    print(f"  → {len(pages)} 件取得")

    # ステージ別に分類
    stage_counts = {}
    email_counts = {}
    for page in pages:
        stage = page.get("パイプライン", "未設定")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        if page.get("メールアドレス"):
            email_counts[stage] = email_counts.get(stage, 0) + 1

    print("\nステージ別件数:")
    for stage in sorted(stage_counts.keys()):
        count = stage_counts[stage]
        ec = email_counts.get(stage, 0)
        marker = " ← 処理対象" if stage in PIPELINE_STAGES else ""
        if target_stage and stage != target_stage:
            marker = ""
        print(f"  {stage}: {count} 件 (メールあり: {ec} 件){marker}")

    # 処理対象を絞り込み
    results = {"success": 0, "no_email": 0, "error": 0, "dry_run": 0, "no_template": 0}
    sent = 0

    for page in pages:
        if sent >= limit:
            print(f"\n送信上限 ({limit} 件) に達しました。残りは次回実行で処理します。")
            break

        stage = page.get("パイプライン", "")
        if stage not in PIPELINE_STAGES:
            continue
        if target_stage and stage != target_stage:
            continue

        stage_config = PIPELINE_STAGES[stage]
        result = process_stage(page, stage_config, dry_run=dry_run)
        results[result] = results.get(result, 0) + 1

        if result in ("success", "dry_run"):
            sent += 1
            if not dry_run and result == "success":
                time.sleep(EMAIL_DELAY_SECONDS)

    print(f"\n=== 処理完了 ===")
    print(f"  送信成功: {results.get('success', 0)}")
    print(f"  メールなし(スキップ): {results.get('no_email', 0)}")
    print(f"  エラー: {results.get('error', 0)}")
    if dry_run:
        print(f"  DRY-RUN: {results.get('dry_run', 0)}")
    print(f"  送信ログ: {SEND_LOG_FILE}")


def main():
    parser = argparse.ArgumentParser(description="営業自動化パイプライン")
    parser.add_argument("--stage", default=None,
                        help="処理対象ステージ (例: 新規, 連絡済み)")
    parser.add_argument("--limit", type=int, default=None,
                        help="送信件数上限 (デフォルト: config.EMAIL_BATCH_SIZE)")
    parser.add_argument("--dry-run", action="store_true",
                        help="確認のみ（メール送信・ステータス更新しない）")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        print("エラー: NOTION_TOKEN 環境変数を設定してください")
        sys.exit(1)

    if not args.dry_run and not SMTP_PASSWORD:
        print("エラー: SMTP_PASSWORD 環境変数を設定してください")
        print("  Google Workspace の場合、アプリパスワードを生成してください:")
        print("  https://myaccount.google.com/apppasswords")
        sys.exit(1)

    run_pipeline(
        target_stage=args.stage,
        dry_run=args.dry_run,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
