# Useful Commands for Google Cloud VM (`bpsc-bot`)

Your BPSC Telegram bot is deployed on Google Cloud Compute Engine (`us-central1-a`) running on the Debian 12 `e2-micro` Always Free tier.

---

## 1. Connect to VM via Cloud Shell
```bash
gcloud compute ssh bpsc-bot --zone=us-central1-a
```

---

## 2. Check Bot Service Status
```bash
sudo systemctl status bpsc-bot
```

---

## 3. View Live Logs (Real-time Processing)
```bash
sudo journalctl -u bpsc-bot -f
```

---

## 4. Restart Bot Service
```bash
sudo systemctl restart bpsc-bot
```

---

## 5. Stop / Start Bot Service
```bash
# Stop
sudo systemctl stop bpsc-bot

# Start
sudo systemctl start bpsc-bot
```

---

## 6. Check Job History & Queue from CLI
```bash
cd ~/bpsc && source venv/bin/activate
python bot.py status
```

---

## 7. Retry a Failed Edition
```bash
cd ~/bpsc && source venv/bin/activate
python bot.py retry 2026-10-10
```

---

## 8. Updating Code on Server (if you modify code locally)

### Step A (On your PC):
Create a fresh code bundle. This deliberately excludes `.env`, so the server's
Telegram token and model credentials remain on the server:
```powershell
$files = @('bot.py', 'core.py', 'sol_chat.py', 'pdf_flow.py', 'news_selection.py', 'gemini_native.py', 'native_layout.py', 'region_assignment.py', 'transport.py', 'gemini_quota.py', 'gemini_budget.py', 'gemini_layout_trial.py', 'raster_layout.py', 'staged_scan.py', 'requirements.txt', 'selection_skill')
Remove-Item -LiteralPath 'deploy.zip' -ErrorAction SilentlyContinue
Compress-Archive -LiteralPath $files -DestinationPath 'deploy.zip' -CompressionLevel Optimal
```

### Step B (In Cloud Shell):
Upload `deploy.zip`, copy to VM and restart:
```bash
gcloud compute scp ~/deploy.zip bpsc-bot:~/ --zone=us-central1-a
gcloud compute ssh bpsc-bot --zone=us-central1-a --command="unzip -o ~/deploy.zip -d ~/bpsc/ && sudo systemctl restart bpsc-bot"
```

---

## 9. How to Pause or Stop the App Whenever Needed

You have three levels of control depending on what you want to do:

### Level 1: Temporarily pause the bot (Keep server alive, stop bot process)
Use this if you want the bot to stop listening to Telegram messages temporarily:
```bash
# Connect to VM
gcloud compute ssh bpsc-bot --zone=us-central1-a

# Pause/Stop bot
sudo systemctl stop bpsc-bot

# Start bot back up whenever you are ready:
sudo systemctl start bpsc-bot
```

### Level 2: Stop the VM completely (Keep data and files intact, power off machine)
Use this if you are not using the bot for weeks and want to power down the VM:
```bash
# In Cloud Shell:
gcloud compute instances stop bpsc-bot --zone=us-central1-a

# To turn it back on later:
gcloud compute instances start bpsc-bot --zone=us-central1-a
```
*(Your files, virtual environment, and database stay completely safe on the disk).*

### Level 3: Permanently delete everything (Zero footprint, removes VM & disk)
Use this if you want to completely remove the server and project:
```bash
# In Cloud Shell:
gcloud compute instances delete bpsc-bot --zone=us-central1-a
```

---

## 10. How to Check Billing (Confirming It's ₹0)

1. Open **[console.cloud.google.com/billing](https://console.cloud.google.com/billing)**.
2. Click **Reports** in the left menu.
3. Your usage is broken down by service:
   - **Compute Engine (e2-micro)**: ₹0 (covered under the free tier 744 hours/month discount).
   - **Persistent Disk (Standard 30 GB)**: ₹0 (covered under free 30 GB allowance).
   - **Network Egress**: ₹0 (1 GB free per month, Telegram API only takes a few MBs).
4. **Setting a ₹0/₹1 Budget Alert** (Recommended):
   - In the Billing menu, go to **Budgets & alerts** → **Create Budget**.
   - Set the budget threshold to ₹1.
   - Enter your email address to get notified instantly if any billable charge ever occurs.

