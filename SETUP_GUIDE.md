# Project Setup Cheat‑Sheet

## 1️⃣ Gemini / Antigravity Local Setup
- Install **Antigravity** (`agy` CLI) – follows the official guide: <https://github.com/google/antigravity>
- Ensure the **Google Cloud SDK** (`gcloud`) is installed and added to `PATH`.
- Keep a service‑account JSON key handy (e.g., `august-cascade-457313-n3-cb0b32e0a9b7.json`).

## 2️⃣ Google Cloud – Workload Identity Federation (WIF)
1. **Create a Workload‑Identity Pool** (once per project)
   ```bash
   gcloud iam workload-identity-pools create github-actions-pool \
     --project=august-cascade-457313-n3 \
     --location=global \
     --display-name="GitHub Actions pool for BPSC Minutes"
   ```
2. **Create an OIDC Provider** linked to GitHub
   ```bash
   gcloud iam workload-identity-pools providers create-oidc github-actions-provider \
     --project=august-cascade-457313-n3 \
     --location=global \
     --workload-identity-pool=github-actions-pool \
     --display-name="GitHub Actions provider for BPSC Minutes" \
     --issuer-uri="https://token.actions.githubusercontent.com" \
     --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
     --attribute-condition="assertion.repository == 'kislay26/bpsc_minutes'" \
     --allowed-audiences="sts.googleapis.com/googlecloud"
   ```
3. **Capture the full provider name** – this becomes the `GCP_WIP` secret:
   ```bash
   gcloud iam workload-identity-pools providers describe github-actions-provider \
     --project=august-cascade-457313-n3 \
     --location=global \
     --workload-identity-pool=github-actions-pool \
     --format='value(name)'
   ```
   Example output:
   ```
   projects/424378696816/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider
   ```
4. **Grant the service‑account permission to act as a Workload‑Identity user** (run with a user that has Owner/Service‑Account‑Admin rights):
   ```bash
   gcloud iam service-accounts add-iam-policy-binding 424378696816-compute@developer.gserviceaccount.com \
     --project=august-cascade-457313-n3 \
     --member="principalSet://iam.googleapis.com/projects/august-cascade-457313-n3/locations/global/workloadIdentityPools/github-actions-pool/*" \
     --role="roles/iam.workloadIdentityUser"
   ```

## 3️⃣ GitHub Repository Secrets
| Secret name | Value (copy‑paste) |
|------------|-------------------|
| `GCP_PROJECT` | `august-cascade-457313-n3` |
| `GCP_WIP` | `projects/424378696816/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider` |
| `GCP_SA` | `424378696816-compute@developer.gserviceaccount.com` |
| `NATIVE_PAGES_BUCKET` | `bpsc-native-pages` |

Create them under **Settings → Secrets → Actions** → **New repository secret**.

## 4️⃣ Clean Large Files from Git History (optional but recommended)
If you have large artefacts (e.g., `.model-cache`, `.venv`) that exceed GitHub’s size limits:
1. Clone a fresh copy of the repo.
2. Install `git-filter-repo`:
   ```bash
   pip install --quiet git-filter-repo
   ```
3. Rewrite history to drop the directories:
   ```bash
   git filter-repo --path .model-cache --path .venv --invert-paths
   ```
4. Commit the updated `.gitignore` (if not already) and force‑push:
   ```bash
   git push -u origin main --force
   ```
   > **Note:** This rewrites all commit SHAs; collaborators must re‑clone.

## 5️⃣ GitHub Actions CI/CD Workflow (file: `.github/workflows/main.yml`)
```yaml
name: CI/CD

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build-deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write   # needed for workload‑identity federation
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi

      - name: Run tests (optional)
        run: |
          if command -v pytest >/dev/null 2>&1; then pytest; else echo "No pytest found, skipping tests"; fi

      - name: Authenticate to Google Cloud
        id: auth
        uses: google-github-actions/auth@v2
        with:
          token_format: "access_token"
          workload_identity_provider: ${{ secrets.GCP_WIP }}
          service_account: ${{ secrets.GCP_SA }}

      - name: Configure Docker for GCR
        run: |
          gcloud auth configure-docker

      - name: Build Docker image
        env:
          IMAGE: gcr.io/${{ secrets.GCP_PROJECT }}/bpsc-minutes:${{ github.sha }}
        run: |
          docker build -t $IMAGE .
          docker push $IMAGE

      - name: Deploy to Cloud Run
        env:
          IMAGE: gcr.io/${{ secrets.GCP_PROJECT }}/bpsc-minutes:${{ github.sha }}
          SERVICE_NAME: bpsc-minutes
          REGION: us-central1
        run: |
          gcloud run deploy $SERVICE_NAME \
            --image $IMAGE \
            --region $REGION \
            --platform managed \
            --allow-unauthenticated \
            --quiet
```

