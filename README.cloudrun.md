# 3D Generation API - Deploy to Cloud Run

This repo contains a FastAPI app (`api.py`) that generates 3D STL files via Tencent AI3D and stores them on Supabase.

## Prerequisites
- gcloud CLI installed and authenticated
- A GCP project selected: `gcloud config set project YOUR_PROJECT_ID`
- Artifact Registry repository (optional; defaults to gcr.io if not created)
- Supabase project with a bucket (default `memory-photos`)
- Tencent Cloud credentials

## Configure environment
1. Create a `.env` from the sample and fill in values (for local testing):
   ```bash
   cp .env.sample .env
   ```
2. For Cloud Run, create a Secret or supply environment variables directly.

Required variables:
- `CORS_ALLOWED_ORIGINS`
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET`
- `TENCENT_SECRET_ID`, `TENCENT_SECRET_KEY`

## Build and deploy

### Option A: Using gcloud builds submit (Dockerfile provided)
```bash
PROJECT_ID=your-project-id
SERVICE=convert-to-3d
REGION=us-central1
IMAGE=gcr.io/$PROJECT_ID/$SERVICE:latest

gcloud auth configure-docker

gcloud builds submit --tag $IMAGE .

gcloud run deploy $SERVICE \
  --image $IMAGE \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --max-instances 3 \
  --set-env-vars CORS_ALLOWED_ORIGINS="https://your-frontend.example" \
  --set-env-vars SUPABASE_URL="your_supabase_url" \
  --set-env-vars SUPABASE_ANON_KEY="your_anon_key" \
  --set-env-vars SUPABASE_SERVICE_KEY="your_service_key" \
  --set-env-vars SUPABASE_BUCKET="memory-photos" \
  --set-env-vars TENCENT_SECRET_ID="your_tencent_id" \
  --set-env-vars TENCENT_SECRET_KEY="your_tencent_key"
```

### Option B: With Cloud Build (cloudbuild.yaml)
```bash
PROJECT_ID=your-project-id
SERVICE=convert-to-3d
REGION=us-central1

# Submits Cloud Build, which builds and deploys via cloudbuild.yaml
gcloud builds submit --substitutions _SERVICE=$SERVICE,_REGION=$REGION
```

## Local run
```bash
pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8080
```

## Health check
`GET /health` should return a JSON status object.
