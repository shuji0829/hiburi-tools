"""HIBURI営業自動化システム - ナビタパイプライン

ナビタ（駅設置案内地図広告）の営業自動化:
1. 設置駅リスト（CSV / Notion）から対象駅を読み込み
2. 更新月の3ヶ月前にアプローチ対象フラグを立てる
3. GoogleマップAPIで駅から半径500m圏内の事業者を抽出
4. Notion CRMと照合して重複・NG先を除外
5. 業種別メールテンプレートを生成
6. scheduler.pyの時間制御と連携して分散送信
"""

import csv
import logging
import math
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from src.config import GOOGLE_MAPS_API_KEY, PIPELINE_NAVITA
from src.notion_client import NotionClient
from src.scheduler import SendScheduler
from src.mail_sender import MailSender

JST = ZoneInfo("Asia/Tokyo")
logger = logging.getLogger(__name__)

STATION_CSV_PATH = Path(__file__).parent.parent / "data" / "navita_stations.csv"

GOOGLE_PLACES_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
GOOGLE_PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

SEARCH_RADIUS_METERS = 500

# GoogleマップAPIの業種タイプ → HIBURI業種カテゴリ
PLACE_TYPE_TO_CATEGORY = {
    "restaurant": "飲食",
    "cafe": "飲食",
    "bar": "飲食",
    "bakery": "飲食",
    "meal_delivery": "飲食",
    "meal_takeaway": "飲食",
    "hair_care": "美容",
    "beauty_salon": "美容",
    "spa": "美容",
    "doctor": "医療",
    "dentist": "医療",
    "pharmacy": "医療",
    "hospital": "医療",
    "physiotherapist": "医療",
    "veterinary_care": "医療",
    "store": "小売",
    "clothing_store": "小売",
    "shoe_store": "小売",
    "jewelry_store": "小売",
    "furniture_store": "小売",
    "electronics_store": "小売",
    "convenience_store": "小売",
    "supermarket": "小売",
    "pet_store": "小売",
    "book_store": "小売",
    "florist": "小売",
    "lawyer": "士業",
    "accounting": "士業",
    "insurance_agency": "士業",
    "real_estate_agency": "士業",
}

# ナビタ用業種別メールテンプレート
NAVITA_EMAIL_TEMPLATES = {
    "飲食": {
        "subject": "【{station_name}駅ナビタ広告】{name}様の集客力アップをご支援します",
        "pain_points": [
            "駅利用者への認知が十分でなく、通りがかり客を取りこぼしている",
            "WEB広告やSNSは運用しているが、駅周辺のオフライン集客が弱い",
            "競合店との差別化に苦戦している",
        ],
        "proposals": [
            "{station_name}駅ナビタ案内図への広告掲載で、毎日数万人の駅利用者にリーチ",
            "ナビタ広告×Googleマップ連携で、オンラインとオフラインの相乗効果を実現",
            "飲食店特化のホームページ制作・Instagram広告で総合的な集客をサポート",
        ],
    },
    "美容": {
        "subject": "【{station_name}駅ナビタ広告】{name}様のサロン集客をお手伝いします",
        "pain_points": [
            "駅近の好立地なのに、新規のお客様に見つけてもらえない",
            "ホットペッパー等のポータルサイト依存から脱却したい",
            "リピーター獲得のための認知度向上が課題",
        ],
        "proposals": [
            "{station_name}駅ナビタ案内図への広告掲載で、駅利用者に毎日アピール",
            "美容サロン特化のホームページ制作で、ブランドイメージを確立",
            "LINE公式アカウント連携・リピート促進のDX化をサポート",
        ],
    },
    "医療": {
        "subject": "【{station_name}駅ナビタ広告】{name}様の患者集客をサポートいたします",
        "pain_points": [
            "開院したが、地域住民への認知がまだ不十分",
            "駅を利用する通院患者へのアクセス案内が重要",
            "WEB上の情報発信が追いついていない",
        ],
        "proposals": [
            "{station_name}駅ナビタ案内図への掲載で、駅利用者に医院の場所を分かりやすく案内",
            "医療機関特化のホームページ制作・WEB問診システムの導入",
            "Google広告の「地域名×診療科」対策で新規患者を獲得",
        ],
    },
    "小売": {
        "subject": "【{station_name}駅ナビタ広告】{name}様の店舗集客をご支援します",
        "pain_points": [
            "駅周辺の店舗なのに、通行人に素通りされている",
            "ECサイトとの競争の中でリアル店舗の強みを活かしたい",
            "地域密着型の認知施策が不足している",
        ],
        "proposals": [
            "{station_name}駅ナビタ案内図への広告掲載で、駅利用者を店舗に誘導",
            "EC連携型ホームページ制作で、オンライン・オフライン双方の売上を拡大",
            "Google広告・SNS広告で地域の見込み客にリーチ",
        ],
    },
    "士業": {
        "subject": "【{station_name}駅ナビタ広告】{name}様の事務所認知度向上をご提案します",
        "pain_points": [
            "専門性は高いが、地域住民や事業者への認知が課題",
            "紹介頼みの集客から脱却したい",
            "WEBでの情報発信が同業他社に比べて遅れている",
        ],
        "proposals": [
            "{station_name}駅ナビタ案内図で事務所の存在を地域にアピール",
            "士業特化のホームページ制作で専門性と信頼感を訴求",
            "Google広告の「地域名×業種」対策で相談件数を増加",
        ],
    },
}

COMPANY_SIGNATURE = (
    "\n\n━━━━━━━━━━━━━━━━━━━━\n"
    "株式会社HIBURI\n"
    "代表取締役\n"
    "TEL: XXX-XXXX-XXXX\n"
    "MAIL: info@hiburi.co.jp\n"
    "WEB: https://hiburi.co.jp\n"
    "━━━━━━━━━━━━━━━━━━━━"
)


def classify_business_category(place_types: list[str]) -> str:
    """Googleマップの場所タイプからHIBURI業種カテゴリに変換"""
    for pt in place_types:
        if pt in PLACE_TYPE_TO_CATEGORY:
            return PLACE_TYPE_TO_CATEGORY[pt]
    return "その他"


def months_until_renewal(renewal_month: int, reference_date: date | None = None) -> int:
    """更新月まであと何ヶ月か計算"""
    ref = reference_date or date.today()
    current_month = ref.month
    if renewal_month >= current_month:
        return renewal_month - current_month
    else:
        return 12 - current_month + renewal_month


class StationLoader:
    """設置駅リストの読み込み"""

    @staticmethod
    def load_from_csv(csv_path: Path | None = None) -> list[dict]:
        """CSVから駅リストを読み込む

        CSVフォーマット:
        station_name,line_name,renewal_month,lat,lng
        渋谷,JR山手線,6,35.6580,139.7016
        """
        path = csv_path or STATION_CSV_PATH
        if not path.exists():
            logger.warning(f"駅CSVファイルが見つかりません: {path}")
            return []

        stations = []
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stations.append({
                    "station_name": row.get("station_name", "").strip(),
                    "line_name": row.get("line_name", "").strip(),
                    "renewal_month": int(row.get("renewal_month", 0)),
                    "lat": float(row.get("lat", 0)),
                    "lng": float(row.get("lng", 0)),
                })

        logger.info(f"駅リスト読み込み: {len(stations)}件 ({path})")
        return stations

    @staticmethod
    def generate_sample_csv(csv_path: Path | None = None) -> Path:
        """サンプルCSVを生成"""
        path = csv_path or STATION_CSV_PATH
        path.parent.mkdir(parents=True, exist_ok=True)

        sample_stations = [
            {"station_name": "渋谷", "line_name": "JR山手線", "renewal_month": 6, "lat": 35.6580, "lng": 139.7016},
            {"station_name": "新宿", "line_name": "JR山手線", "renewal_month": 9, "lat": 35.6896, "lng": 139.7006},
            {"station_name": "池袋", "line_name": "JR山手線", "renewal_month": 12, "lat": 35.7295, "lng": 139.7109},
            {"station_name": "横浜", "line_name": "JR東海道線", "renewal_month": 3, "lat": 35.4657, "lng": 139.6225},
            {"station_name": "大宮", "line_name": "JR京浜東北線", "renewal_month": 8, "lat": 35.9063, "lng": 139.6237},
        ]

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["station_name", "line_name", "renewal_month", "lat", "lng"])
            writer.writeheader()
            writer.writerows(sample_stations)

        logger.info(f"サンプル駅CSV生成: {path} ({len(sample_stations)}件)")
        return path


class GoogleMapsClient:
    """Google Maps API操作クライアント"""

    def __init__(self, api_key: str | None = None, dry_run: bool = True):
        self.api_key = api_key or GOOGLE_MAPS_API_KEY
        self.dry_run = dry_run
        self.has_api_key = bool(self.api_key)
        if not self.has_api_key and not self.dry_run:
            logger.warning(
                "GOOGLE_MAPS_API_KEY が未設定です。"
                "CSVの座標情報を使い、サンプルデータでフォールバックします。"
            )

    def geocode_station(self, station_name: str) -> dict | None:
        """駅名から緯度経度を取得"""
        if self.dry_run:
            logger.info(f"[DRY_RUN] ジオコーディングスキップ: {station_name}駅")
            return None

        if not self.has_api_key:
            logger.warning(f"[FALLBACK] APIキー未設定のためジオコーディング不可: {station_name}駅（CSVの座標を使用してください）")
            return None

        params = {
            "address": f"{station_name}駅",
            "key": self.api_key,
            "language": "ja",
        }

        try:
            resp = requests.get(GOOGLE_GEOCODE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data["status"] == "OK" and data["results"]:
                loc = data["results"][0]["geometry"]["location"]
                return {"lat": loc["lat"], "lng": loc["lng"]}
        except Exception as e:
            logger.error(f"ジオコーディングエラー: {station_name} - {e}")
        return None

    def search_nearby_businesses(self, lat: float, lng: float, station_name: str) -> list[dict]:
        """指定座標の半径500m圏内の事業者を検索"""
        if self.dry_run:
            logger.info(f"[DRY_RUN] Places API検索スキップ: {station_name}駅 ({lat}, {lng})")
            return self._generate_sample_businesses(station_name)

        if not self.has_api_key:
            logger.warning(f"[FALLBACK] APIキー未設定のためPlaces API検索不可: {station_name}駅 → サンプルデータで代替")
            return self._generate_sample_businesses(station_name)

        all_results = []
        next_page_token = None

        for page in range(3):  # 最大3ページ（60件）
            params = {
                "location": f"{lat},{lng}",
                "radius": SEARCH_RADIUS_METERS,
                "key": self.api_key,
                "language": "ja",
            }
            if next_page_token:
                params["pagetoken"] = next_page_token

            try:
                resp = requests.get(GOOGLE_PLACES_NEARBY_URL, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                for place in data.get("results", []):
                    category = classify_business_category(place.get("types", []))
                    if category == "その他":
                        continue

                    all_results.append({
                        "place_id": place.get("place_id", ""),
                        "name": place.get("name", ""),
                        "address": place.get("vicinity", ""),
                        "category": category,
                        "types": place.get("types", []),
                        "rating": place.get("rating"),
                        "station_name": station_name,
                    })

                next_page_token = data.get("next_page_token")
                if not next_page_token:
                    break

            except Exception as e:
                logger.error(f"Places API検索エラー: {station_name} page={page} - {e}")
                break

        logger.info(f"周辺事業者検索完了: {station_name}駅 → {len(all_results)}件")
        return all_results

    def get_place_details(self, place_id: str) -> dict | None:
        """場所の詳細情報（電話番号・メール・WebサイトURL）を取得"""
        if self.dry_run:
            return {
                "phone": "03-XXXX-XXXX",
                "website": "https://example.com",
                "email": "",
            }

        if not self.has_api_key:
            logger.info(f"[FALLBACK] APIキー未設定のため詳細情報取得不可: {place_id}")
            return {"phone": "", "website": "", "email": ""}

        params = {
            "place_id": place_id,
            "fields": "formatted_phone_number,website,url",
            "key": self.api_key,
            "language": "ja",
        }

        try:
            resp = requests.get(GOOGLE_PLACE_DETAILS_URL, params=params, timeout=10)
            resp.raise_for_status()
            result = resp.json().get("result", {})
            return {
                "phone": result.get("formatted_phone_number", ""),
                "website": result.get("website", ""),
                "email": "",  # Google APIからメールは直接取得不可
            }
        except Exception as e:
            logger.error(f"Place Details APIエラー: {place_id} - {e}")
            return None

    def _generate_sample_businesses(self, station_name: str) -> list[dict]:
        """dry_run用サンプルデータ"""
        samples = [
            {
                "place_id": f"dry_run_{station_name}_1",
                "name": f"{station_name}イタリアンレストラン",
                "address": f"東京都渋谷区{station_name}1-1-1",
                "category": "飲食",
                "types": ["restaurant"],
                "rating": 4.2,
                "station_name": station_name,
            },
            {
                "place_id": f"dry_run_{station_name}_2",
                "name": f"ヘアサロン{station_name}",
                "address": f"東京都渋谷区{station_name}2-2-2",
                "category": "美容",
                "types": ["beauty_salon"],
                "rating": 4.5,
                "station_name": station_name,
            },
            {
                "place_id": f"dry_run_{station_name}_3",
                "name": f"{station_name}内科クリニック",
                "address": f"東京都渋谷区{station_name}3-3-3",
                "category": "医療",
                "types": ["doctor"],
                "rating": 3.8,
                "station_name": station_name,
            },
            {
                "place_id": f"dry_run_{station_name}_4",
                "name": f"{station_name}セレクトショップ",
                "address": f"東京都渋谷区{station_name}4-4-4",
                "category": "小売",
                "types": ["clothing_store"],
                "rating": 4.0,
                "station_name": station_name,
            },
            {
                "place_id": f"dry_run_{station_name}_5",
                "name": f"{station_name}法律事務所",
                "address": f"東京都渋谷区{station_name}5-5-5",
                "category": "士業",
                "types": ["lawyer"],
                "rating": 4.1,
                "station_name": station_name,
            },
        ]
        logger.info(f"[DRY_RUN] サンプル事業者 {len(samples)}件 生成: {station_name}駅")
        return samples


class NavitaEmailGenerator:
    """ナビタ用業種別メールテンプレート生成"""

    def generate(self, target: dict) -> dict:
        """業種別メール文面を生成

        Args:
            target: {
                "name": str,
                "category": str,  # 飲食/美容/医療/小売/士業
                "station_name": str,
                "address": str,
            }
        """
        name = target.get("name", "")
        category = target.get("category", "その他")
        station_name = target.get("station_name", "")

        template = NAVITA_EMAIL_TEMPLATES.get(category)
        if template is None:
            template = NAVITA_EMAIL_TEMPLATES["小売"]
            category = "事業者"

        subject = template["subject"].format(name=name, station_name=station_name)
        pain_points = "\n".join(
            f"  - {p}" for p in template["pain_points"]
        )
        proposals = "\n".join(
            f"  {i+1}. {p.format(station_name=station_name)}"
            for i, p in enumerate(template["proposals"])
        )

        body = f"""{name} 御中

突然のご連絡失礼いたします。
株式会社HIBURIの代表を務めております。

{station_name}駅に設置されているナビタ（案内地図広告）の
更新時期が近づいているため、ご連絡させていただきました。

{category}の事業者様から、よくお聞きする課題として：

{pain_points}

といったお声をいただいております。

弊社では、ナビタ広告掲載と合わせて以下のサービスをご提供しております：

{proposals}

ナビタ広告は、{station_name}駅を毎日利用する方に
{name}様の存在を自然にアピールできる効果的な媒体です。

まずは15分程度のオンライン面談で、
貴社の現状やご要望をお聞かせいただけませんか？

ご都合のよい日時をいくつかお教えいただけますと幸いです。

何卒よろしくお願い申し上げます。
{COMPANY_SIGNATURE}"""

        return {"subject": subject, "body": body}

    def generate_batch(self, targets: list[dict]) -> list[dict]:
        """複数の送信先に対して一括生成"""
        results = []
        for t in targets:
            email = self.generate(t)
            results.append({**t, "subject": email["subject"], "body": email["body"]})
        return results


class NavitaPipeline:
    """ナビタパイプライン統合クラス"""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.maps = GoogleMapsClient(dry_run=dry_run)
        self.notion = NotionClient(dry_run=dry_run)
        self.email_gen = NavitaEmailGenerator()
        self.scheduler = SendScheduler(dry_run=dry_run)
        self.mail_sender = MailSender(dry_run=dry_run)

    def load_stations(self, csv_path: Path | None = None) -> list[dict]:
        """駅リストを読み込み"""
        stations = StationLoader.load_from_csv(csv_path)
        if not stations:
            logger.info("駅リストが空のため、サンプルCSVを生成します")
            StationLoader.generate_sample_csv(csv_path)
            stations = StationLoader.load_from_csv(csv_path)
        return stations

    def filter_approaching_renewal(self, stations: list[dict], months_ahead: int = 3) -> list[dict]:
        """更新月の指定月数前に達した駅をフィルタ

        Args:
            stations: 駅リスト
            months_ahead: 何ヶ月前からアプローチ対象にするか（デフォルト3）
        """
        today = date.today()
        approaching = []

        for s in stations:
            remaining = months_until_renewal(s["renewal_month"], today)
            if remaining <= months_ahead:
                s["months_until_renewal"] = remaining
                approaching.append(s)
                logger.info(
                    f"[対象] {s['station_name']}駅 ({s['line_name']}) "
                    f"更新月: {s['renewal_month']}月 (残り{remaining}ヶ月)"
                )

        logger.info(f"更新月{months_ahead}ヶ月以内: {len(approaching)}/{len(stations)}駅")
        return approaching

    def search_businesses_for_station(self, station: dict) -> list[dict]:
        """1駅の周辺事業者を検索＋詳細取得"""
        lat = station.get("lat", 0)
        lng = station.get("lng", 0)
        name = station["station_name"]

        if lat == 0 and lng == 0:
            geo = self.maps.geocode_station(name)
            if geo:
                lat, lng = geo["lat"], geo["lng"]
            else:
                logger.warning(f"座標が取得できません: {name}駅")
                return []

        businesses = self.maps.search_nearby_businesses(lat, lng, name)

        for biz in businesses:
            details = self.maps.get_place_details(biz.get("place_id", ""))
            if details:
                biz["phone"] = details.get("phone", "")
                biz["website"] = details.get("website", "")
                biz["email"] = details.get("email", "")

        return businesses

    def deduplicate_with_crm(self, businesses: list[dict]) -> list[dict]:
        """Notion CRMと照合して重複を除外"""
        unique = []
        for biz in businesses:
            email = biz.get("email", "")
            if email:
                existing = self.notion.find_by_email(email)
                if existing:
                    logger.info(f"[重複スキップ] {biz['name']} ({email})")
                    continue
            unique.append(biz)

        skipped = len(businesses) - len(unique)
        if skipped > 0:
            logger.info(f"重複除外: {skipped}件スキップ → {len(unique)}件が対象")
        return unique

    def register_to_crm(self, businesses: list[dict]) -> dict:
        """事業者データをNotion CRMに登録"""
        result = {"registered": 0, "failed": 0}

        for biz in businesses:
            crm_data = {
                "name": biz["name"],
                "email": biz.get("email", ""),
                "pipeline": PIPELINE_NAVITA,
                "category": biz.get("category", "その他"),
                "address": biz.get("address", ""),
                "status": "new",
                "source": "Googleマップ",
            }
            try:
                self.notion.add_crm_record(crm_data)
                result["registered"] += 1
            except Exception as e:
                logger.error(f"CRM登録エラー: {biz['name']} - {e}")
                result["failed"] += 1

        return result

    def send_emails(self, targets_with_email: list[dict]) -> dict:
        """メール生成→スケジューラー経由で送信"""
        email_targets = self.email_gen.generate_batch(targets_with_email)

        send_result = self.scheduler.execute_send(
            pipeline=PIPELINE_NAVITA,
            targets=email_targets,
            send_func=self.mail_sender.send,
        )

        return send_result

    def run(self, csv_path: Path | None = None, months_ahead: int = 3) -> dict:
        """パイプライン全体を実行

        1. 駅リスト読み込み
        2. 更新月フィルタ
        3. 周辺事業者検索
        4. 重複除外
        5. CRM登録
        6. メール送信
        """
        mode = "DRY_RUN" if self.dry_run else "LIVE"
        logger.info(f"=== ナビタパイプライン開始 [{mode}] ===")

        # 1. 駅リスト読み込み
        stations = self.load_stations(csv_path)
        if not stations:
            logger.error("駅リストが空です。処理を中断します。")
            return {"mode": mode, "error": "駅リストが空"}

        # 2. 更新月フィルタ
        target_stations = self.filter_approaching_renewal(stations, months_ahead)
        if not target_stations:
            logger.info("更新月が近い駅はありません。")
            return {
                "mode": mode,
                "total_stations": len(stations),
                "target_stations": 0,
                "businesses_found": 0,
            }

        # 3. 周辺事業者検索
        all_businesses = []
        for station in target_stations:
            businesses = self.search_businesses_for_station(station)
            all_businesses.extend(businesses)

        # 4. 重複除外
        unique_businesses = self.deduplicate_with_crm(all_businesses)

        # 5. CRM登録
        crm_result = self.register_to_crm(unique_businesses)

        # 6. メール送信（メールアドレスがある事業者のみ）
        sendable = [b for b in unique_businesses if b.get("email")]
        send_result = {}
        if sendable:
            send_result = self.send_emails(sendable)
        else:
            logger.info("メールアドレス付きの事業者がないため、送信はスキップ")

        # カテゴリ別集計
        by_category = {}
        for biz in unique_businesses:
            cat = biz.get("category", "その他")
            by_category[cat] = by_category.get(cat, 0) + 1

        # ログをNotionに記録
        self.notion.log_execution({
            "action": "navita_pipeline",
            "pipeline": PIPELINE_NAVITA,
            "target": f"{len(target_stations)}駅 / {len(unique_businesses)}事業者",
            "status": "success",
            "detail": (
                f"駅: {len(target_stations)}/{len(stations)} / "
                f"事業者: {len(all_businesses)}件検出 → "
                f"{len(unique_businesses)}件(重複除外後) / "
                f"CRM登録: {crm_result['registered']}件 / "
                f"メール送信: {send_result.get('sent', 0)}件"
            ),
            "mode": "dry_run" if self.dry_run else "live",
        })

        summary = {
            "mode": mode,
            "total_stations": len(stations),
            "target_stations": len(target_stations),
            "target_station_names": [s["station_name"] for s in target_stations],
            "businesses_found": len(all_businesses),
            "after_dedup": len(unique_businesses),
            "by_category": by_category,
            "crm_registration": crm_result,
            "email_send": send_result,
        }

        logger.info(f"=== ナビタパイプライン完了 [{mode}] ===")
        return summary


if __name__ == "__main__":
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    pipeline = NavitaPipeline(dry_run=True)
    result = pipeline.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
