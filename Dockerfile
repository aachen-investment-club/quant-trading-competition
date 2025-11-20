# Participant & Evaluator image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/usr/src/app

# system deps for building wheels (xgboost/lightgbm), tzdata for pandas
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    curl ca-certificates \
    git \
    libgomp1 \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files (participants mainly care about notebooks/src)
COPY . .

# Jupyter port
EXPOSE 8888

# Provide simple CLIs inside the image:
#   submit     -> python tools/submit.py
#   local-eval -> python src/local_eval.py (defaults to repo data path)
#   sync-data  -> fetches active test data from S3 based on DynamoDB config
RUN printf '#!/bin/sh\nset -e\nexec python tools/submit.py "$@"\n' > /usr/local/bin/submit \
    && printf '#!/bin/sh\nset -e\n[ "$#" -gt 0 ] || set -- submission/submission.py\nexec python src/local_eval.py "$@"\n' > /usr/local/bin/local-eval \
    && printf '#!/bin/sh\nset -e\nexec python tools/sync_data.py "$@"\n' > /usr/local/bin/sync-data \
    && printf '#!/bin/sh\nset -e\nexec python tools/check_status.py "$@"\n' > /usr/local/bin/check-status \
    && chmod +x /usr/local/bin/submit /usr/local/bin/local-eval /usr/local/bin/sync-data /usr/local/bin/check-status
