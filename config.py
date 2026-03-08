"""
HIBURI Tools 共通設定
"""

import os

# Notion API 設定
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Excel列名 → Notionプロパティ名のマッピング（複数の列名に対応）
COLUMN_ALIASES = {
    "施設名": "事業者名",
    "事業者名": "事業者名",
    "メールアドレス": "メールアドレス",
    "区分": "カテゴリ",
    "カテゴリ": "カテゴリ",
    "指定種別": "パイプライン",
    "パイプライン": "パイプライン",
    "住所": "住所",
    "データソース": "データソース",
    "電話番号": "電話番号",
    "ホームページ": "ホームページ",
}

# データソースのデフォルト値
DEFAULT_DATA_SOURCE = "厚労省新規指定"

# Notionプロパティ名 → タイプ定義
PROPERTY_TYPES = {
    "事業者名": "title",
    "メールアドレス": "email",
    "パイプライン": "select",
    "カテゴリ": "select",
    "住所": "rich_text",
    "データソース": "select",
    "電話番号": "phone_number",
    "ホームページ": "url",
}

# 厚生局スクレイパー設定
KOUSEIKYOKU_BASE_URL = "https://kouseikyoku.mhlw.go.jp"
KOUSEIKYOKU_REGIONS = {
    "関東信越": "/kantoshinetsu/chousa/shitei.html",
}

# スケジューラ設定
SCHEDULE_SCRAPER_DAY = "monday"  # 毎週月曜
SCHEDULE_SCRAPER_TIME = "09:00"
SCHEDULE_SYNC_TIME = "10:00"    # 毎日10時
SCHEDULE_PIPELINE_TIME = "11:00"  # 毎日11時
