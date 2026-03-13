#!/bin/bash
set -euo pipefail

# Only run in remote (web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Ensure jq is available (needed for Slack API scripts)
if ! command -v jq &> /dev/null; then
  apt-get update -qq && apt-get install -y -qq jq > /dev/null 2>&1
fi

# Ensure curl is available
if ! command -v curl &> /dev/null; then
  apt-get update -qq && apt-get install -y -qq curl > /dev/null 2>&1
fi

# Load .env into session environment if available
if [ -f "$CLAUDE_PROJECT_DIR/.env" ] && [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  while IFS= read -r line; do
    # Skip comments and empty lines
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    echo "export $line" >> "$CLAUDE_ENV_FILE"
  done < "$CLAUDE_PROJECT_DIR/.env"
fi

# Make helper scripts executable
chmod +x "$CLAUDE_PROJECT_DIR/scripts/"*.sh 2>/dev/null || true
