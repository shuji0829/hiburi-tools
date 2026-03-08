"""
営業自動化パイプライン
Notionのステータスに応じて自動メール送信・ステータス更新を行う

ステータス:
  リード → 見込み → アクティブ顧客 / 非アクティブ顧客

処理フロー:
  1. Notionから対象レコードを取得
  2. 住所から最寄駅を取得
  3. テンプレートに宛先情報を差し込んでメール送信
  4. ステータスを更新

テンプレート:
  templates/ フォルダ内のテキストファイルを使用
  使える変数: {会社名}, {最寄駅}, {住所}, {電話番号}, {診療科目}

使い方:
  確認のみ:  python 営業自動化パイプライン.py --dry-run
  リードのみ: python 営業自動化パイプライン.py --stage リード --limit 50
  本番実行:  python 営業自動化パイプライン.py --stage リード
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
from station_lookup import get_nearest_station


# 送信ログファイル
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
SEND_LOG_FILE = os.path.join(
    LOG_DIR, f"email_send_{datetime.now():%Y%m%d}.csv"
)

# テンプレートフォルダ
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# パイプライン定義（クリニック顧客データベースの「ステータス」に対応）
PIPELINE_STAGES = {
    "リード": {
        "action": "initial_outreach",
        "next_stage": "見込み",
        "description": "初回営業メール送信",
    },
    "見込み": {
        "action": "followup",
        "next_stage": "見込み",
        "description": "フォローアップメール送信",
    },
}
# 旧ステージ名との互換性
PIPELINE_STAGES["新規"] = PIPELINE_STAGES["リード"]

# カテゴリ別テンプレート
CATEGORY_TEMPLATES = {
    "歯科": "dental",
    "薬局": "pharmacy",
    "薬": "pharmacy",
    "調剤": "pharmacy",
    "ドラッグ": "pharmacy",
}


def load_template(template_key):
    """テンプレートファイルを読み込む → {"subject": ..., "body": ...}"""
    path = os.path.join(TEMPLATE_DIR, f"{template_key}.txt")
    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # フォーマット: 1行目が "subject: ..." で、"---" 区切りの後が本文
    parts = content.split("---", 1)
    if len(parts) != 2:
        return None

    header = parts[0].strip()
    body = parts[1].strip()

    subject = ""
    if header.lower().startswith("subject:"):
        subject = header[len("subject:"):].strip()

    return {"subject": subject, "body": body}


def get_template_key(action, category):
    """カテゴリに応じたテンプレートキーを返す"""
    if category:
        for keyword, template_suffix in CATEGORY_TEMPLATES.items():
            if keyword in category:
                specific_key = f"{action}_{template_suffix}"
                if load_template(specific_key):
                    return specific_key
    return action


def render_template(template, variables):
    """テンプレートに変数を差し込む。未定義変数は空文字に"""
    subject = template["subject"]
    body = template["body"]

    for key, value in variables.items():
        subject = subject.replace(f"{{{key}}}", value)
        body = body.replace(f"{{{key}}}", value)

    return subject, body


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
    name = page.get("会社名", "") or page.get("事業者名", "不明")
    email = page.get("メールアドレス", "")
    category = page.get("診療科目", "") or page.get("カテゴリ", "")
    address = page.get("所在地", "") or page.get("住所", "")
    phone = page.get("電話番号", "")
    page_id = page["_page_id"]
    action = stage_config["action"]
    next_stage = stage_config["next_stage"]
    current_stage = [k for k, v in PIPELINE_STAGES.items() if v == stage_config][0]

    # メールアドレスがない場合はスキップ
    if not email:
        print(f"  [{name}] メールアドレスなし → スキップ")
        log_send(name, "", current_stage, action, "skipped_no_email")
        return "no_email"

    # カテゴリに応じたテンプレート選択
    template_key = get_template_key(action, category)
    template = load_template(template_key)
    if not template:
        print(f"  [{name}] テンプレートなし: {template_key}")
        return "no_template"

    # 最寄駅を取得
    station = get_nearest_station(address) if address else ""

    # テンプレート変数
    variables = {
        "会社名": name,
        "事業者名": name,
        "最寄駅": station or "最寄",
        "住所": address,
        "電話番号": phone,
        "診療科目": category,
        "担当者名": FROM_NAME,
    }

    subject, body = render_template(template, variables)

    if dry_run:
        print(f"  [{name}] → {email} (テンプレート: {template_key})")
        print(f"    件名: {subject}")
        if station:
            print(f"    最寄駅: {station}")
        print(f"    → 次ステージ: {next_stage}")
        return "dry_run"

    try:
        send_email(email, subject, body)
        print(f"  [{name}] 送信完了 → {email}")

        # Notionステータス更新
        properties = {"ステータス": {"select": {"name": next_stage}}}
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
    print(f"テンプレート: {TEMPLATE_DIR}")
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
        stage = page.get("ステータス", "") or page.get("パイプライン", "未設定")
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

        stage = page.get("ステータス", "") or page.get("パイプライン", "")
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
                        help="処理対象ステージ (例: リード, 見込み)")
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
