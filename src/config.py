"""HIBURI営業自動化システム - 設定"""

import os
from dotenv import load_dotenv

load_dotenv()

# Notion API
NOTION_API_KEY = os.getenv("NOTION_API_KEY", "")
NOTION_CRM_DATABASE_ID = os.getenv("NOTION_CRM_DATABASE_ID", "")
NOTION_LOG_DATABASE_ID = os.getenv("NOTION_LOG_DATABASE_ID", "")

# Google Maps API
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# Outlook
OUTLOOK_PROFILE_NAME = os.getenv("OUTLOOK_PROFILE_NAME", "Outlook")

# Claude API (メール文面自動生成用)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# 送信制御ルール
SEND_RULES = {
    "allowed_days": [0, 1, 2, 3, 4],  # 月〜金 (0=月曜)
    "allowed_hours_start": 8,
    "allowed_hours_end": 18,
    "lunch_start": 12,
    "lunch_end": 13,
    "daily_limit_clinic": 50,
    "daily_limit_navita": 30,
}

# パイプライン種別
PIPELINE_CLINIC = "clinic"
PIPELINE_NAVITA = "navita"
