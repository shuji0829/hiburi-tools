"""
住所から最寄駅を取得するモジュール

Nominatim (OpenStreetMap) でジオコーディング → HeartRails Express API で最寄駅検索
どちらも無料・API キー不要
"""

import re
import time
import requests

# キャッシュ（同一住所の重複APIコールを防止）
_cache = {}

# Nominatim ユーザーエージェント（利用規約で必須）
NOMINATIM_UA = "hiburi-tools/1.0 (shuji.tomitaka@hiburi.co.jp)"


def _normalize_address(address):
    """住所を正規化（全角数字→半角、郵便番号除去）"""
    # 郵便番号除去（半角・全角両対応）
    clean = re.sub(r'〒?\s*[０-９\d]{3}[-ー－]?[０-９\d]{4}\s*', '', address)
    # 全角数字→半角
    zen = '０１２３４５６７８９'
    han = '0123456789'
    for z, h in zip(zen, han):
        clean = clean.replace(z, h)
    # 全角ハイフン類→半角
    clean = clean.replace('ー', '-').replace('－', '-')
    return clean.strip()


def _simplify_address(address):
    """番地以降を除去して町名レベルにする（Nominatimの精度向上）"""
    # 「X丁目Y番Z号」や「X-Y-Z」パターンを除去
    simplified = re.sub(r'\d+丁目.*$', '', address)
    if simplified != address:
        return simplified.strip()
    # 数字-数字 パターン（番地）を除去
    simplified = re.sub(r'\d+[-の]\d+.*$', '', address)
    if simplified != address:
        return simplified.strip()
    # 末尾の数字を除去
    simplified = re.sub(r'\d+$', '', address)
    return simplified.strip()


def _geocode(address):
    """住所 → (lat, lng) を返す。失敗時は None"""
    clean = _normalize_address(address)
    if not clean:
        return None

    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": NOMINATIM_UA}

    # まず全住所で試行、ダメなら町名レベルに簡略化
    for query in [clean, _simplify_address(clean)]:
        if not query:
            continue
        params = {
            "q": query,
            "format": "json",
            "limit": 1,
            "countrycodes": "jp",
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            results = resp.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"])
        except Exception:
            pass
        time.sleep(1.1)  # Nominatim rate limit

    return None


def _nearest_station(lat, lng):
    """(lat, lng) → 最寄駅名を返す。失敗時は None"""
    url = "https://express.heartrails.com/api/json"
    params = {
        "method": "getStations",
        "x": lng,
        "y": lat,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        stations = data.get("response", {}).get("station", [])
        if stations:
            return stations[0]["name"]
    except Exception:
        pass
    return None


def get_nearest_station(address):
    """住所文字列から最寄駅名を返す。取得できない場合は空文字"""
    if not address:
        return ""

    # キャッシュ確認
    if address in _cache:
        return _cache[address]

    coords = _geocode(address)
    if not coords:
        _cache[address] = ""
        return ""

    station = _nearest_station(*coords)
    result = station or ""
    _cache[address] = result
    return result


def get_nearest_station_batch(addresses):
    """住所リスト → {住所: 最寄駅名} の辞書を返す"""
    results = {}
    for addr in addresses:
        results[addr] = get_nearest_station(addr)
    return results


if __name__ == "__main__":
    # テスト
    test_addresses = [
        "〒316-0015 茨城県日立市金沢町１-６-８",
        "〒308-0825 茨城県筑西市下中山５５１-１",
        "埼玉県川越市脇田町18-6",
    ]
    for addr in test_addresses:
        station = get_nearest_station(addr)
        print(f"{addr} → {station or '(取得失敗)'}")
