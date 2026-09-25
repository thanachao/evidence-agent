"""
Tool Dispatch Lambda — Phase 4.

Runs whatever tools PlanStep requested, writes each call AND its result to
the Object Lock evidence bucket (immutable, append-only), then writes the
tool_result messages back to the session in DynamoDB so the next PlanStep
sees them — same "results go back in as a user turn" mechanic as
agent/loop.py, just split across a stateless invocation instead of a
Python loop iteration.

Input:
    {"session_id": "...", "tool_calls": [{"name", "input", "tool_use_id"}, ...]}

Output:
    {"session_id": "..."}   # nothing else needed — CheckStopReason re-reads PlanStep's next output
"""

import os
import json
import time
import boto3

from agent.tools_aws import AWS_IMPL as TOOL_IMPL

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["SESSIONS_TABLE"])
s3 = boto3.client("s3")
EVIDENCE_BUCKET = os.environ["EVIDENCE_BUCKET"]


def _write_evidence(session_id: str, step: int, tool_name: str, tool_input: dict, result: str) -> None:
    # One immutable object per tool call. Object Lock on the bucket means
    # this cannot be edited or deleted for the retention period, even by
    # an admin — see docs/adr/0001 for why that matters here specifically.
    key = f"{session_id}/step-{step:03d}-{tool_name}-{int(time.time())}.json"
    body = json.dumps({
        "session_id": session_id, "step": step, "tool": tool_name,
        "input": tool_input, "result": result, "timestamp": time.time(),
    })
    s3.put_object(Bucket=EVIDENCE_BUCKET, Key=key, Body=body, ContentType="application/json")


def handler(event, context):
    session_id = event["session_id"]
    tool_calls = event["tool_calls"]

    item = table.get_item(Key={"session_id": session_id})["Item"]
    messages = json.loads(item["messages_json"])
    step = int(item["step_count"])

    results = []
    for call in tool_calls:
        name, tool_input, tool_use_id = call["name"], call["input"], call["tool_use_id"]

        # The write action never executes here — it's routed to the
        # approval gate before DispatchTools is ever reached. Defensive
        # check in case wiring changes later.
        if name == "flag_finding_for_remediation":
            raise RuntimeError("write action reached DispatchTools without approval — check state machine wiring")

        out = TOOL_IMPL[name](**tool_input)
        _write_evidence(session_id, step, name, tool_input, out)
        results.append({"type": "tool_result", "tool_use_id": tool_use_id, "content": out})

    messages.append({"role": "user", "content": results})
    table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET messages_json = :m",
        ExpressionAttributeValues={":m": json.dumps(messages)},
    )
    return {"session_id": session_id}
