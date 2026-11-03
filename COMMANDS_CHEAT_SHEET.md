# BPSC Minutes Bot — Quick Reference & Operations Guide

This guide contains all the direct commands to manage, inspect, and debug the Sol BPSC Bot on Google Cloud.

---

## 1. Connecting to the VM

Always open **Google Cloud Shell** in your browser, then run:

```bash
gcloud compute ssh bpsc-bot --zone=us-central1-a
```

*(If prompted to create an SSH key or accept defaults, type `Y` or press `Enter`).*

---

## 2. Updating the Bot to the Latest Code

Whenever code is changed or pushed to GitHub, run this inside the VM:

```bash
cd ~/bpsc && git pull && sudo systemctl restart bpsc-bot
```

To verify the service is active and running:

```bash
sudo systemctl status bpsc-bot
```

---

## 3. Watching Live Bot Logs in Real Time

To see what the bot is doing right as you send commands in Telegram:

```bash
journalctl -u bpsc-bot -f
```

*(Press `Ctrl + C` at any time to exit the live log stream).*

To see the last 100 lines of logs if something failed:

```bash
journalctl -u bpsc-bot -n 100 --no-pager
```

---

## 4. Telegram Channel Commands (Send directly in Telegram)

Send any of these in your **BPSC Cuttings** channel:

| Command | What it does |
|---|---|
| `run` or `run 2026-10-24` | Starts processing saved newspaper PDFs for that date |
| `retry` or `retry 2026-10-24` | Re-queues a failed or interrupted edition without losing cached pages |
| `today` or `/today` | Generates today's web-curated current affairs digest (AI, National, International, Bihar) |
| `practice 5` | Gives 5 instant BPSC exam practice MCQs with explanations |
| `status` | Checks bot state |

---

## 5. Emergency Service Controls

If the bot ever freezes or needs a full restart:

```bash
# Restart the bot
sudo systemctl restart bpsc-bot

# Stop the bot
sudo systemctl stop bpsc-bot

# Start the bot
sudo systemctl start bpsc-bot
```

---

## 6. Inspecting Cached Edition Data on the VM

Every page extracted is cached locally on the VM at:

```bash
ls -lh ~/bpsc/data/
ls -lh ~/bpsc/data/2026-10-24/
```
