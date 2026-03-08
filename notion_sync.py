"""
Excel → Notion 同期スクリプト
営業リストExcelファイルをNotionデータベースに同期する
"""

import os
import sys
import requests
import openpyxl


NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Excel列名 → Notionプロパティ名のマッピング
COLUMN_MAPPING = {
    "事業者名": "事業者名",
    "メールアドレス": "メールアドレス",
    "パイプライン": "パイプライン",
    "カテゴリ": "カテゴリ",
    "住所": "住所",
    "データソース": "データソース",
}

# Notionプロパティタイプ定義（データベーススキーマに基づく）
PROPERTY_TYPES = {
    "事業者名": "title",
    "メールアドレス": "email",
    "パイプライン": "select",
    "カテゴリ": "select",
    "住所": "rich_text",
    "データソース": "select",
}


def get_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def build_notion_properties(row_data):
    """Excel行データからNotionプロパティを構築する"""
    properties = {}

    for excel_col, notion_prop in COLUMN_MAPPING.items():
        value = row_data.get(excel_col)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            continue

        value = str(value).strip()
        prop_type = PROPERTY_TYPES[notion_prop]

        if prop_type == "title":
            properties[notion_prop] = {
                "title": [{"text": {"content": value}}]
            }
        elif prop_type == "email":
            properties[notion_prop] = {"email": value}
        elif prop_type == "select":
            properties[notion_prop] = {"select": {"name": value}}
        elif prop_type == "rich_text":
            properties[notion_prop] = {
                "rich_text": [{"text": {"content": value}}]
            }

    return properties


def query_existing_pages():
    """既存ページを事業者名でインデックス化して返す"""
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


def create_page(properties):
    """Notionにページを新規作成"""
    url = f"{NOTION_API_URL}/pages"
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    }
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


def read_excel(file_path, sheet_name):
    """Excelファイルを読み込み、行データのリストを返す"""
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb[sheet_name]

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        print("Excelファイルにデータがありません")
        return []

    headers = [str(h).strip() if h else "" for h in rows[0]]
    allowed_columns = set(COLUMN_MAPPING.keys())
    data = []
    for row in rows[1:]:
        row_dict = {}
        for i, header in enumerate(headers):
            if header in allowed_columns and i < len(row):
                row_dict[header] = row[i]
        if any(v is not None for v in row_dict.values()):
            data.append(row_dict)

    wb.close()
    return data


def sync(file_path, sheet_name):
    """メイン同期処理"""
    print(f"Excelファイル読み込み: {file_path} (シート: {sheet_name})")
    rows = read_excel(file_path, sheet_name)
    print(f"  → {len(rows)} 行のデータを検出")

    if not rows:
        return

    print("既存Notionページを取得中...")
    existing = query_existing_pages()
    print(f"  → 既存ページ: {len(existing)} 件")

    created = 0
    updated = 0
    skipped = 0
    failed = 0

    for i, row in enumerate(rows, 1):
        name = row.get("事業者名")
        if not name or (isinstance(name, str) and name.strip() == ""):
            skipped += 1
            continue

        name = str(name).strip()
        properties = build_notion_properties(row)

        try:
            if name in existing:
                print(f"  [{i}/{len(rows)}] 更新: {name}")
                update_page(existing[name], properties)
                updated += 1
            else:
                print(f"  [{i}/{len(rows)}] 新規作成: {name}")
                create_page(properties)
                created += 1
        except Exception as e:
            print(f"  [{i}/{len(rows)}] エラー: {name} - {e}")
            failed += 1

    print(f"\n同期完了: 成功 {created + updated} 件 (新規 {created}, 更新 {updated}), "
          f"失敗 {failed} 件, スキップ {skipped} 件")


if __name__ == "__main__":
    if not NOTION_TOKEN:
        print("エラー: NOTION_TOKEN 環境変数を設定してください")
        sys.exit(1)
    if not NOTION_DATABASE_ID:
        print("エラー: NOTION_DATABASE_ID 環境変数を設定してください")
        sys.exit(1)

    if len(sys.argv) >= 3:
        excel_path = sys.argv[1]
        sheet = sys.argv[2]
    else:
        excel_path = os.environ.get("EXCEL_FILE", "営業リスト_sample.xlsx")
        sheet = os.environ.get("SHEET_NAME", "営業リスト")

    if not os.path.exists(excel_path):
        print(f"エラー: ファイルが見つかりません: {excel_path}")
        sys.exit(1)

    sync(excel_path, sheet)
