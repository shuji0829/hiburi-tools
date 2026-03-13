#!/bin/bash
# Slackチャンネル一覧を取得するヘルパースクリプト
# 使い方: ./scripts/slack-channels.sh

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

curl -s 'https://slack.com/api/conversations.list?types=public_channel&limit=100' \
    -H "Authorization: Bearer $SLACK_BOT_TOKEN" | jq -r '.channels[] | "\(.id)\t\(.name)"'
