#!/usr/bin/env bash
# RecoverAI — one-shot, idempotent deployment to Google Cloud + Firebase.
#
#   PROJECT_ID=my-proj ./deploy/deploy.sh            # everything
#   PROJECT_ID=my-proj ./deploy/deploy.sh backend    # only Cloud Run
#   PROJECT_ID=my-proj ./deploy/deploy.sh frontend   # only Firebase Hosting + rules
#
# Prereqs (see README "Deploy"): gcloud, firebase-tools, node 20+, python 3.11+, jq, openssl;
#   gcloud auth login && gcloud auth application-default login && firebase login
# Billing must be enabled on PROJECT_ID.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
GEMINI_LOCATION="${GEMINI_LOCATION:-global}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.8-flash}"
GEMINI_LITE_MODEL="${GEMINI_LITE_MODEL:-gemini-3.5-flash-lite}"
FIRESTORE_LOCATION="${FIRESTORE_LOCATION:-$REGION}"
SERVICE="${SERVICE:-recoverai-api}"
BUCKET="${EVIDENCE_BUCKET:-${PROJECT_ID}-recoverai-evidence}"
SA_NAME="${SA_NAME:-recoverai-api}"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
DEMO_MODE="${DEMO_MODE:-true}"
MIN_INSTANCES="${MIN_INSTANCES:-1}"
BANK_USER_EMAIL="${BANK_USER_EMAIL:-analyst@recoverai-demo.example}"
WHAT="${1:-all}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT/deploy/.state"; mkdir -p "$STATE_DIR"
log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null || { echo "Missing required tool: $1" >&2; exit 1; }; }
for t in gcloud jq openssl; do need "$t"; done

gcloud config set project "$PROJECT_ID" >/dev/null
ORIGINS="https://${PROJECT_ID}.web.app,https://${PROJECT_ID}.firebaseapp.com"

setup_platform() {
  log "Enabling APIs"
  gcloud services enable run.googleapis.com aiplatform.googleapis.com firestore.googleapis.com \
    storage.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com iam.googleapis.com \
    iamcredentials.googleapis.com firebase.googleapis.com firebasehosting.googleapis.com \
    identitytoolkit.googleapis.com logging.googleapis.com

  log "Firestore (native) in ${FIRESTORE_LOCATION}"
  if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
    gcloud firestore databases create --location="$FIRESTORE_LOCATION" --type=firestore-native
  fi

  log "Private evidence bucket gs://${BUCKET} + CORS"
  if ! gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" \
      --uniform-bucket-level-access --public-access-prevention
  fi
  sed "s/PROJECT_ID/${PROJECT_ID}/g" "$ROOT/cors.json" > "$STATE_DIR/cors.json"
  gcloud storage buckets update "gs://${BUCKET}" --cors-file="$STATE_DIR/cors.json"
  echo '{"rule":[{"action":{"type":"Delete"},"condition":{"age":90}}]}' > "$STATE_DIR/lifecycle.json"
  gcloud storage buckets update "gs://${BUCKET}" --lifecycle-file="$STATE_DIR/lifecycle.json"

  log "Service account ${SA} and least-privilege IAM"
  if ! gcloud iam service-accounts describe "$SA" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$SA_NAME" --display-name="RecoverAI API (Cloud Run)"
  fi
  for role in roles/aiplatform.user roles/datastore.user roles/firebaseauth.viewer roles/logging.logWriter; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA}" --role="$role" \
      --condition=None >/dev/null
  done
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${SA}" \
    --role=roles/storage.objectAdmin >/dev/null
  # Signed URLs on Cloud Run use IAM signBlob on the runtime SA itself.
  gcloud iam service-accounts add-iam-policy-binding "$SA" --member="serviceAccount:${SA}" \
    --role=roles/iam.serviceAccountTokenCreator >/dev/null

  log "Firebase project, web app and Auth providers"
  need firebase
  firebase projects:addfirebase "$PROJECT_ID" >/dev/null 2>&1 || true
  APP_ID="$(firebase apps:list WEB --project "$PROJECT_ID" --json | jq -r '.result[0].appId // empty')"
  if [[ -z "$APP_ID" ]]; then
    firebase apps:create WEB recoverai-web --project "$PROJECT_ID" >/dev/null
    APP_ID="$(firebase apps:list WEB --project "$PROJECT_ID" --json | jq -r '.result[0].appId')"
  fi
  firebase apps:sdkconfig WEB "$APP_ID" --project "$PROJECT_ID" --json | jq '.result.sdkConfig // .result' > "$STATE_DIR/sdkconfig.json"
  TOKEN="$(gcloud auth print-access-token)"
  curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT_ID" \
    "https://identitytoolkit.googleapis.com/v2/projects/${PROJECT_ID}/identityPlatform:initializeAuth" >/dev/null 2>&1 || true
  curl -fsS -X PATCH -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT_ID" \
    -H "Content-Type: application/json" \
    "https://identitytoolkit.googleapis.com/admin/v2/projects/${PROJECT_ID}/config?updateMask=signIn.anonymous.enabled,signIn.email.enabled,signIn.email.passwordRequired" \
    -d '{"signIn":{"anonymous":{"enabled":true},"email":{"enabled":true,"passwordRequired":true}}}' >/dev/null \
    || echo "WARN: could not enable Auth providers via API; enable Anonymous + Email/Password in the Firebase console."
}

deploy_backend() {
  log "Cloud Run: ${SERVICE} (Cloud Build from backend/)"
  [[ -f "$STATE_DIR/a2a_token" ]] || openssl rand -hex 24 > "$STATE_DIR/a2a_token"
  A2A_TOKEN="$(cat "$STATE_DIR/a2a_token")"
  ENV_VARS="^##^GOOGLE_GENAI_USE_VERTEXAI=TRUE##GOOGLE_CLOUD_PROJECT=${PROJECT_ID}##GOOGLE_CLOUD_LOCATION=${REGION}"
  ENV_VARS+="##GEMINI_LOCATION=${GEMINI_LOCATION}##GEMINI_MODEL=${GEMINI_MODEL}##GEMINI_LITE_MODEL=${GEMINI_LITE_MODEL}"
  ENV_VARS+="##EVIDENCE_BUCKET=${BUCKET}##DEMO_MODE=${DEMO_MODE}##MOCK_MODE=false##AUTH_MODE=firebase"
  ENV_VARS+="##ALLOWED_ORIGINS=${ORIGINS}##A2A_TOKEN=${A2A_TOKEN}##SEED_ON_STARTUP=true##COPILOT_RUNTIME=cloudrun"
  gcloud run deploy "$SERVICE" --source "$ROOT/backend" --region "$REGION" \
    --service-account "$SA" --allow-unauthenticated \
    --min-instances "$MIN_INSTANCES" --max-instances 5 --concurrency 40 \
    --cpu 1 --memory 1Gi --timeout 300 --cpu-boost \
    --set-env-vars "$ENV_VARS"
  RUN_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
  echo "$RUN_URL" > "$STATE_DIR/run_url"
  curl -fsS "$RUN_URL/healthz" && echo
}

deploy_frontend() {
  need firebase; need npm
  RUN_URL="${RUN_URL:-$(cat "$STATE_DIR/run_url" 2>/dev/null || gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')}"
  [[ -f "$STATE_DIR/sdkconfig.json" ]] || { echo "Run '$0 all' once first (Firebase web config missing)"; exit 1; }
  log "Frontend build (Vite) with Firebase web config"
  jq -r --arg chat "$RUN_URL" --arg demo "$DEMO_MODE" '
    "VITE_FIREBASE_API_KEY=\(.apiKey)\nVITE_FIREBASE_AUTH_DOMAIN=\(.authDomain)\nVITE_FIREBASE_PROJECT_ID=\(.projectId)\nVITE_FIREBASE_APP_ID=\(.appId)\nVITE_CHAT_BASE=\($chat)\nVITE_DEMO_MODE=\($demo)\nVITE_MOCK=false"' \
    "$STATE_DIR/sdkconfig.json" > "$ROOT/frontend/.env.production.local"
  (cd "$ROOT/frontend" && npm ci && npm run build)

  log "Firebase Hosting (rewrite /api/** -> Cloud Run ${SERVICE} in ${REGION}) + Firestore rules"
  jq --arg r "$REGION" --arg s "$SERVICE" \
    '(.hosting.rewrites[] | select(.run) | .run) |= {serviceId: $s, region: $r}' \
    "$ROOT/firebase.json" > "$ROOT/firebase.generated.json"
  (cd "$ROOT" && firebase deploy --project "$PROJECT_ID" --config firebase.generated.json --only hosting,firestore:rules --non-interactive)
  rm -f "$ROOT/firebase.generated.json"
}

seed_data() {
  log "Seeding synthetic bank data + demo analyst account (uses your ADC)"
  PY="${PYTHON:-python3}"
  if [[ ! -d "$ROOT/.venv" ]]; then "$PY" -m venv "$ROOT/.venv"; fi
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
  export GOOGLE_CLOUD_PROJECT="$PROJECT_ID" MOCK_MODE=false
  "$ROOT/.venv/bin/python" "$ROOT/scripts/seed.py"
  if [[ ! -f "$STATE_DIR/bank_password" ]]; then openssl rand -base64 18 | tr -d '/+=' > "$STATE_DIR/bank_password"; fi
  BANK_USER_EMAIL="$BANK_USER_EMAIL" BANK_USER_PASSWORD="$(cat "$STATE_DIR/bank_password")" \
    "$ROOT/.venv/bin/python" "$ROOT/scripts/make_bank_user.py"
}

case "$WHAT" in
  all) setup_platform; deploy_backend; seed_data; deploy_frontend ;;
  platform) setup_platform ;;
  backend) deploy_backend ;;
  frontend) deploy_frontend ;;
  seed) seed_data ;;
  *) echo "usage: $0 [all|platform|backend|frontend|seed]"; exit 2 ;;
esac

log "Done"
echo "Victim app : https://${PROJECT_ID}.web.app"
echo "Bank app   : https://${PROJECT_ID}.web.app/bank  (login: ${BANK_USER_EMAIL} / password in deploy/.state/bank_password)"
echo "API        : $(cat "$STATE_DIR/run_url" 2>/dev/null || echo '?')"
echo "E2E check  : API_BASE=\$(cat deploy/.state/run_url) .venv/bin/python scripts/e2e_demo.py"
