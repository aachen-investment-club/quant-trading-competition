# Participant & Evaluator image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/usr/src/app

# system deps for building wheels (xgboost/lightgbm), tzdata for pandas
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl ca-certificates \
    git \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files (participants mainly care about notebooks/src)
COPY . .

# Jupyter port
EXPOSE 8888

# Provide a simple CLI: `submit` calls the Python submit tool from the project root
# (WORKDIR is /usr/src/app, which contains tools/submit.py)
RUN printf '#!/bin/sh\nset -e\nexec python tools/submit.py "$@"\n' > /usr/local/bin/submit \
    && chmod +x /usr/local/bin/submit

# Default command launches JupyterLab for participants
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=''"]
