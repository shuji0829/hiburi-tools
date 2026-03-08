"""
Excel to Notion sync script
"""

import argparse
import os
import sys
import requests
import openpyxl


NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Excel列名 → Notionプロパティ名のマッピング
# サンプル形式: Excel列名がそのままNotionプロパティ名
COLUMN_MAPPING = {
    "事業者名": "事業者名",
    "メールアドレス": "メールアドレス",
    "カテゴリ": "カテゴリ",
    "パイプライン": "パイプライン",
    "住所": "住所",
    "データソース": "データソース",
}

# Notionプロパティ名 → タイプ定義
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
    """Excel行データからNotionプロパティを構築する（6プロパティのみ）"""
    properties = {}

    for excel_col, notion_prop in COLUMN_MAPPING.items():
        value = row_data.get(excel_col)
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

    return properties


def get_business_name(row_data):
    """行データから事業者名を取得"""
    name = row_data.get("事業者名")
    if name and isinstance(name, str):
        name = name.strip()
    return name if name else None


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


def find_header_row(rows):
    """ヘッダー行を自動検出（施設名・メールアドレス等が含まれる行）"""
    search_keys = {"事業者名", "メールアドレス", "住所", "カテゴリ", "パイプライン", "データソース"}
    for idx, row in enumerate(rows):
        cells = [str(c).strip() if c else "" for c in row]
        matched = [c for c in cells if c in search_keys]
        if len(matched) >= 3:
            return idx
    return None


def read_excel(file_path, sheet_name, header_row=None):
    """Excelファイルを読み込み、マッピング対象列のみ返す"""
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        print("Excelファイルにデータがありません")
        wb.close()
        return []

    if header_row is not None:
        h_idx = header_row - 1
    else:
        h_idx = find_header_row(rows)
        if h_idx is None:
            print("エラー: ヘッダー行が見つかりません。--header-row で指定してください")
            print("  先頭5行の内容:")
            for i, r in enumerate(rows[:5], 1):
                print(f"    行{i}: {r}")
            wb.close()
            return []
        print(f"  ヘッダー行を自動検出: {h_idx + 1}行目")

    headers = [str(h).strip() if h else "" for h in rows[h_idx]]
    allowed_columns = set(COLUMN_MAPPING.keys())
    matched = [h for h in headers if h in allowed_columns]
    ignored = [h for h in headers if h and h not in allowed_columns]
    print(f"  マッピング対象列: {matched}")
    if ignored:
        print(f"  無視する列: {ignored}")

    data = []
    for row in rows[h_idx + 1:]:
        row_dict = {}
        for i, header in enumerate(headers):
            if header in allowed_columns and i < len(row):
                row_dict[header] = row[i]
        if any(v is not None for v in row_dict.values()):
            data.append(row_dict)

    wb.close()
    return data


def sync(file_path, sheet_name, dry_run=False, header_row=None):
    """メイン同期処理"""
    print(f"Excelファイル読み込み: {file_path} (シート: {sheet_name})")
    rows = read_excel(file_path, sheet_name, header_row=header_row)
    print(f"  → {len(rows)} 行のデータを検出")
    if not rows:
        return

    if dry_run:
        print("\n[DRY-RUN モード] Notion APIへの送信はスキップします")
        existing = {}
    else:
        print("\n[本番モード] Notion APIに送信します")
        print("既存Notionページを取得中...")
        existing = query_existing_pages()
        print(f"  → 既存ページ: {len(existing)} 件")

    created = 0
    updated = 0
    skipped = 0
    failed = 0

    for i, row in enumerate(rows, 1):
        name = get_business_name(row)
        if not name:
            skipped += 1
            continue
        properties = build_notion_properties(row)

        if dry_run:
            action = "更新(予定)" if name in existing else "新規作成(予定)"
            print(f"  [{i}/{len(rows)}] {action}: {name}")
            print(f"    送信プロパティ: {list(properties.keys())}")
            if name in existing:
                updated += 1
            else:
                created += 1
            continue

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


def main():
    parser = argparse.ArgumentParser(description="Excel to Notion sync")
    parser.add_argument("--excel", required=True, help="Excelファイルのパス")
    parser.add_argument("--sheet", required=True, help="シート名")
    parser.add_argument("--header-row", type=int, default=None, help="ヘッダー行番号 (1始まり)")
    parser.add_argument("--dry-run", action="store_true", help="確認のみ")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        print("エラー: NOTION_TOKEN 環境変数を設定してください")
        sys.exit(1)
    if not NOTION_DATABASE_ID:
        print("エラー: NOTION_DATABASE_ID 環境変数を設定してください")
        sys.exit(1)
    if not os.path.exists(args.excel):
        print(f"エラー: ファイルが見つかりません: {args.excel}")
        sys.exit(1)

    sync(args.excel, args.sheet, dry_run=args.dry_run, header_row=args.header_row)


if __name__ == "__main__":
    main()
