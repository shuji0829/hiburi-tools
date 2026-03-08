"""
営業自動化パイプライン
Notionのパイプラインステージに応じて自動メール送信・ステータス更新を行う

パイプラインステージ:
  新規 → 連絡済み → フォローアップ → 商談中 → 成約 / 休止

処理フロー:
  1. Notionから対象レコードを取得
  2. ステージごとのアクションを実行
  3. ステータスを更新
"""

import argparse
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import NOTION_TOKEN, NOTION_DATABASE_ID, PROPERTY_TYPES
from notion_client import query_all_pages, update_page, build_notion_properties


# SMTP設定（環境変数から取得）
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER)
FROM_NAME = os.environ.get("FROM_NAME", "HIBURI株式会社")

# パイプライン定義: {現ステージ: (アクション, 次ステージ)}
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

# メールテンプレート
EMAIL_TEMPLATES = {
    "initial_outreach": {
        "subject": "【ご挨拶】{事業者名}様 - HIBURI株式会社",
        "body": """
{事業者名} 御中

はじめまして。HIBURI株式会社と申します。

この度、新規指定おめでとうございます。

弊社では医療機関様向けのサービスを提供しております。
ご興味がございましたら、お気軽にご連絡ください。

━━━━━━━━━━━━━━━━━━━━━━
HIBURI株式会社
Email: {from_email}
━━━━━━━━━━━━━━━━━━━━━━
""",
    },
    "followup": {
        "subject": "【再度のご案内】{事業者名}様 - HIBURI株式会社",
        "body": """
{事業者名} 御中

先日はご挨拶のメールをお送りさせていただきました。
ご多忙のところ恐れ入りますが、改めてご案内申し上げます。

弊社サービスについてご不明点がございましたら、
お気軽にお問い合わせください。

━━━━━━━━━━━━━━━━━━━━━━
HIBURI株式会社
Email: {from_email}
━━━━━━━━━━━━━━━━━━━━━━
""",
    },
    "final_followup": {
        "subject": "【最終ご案内】{事業者名}様 - HIBURI株式会社",
        "body": """
{事業者名} 御中

数回にわたりご連絡をさせていただきましたが、
お忙しいところ恐縮です。

本メールをもちまして一旦ご案内を控えさせていただきます。
ご興味をお持ちの際は、いつでもお気軽にご連絡ください。

━━━━━━━━━━━━━━━━━━━━━━
HIBURI株式会社
Email: {from_email}
━━━━━━━━━━━━━━━━━━━━━━
""",
    },
}


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


def render_template(template_key, variables):
    """テンプレートを変数で展開"""
    template = EMAIL_TEMPLATES.get(template_key)
    if not template:
        return None, None
    subject = template["subject"].format(**variables)
    body = template["body"].format(**variables)
    return subject, body


def process_stage(page, stage_config, dry_run=False):
    """1レコードのパイプライン処理"""
    name = page.get("事業者名", "不明")
    email = page.get("メールアドレス", "")
    page_id = page["_page_id"]
    action = stage_config["action"]
    next_stage = stage_config["next_stage"]

    variables = {
        "事業者名": name,
        "from_email": FROM_EMAIL,
    }

    # メールアドレスがない場合はステージ更新のみ
    if not email:
        print(f"  [{name}] メールアドレスなし → ステージ更新のみ: {next_stage}")
        if not dry_run:
            properties = {"パイプライン": {"select": {"name": next_stage}}}
            update_page(page_id, properties)
        return "no_email"

    subject, body = render_template(action, variables)
    if not subject:
        print(f"  [{name}] テンプレートなし: {action}")
        return "no_template"

    if dry_run:
        print(f"  [{name}] メール送信(予定): {email}")
        print(f"    件名: {subject}")
        print(f"    → ステージ更新: {next_stage}")
        return "dry_run"

    try:
        send_email(email, subject, body)
        print(f"  [{name}] メール送信完了: {email}")

        # Notionステータス更新
        properties = {"パイプライン": {"select": {"name": next_stage}}}
        update_page(page_id, properties)
        print(f"  [{name}] ステージ更新: {next_stage}")
        return "success"
    except Exception as e:
        print(f"  [{name}] エラー: {e}")
        return "error"


def run_pipeline(target_stage=None, dry_run=False, limit=None):
    """パイプライン実行"""
    print(f"=== 営業自動化パイプライン ===")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"モード: {'DRY-RUN' if dry_run else '本番'}")
    print()

    # Notionから全ページ取得
    print("Notionページ取得中...")
    pages = query_all_pages()
    print(f"  → {len(pages)} 件取得")

    # ステージ別に分類
    stage_counts = {}
    for page in pages:
        stage = page.get("パイプライン", "未設定")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    print("\nステージ別件数:")
    for stage, count in sorted(stage_counts.items()):
        marker = " ← 処理対象" if stage in PIPELINE_STAGES else ""
        if target_stage and stage != target_stage:
            marker = ""
        print(f"  {stage}: {count} 件{marker}")

    # 処理対象を絞り込み
    results = {"success": 0, "no_email": 0, "error": 0, "dry_run": 0, "no_template": 0}
    processed = 0

    for page in pages:
        stage = page.get("パイプライン", "")
        if stage not in PIPELINE_STAGES:
            continue
        if target_stage and stage != target_stage:
            continue
        if limit and processed >= limit:
            break

        stage_config = PIPELINE_STAGES[stage]
        print(f"\n[{stage}] {stage_config['description']}")
        result = process_stage(page, stage_config, dry_run=dry_run)
        results[result] = results.get(result, 0) + 1
        processed += 1

    print(f"\n=== 処理完了 ===")
    print(f"処理件数: {processed}")
    for key, count in results.items():
        if count > 0:
            print(f"  {key}: {count}")


def main():
    parser = argparse.ArgumentParser(description="営業自動化パイプライン")
    parser.add_argument("--stage", default=None,
                        help="処理対象ステージ (例: 新規, 連絡済み)")
    parser.add_argument("--limit", type=int, default=None,
                        help="処理件数上限")
    parser.add_argument("--dry-run", action="store_true",
                        help="確認のみ（メール送信・ステータス更新しない）")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        print("エラー: NOTION_TOKEN 環境変数を設定してください")
        sys.exit(1)

    if not args.dry_run and (not SMTP_USER or not SMTP_PASSWORD):
        print("警告: SMTP_USER / SMTP_PASSWORD が未設定。メール送信はスキップされます。")

    run_pipeline(
        target_stage=args.stage,
        dry_run=args.dry_run,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
