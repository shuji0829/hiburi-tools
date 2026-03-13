#!/bin/bash
# Slackチャンネルの最新メッセージを取得するヘルパースクリプト
# 使い方: ./scripts/slack-read.sh <channel> [件数]
# 例: ./scripts/slack-read.sh general        → 最新5件
#     ./scripts/slack-read.sh general 10     → 最新10件

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

CHANNEL="${1:?Usage: slack-read.sh <channel> [件数]}"
LIMIT="${2:-5}"

# チャンネル名→IDの変換
declare -A CHANNEL_MAP=(
    ["general"]="C0A96UBMDC5"
    ["random"]="C0A9DV4LZFE"
    ["看板"]="C0A940E3YRZ"
)

CHANNEL_ID="${CHANNEL_MAP[$CHANNEL]:-$CHANNEL}"

RESPONSE=$(curl -s "https://slack.com/api/conversations.history?channel=${CHANNEL_ID}&limit=${LIMIT}" \
    -H "Authorization: Bearer $SLACK_BOT_TOKEN")

if [ "$(echo "$RESPONSE" | jq -r '.ok')" != "true" ]; then
    echo "Error: $(echo "$RESPONSE" | jq -r '.error')" >&2
    exit 1
fi

echo "$RESPONSE" | jq -r '.messages[] | "[\(.ts | tonumber | strftime("%Y-%m-%d %H:%M:%S"))] \(.user // .bot_id): \(.text)"'
