"""
Notion API クライアント
"""

import requests
from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID, NOTION_API_URL,
    NOTION_VERSION, PROPERTY_TYPES, COLUMN_ALIASES, DEFAULT_DATA_SOURCE,
)


def get_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def build_notion_properties(row_data):
    """Excel行データからNotionプロパティを構築する"""
    properties = {}

    for excel_col, value in row_data.items():
        notion_prop = COLUMN_ALIASES.get(excel_col)
        if not notion_prop or notion_prop not in PROPERTY_TYPES:
            continue
        if value is None or (isinstance(value, str) and value.strip() == ""):
            continue
        value = str(value).strip()
        prop_type = PROPERTY_TYPES[notion_prop]
        if prop_type == "title":
            properties[notion_prop] = {"title": [{"text": {"content": value}}]}
        elif prop_type == "email":
            properties[notion_prop] = {"email": value}
        elif prop_type == "select":
            properties[notion_prop] = {"select": {"name": value}}
        elif prop_type == "rich_text":
            properties[notion_prop] = {"rich_text": [{"text": {"content": value}}]}
        elif prop_type == "phone_number":
            properties[notion_prop] = {"phone_number": value}
        elif prop_type == "url":
            properties[notion_prop] = {"url": value}

    # データソース列がない場合はデフォルト値を設定
    if "データソース" not in properties:
        properties["データソース"] = {"select": {"name": DEFAULT_DATA_SOURCE}}

    return properties


def parse_notion_property(prop_name, prop_data):
    """Notionプロパティから値を抽出する"""
    prop_type = prop_data.get("type", "")

    if prop_type == "title":
        title_list = prop_data.get("title", [])
        return title_list[0]["plain_text"] if title_list else ""
    elif prop_type == "email":
        return prop_data.get("email") or ""
    elif prop_type == "select":
        sel = prop_data.get("select")
        return sel["name"] if sel else ""
    elif prop_type == "rich_text":
        rt_list = prop_data.get("rich_text", [])
        return rt_list[0]["plain_text"] if rt_list else ""
    elif prop_type == "phone_number":
        return prop_data.get("phone_number") or ""
    elif prop_type == "url":
        return prop_data.get("url") or ""
    return ""


def query_existing_pages():
    """既存ページを事業者名でインデックス化して返す {name: page_id}"""
    existing = {}
    url = f"{NOTION_API_URL}/databases/{NOTION_DATABASE_ID}/query"
    has_more = True
    start_cursor = None
    while has_more:
        payload = {}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        resp = requests.post(url, headers=get_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()
        for page in data.get("results", []):
            title_prop = page["properties"].get("事業者名", {})
            title_list = title_prop.get("title", [])
            if title_list:
                name = title_list[0].get("plain_text", "")
                if name:
                    existing[name] = page["id"]
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")
    return existing


def query_all_pages():
    """全ページの全プロパティを取得 → [{prop_name: value, ...}, ...]"""
    pages = []
    url = f"{NOTION_API_URL}/databases/{NOTION_DATABASE_ID}/query"
    has_more = True
    start_cursor = None
    while has_more:
        payload = {}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        resp = requests.post(url, headers=get_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()
        for page in data.get("results", []):
            row = {"_page_id": page["id"]}
            for prop_name, prop_data in page["properties"].items():
                if prop_name in PROPERTY_TYPES:
                    row[prop_name] = parse_notion_property(prop_name, prop_data)
            pages.append(row)
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")
    return pages


def create_page(properties):
    """Notionにページを新規作成"""
    url = f"{NOTION_API_URL}/pages"
    payload = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": properties}
    resp = requests.post(url, headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


def update_page(page_id, properties):
    """既存ページを更新"""
    url = f"{NOTION_API_URL}/pages/{page_id}"
    payload = {"properties": properties}
    resp = requests.patch(url, headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


def archive_page(page_id):
    """ページをアーカイブ（論理削除）"""
    url = f"{NOTION_API_URL}/pages/{page_id}"
    payload = {"archived": True}
    resp = requests.patch(url, headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()
