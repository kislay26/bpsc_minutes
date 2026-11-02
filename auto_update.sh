#!/bin/bash
# Robust auto-update: force pulls from GitHub and restarts the bot service.
# Cron: */2 * * * * /home/kislaykrishna26/auto_update.sh >> /home/kislaykrishna26/auto_update.log 2>&1

set -euo pipefail
REPO_DIR="/home/kislaykrishna26/bpsc"
SERVICE="bpsc-bot"
LOG_MARK="[auto_update $(date '+%Y-%m-%d %H:%M:%S')]"

cd "$REPO_DIR"

# Remove git lock files that can block pulls
rm -f .git/index.lock .git/refs/heads/*.lock 2>/dev/null || true

# Stash any local changes (shouldn't be any, but just in case)
git stash --quiet 2>/dev/null || true

# Fetch and hard reset to origin/main (never fails on conflict)
git fetch origin --quiet
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    # No update needed
    exit 0
fi

echo "$LOG_MARK Updating $LOCAL -> $REMOTE"
git reset --hard origin/main --quiet

# Activate venv and install any new dependencies
source "$REPO_DIR/venv/bin/activate"
pip install -q -r requirements.txt 2>/dev/null || true

# Restart the service
sudo systemctl restart "$SERVICE"
echo "$LOG_MARK Service restarted successfully."
