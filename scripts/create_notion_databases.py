"""Notion上にCRM管理DBと実行ログDBを自動作成するスクリプト"""

import os
import requests
import json
import sys

from dotenv import load_dotenv

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY", "")
PARENT_PAGE_ID = os.getenv("NOTION_PARENT_PAGE_ID", "")

if not NOTION_API_KEY or not PARENT_PAGE_ID:
    print("Error: NOTION_API_KEY and NOTION_PARENT_PAGE_ID must be set in .env")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

BASE_URL = "https://api.notion.com/v1/databases"


def create_database(title: str, properties: dict) -> dict:
    payload = {
        "parent": {"type": "page_id", "page_id": PARENT_PAGE_ID},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
    }
    resp = requests.post(BASE_URL, headers=HEADERS, json=payload)
    if resp.status_code != 200:
        print(f"Error creating '{title}': {resp.status_code}")
        print(resp.text)
        sys.exit(1)
    return resp.json()


def select_options(names: list[str]) -> dict:
    return {"select": {"options": [{"name": n} for n in names]}}


def main():
    # --- CRM管理DB ---
    crm_props = {
        "事業者名": {"title": {}},
        "メールアドレス": {"email": {}},
        "パイプライン": select_options(["clinic", "navita"]),
        "カテゴリ": select_options([
            "内科", "歯科", "薬局", "整形外科", "皮膚科",
            "飲食", "美容", "医療", "小売", "士業", "その他",
        ]),
        "住所": {"rich_text": {}},
        "ステータス": select_options(["new", "contacted", "replied"]),
        "データソース": select_options(["厚生局", "Googleマップ"]),
        "登録日": {"date": {}},
    }
    crm = create_database("CRM管理DB", crm_props)
    crm_id = crm["id"]
    print(f"CRM管理DB 作成完了: {crm_id}")

    # --- 実行ログDB ---
    log_props = {
        "アクション": {"title": {}},
        "パイプライン": select_options(["clinic", "navita"]),
        "対象": {"rich_text": {}},
        "ステータス": select_options(["success", "failed", "partial", "dry_run"]),
        "詳細": {"rich_text": {}},
        "実行モード": select_options(["dry_run", "live"]),
        "実行日時": {"date": {}},
    }
    log = create_database("実行ログDB", log_props)
    log_id = log["id"]
    print(f"実行ログDB 作成完了: {log_id}")

    print("\n========================================")
    print("  .env に以下を設定してください:")
    print("========================================")
    print(f"NOTION_CRM_DATABASE_ID={crm_id}")
    print(f"NOTION_LOG_DATABASE_ID={log_id}")
    print("========================================")


if __name__ == "__main__":
    main()
