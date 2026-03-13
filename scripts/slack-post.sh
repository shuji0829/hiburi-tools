#!/bin/bash
# Slack APIでメッセージを送信するヘルパースクリプト
# 使い方: ./scripts/slack-post.sh <channel> <message>
# 例: ./scripts/slack-post.sh general "テストメッセージ"

set -euo pipefail

# .envからトークンを読み込み
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

if [ -z "${SLACK_BOT_TOKEN:-}" ]; then
    echo "Error: SLACK_BOT_TOKEN is not set" >&2
    exit 1
fi

CHANNEL="${1:?Usage: slack-post.sh <channel> <message>}"
MESSAGE="${2:?Usage: slack-post.sh <channel> <message>}"

curl -s -X POST 'https://slack.com/api/chat.postMessage' \
    -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
    -H 'Content-Type: application/json; charset=utf-8' \
    -d "$(jq -n --arg channel "$CHANNEL" --arg text "$MESSAGE" '{channel: $channel, text: $text}')"
