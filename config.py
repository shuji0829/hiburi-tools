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

# メール送信設定（Google Workspace / Gmail）
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "shuji.tomitaka@hiburi.co.jp")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")  # Googleアプリパスワード
FROM_EMAIL = os.environ.get("FROM_EMAIL", "shuji.tomitaka@hiburi.co.jp")
FROM_NAME = os.environ.get("FROM_NAME", "HIBURI株式会社 富高修司")

# メール送信制限
EMAIL_BATCH_SIZE = 50       # 1回の実行で送信する最大件数
EMAIL_DELAY_SECONDS = 5     # メール間の待機時間（秒）

# スケジューラ設定
SCHEDULE_SCRAPER_DAY = "monday"  # 毎週月曜
SCHEDULE_SCRAPER_TIME = "09:00"
SCHEDULE_SYNC_TIME = "10:00"    # 毎日10時
SCHEDULE_HP_SEARCH_TIME = "20:00"  # 毎日20時（HP検索）
SCHEDULE_PIPELINE_TIME = "11:00"  # 毎日11時

# HP検索設定
HP_SEARCH_DAILY_LIMIT = 200  # 1日あたりの検索件数上限
HP_SEARCH_EXCEL = os.environ.get(
    "HP_SEARCH_EXCEL", "厚生局_新規指定一覧_R0704-R0803.xlsx"
)
