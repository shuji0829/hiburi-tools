"""HIBURI営業自動化システム - 診療科別メールテンプレート自動生成

5つの診療科（内科・歯科・薬局・整形外科・皮膚科）に合わせた
営業メールを生成する。HIBURIの商材（WEB制作・広告・DX）を
セット提案する文面。

Claude APIを使った文面自動生成にも対応。
"""

import logging
from datetime import date

import anthropic

from src.config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

COMPANY_INFO = {
    "name": "株式会社HIBURI",
    "services": [
        "ホームページ制作・リニューアル",
        "WEB広告運用（Google広告・SNS広告）",
        "DXサポート（予約システム・電子カルテ連携・業務効率化）",
        "経営コンサルティング",
    ],
    "signature": (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "株式会社HIBURI\n"
        "代表取締役\n"
        "TEL: XXX-XXXX-XXXX\n"
        "MAIL: info@hiburi.co.jp\n"
        "WEB: https://hiburi.co.jp\n"
        "━━━━━━━━━━━━━━━━━━━━"
    ),
}

# 診療科ごとの提案ポイント
CATEGORY_SELLING_POINTS = {
    "内科": {
        "pain_points": [
            "開業直後の患者集客に不安がある",
            "近隣の競合クリニックとの差別化が難しい",
            "オンライン予約やWEB問診の導入を検討中",
        ],
        "proposals": [
            "内科特化のホームページで「症状から探す」導線を構築",
            "Google広告で「地域名×内科」の検索上位を獲得",
            "WEB問診・オンライン予約システムの導入で受付業務を効率化",
        ],
    },
    "歯科": {
        "pain_points": [
            "歯科は競争が激しく、開業初期の集患が課題",
            "自費診療（矯正・インプラント・ホワイトニング）のPRが重要",
            "口コミ・レビュー対策が急務",
        ],
        "proposals": [
            "自費診療メニューを訴求するビジュアル重視のホームページ制作",
            "Instagram・Google広告で地域の潜在患者にリーチ",
            "Googleビジネスプロフィール最適化と口コミ施策",
        ],
    },
    "薬局": {
        "pain_points": [
            "処方箋依存からの脱却、かかりつけ薬局としてのブランディング",
            "地域住民への認知度向上",
            "電子処方箋やオンライン服薬指導への対応",
        ],
        "proposals": [
            "かかりつけ薬局としての信頼感を伝えるホームページ制作",
            "地域密着型のWEB広告で近隣住民に認知拡大",
            "電子処方箋・オンライン服薬指導システムの導入サポート",
        ],
    },
    "整形外科": {
        "pain_points": [
            "リハビリ施設の充実をアピールしたい",
            "スポーツ整形・高齢者対応など専門性の打ち出し",
            "MRI等の設備投資の回収に向けた集患が必要",
        ],
        "proposals": [
            "設備・リハビリ環境を魅力的に伝えるホームページ制作",
            "「地域名×整形外科×腰痛」などロングテールキーワードのSEO/広告",
            "リハビリ予約管理システムのDX化で患者満足度向上",
        ],
    },
    "皮膚科": {
        "pain_points": [
            "美容皮膚科の需要拡大に対応したい",
            "自費診療（シミ取り・脱毛等）の集患がカギ",
            "SNS（Instagram等）での発信が重要な診療科",
        ],
        "proposals": [
            "症例写真・ビフォーアフターを活用した美容皮膚科向けHP制作",
            "Instagram広告＋Google広告のクロスメディア戦略",
            "LINE予約・オンライン問診で若年層の利便性を向上",
        ],
    },
}


class EmailGenerator:
    """診療科別メールテンプレート生成"""

    def __init__(self):
        self.company = COMPANY_INFO
        self.selling_points = CATEGORY_SELLING_POINTS

    def generate(self, target: dict) -> dict:
        """テンプレートからメール文面を生成

        Args:
            target: {
                "name": str,        # 診療所名
                "category": str,    # 内科/歯科/薬局/整形外科/皮膚科
                "address": str,     # 住所（任意）
            }

        Returns:
            {"subject": str, "body": str}
        """
        name = target.get("name", "")
        category = target.get("category", "その他")

        points = self.selling_points.get(category)
        if points is None:
            points = self.selling_points["内科"]
            category_label = "クリニック"
        else:
            category_label = category

        subject = self._build_subject(name, category)
        body = self._build_body(name, category, category_label, points)

        return {"subject": subject, "body": body}

    def _build_subject(self, name: str, category: str) -> str:
        subjects = {
            "内科": f"【ご開業おめでとうございます】{name}様のWEB集患・DXをサポートいたします",
            "歯科": f"【ご開業おめでとうございます】{name}様の集患・自費診療PRをお手伝いします",
            "薬局": f"【ご開業おめでとうございます】{name}様のかかりつけ薬局ブランディングをご支援",
            "整形外科": f"【ご開業おめでとうございます】{name}様のリハビリ集患・WEB戦略をご提案",
            "皮膚科": f"【ご開業おめでとうございます】{name}様の美容皮膚科集患・SNS戦略をご提案",
        }
        return subjects.get(
            category,
            f"【ご開業おめでとうございます】{name}様のWEB集患をサポートいたします",
        )

    def _build_body(self, name: str, category: str, category_label: str, points: dict) -> str:
        today = date.today()
        proposals_text = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(points["proposals"]))
        pain_points_text = "\n".join(f"  - {p}" for p in points["pain_points"])

        body = f"""{name} 御中

突然のご連絡失礼いたします。
株式会社HIBURIの代表を務めております。

この度はご開業、誠におめでとうございます。

弊社は{category_label}をはじめとする医療機関様に特化した
WEB集患・DX支援を行っている会社です。

{category_label}の先生方から、開業時によくお聞きする課題として：

{pain_points_text}

といったお声をいただいております。

弊社では、こうした課題に対して以下のサービスをご提供しております：

{proposals_text}

開業後の集患が軌道に乗るまでの大切な時期に、
少しでもお力になれればと思いご連絡いたしました。

まずは15分程度のオンライン面談で、
{name}様の現状やお困りごとをお聞かせいただけませんか？

ご都合のよい日時をいくつかお教えいただけますと幸いです。

何卒よろしくお願い申し上げます。

{self.company["signature"]}"""

        return body

    def generate_batch(self, targets: list[dict]) -> list[dict]:
        """複数の送信先に対してメール文面を一括生成"""
        results = []
        for t in targets:
            email = self.generate(t)
            results.append({
                **t,
                "subject": email["subject"],
                "body": email["body"],
            })
        return results


class AIEmailGenerator:
    """Claude APIを使ったメール文面自動生成"""

    def __init__(self, api_key: str | None = None, dry_run: bool = True):
        self.api_key = api_key or ANTHROPIC_API_KEY
        self.dry_run = dry_run
        if self.api_key and not dry_run:
            self.client = anthropic.Anthropic(api_key=self.api_key)
        else:
            self.client = None

    def generate(self, target: dict) -> dict:
        """Claude APIでメール文面を生成

        Args:
            target: {
                "name": str,
                "category": str,
                "address": str,
            }
        """
        if self.dry_run or self.client is None:
            logger.info(f"[DRY_RUN] Claude API呼び出しスキップ: {target.get('name')}")
            fallback = EmailGenerator()
            return fallback.generate(target)

        name = target.get("name", "")
        category = target.get("category", "その他")
        address = target.get("address", "")

        prompt = f"""あなたは株式会社HIBURIの営業担当です。
新規開業した医療機関に対して、初回アプローチメールを作成してください。

【送信先情報】
- 診療所名: {name}
- 診療科: {category}
- 住所: {address}

【HIBURIの商材】
- ホームページ制作・リニューアル
- WEB広告運用（Google広告・SNS広告）
- DXサポート（予約システム・電子カルテ連携・業務効率化）
- 経営コンサルティング

【メール作成ルール】
1. 件名は「【ご開業おめでとうございます】」から始める
2. {category}の特有の課題に触れる
3. HIBURIの3つの商材をセットで提案する
4. 15分のオンライン面談を打診する
5. 押し売り感を出さず、誠実で丁寧なトーンにする
6. 500文字以内でコンパクトにまとめる

以下の形式で出力してください：
件名: (ここに件名)
---
(ここに本文)"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = message.content[0].text

            if "---" in response_text:
                parts = response_text.split("---", 1)
                subject_line = parts[0].strip()
                if subject_line.startswith("件名:"):
                    subject_line = subject_line[len("件名:"):].strip()
                elif subject_line.startswith("件名："):
                    subject_line = subject_line[len("件名："):].strip()
                body = parts[1].strip() + f"\n\n{COMPANY_INFO['signature']}"
            else:
                subject_line = f"【ご開業おめでとうございます】{name}様へのご提案"
                body = response_text + f"\n\n{COMPANY_INFO['signature']}"

            logger.info(f"[AI生成] {name}: 件名={subject_line[:30]}...")
            return {"subject": subject_line, "body": body}

        except Exception as e:
            logger.error(f"Claude API エラー: {e} - テンプレートにフォールバック")
            fallback = EmailGenerator()
            return fallback.generate(target)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    gen = EmailGenerator()

    categories = ["内科", "歯科", "薬局", "整形外科", "皮膚科"]
    for cat in categories:
        result = gen.generate({
            "name": f"サンプル{cat}クリニック",
            "category": cat,
        })
        print(f"\n{'='*60}")
        print(f"【{cat}】")
        print(f"件名: {result['subject']}")
        print(f"本文:\n{result['body'][:200]}...")
        print(f"{'='*60}")
