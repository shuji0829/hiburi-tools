"""HIBURI営業自動化システム - メール送信エンジン

VBA経由でOutlookからメール送信を行う。
Pythonからwin32comでOutlookを操作するアプローチと、
VBAスクリプト生成の両方に対応。
"""

import csv
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
logger = logging.getLogger(__name__)

VBA_TEMPLATE_DIR = Path(__file__).parent.parent / "vba"
QUEUE_DIR = Path(__file__).parent.parent / "data" / "mail_queue"


class MailSender:
    """メール送信管理"""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    def send_via_outlook_com(self, target: dict) -> bool:
        """win32comでOutlook送信（Windows環境用）

        Args:
            target: {
                "name": str,
                "email": str,
                "subject": str,
                "body": str,
            }
        """
        if self.dry_run:
            logger.info(
                f"[DRY_RUN] メール送信予定: "
                f"To={target['email']} Subject={target['subject']}"
            )
            return True

        try:
            import win32com.client
            outlook = win32com.client.Dispatch("Outlook.Application")
            mail = outlook.CreateItem(0)
            mail.To = target["email"]
            mail.Subject = target["subject"]
            mail.Body = target["body"]
            mail.Send()
            logger.info(f"[SENT] {target['email']}: {target['subject']}")
            return True
        except ImportError:
            logger.error("win32comが利用できません。Windows環境でpywin32をインストールしてください。")
            return False
        except Exception as e:
            logger.error(f"メール送信エラー: {target['email']} - {e}")
            return False

    def generate_vba_queue(self, targets: list[dict]) -> Path:
        """VBAで読み込み可能なCSVキューファイルを生成

        VBA側でこのCSVを読み込んでOutlookから送信する。
        """
        now = datetime.now(JST)
        filename = f"queue_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = QUEUE_DIR / filename

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=["name", "email", "subject", "body"]
            )
            writer.writeheader()
            for t in targets:
                writer.writerow({
                    "name": t.get("name", ""),
                    "email": t.get("email", ""),
                    "subject": t.get("subject", ""),
                    "body": t.get("body", ""),
                })

        logger.info(f"[キュー生成] {filepath} ({len(targets)}件)")
        return filepath

    def send(self, target: dict) -> bool:
        """統合送信インターフェース"""
        return self.send_via_outlook_com(target)


def generate_vba_script() -> str:
    """Outlook送信用VBAスクリプトを生成"""
    return '''Sub SendFromCSV()
    Dim fso As Object, ts As Object
    Dim filePath As String
    Dim line As String
    Dim parts() As String
    Dim olApp As Outlook.Application
    Dim olMail As Outlook.MailItem
    Dim firstLine As Boolean

    filePath = InputBox("CSVファイルパスを入力してください:")
    If filePath = "" Then Exit Sub

    Set fso = CreateObject("Scripting.FileSystemObject")
    Set ts = fso.OpenTextFile(filePath, 1, False, -1)
    Set olApp = Outlook.Application

    firstLine = True
    Do While Not ts.AtEndOfStream
        line = ts.ReadLine
        If firstLine Then
            firstLine = False
        Else
            parts = Split(line, ",")
            If UBound(parts) >= 3 Then
                Set olMail = olApp.CreateItem(olMailItem)
                olMail.To = Trim(parts(1))
                olMail.Subject = Trim(parts(2))
                olMail.Body = Trim(parts(3))
                olMail.Send
            End If
        End If
    Loop

    ts.Close
    MsgBox "送信完了"
End Sub
'''
