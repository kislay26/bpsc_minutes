# Deploying BPSC‑Minutes with CI/CD on Google Cloud (Gemini)

This guide captures everything we learned while setting up the GitHub‑Actions CI/CD pipeline that builds, pushes, and deploys the **BPSC‑Minutes** service to **Google Cloud (Gemini / Cloud Run)**.  The repository already contains a workflow file at
`.github/workflows/main.yml` – the steps below explain the surrounding Google Cloud configuration and the GitHub‑side setup that makes the pipeline work.

---

## 📦 Prerequisites

| Requirement | How to obtain |
|------------|----------------|
| **Google Cloud project** | Create a new project in the Google Cloud Console (or reuse an existing one). Record the **Project ID** (e.g., `my‑bpsc‑project`). |
| **Billing** | Attach a billing account to the project – required for Cloud Run, Artifact Registry, and Cloud Build. |
| **APIs enabled** | Enable the following APIs for the project:
- Cloud Run (`run.googleapis.com`)
- Artifact Registry (`artifactregistry.googleapis.com`) or Container Registry (`containerregistry.googleapis.com`)
- Cloud Build (`cloudbuild.googleapis.com`)
- IAM (`iam.googleapis.com`)
- Secret Manager (optional) |
| **gcloud CLI** | Install locally ( https://cloud.google.com/sdk/docs/install ) and run `gcloud auth login` to authenticate. |
| **GitHub Personal Access Token** | Must have `repo` scope; stored as a secret in the repo (see *GitHub Secrets* section). |
| **Docker** | Required for building the container image locally (the CI workflow does this on Ubuntu runners). |

---

## 🔐 GitHub Secrets & Variables

The workflow expects three secrets (and optionally a variable) to be present in **Repository → Settings → Secrets and variables → Actions**:

| Secret / Variable | Description | Example value |
|-------------------|-------------|---------------|
| `GCP_WIP` | Workload‑Identity Provider resource name (e.g., `projects/123456/locations/global/workloadIdentityPools/my‑pool/providers/github`). See *Workload Identity Federation* below. |
| `GCP_SA` | Service‑account email that the pipeline will impersonate (e.g., `bpsc-minutes-sa@my-bpsc-project.iam.gserviceaccount.com`). |
| `GCP_PROJECT` | The Google Cloud **Project ID** (plain text, can be a repository **Variable**). |
| `REGION` (optional) | Cloud Run region (`us-central1` is a good default). |

> **Do not** commit any of these values to the repository. They are kept secret on GitHub.

---

## 🛠️ Google Cloud Setup Steps

1. **Create the project**
   ```bash
   gcloud projects create my-bpsc-project --name="BPSC Minutes"
   gcloud config set project my-bpsc-project
   ```
2. **Link a billing account**
   ```bash
   gcloud beta billing projects link my-bpsc-project --billing-account=YOUR_BILLING_ACCOUNT_ID
   ```
3. **Enable required APIs**
   ```bash
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com iam.googleapis.com
   ```
4. **Create a service account** that the CI will impersonate
   ```bash
   gcloud iam service-accounts create bpsc-minutes-sa \
       --display-name="BPSC Minutes CI service account"
   ```
5. **Grant the service account the necessary roles**
   ```bash
   # Cloud Run Admin + Service Account User + Artifact Registry Writer
   gcloud projects add-iam-policy-binding my-bpsc-project \
       --member="serviceAccount:bpsc-minutes-sa@my-bpsc-project.iam.gserviceaccount.com" \
       --role="roles/run.admin"
   gcloud projects add-iam-policy-binding my-bpsc-project \
       --member="serviceAccount:bpsc-minutes-sa@my-bpsc-project.iam.gserviceaccount.com" \
       --role="roles/iam.serviceAccountUser"
   gcloud projects add-iam-policy-binding my-bpsc-project \
       --member="serviceAccount:bpsc-minutes-sa@my-bpsc-project.iam.gserviceaccount.com" \
       --role="roles/artifactregistry.writer"
   ```
6. **Create an Artifact Registry repository** (or use Container Registry). Example with Artifact Registry:
   ```bash
   gcloud artifacts repositories create bpsc-repo \
       --repository-format=docker \
       --location=us-central1 \
       --description="Docker images for BPSC Minutes"
   ```
   The image name used in the workflow will be:
   `us-central1-docker.pkg.dev/<PROJECT_ID>/bpsc-repo/bpsc-minutes:<sha>`
7. **Set up Workload Identity Federation** (so GitHub Actions can obtain short‑lived GCP tokens without a long‑lived key file).
   - In the Cloud Console, go to **IAM → Workload Identity Pools** → *Create pool* → name it `github-pool`.
   - Inside the pool, **Create provider** → *GitHub* → specify your GitHub organization/user (`kislay26`).
   - Add an attribute mapping:
     ```
     attribute.repository = "${{github.repository}}"
     attribute.ref = "${{github.ref}}"
     ```
   - Click **Create**.  Note the **resource name** that appears, e.g.:
     `projects/123456/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
   - Store that full resource name in the GitHub secret `GCP_WIP`.
8. **Allow the pool to impersonate the service account**
   ```bash
   gcloud iam service-accounts add-iam-policy-binding \
       bpsc-minutes-sa@my-bpsc-project.iam.gserviceaccount.com \
       --member="principalSet://iam.googleapis.com/projects/123456/locations/global/workloadIdentityPools/github-pool/*" \
       --role="roles/iam.workloadIdentityUser"
   ```
   This grants any GitHub workflow that authenticates via the pool the ability to act as the service account.

---

## 🚀 CI/CD Workflow Overview (GitHub Actions)

The file `.github/workflows/main.yml` does the heavy lifting.  Briefly:

1. **Checkout** the repository.
2. **Set up Python** (for any test step).
3. **Install dependencies** from `requirements.txt` (optional).
4. **Authenticate to GCP** using the `google-github-actions/auth@v2` action with the two secrets (`GCP_WIP` and `GCP_SA`). This yields a short‑lived access token.
5. **Configure Docker** to push to the Artifact Registry (`gcloud auth configure-docker`).
6. **Build the Docker image** and tag it with the commit SHA:
   ```bash
   IMAGE=gcr.io/${{ secrets.GCP_PROJECT }}/bpsc-minutes:${{ github.sha }}
   docker build -t $IMAGE .
   docker push $IMAGE
   ```
7. **Deploy to Cloud Run** using `gcloud run deploy`.
8. The job finishes with a quick status output.

Because the workflow triggers on **push to `main`**, any new commit (including the forced push you just performed) automatically starts a new build and deployment.

---

## 📋 Checklist for a First Deploy

1. **Create GCP project & enable APIs** – completed in steps 1‑3 above.
2. **Create service account & assign roles** – step 4‑5.
3. **Create Artifact Registry repository** – step 6.
4. **Set up Workload Identity Federation** – step 7‑8.
5. **Add GitHub secrets** (`GCP_WIP`, `GCP_SA`, `GCP_PROJECT`).
6. **Push the repository** – you already forced a push; GitHub Actions started the workflow.
7. **Verify the Cloud Run service** – after the workflow succeeds, go to **Cloud Run** in the GCP console.  You should see a service named `bpsc‑minutes` with the latest image tag.
8. **Test the deployed endpoint** – if the container exposes HTTP, you can hit the URL shown in Cloud Run (it ends with `run.app`).

---

## 🛑 Common Pitfalls & Tips

- **Secret‑Scanning Push Protection** – never commit files that contain credentials (e.g., the service‑account JSON).  Use `.gitignore` (already contains `.env`, `.venv/`, `.model-cache/`).
- **Workload Identity Provider URL** – the exact string must be stored *exactly* in `GCP_WIP`.  A missing `/` or extra whitespace will cause authentication failures.
- **Image name mismatch** – the workflow builds `gcr.io/${{ secrets.GCP_PROJECT }}/bpsc-minutes:${{ github.sha }}`.  If you use Artifact Registry (`us-central1-docker.pkg.dev`), adjust the workflow or repository name accordingly.
- **Region consistency** – Cloud Run region (`--region`) must match the region of the Artifact Registry repository.
- **Permissions** – if the workflow fails at `gcloud run deploy`, double‑check that the service account has `run.admin` and `iam.serviceAccountUser` on the project.

---

## 📚 Further Reading
- **Google Cloud Workload Identity Federation** – https://cloud.google.com/iam/docs/workload-identity-federation
- **GitHub Actions for GCP** – https://github.com/google-github-actions/auth
- **Deploying containers to Cloud Run** – https://cloud.google.com/run/docs/deploying
- **Secret scanning & push protection** – https://docs.github.com/code-security/secret-scanning/working-with-secret-scanning-and-push-protection

---

*This guide is a living document.  As you iterate on the CI/CD pipeline, feel free to update it with new steps or lessons learned.*

