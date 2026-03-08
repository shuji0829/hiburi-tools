Attribute VB_Name = "SendFromCSV"
' HIBURI営業自動化システム - Outlook送信VBAモジュール
' Python側で生成したCSVキューを読み込み、Outlookからメール送信する
'
' 使い方:
' 1. OutlookのVBAエディタにこのモジュールをインポート
' 2. SendFromCSVマクロを実行
' 3. CSVファイルパスを指定

Sub SendFromCSV()
    Dim fso As Object, ts As Object
    Dim filePath As String
    Dim line As String
    Dim parts() As String
    Dim olApp As Outlook.Application
    Dim olMail As Outlook.MailItem
    Dim firstLine As Boolean
    Dim sentCount As Long

    filePath = InputBox("送信キューCSVファイルのパスを入力してください:", "HIBURI送信システム")
    If filePath = "" Then Exit Sub

    If Dir(filePath) = "" Then
        MsgBox "ファイルが見つかりません: " & filePath, vbCritical
        Exit Sub
    End If

    Set fso = CreateObject("Scripting.FileSystemObject")
    Set ts = fso.OpenTextFile(filePath, 1, False, -1) ' UTF-8対応
    Set olApp = Outlook.Application

    firstLine = True
    sentCount = 0

    Do While Not ts.AtEndOfStream
        line = ts.ReadLine
        If firstLine Then
            firstLine = False  ' ヘッダー行スキップ
        Else
            parts = Split(line, ",")
            If UBound(parts) >= 3 Then
                Set olMail = olApp.CreateItem(olMailItem)
                olMail.To = Trim(Replace(parts(1), """", ""))
                olMail.Subject = Trim(Replace(parts(2), """", ""))
                olMail.Body = Trim(Replace(parts(3), """", ""))
                olMail.Send
                sentCount = sentCount + 1
            End If
        End If
    Loop

    ts.Close
    Set ts = Nothing
    Set fso = Nothing

    MsgBox sentCount & "件のメールを送信しました。", vbInformation, "HIBURI送信システム"
End Sub
