import os, json, boto3, re

ecs = boto3.client("ecs")

CLUSTER_ARN   = os.environ["ECS_CLUSTER_ARN"]
TASK_DEF_ARN  = os.environ["ECS_TASK_DEF_ARN"]
SUBNETS       = os.environ["SUBNETS"].split(",")         # "subnet-...,subnet-..."
SECURITY_GIDS = os.environ["SECURITY_GROUPS"].split(",") # "sg-..."
COST_BPS      = os.environ.get("COST_BPS", "1.0")
TIMEOUT_SEC   = os.environ.get("TIMEOUT_SECONDS", "600")
TESTDATA_BUCKET = os.environ["TESTDATA_BUCKET"]
TESTDATA_KEY    = os.environ["TESTDATA_KEY"]
DDB_TABLE       = os.environ["DDB_TABLE"]

SUBMISSION_KEY_RE = re.compile(r"([^/]+)/([^/]+)/submission\.py$")
CONTAINER_NAME = "evaluator"  # muss zum TaskDefinition-Namen passen!

def lambda_handler(event, ctx):
    records = event.get('Records', [])
    if not records:
        return {"ok": True, "tasks": [], "failures": []}

    tasks = []
    failures = []
    for rec in records:
        try:
            bucket = rec['s3']['bucket']['name']
            key = rec['s3']['object']['key']
        except KeyError:
            failures.append({"reason": "MalformedEvent", "record": rec})
            continue

        match = SUBMISSION_KEY_RE.match(key)
        if not match:
            failures.append({"reason": "UnexpectedKeyFormat", "key": key})
            continue

        participant_id, submission_id = match.group(1), match.group(2)
        submission_prefix = f"{participant_id}/{submission_id}/"

        resp = ecs.run_task(
            cluster=CLUSTER_ARN,
            taskDefinition=TASK_DEF_ARN,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": SUBNETS,
                    "securityGroups": SECURITY_GIDS,
                    "assignPublicIp": "DISABLED",
                }
            },
            overrides={
                "containerOverrides": [{
                    "name": CONTAINER_NAME,
                    "environment": [
                        {"name": "SUBMISSIONS_BUCKET", "value": bucket},
                        {"name": "SUBMISSION_PREFIX",  "value": submission_prefix},
                        {"name": "PARTICIPANT_ID",     "value": participant_id},
                        {"name": "TESTDATA_BUCKET",    "value": TESTDATA_BUCKET},
                        {"name": "TESTDATA_KEY",       "value": TESTDATA_KEY},
                        {"name": "DDB_TABLE",          "value": DDB_TABLE},
                        {"name": "COST_BPS",           "value": str(COST_BPS)},
                        {"name": "TIMEOUT_SECONDS",    "value": str(TIMEOUT_SEC)},
                    ],
                }]
            },
            count=1,
        )
        tasks.extend(resp.get('tasks', []))
        run_failures = resp.get('failures', [])
        if run_failures:
            failures.extend(run_failures)

    result = {"ok": not failures, "tasks": tasks}
    if failures:
        result["failures"] = failures
    return result

