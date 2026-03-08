"""
Excel ⇔ Notion 双方向同期スクリプト

Phase 0: 共通モジュール利用リファクタ
Phase 1: --reverse (Notion → Excel逆同期)
Phase 2: 差分同期 (新規/更新/削除検出、変更なしスキップ)
"""

import argparse
import os
import sys

from config import (
    NOTION_TOKEN, NOTION_DATABASE_ID, COLUMN_ALIASES,
    PROPERTY_TYPES, DEFAULT_DATA_SOURCE,
)
from notion_client import (
    build_notion_properties, query_existing_pages, query_all_pages,
    create_page, update_page, archive_page, parse_notion_property,
)
from excel_client import read_excel, write_excel, update_excel_in_place


def get_business_name(row_data):
    """行データから事業者名を取得（施設名・事業者名どちらにも対応）"""
    name = row_data.get("事業者名") or row_data.get("施設名")
    if name and isinstance(name, str):
        name = name.strip()
    return name if name else None


def compute_diff(excel_rows, notion_pages):
    """Excel行とNotionページの差分を計算

    Returns:
        new_rows: Excelにあり Notion にないレコード
        updated_rows: 両方にあり値が異なるレコード [(row, page_id, changes)]
        unchanged: 両方にあり値が同じレコード
        deleted_names: Notionにあり Excel にないレコード名 [(name, page_id)]
    """
    # Notionページを事業者名でインデックス化
    notion_by_name = {}
    for page in notion_pages:
        name = page.get("事業者名", "").strip()
        if name:
            notion_by_name[name] = page

    excel_names = set()
    new_rows = []
    updated_rows = []
    unchanged = []

    for row in excel_rows:
        name = get_business_name(row)
        if not name:
            continue
        excel_names.add(name)

        if name not in notion_by_name:
            new_rows.append(row)
            continue

        # 値の比較
        notion_page = notion_by_name[name]
        changes = {}
        for excel_col, value in row.items():
            notion_prop = COLUMN_ALIASES.get(excel_col)
            if not notion_prop or notion_prop not in PROPERTY_TYPES:
                continue
            excel_val = str(value).strip() if value else ""
            notion_val = str(notion_page.get(notion_prop, "")).strip()
            if excel_val and excel_val != notion_val:
                changes[notion_prop] = {"excel": excel_val, "notion": notion_val}

        if changes:
            updated_rows.append((row, notion_page["_page_id"], changes))
        else:
            unchanged.append(name)

    # 削除検出: Notionにあり Excel にない
    deleted_names = [
        (name, page["_page_id"])
        for name, page in notion_by_name.items()
        if name not in excel_names
    ]

    return new_rows, updated_rows, unchanged, deleted_names


def sync_excel_to_notion(file_path, sheet_name, dry_run=False,
                         header_row=None, detect_deletes=False):
    """Excel → Notion 同期（差分検出付き）"""
    print(f"Excelファイル読み込み: {file_path} (シート: {sheet_name})")
    rows = read_excel(file_path, sheet_name, header_row=header_row)
    print(f"  → {len(rows)} 行のデータを検出")
    if not rows:
        return

    print("Notionページを取得中...")
    notion_pages = query_all_pages()
    print(f"  → 既存ページ: {len(notion_pages)} 件")

    new_rows, updated_rows, unchanged, deleted_names = compute_diff(rows, notion_pages)

    # サマリー表示
    print(f"\n--- 差分サマリー ---")
    print(f"  新規: {len(new_rows)} 件")
    print(f"  更新: {len(updated_rows)} 件")
    print(f"  変更なし: {len(unchanged)} 件")
    if detect_deletes:
        print(f"  削除候補: {len(deleted_names)} 件")
    print()

    if dry_run:
        print("[DRY-RUN モード] Notion APIへの送信はスキップします\n")

    created = 0
    updated = 0
    failed = 0

    # 新規作成
    for row in new_rows:
        name = get_business_name(row)
        properties = build_notion_properties(row)
        if dry_run:
            print(f"  [新規作成(予定)] {name}")
            print(f"    プロパティ: {list(properties.keys())}")
            created += 1
        else:
            try:
                print(f"  [新規作成] {name}")
                create_page(properties)
                created += 1
            except Exception as e:
                print(f"  [エラー] {name} - {e}")
                failed += 1

    # 更新
    for row, page_id, changes in updated_rows:
        name = get_business_name(row)
        properties = build_notion_properties(row)
        if dry_run:
            print(f"  [更新(予定)] {name}")
            for prop, diff in changes.items():
                print(f"    {prop}: {diff['notion']} → {diff['excel']}")
            updated += 1
        else:
            try:
                print(f"  [更新] {name}")
                update_page(page_id, properties)
                updated += 1
            except Exception as e:
                print(f"  [エラー] {name} - {e}")
                failed += 1

    # 削除
    archived = 0
    if detect_deletes and deleted_names:
        for name, page_id in deleted_names:
            if dry_run:
                print(f"  [アーカイブ(予定)] {name}")
                archived += 1
            else:
                try:
                    print(f"  [アーカイブ] {name}")
                    archive_page(page_id)
                    archived += 1
                except Exception as e:
                    print(f"  [エラー] {name} - {e}")
                    failed += 1

    print(f"\n同期完了: 新規 {created}, 更新 {updated}, "
          f"アーカイブ {archived}, 変更なし {len(unchanged)}, 失敗 {failed}")


def sync_notion_to_excel(file_path, sheet_name, dry_run=False, header_row=None):
    """Notion → Excel 逆同期"""
    print("Notionページを取得中...")
    notion_pages = query_all_pages()
    print(f"  → {len(notion_pages)} 件のページを取得")

    if not notion_pages:
        print("Notionにデータがありません")
        return

    if os.path.exists(file_path):
        print(f"既存Excelファイルを更新: {file_path} (シート: {sheet_name})")
        excel_rows = read_excel(file_path, sheet_name, header_row=header_row)
        excel_names = set()
        for row in excel_rows:
            name = get_business_name(row)
            if name:
                excel_names.add(name)

        # 更新対象: Excelにも存在するレコード
        updates = []
        new_pages = []
        for page in notion_pages:
            name = page.get("事業者名", "").strip()
            if not name:
                continue
            if name in excel_names:
                updates.append(page)
            else:
                new_pages.append(page)

        if dry_run:
            print(f"\n[DRY-RUN] 更新: {len(updates)} 件, 新規追加: {len(new_pages)} 件")
            for page in updates[:10]:
                print(f"  [更新(予定)] {page.get('事業者名')}")
            for page in new_pages[:10]:
                print(f"  [新規追加(予定)] {page.get('事業者名')}")
            return

        updated_count = 0
        if updates:
            updated_count = update_excel_in_place(file_path, sheet_name, updates)

        print(f"  → 更新: {updated_count} 件")
        if new_pages:
            print(f"  → 新規Notionページ {len(new_pages)} 件はExcelに手動追加が必要です")
    else:
        # Excelファイルが存在しない場合は新規作成
        print(f"Excelファイルを新規作成: {file_path}")
        headers = [k for k in PROPERTY_TYPES.keys()]
        if dry_run:
            print(f"\n[DRY-RUN] {len(notion_pages)} 件を新規書き出し予定")
            return
        write_excel(file_path, sheet_name, notion_pages, headers=headers)

    print("逆同期完了")


def main():
    parser = argparse.ArgumentParser(description="Excel ⇔ Notion 双方向同期")
    parser.add_argument("--excel", required=True, help="Excelファイルのパス")
    parser.add_argument("--sheet", required=True, help="シート名")
    parser.add_argument("--header-row", type=int, default=None, help="ヘッダー行番号 (1始まり)")
    parser.add_argument("--dry-run", action="store_true", help="確認のみ（API送信しない）")
    parser.add_argument("--reverse", action="store_true", help="Notion → Excel 逆同期")
    parser.add_argument("--detect-deletes", action="store_true",
                        help="Notionにのみ存在するレコードをアーカイブ")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        print("エラー: NOTION_TOKEN 環境変数を設定してください")
        sys.exit(1)
    if not NOTION_DATABASE_ID:
        print("エラー: NOTION_DATABASE_ID 環境変数を設定してください")
        sys.exit(1)
    if not os.path.exists(args.excel) and not args.reverse:
        print(f"エラー: ファイルが見つかりません: {args.excel}")
        sys.exit(1)

    if args.reverse:
        sync_notion_to_excel(args.excel, args.sheet,
                             dry_run=args.dry_run, header_row=args.header_row)
    else:
        sync_excel_to_notion(args.excel, args.sheet,
                             dry_run=args.dry_run, header_row=args.header_row,
                             detect_deletes=args.detect_deletes)


if __name__ == "__main__":
    main()
