#!/usr/bin/env python3
"""
Approval CLI — Phase 5. Deliberately minimal: this IS the human-in-the-loop
interface. A real product would have a UI; a portfolio project just needs
to prove the pause-and-resume mechanic actually works.

List pending approvals:
    python scripts/approve.py

Approve one:
    python scripts/approve.py <session_id> --approve

Reject one:
    python scripts/approve.py <session_id> --reject
"""

import sys
import json
import boto3

dynamodb = boto3.resource("dynamodb")
sfn = boto3.client("stepfunctions")

# TODO(chao): read these from a config file or CDK output instead of
# hardcoding — fine for now, not fine to leave this way.
# From the cdk deploy output — EvidenceAgentPipeline.ApprovalsTableOutput.
# Should be stable across the redeploys since then (only Lambda code/env
# vars changed, not the table's own definition) — but if this 404s again,
# reconfirm with: aws cloudformation describe-stacks --stack-name EvidenceAgentPipeline --query "Stacks[0].Outputs"
APPROVALS_TABLE = "EvidenceAgentPipeline-ApprovalsTableF18C2B8F-JAQB6W0GLZBE"


def list_pending():
    table = dynamodb.Table(APPROVALS_TABLE)
    items = table.scan(FilterExpression=boto3.dynamodb.conditions.Attr("status").eq("PENDING"))["Items"]
    if not items:
        print("No pending approvals.")
        return
    for item in items:
        print(f"session={item['session_id']}  proposed_action={item['proposed_action']}")


def decide(session_id: str, approve: bool):
    table = dynamodb.Table(APPROVALS_TABLE)
    item = table.get_item(Key={"session_id": session_id}).get("Item")
    if not item:
        print(f"No pending approval found for {session_id}")
        return

    if approve:
        output = json.dumps({"decision": "approved", "proposed_action": item["proposed_action"]})
        sfn.send_task_success(taskToken=item["task_token"], output=output)
        print(f"Approved. Step Functions execution for {session_id} will resume.")
    else:
        sfn.send_task_failure(taskToken=item["task_token"], error="RejectedByHuman", cause="Rejected via approve.py")
        print(f"Rejected. Execution for {session_id} will fail out.")

    table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #st = :s",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={":s": "APPROVED" if approve else "REJECTED"},
    )


if __name__ == "__main__":
    if len(sys.argv) == 1:
        list_pending()
    elif len(sys.argv) == 3 and sys.argv[2] == "--approve":
        decide(sys.argv[1], approve=True)
    elif len(sys.argv) == 3 and sys.argv[2] == "--reject":
        decide(sys.argv[1], approve=False)
    else:
        print(__doc__)
