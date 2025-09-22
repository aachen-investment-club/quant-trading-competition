import os, json, decimal
import boto3

TABLE = os.environ["DDB_TABLE"]
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE)

SCAN_LIMIT = 500
MAX_ITEMS = 5000


def _to_float(o):
    if isinstance(o, list):  return [_to_float(x) for x in o]
    if isinstance(o, dict):  return {k:_to_float(v) for k,v in o.items()}
    if isinstance(o, decimal.Decimal): return float(o)
    return o

def handler(event, ctx):
    # scan leaderboard entries, keep best score per participant
    items = []
    last_evaluated_key = None
    while True:
        scan_args = {"Limit": SCAN_LIMIT}
        if last_evaluated_key:
            scan_args["ExclusiveStartKey"] = last_evaluated_key
        resp = table.scan(**scan_args)
        items.extend(resp.get("Items", []))
        if len(items) >= MAX_ITEMS:
            items = items[:MAX_ITEMS]
            break
        last_evaluated_key = resp.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

    best = {}
    for it in items:
        pid = it.get("participant_id")
        if pid is None:
            continue
        score = float(it.get("score", 0.0))
        if pid not in best or score > best[pid]["score"]:
            best[pid] = {
                "participant_id": pid,
                "score": score,
                "metrics": it.get("metrics"),
                "submission_id": it.get("submission_id"),
                "timestamp": it.get("timestamp"),
            }
    leaderboard = sorted(best.values(), key=lambda x: x["score"], reverse=True)
    return {
        "statusCode": 200,
        "headers": {"Content-Type":"application/json","Access-Control-Allow-Origin":"*"},
        "body": json.dumps(_to_float(leaderboard))
    }

