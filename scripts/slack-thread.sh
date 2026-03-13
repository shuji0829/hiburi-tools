#!/bin/bash
# Slack投稿へのスレッド返信を取得するヘルパースクリプト
# 使い方: ./scripts/slack-thread.sh <channel> <timestamp>
# 例: ./scripts/slack-thread.sh general 1773442136.934349
#
# timestampはslack-read.shの出力やslack-post.shの返り値(ts)から取得可能

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

if [ -z "${SLACK_BOT_TOKEN:-}" ]; then
    echo "Error: SLACK_BOT_TOKEN is not set" >&2
    exit 1
fi

CHANNEL="${1:?Usage: slack-thread.sh <channel> <timestamp>}"
THREAD_TS="${2:?Usage: slack-thread.sh <channel> <timestamp>}"

# チャンネル名→IDの変換
declare -A CHANNEL_MAP=(
    ["general"]="C0A96UBMDC5"
    ["random"]="C0A9DV4LZFE"
    ["看板"]="C0A940E3YRZ"
)

CHANNEL_ID="${CHANNEL_MAP[$CHANNEL]:-$CHANNEL}"

RESPONSE=$(curl -s "https://slack.com/api/conversations.replies?channel=${CHANNEL_ID}&ts=${THREAD_TS}" \
    -H "Authorization: Bearer $SLACK_BOT_TOKEN")

if [ "$(echo "$RESPONSE" | jq -r '.ok')" != "true" ]; then
    echo "Error: $(echo "$RESPONSE" | jq -r '.error')" >&2
    exit 1
fi

# 最初のメッセージ（親投稿）はスキップし、返信のみ表示
REPLY_COUNT=$(echo "$RESPONSE" | jq '.messages | length')

if [ "$REPLY_COUNT" -le 1 ]; then
    echo "（スレッド返信なし）"
    exit 0
fi

echo "$RESPONSE" | jq -r '.messages[1:] | .[] | "[\(.ts | tonumber | strftime("%Y-%m-%d %H:%M:%S"))] \(.user // .bot_id): \(.text)"'
