"""
Execute Write Lambda — Phase 5. Runs ONLY after human approval.

The one side-effecting action in the whole system. Deliberately small
blast radius: tags a resource, does not delete/modify/create anything.
Its own scoped IAM role (see pipeline_stack.py) is the ONLY role in this
project permitted to call s3:PutBucketTagging — not even Anthropic's
model ever gets those credentials, only this Lambda does, and only after
a human said yes.

Input:
    {"session_id": "...", "proposed_action": {"bucket_name": "...", "finding": "..."}}
"""

import os
import json
import time
import boto3

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["SESSIONS_TABLE"])
EVIDENCE_BUCKET = os.environ["EVIDENCE_BUCKET"]


def handler(event, context):
    session_id = event["session_id"]
    action = event["proposed_action"]
    bucket_name = action["bucket_name"]
    finding = action.get("finding", "unspecified")

    existing = s3.get_bucket_tagging(Bucket=bucket_name).get("TagSet", []) if _has_tags(bucket_name) else []
    new_tags = [t for t in existing if t["Key"] != "RemediationFlag"]
    # Tags have a strict allowed character set (letters, numbers, spaces,
    # + - = . _ : / @) — no commas, no apostrophes. Model-generated free
    # text routinely contains both, so it can never safely be used as a
    # tag VALUE directly (this failed for real with InvalidTag on the
    # first attempt). The tag is a short, safe pointer; the actual
    # narrative goes to the evidence bucket below, unrestricted.
    new_tags.append({"Key": "RemediationFlag", "Value": f"flagged-{session_id}"})
    s3.put_bucket_tagging(Bucket=bucket_name, Tagging={"TagSet": new_tags})

    key = f"{session_id}/write-action-{int(time.time())}.json"
    s3.put_object(
        Bucket=EVIDENCE_BUCKET, Key=key, ContentType="application/json",
        Body=json.dumps({"session_id": session_id, "action": "flag_finding_for_remediation",
                          "bucket_name": bucket_name, "finding": finding, "timestamp": time.time()}),
    )

    table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #st = :status",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={":status": "WRITE_COMPLETED"},
    )
    return {"session_id": session_id, "bucket_tagged": bucket_name}


def _has_tags(bucket_name: str) -> bool:
    try:
        s3.get_bucket_tagging(Bucket=bucket_name)
        return True
    except s3.exceptions.ClientError:
        return False
