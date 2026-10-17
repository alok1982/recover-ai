#!/usr/bin/env bash
# RecoverAI — one-shot, idempotent deployment to Google Cloud + Firebase.
#
#   ./deploy/deploy.sh                 # everything, project recoverai-511917 (default)
#   PROJECT_ID=other-proj ./deploy/deploy.sh
#   ./deploy/deploy.sh backend         # one stage: platform | backend | pubsub | seed | search | frontend | check
#
# Prereqs (README "Deploy"): gcloud (incl. bq), firebase-tools, node 20+, python 3.11+, jq, openssl, curl.
#   gcloud auth login alokkumar.iiitm@gmail.com
#   gcloud auth application-default login
#   firebase login
# Billing must be enabled on the project. No keys or secrets are written to the repo: generated values live in the
# git-ignored deploy/.state/ directory.
set -euo pipefail

# Box-local CLI installs (harmless elsewhere)
for d in /home/box/tools/google-cloud-sdk/bin /home/box/tools/npm-global/bin; do [[ -d "$d" ]] && PATH="$d:$PATH"; done
export PATH

PROJECT_ID="${PROJECT_ID:-recoverai-511917}"
GCLOUD_ACCOUNT="${GCLOUD_ACCOUNT:-alokkumar.iiitm@gmail.com}"
REGION="${REGION:-asia-south1}"
GEMINI_LOCATION="${GEMINI_LOCATION:-global}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.8-flash}"
GEMINI_LITE_MODEL="${GEMINI_LITE_MODEL:-gemini-3.5-flash-lite}"
FIRESTORE_LOCATION="${FIRESTORE_LOCATION:-$REGION}"
BQ_LOCATION="${BQ_LOCATION:-$REGION}"
BQ_DATASET="${BQ_DATASET:-recoverai_analytics}"
SERVICE="${SERVICE:-recoverai-api}"
BUCKET="${EVIDENCE_BUCKET:-${PROJECT_ID}-recoverai-evidence}"
KNOWLEDGE_BUCKET="${KNOWLEDGE_BUCKET:-${PROJECT_ID}-recoverai-knowledge}"
SA_NAME="${SA_NAME:-recoverai-api}"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
PUSH_SA="pubsub-push@${PROJECT_ID}.iam.gserviceaccount.com"
TOPIC_CASE="fraud-case-submitted"
TOPIC_DECISION="bank-decision"
TOPIC_DLQ="recoverai-dlq"
SEARCH_DATASTORE="${SEARCH_DATASTORE:-recoverai-rules}"
SEARCH_ENGINE="${SEARCH_ENGINE:-recoverai-rules-app}"
DEMO_MODE="${DEMO_MODE:-true}"
ENABLE_ML_SCORE="${ENABLE_ML_SCORE:-true}"
MIN_INSTANCES="${MIN_INSTANCES:-1}"
BANK_USER_EMAIL="${BANK_USER_EMAIL:-analyst@recoverai-demo.example}"
WHAT="${1:-all}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT/deploy/.state"; mkdir -p "$STATE_DIR"
log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARN: %s\033[0m\n' "$*" >&2; }
need() { command -v "$1" >/dev/null || { echo "Missing required tool: $1" >&2; exit 1; }; }
for t in gcloud bq jq openssl curl; do need "$t"; done

ACTIVE="$(gcloud config get-value account 2>/dev/null || true)"
if [[ -z "$ACTIVE" ]]; then
  echo "Not signed in. Run: gcloud auth login ${GCLOUD_ACCOUNT} && gcloud auth application-default login && firebase login" >&2
  exit 1
fi
[[ "$ACTIVE" == "$GCLOUD_ACCOUNT" ]] || warn "active gcloud account is ${ACTIVE}, expected ${GCLOUD_ACCOUNT} (set GCLOUD_ACCOUNT to silence)"
gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
PUBSUB_AGENT="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"
# Deterministic Cloud Run URL: used as the OIDC audience for both push subscriptions (known before the first deploy).
PUSH_AUDIENCE="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
ORIGINS="https://${PROJECT_ID}.web.app,https://${PROJECT_ID}.firebaseapp.com"
run_url() { cat "$STATE_DIR/run_url" 2>/dev/null || gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'; }

setup_platform() {
  log "Enabling APIs"
  gcloud services enable run.googleapis.com aiplatform.googleapis.com firestore.googleapis.com \
    storage.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com iam.googleapis.com \
    iamcredentials.googleapis.com firebase.googleapis.com firebasehosting.googleapis.com \
    identitytoolkit.googleapis.com logging.googleapis.com \
    bigquery.googleapis.com pubsub.googleapis.com discoveryengine.googleapis.com

  log "Firestore (native) in ${FIRESTORE_LOCATION}"
  if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
    gcloud firestore databases create --location="$FIRESTORE_LOCATION" --type=firestore-native
  fi

  log "Private evidence bucket gs://${BUCKET} + CORS + lifecycle"
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
  for role in roles/aiplatform.user roles/datastore.user roles/firebaseauth.viewer roles/logging.logWriter \
              roles/bigquery.jobUser roles/discoveryengine.viewer; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA}" --role="$role" \
      --condition=None >/dev/null
  done
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${SA}" \
    --role=roles/storage.objectAdmin >/dev/null
  # Signed URLs on Cloud Run use IAM signBlob on the runtime SA itself.
  gcloud iam service-accounts add-iam-policy-binding "$SA" --member="serviceAccount:${SA}" \
    --role=roles/iam.serviceAccountTokenCreator >/dev/null

  setup_bigquery
  setup_topics

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
    || warn "could not enable Auth providers via API; enable Anonymous + Email/Password in the Firebase console."
}

setup_bigquery() {
  log "BigQuery dataset ${BQ_DATASET} (${BQ_LOCATION}) + tables (F14)"
  if ! bq --project_id="$PROJECT_ID" show --format=none "${PROJECT_ID}:${BQ_DATASET}" >/dev/null 2>&1; then
    bq --project_id="$PROJECT_ID" --location="$BQ_LOCATION" mk --dataset \
      --description "RecoverAI synthetic bank transactions + anonymised case events" "${PROJECT_ID}:${BQ_DATASET}"
  fi
  sed "s/recoverai_analytics\./${BQ_DATASET}./g" "$ROOT/backend/sql/create_tables.sql" \
    | bq --project_id="$PROJECT_ID" --location="$BQ_LOCATION" query --use_legacy_sql=false --quiet >/dev/null
  # roles/bigquery.dataEditor on the dataset only (WRITER == dataEditor in dataset ACLs)
  bq --project_id="$PROJECT_ID" show --format=prettyjson "${PROJECT_ID}:${BQ_DATASET}" > "$STATE_DIR/dataset.json"
  if ! jq -e --arg sa "$SA" '.access[] | select(.userByEmail == $sa)' "$STATE_DIR/dataset.json" >/dev/null; then
    jq --arg sa "$SA" '.access += [{"role": "WRITER", "userByEmail": $sa}]' "$STATE_DIR/dataset.json" > "$STATE_DIR/dataset.new.json"
    bq --project_id="$PROJECT_ID" update --source "$STATE_DIR/dataset.new.json" "${PROJECT_ID}:${BQ_DATASET}" >/dev/null
  fi
}

setup_topics() {
  log "Pub/Sub topics ${TOPIC_CASE}, ${TOPIC_DECISION}, ${TOPIC_DLQ} + push service account (F15)"
  for t in "$TOPIC_CASE" "$TOPIC_DECISION" "$TOPIC_DLQ"; do
    gcloud pubsub topics describe "$t" >/dev/null 2>&1 || gcloud pubsub topics create "$t" >/dev/null
  done
  for t in "$TOPIC_CASE" "$TOPIC_DECISION"; do
    gcloud pubsub topics add-iam-policy-binding "$t" --member="serviceAccount:${SA}" --role=roles/pubsub.publisher >/dev/null
  done
  if ! gcloud iam service-accounts describe "$PUSH_SA" >/dev/null 2>&1; then
    gcloud iam service-accounts create pubsub-push --display-name="Pub/Sub push to RecoverAI"
  fi
  # Make sure the Pub/Sub service agent exists, then let it mint OIDC tokens for pubsub-push and dead-letter.
  curl -fsS -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "x-goog-user-project: $PROJECT_ID" \
    "https://serviceusage.googleapis.com/v1beta1/projects/${PROJECT_NUMBER}/services/pubsub.googleapis.com:generateServiceIdentity" \
    >/dev/null 2>&1 || true
  gcloud iam service-accounts add-iam-policy-binding "$PUSH_SA" --member="serviceAccount:${PUBSUB_AGENT}" \
    --role=roles/iam.serviceAccountTokenCreator >/dev/null
  gcloud pubsub topics add-iam-policy-binding "$TOPIC_DLQ" --member="serviceAccount:${PUBSUB_AGENT}" \
    --role=roles/pubsub.publisher >/dev/null
}

prepare_knowledge_bundle() {
  # Offline citation fallback inside the image (used only if Vertex AI Search is not configured).
  rm -rf "$ROOT/backend/knowledge_bundle"/text "$ROOT/backend/knowledge_bundle/sources.json"
  mkdir -p "$ROOT/backend/knowledge_bundle/text"
  cp "$ROOT/knowledge/sources.json" "$ROOT/backend/knowledge_bundle/"
  cp "$ROOT"/knowledge/text/*.txt "$ROOT/backend/knowledge_bundle/text/"
}

deploy_backend() {
  log "Cloud Run: ${SERVICE} (Cloud Build from backend/)"
  prepare_knowledge_bundle
  SERVING_CONFIG="$(cat "$STATE_DIR/serving_config" 2>/dev/null || true)"
  ENV_VARS="^##^GOOGLE_GENAI_USE_VERTEXAI=TRUE##GOOGLE_CLOUD_PROJECT=${PROJECT_ID}##GOOGLE_CLOUD_LOCATION=${REGION}"
  ENV_VARS+="##GEMINI_LOCATION=${GEMINI_LOCATION}##GEMINI_MODEL=${GEMINI_MODEL}##GEMINI_LITE_MODEL=${GEMINI_LITE_MODEL}"
  ENV_VARS+="##EVIDENCE_BUCKET=${BUCKET}##DEMO_MODE=${DEMO_MODE}##MOCK_MODE=false##AUTH_MODE=firebase"
  ENV_VARS+="##ALLOWED_ORIGINS=${ORIGINS}##COPILOT_RUNTIME=cloudrun"
  ENV_VARS+="##EVENT_BUS=pubsub##TOPIC_CASE_SUBMITTED=${TOPIC_CASE}##TOPIC_BANK_DECISION=${TOPIC_DECISION}"
  ENV_VARS+="##PUSH_AUDIENCE=${PUSH_AUDIENCE}##PUSH_SA_EMAIL=${PUSH_SA}"
  ENV_VARS+="##ANALYTICS_BACKEND=bigquery##BQ_DATASET=${BQ_DATASET}##BQ_LOCATION=${BQ_LOCATION}##ENABLE_ML_SCORE=${ENABLE_ML_SCORE}"
  ENV_VARS+="##KNOWLEDGE_DIR=/srv/knowledge##VERTEX_SEARCH_SERVING_CONFIG=${SERVING_CONFIG}"
  gcloud run deploy "$SERVICE" --source "$ROOT/backend" --region "$REGION" \
    --service-account "$SA" --allow-unauthenticated \
    --min-instances "$MIN_INSTANCES" --max-instances 5 --concurrency 40 \
    --cpu 1 --memory 1Gi --timeout 300 --cpu-boost \
    --set-env-vars "$ENV_VARS"
  RUN_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
  echo "$RUN_URL" > "$STATE_DIR/run_url"
  curl -fsS "$RUN_URL/healthz" && echo
}

upsert_push_sub() {  # name topic path
  local name="$1" topic="$2" path="$3" url
  url="$(run_url)"
  local common=(--push-endpoint="${url}${path}" --push-auth-service-account="$PUSH_SA"
                --push-auth-token-audience="$PUSH_AUDIENCE" --dead-letter-topic="$TOPIC_DLQ"
                --max-delivery-attempts=5 --ack-deadline=30 --min-retry-delay=5s --max-retry-delay=60s)
  if gcloud pubsub subscriptions describe "$name" >/dev/null 2>&1; then
    gcloud pubsub subscriptions update "$name" "${common[@]}" >/dev/null
  else
    gcloud pubsub subscriptions create "$name" --topic="$topic" "${common[@]}" >/dev/null
  fi
  gcloud pubsub subscriptions add-iam-policy-binding "$name" --member="serviceAccount:${PUBSUB_AGENT}" \
    --role=roles/pubsub.subscriber >/dev/null
  echo "  $name: $topic -> ${url}${path} (OIDC aud ${PUSH_AUDIENCE})"
}

setup_pubsub() {
  log "Pub/Sub push subscriptions with OIDC + dead-lettering (F15)"
  setup_topics
  upsert_push_sub fraud-case-to-bank "$TOPIC_CASE" /bank/a2a/inbox
  upsert_push_sub bank-decision-to-victim "$TOPIC_DECISION" /api/events/bank-decision
  gcloud pubsub subscriptions describe dlq-inspect >/dev/null 2>&1 || \
    gcloud pubsub subscriptions create dlq-inspect --topic="$TOPIC_DLQ" --message-retention-duration=7d >/dev/null
}

py_env() {
  PY="${PYTHON:-python3}"
  if [[ ! -d "$ROOT/.venv" ]]; then "$PY" -m venv "$ROOT/.venv"; fi
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
}

seed_data() {
  log "Seeding BigQuery synthetic bank data (+ S2 model) and the demo analyst (uses your ADC)"
  py_env
  GOOGLE_CLOUD_PROJECT="$PROJECT_ID" MOCK_MODE=false ANALYTICS_BACKEND=bigquery BQ_DATASET="$BQ_DATASET" \
    BQ_LOCATION="$BQ_LOCATION" "$ROOT/.venv/bin/python" "$ROOT/scripts/seed_bigquery.py" \
    $( [[ "$ENABLE_ML_SCORE" == "true" ]] || echo "--no-ml" )
  if [[ ! -f "$STATE_DIR/bank_password" ]]; then openssl rand -base64 18 | tr -d '/+=' > "$STATE_DIR/bank_password"; fi
  GOOGLE_CLOUD_PROJECT="$PROJECT_ID" BANK_USER_EMAIL="$BANK_USER_EMAIL" BANK_USER_PASSWORD="$(cat "$STATE_DIR/bank_password")" \
    "$ROOT/.venv/bin/python" "$ROOT/scripts/make_bank_user.py"
}

setup_search() {
  log "Vertex AI Search over official sources (F16, SHOULD) — best effort"
  gcloud storage buckets describe "gs://${KNOWLEDGE_BUCKET}" >/dev/null 2>&1 || \
    gcloud storage buckets create "gs://${KNOWLEDGE_BUCKET}" --location="$REGION" --uniform-bucket-level-access --public-access-prevention
  gcloud storage rsync "$ROOT/knowledge" "gs://${KNOWLEDGE_BUCKET}" --recursive --quiet
  jq -c --arg b "$KNOWLEDGE_BUCKET" '.sources[] | {id: .id, structData: {title, url, publisher, country, topics, published},
      content: {mimeType: "text/plain", uri: ("gs://" + $b + "/" + .text)}}' "$ROOT/knowledge/sources.json" > "$STATE_DIR/metadata.jsonl"
  gcloud storage cp "$STATE_DIR/metadata.jsonl" "gs://${KNOWLEDGE_BUCKET}/metadata.jsonl" --quiet
  local api="https://discoveryengine.googleapis.com/v1/projects/${PROJECT_ID}/locations/global/collections/default_collection"
  local tok; tok="$(gcloud auth print-access-token)"
  local H=(-H "Authorization: Bearer $tok" -H "x-goog-user-project: $PROJECT_ID" -H "Content-Type: application/json")
  curl -fsS "${H[@]}" "$api/dataStores/${SEARCH_DATASTORE}" >/dev/null 2>&1 || \
    curl -fsS -X POST "${H[@]}" "$api/dataStores?dataStoreId=${SEARCH_DATASTORE}" \
      -d '{"displayName":"RecoverAI official rule sources","industryVertical":"GENERIC","solutionTypes":["SOLUTION_TYPE_SEARCH"],"contentConfig":"CONTENT_REQUIRED"}' >/dev/null \
    || { warn "could not create the data store — create it in the console (see README) and set VERTEX_SEARCH_SERVING_CONFIG"; return 0; }
  sleep 5
  curl -fsS -X POST "${H[@]}" "$api/dataStores/${SEARCH_DATASTORE}/branches/0/documents:import" \
    -d "{\"gcsSource\":{\"inputUris\":[\"gs://${KNOWLEDGE_BUCKET}/metadata.jsonl\"],\"dataSchema\":\"document\"},\"reconciliationMode\":\"FULL\"}" >/dev/null \
    || warn "document import request failed; retry with: $0 search"
  curl -fsS "${H[@]}" "$api/engines/${SEARCH_ENGINE}" >/dev/null 2>&1 || \
    curl -fsS -X POST "${H[@]}" "$api/engines?engineId=${SEARCH_ENGINE}" \
      -d "{\"displayName\":\"RecoverAI rules\",\"dataStoreIds\":[\"${SEARCH_DATASTORE}\"],\"solutionType\":\"SOLUTION_TYPE_SEARCH\",\"searchEngineConfig\":{\"searchTier\":\"SEARCH_TIER_STANDARD\"}}" >/dev/null \
    || { warn "could not create the search app; see README"; return 0; }
  echo "projects/${PROJECT_ID}/locations/global/collections/default_collection/engines/${SEARCH_ENGINE}/servingConfigs/default_search" \
    > "$STATE_DIR/serving_config"
  if gcloud run services describe "$SERVICE" --region "$REGION" >/dev/null 2>&1; then
    gcloud run services update "$SERVICE" --region "$REGION" \
      --update-env-vars "VERTEX_SEARCH_SERVING_CONFIG=$(cat "$STATE_DIR/serving_config")" >/dev/null
  fi
  echo "  serving config: $(cat "$STATE_DIR/serving_config") (indexing can take a while; the co-pilot falls back to local sources meanwhile)"
}

deploy_frontend() {
  need firebase; need npm
  RUN_URL="${RUN_URL:-$(run_url)}"
  [[ -f "$STATE_DIR/sdkconfig.json" ]] || { echo "Run '$0 platform' once first (Firebase web config missing)"; exit 1; }
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

check() {
  log "End-to-end check against $(run_url)"
  py_env
  API_BASE="$(run_url)" "$ROOT/.venv/bin/python" "$ROOT/scripts/e2e_demo.py"
}

case "$WHAT" in
  all) setup_platform; deploy_backend; setup_pubsub; seed_data; setup_search; deploy_frontend ;;
  platform) setup_platform ;;
  backend) deploy_backend ;;
  pubsub) setup_pubsub ;;
  seed) seed_data ;;
  search) setup_search ;;
  frontend) deploy_frontend ;;
  check) check ;;
  *) echo "usage: $0 [all|platform|backend|pubsub|seed|search|frontend|check]"; exit 2 ;;
esac

log "Done"
echo "Victim app : https://${PROJECT_ID}.web.app"
echo "Bank app   : https://${PROJECT_ID}.web.app/bank  (login: ${BANK_USER_EMAIL} / password in deploy/.state/bank_password)"
echo "API        : $(cat "$STATE_DIR/run_url" 2>/dev/null || echo '?')"
echo "E2E check  : $0 check"
