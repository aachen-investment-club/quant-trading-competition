# /infra/entrypoint_eval.py (verbessert)
import os, sys, json, time, importlib.util, boto3
from pathlib import Path, PurePosixPath
import pandas as pd

from decimal import Decimal, InvalidOperation
import math
import numpy as np

def _to_decimal(x):
    # drop NaN/Inf (DDB can't store them)
    if x is None:
        return None
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        return Decimal(str(x))
    if isinstance(x, (int,)):
        return Decimal(str(x))
    if isinstance(x, Decimal):
        return x
    # numpy numbers
    if isinstance(x, (np.floating, np.integer)):
        xf = float(x)
        if math.isnan(xf) or math.isinf(xf):
            return None
        return Decimal(str(xf))
    # strings, bools are okay as-is
    if isinstance(x, (str, bool)):
        return x
    return x  # leave other types to higher-level handlers

def sanitize_for_ddb(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            sv = sanitize_for_ddb(v)
            # DDB doesn't allow None in maps -> drop those keys
            if sv is not None:
                out[k] = sv
        return out
    if isinstance(obj, (list, tuple)):
        # DDB doesn't allow empty lists of mixed/unsupported types -> filter None
        out = [sanitize_for_ddb(v) for v in obj]
        out = [v for v in out if v is not None]
        return out
    return _to_decimal(obj)

def _safe_destination_for_key(dest: Path, key: str, prefix: str) -> Path:
    rel = key[len(prefix):].lstrip('/')
    if not rel:
        raise ValueError('empty object key suffix')
    if key.endswith('submission.py'):
        rel = 'submission.py'
    rel_path = PurePosixPath(rel)
    if rel_path.is_absolute():
        raise ValueError('absolute paths are not allowed')
    if any(part in ('', '.', '..') for part in rel_path.parts):
        raise ValueError('unsafe path segment in object key')
    dest_base = dest.resolve()
    target = (dest_base / Path(*rel_path.parts)).resolve(strict=False)
    if dest_base not in target.parents:
        raise ValueError('object key escapes submission directory')
    return target



SUBMISSION_BUCKET = os.environ["SUBMISSIONS_BUCKET"]
SUBMISSION_PREFIX = os.environ["SUBMISSION_PREFIX"]  # "<participant>/<submission_id>/"
TESTDATA_BUCKET   = os.environ["TESTDATA_BUCKET"]
TESTDATA_KEY      = os.environ["TESTDATA_KEY"]
DDB_TABLE         = os.environ["DDB_TABLE"]
PARTICIPANT_ID    = os.environ["PARTICIPANT_ID"]
COST_BPS          = float(os.environ.get("COST_BPS", "1.0"))
TIMEOUT_SECONDS   = int(os.environ.get("TIMEOUT_SECONDS", "0") or 0)
BARS_PER_YEAR_ENV = os.environ.get("BARS_PER_YEAR")  # optional override, e.g. "24192" for 15-min bars

ROOT   = Path("/usr/src/app")
SRC    = ROOT / "src"
WORK   = ROOT / "work"
SUBMIT = ROOT / "submission"   # <— nicht unter src/

s3  = boto3.client("s3")
ddb = boto3.resource("dynamodb").Table(DDB_TABLE)

def download_s3_dir(bucket, prefix, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    dest_base = dest.resolve()
    paginator = s3.get_paginator('list_objects_v2')
    found = False
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if not key.startswith(prefix) or key.endswith('/'):
                continue
            found = True
            try:
                out = _safe_destination_for_key(dest_base, key, prefix)
            except ValueError as exc:
                raise RuntimeError(f"Refused to download key '{key}': {exc}") from exc
            out.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(out))
    if not found:
        raise RuntimeError(f"No objects under s3://{bucket}/{prefix}")

def load_submission_module():
    sub_py = SUBMIT / "submission.py"
    if not sub_py.exists():
        raise FileNotFoundError(f"{sub_py} not found")
    # sys.path so that submission can import both src.* and its own helpers
    root_path = str(ROOT)
    submit_path = str(SUBMIT)
    if root_path in sys.path:
        sys.path = [p for p in sys.path if p != root_path]
    sys.path.insert(0, root_path)
    if submit_path in sys.path:
        sys.path = [p for p in sys.path if p != submit_path]
    sys.path.append(submit_path)
    spec = importlib.util.spec_from_file_location("submission", sub_py)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def main():
    t0 = time.time()
    WORK.mkdir(parents=True, exist_ok=True)
    download_s3_dir(SUBMISSION_BUCKET, SUBMISSION_PREFIX, SUBMIT)

    data_path = WORK / "test.csv"
    s3.download_file(TESTDATA_BUCKET, TESTDATA_KEY, str(data_path))

    # robustes Laden
    df = pd.read_csv(data_path)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for col in ("close",):
        if col not in df.columns:
            raise KeyError(f"Required column '{col}' missing in test data")

    submission = load_submission_module()
    strategy = submission.build_strategy()
    if hasattr(strategy, "fit"):
        try:
            strategy.fit(df)              # pass the whole df by default
        except TypeError:
            # in case someone's signature is fit(data=...)
            strategy.fit(data=df)
    signals = strategy.generate_signals(df)

    from src.evaluation import evaluate
    metrics = evaluate(signals, df, price_col="close", cost_bps=COST_BPS)

    metrics_ddb = sanitize_for_ddb(metrics)
    score_ddb = metrics_ddb.get("score", Decimal("0"))

    item = sanitize_for_ddb({
        "participant_id": PARTICIPANT_ID,
        "submission_id": SUBMISSION_PREFIX.split("/")[1],
        "timestamp": int(time.time()),
        "metrics": metrics_ddb,
        "score": score_ddb,
    })

    ddb.put_item(Item=item)
    print(json.dumps({"ok": True, "metrics": metrics}, indent=2))

    if TIMEOUT_SECONDS and time.time() - t0 > TIMEOUT_SECONDS:
        print(json.dumps({"warn": "TIMEOUT_SECONDS exceeded after evaluation"}, indent=2))

if __name__ == "__main__":
    main()
