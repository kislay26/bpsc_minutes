# Agent Guidelines & Operational Rules: BPSC Minutes ("Sol")

This file enforces operational instructions and environment facts for any AI agent interacting with this repository.

---

## 1. Google Cloud Environment & VM Access

- **GCP Project ID**: `august-cascade-457313-n3`
- **VM Instance**: `bpsc-bot`
- **Zone**: `us-central1-a`
- **VM Linux User**: `kislaykrishna26`
- **VM Working Directory**: `/home/kislaykrishna26/bpsc`
- **Systemd Service**: `bpsc-bot.service`
- **Auto-Update Cron**: Runs `~/auto_update.sh` every 2 minutes (auto git pull & restart).

### Strict Rules for Guiding the User to the VM:
1. **Never generate direct `ssh.cloud.google.com` links**:
   Google Cloud does not support arbitrary direct SSH deep links and returns a 404 error.
2. **Always provide the official Console links**:
   - **Compute Engine Instances**: `https://console.cloud.google.com/compute/instances?project=august-cascade-457313-n3` (instruct the user to click the blue **SSH** button next to `bpsc-bot`).
   - **Cloud Shell**: `https://shell.cloud.google.com/?project=august-cascade-457313-n3` (run `gcloud compute ssh bpsc-bot --zone=us-central1-a`).
3. **Always inspect the user's terminal prompt before giving commands**:
   - If the user's prompt shows `kislaykrishna26@bpsc-bot:~$` or `~/bpsc$`, **they are ALREADY inside the VM**.
   - **NEVER** instruct the user to run `gcloud compute ssh` when they are already inside the VM (doing so causes `Request had insufficient authentication scopes`).
   - Give them direct in-VM commands:
     * Stream live logs: `journalctl -u bpsc-bot -f`
     * Check latest 100 lines: `journalctl -u bpsc-bot -n 100 --no-pager`
     * Manual update & restart: `cd ~/bpsc && git pull && sudo systemctl restart bpsc-bot`
     * Service status: `sudo systemctl status bpsc-bot`

---

## 2. Daily Newspaper & Telegram Operations

- **Telegram Bot**: `@BPSCCuttingsBot`
- **Telegram Channel**: `BPSC Cuttings` (`-1004260982553`)
- **PDF Upload Format**: Documents must have caption or filename `#TH YYYY-MM-DD` or `#IE YYYY-MM-DD`.
- **Trigger Execution**: Send `run YYYY-MM-DD` or `retry YYYY-MM-DD` in the channel.
- **Cache Reuse**: Disk cache resides in `~/bpsc/data/YYYY-MM-DD/`. Retries reuse audited page regions without re-calling visual models.
