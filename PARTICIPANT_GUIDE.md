# Trading Competition — Participant Guide

Welcome! This guide explains **how your strategy is evaluated**, how to **run the local environment (Docker or native Python)**, and **how to submit** your code.

---

## 1) How your strategy is evaluated

### What you ship
- Put your code in the repository’s `submission/` directory.
- You must provide **`submission.py`** with a function:
  ```python
  def build_strategy():
      # return an object with generate_signals(df) -> pd.Series in {-1, 0, +1}
  ```
- Optional: other helper modules inside `submission/` (you can import them from `submission.py`).

### What the evaluator does
When you submit, the pipeline runs like this:

1. Your local `tools/submit.py` uploads the entire `submission/` folder to **S3** under:
   ```
   s3://<SUBMISSIONS_BUCKET>/<PARTICIPANT_ID>/<SUBMISSION_ID>/...
   ```
   It uploads **`submission.py` last** to ensure your upload is complete before evaluation starts.
2. An **S3 event** triggers an **AWS Lambda (orchestrator)** which starts a private **ECS Fargate** task using the evaluator image.
3. Inside the evaluator container:
   - Test data is read from **S3** (CSV).
   - Your submission is downloaded.
   - The evaluator imports `build_strategy()` from your `submission.py`.
   - It calls `strategy.generate_signals(df)` → a Series of positions in `{-1,0,+1}` (applied on the *next* bar).
   - Then it evaluates performance and writes **metrics + score** to **DynamoDB** (used by the leaderboard API).

### Metrics (cost model and frequency)
- **Transaction costs**: expressed in **basis points (bps)** and applied when the signal **changes** (`-1→0`, `0→+1`, etc.).
- **Metrics recorded** include: annualized return, annualized volatility, Sharpe ratio (primary score), max drawdown, turnover.

> **Tip**: Make sure your `generate_signals` aligns with the evaluator’s assumption: positions from your signal are **entered on the next bar** (one‑bar lag).

---

## 2) Local development

You can develop either with **Docker** (recommended) or a **native Python** environment.

### Option A — Docker (recommended)
1. From the project root, build the image:
   ```bash
   docker build -t trading-comp-env .
   ```
2. Start JupyterLab (bind to your current folder so edits persist):
   ```bash
   # macOS/Linux
   docker run --rm -it -p 8888:8888      -v "$(pwd):/usr/src/app"      trading-comp-env

   # Windows PowerShell
   docker run --rm -it -p 8888:8888      -v "${PWD}:/usr/src/app"      trading-comp-env
   ```
   The Dockerfile exposes JupyterLab on port **8888** and disables the token by default.
3. Use the notebooks under `src/notebooks/` or create your own. Make sure your code imports from `src/` as needed.

### Option B — Native Python
1. Install Python **3.10+** and recommended build tools.
2. From the project root:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. Add the repository root to `PYTHONPATH` so `src/...` imports work:
   ```bash
   # macOS/Linux
   export PYTHONPATH="$(pwd)"

   # Windows PowerShell
   $env:PYTHONPATH = (Get-Location).Path
   ```
4. Launch Jupyter if you prefer notebooks:
   ```bash
   jupyter lab
   ```

---

## 3) How to submit

### Required environment variables
You need credentials and a few variables. Either export them or put them in `.env` (and export manually). The minimum set is:
- `AWS_REGION` (e.g. `eu-central-1`)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (or role‑based creds on an EC2/Workspaces environment)
- `SUBMISSIONS_BUCKET` (provided by the host)
- `PARTICIPANT_ID` (provided by the host)

### Submit using the Python CLI
From the project root:
```bash
# Use a timestamp submission id (default)
python tools/submit.py

# Or specify a custom submission id
SUBMISSION_ID=my-idea-01 python tools/submit.py
```
The script uploads **everything in `submission/`** and prints the target S3 prefix. Your evaluation starts immediately after `submission.py` is uploaded.

### Alternative: submit from inside Docker
The image also provides a `submit` shortcut which calls the same script:
### Option A — Shortcut with env file (recommended)
```bash

docker run --rm --env-file .env -v "${PWD}:/usr/src/app" trading-comp-evaluator submit
```
### Option B — Shortcut
```bash
docker run --rm -it -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_REGION -e SUBMISSIONS_BUCKET -e PARTICIPANT_ID -v "$(pwd):/usr/src/app" trading-comp-env submit
```

---

## 4) Checklist

- [ ] Your `submission/` folder contains **`submission.py`** with **`build_strategy()`**.
- [ ] `generate_signals(df)` returns a **Series of {-1, 0, +1}** aligned to **`df`**.
- [ ] You tested locally on the provided CSV format (must include at least a `close` column; ideally `timestamp` too).
- [ ] You can import `src/...` modules if you rely on shared helpers.
- [ ] Your AWS credentials permit **`s3:PutObject`** into the **submissions bucket** (prefixed by your `PARTICIPANT_ID`).

---

## 5) Troubleshooting

Good luck! 🚀
