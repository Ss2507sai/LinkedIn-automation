#!/bin/bash
# Launch Chrome (Prince profile) with CDP for Playwright attachment.
# Quit all Chrome windows before running this script.
#
# Chrome 149+ blocks CDP on the default user-data-dir. Use a dedicated dir
# (ChromeForAutomation) with your Prince profile copied or symlinked, OR set:
#   CHROME_USER_DATA_DIR  — e.g. ~/Library/Application Support/Google/ChromeForAutomation
#   CHROME_PROFILE_DIRECTORY — internal folder name (chrome://version → "Profile Path")
#   CHROME_DEBUG_PORT — default 9222

set -euo pipefail

PORT="${CHROME_DEBUG_PORT:-9222}"
USER_DATA_DIR="${CHROME_USER_DATA_DIR:-${HOME}/Library/Application Support/Google/ChromeForAutomation}"
PROFILE_DIR="${CHROME_PROFILE_DIRECTORY:-Default}"

echo "Launching Chrome with remote debugging on port ${PORT}..."
echo "  user-data-dir: ${USER_DATA_DIR}"
echo "  profile:       ${PROFILE_DIR}"
echo "Keep this terminal open while automation runs."

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port="${PORT}" \
  --user-data-dir="${USER_DATA_DIR}" \
  --profile-directory="${PROFILE_DIR}" \
  "$@"
