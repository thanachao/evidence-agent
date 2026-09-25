"""
Approval Request Lambda — Phase 5.

Called by Step Functions' RequestApproval state, which uses the
`.waitForTaskToken` integration pattern: execution genuinely pauses here,
mid-state-machine, until something external calls SendTaskSuccess with the
token this Lambda receives. This Lambda's only job is to record that token
somewhere a human can find it — it does NOT decide whether to approve.

Input (Step Functions injects TaskToken automatically):
    {"session_id": "...", "tool_calls": [...], "TaskToken": "..."}

This writes a pending-approval record to DynamoDB. scripts/approve.py reads
it and calls SendTaskSuccess/SendTaskFailure once a human decides.
"""

import os
import boto3

dynamodb = boto3.resource("dynamodb")
approvals_table = dynamodb.Table(os.environ["APPROVALS_TABLE"])


def handler(event, context):
    session_id = event["session_id"]
    task_token = event["TaskToken"]

    write_call = next(tc for tc in event["tool_calls"] if tc["name"] == "flag_finding_for_remediation")

    approvals_table.put_item(Item={
        "session_id": session_id,
        "task_token": task_token,
        "proposed_action": write_call["input"],
        "status": "PENDING",
    })

    print(f"Approval pending for session {session_id}. Run: python scripts/approve.py {session_id}")
    # No return value needed — Step Functions is waiting on the token,
    # not on this Lambda's output. This Lambda just returns normally and
    # the state machine stays paused until scripts/approve.py acts on it.
