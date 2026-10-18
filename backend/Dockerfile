# RecoverAI API — Cloud Run image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# WeasyPrint needs Pango + HarfBuzz; fonts-noto-core ships Noto Sans and Noto Sans Devanagari
# (HarfBuzz shapes Devanagari conjuncts correctly in the evidence-pack PDF).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
      libffi8 shared-mime-info fontconfig fonts-noto-core ffmpeg \
 && rm -rf /var/lib/apt/lists/* \
 && fc-cache -f

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY playbooks ./playbooks
COPY sql ./sql
COPY knowledge_bundle ./knowledge

ENV PORT=8080
EXPOSE 8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75
