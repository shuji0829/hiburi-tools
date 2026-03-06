"""HIBURI営業自動化システム - Notion API連携

CRM管理とログ記録をNotion APIで行う。
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from src.config import NOTION_API_KEY, NOTION_CRM_DATABASE_ID, NOTION_LOG_DATABASE_ID

JST = ZoneInfo("Asia/Tokyo")
logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionClient:
    """Notion API操作クライアント"""

    def __init__(self, api_key: str | None = None, dry_run: bool = True):
        self.api_key = api_key or NOTION_API_KEY
        self.dry_run = dry_run
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }

    def _post(self, endpoint: str, payload: dict) -> dict | None:
        if self.dry_run:
            logger.info(f"[DRY_RUN] POST {endpoint} payload_keys={list(payload.keys())}")
            return {"dry_run": True, "endpoint": endpoint}

        url = f"{NOTION_API_BASE}{endpoint}"
        resp = requests.post(url, json=payload, headers=self.headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _query(self, database_id: str, filter_obj: dict | None = None) -> list[dict]:
        url = f"{NOTION_API_BASE}/databases/{database_id}/query"
        payload = {}
        if filter_obj:
            payload["filter"] = filter_obj

        if self.dry_run:
            logger.info(f"[DRY_RUN] QUERY database={database_id}")
            return []

        resp = requests.post(url, json=payload, headers=self.headers, timeout=30)
        resp.raise_for_status()
        return resp.json().get("results", [])

    def add_crm_record(self, data: dict, database_id: str | None = None) -> dict | None:
        """CRMデータベースにレコードを追加

        Args:
            data: {
                "name": str,          # 事業者名
                "email": str,         # メールアドレス
                "pipeline": str,      # clinic / navita
                "category": str,      # 診療科 or 業種
                "address": str,       # 住所
                "status": str,        # new / contacted / replied / ...
                "source": str,        # 厚生局 / Googleマップ
            }
        """
        db_id = database_id or NOTION_CRM_DATABASE_ID
        properties = {
            "事業者名": {"title": [{"text": {"content": data.get("name", "")}}]},
            "メールアドレス": {"email": data.get("email", "")},
            "パイプライン": {"select": {"name": data.get("pipeline", "")}},
            "カテゴリ": {"select": {"name": data.get("category", "")}},
            "住所": {"rich_text": [{"text": {"content": data.get("address", "")}}]},
            "ステータス": {"select": {"name": data.get("status", "new")}},
            "データソース": {"select": {"name": data.get("source", "")}},
            "登録日": {"date": {"start": datetime.now(JST).date().isoformat()}},
        }

        payload = {"parent": {"database_id": db_id}, "properties": properties}

        logger.info(f"[CRM登録] {data.get('name')} ({data.get('pipeline')})")
        return self._post("/pages", payload)

    def log_execution(self, log_data: dict, database_id: str | None = None) -> dict | None:
        """実行ログをNotionに記録

        Args:
            log_data: {
                "action": str,        # send_email / scrape / etc.
                "pipeline": str,      # clinic / navita
                "target": str,        # 対象名
                "status": str,        # success / failed / dry_run
                "detail": str,        # 詳細メッセージ
                "mode": str,          # dry_run / live
            }
        """
        db_id = database_id or NOTION_LOG_DATABASE_ID
        now = datetime.now(JST)

        properties = {
            "アクション": {"title": [{"text": {"content": log_data.get("action", "")}}]},
            "パイプライン": {"select": {"name": log_data.get("pipeline", "")}},
            "対象": {"rich_text": [{"text": {"content": log_data.get("target", "")}}]},
            "ステータス": {"select": {"name": log_data.get("status", "")}},
            "詳細": {"rich_text": [{"text": {"content": log_data.get("detail", "")[:2000]}}]},
            "実行モード": {"select": {"name": log_data.get("mode", "dry_run")}},
            "実行日時": {"date": {"start": now.isoformat()}},
        }

        payload = {"parent": {"database_id": db_id}, "properties": properties}

        logger.info(f"[ログ記録] {log_data.get('action')} - {log_data.get('target')}")
        return self._post("/pages", payload)

    def find_by_email(self, email: str, database_id: str | None = None) -> list[dict]:
        """メールアドレスでCRMを検索（重複チェック用）"""
        db_id = database_id or NOTION_CRM_DATABASE_ID
        filter_obj = {
            "property": "メールアドレス",
            "email": {"equals": email},
        }
        return self._query(db_id, filter_obj)
