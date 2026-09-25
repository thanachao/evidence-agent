"""
Plan Lambda — Phase 4. The "Plan" half of plan/act/observe, adapted from
agent/loop.py for a stateless Lambda invocation.

Why this exists as its own Lambda instead of one big Lambda running the
whole loop: see docs/adr/0001. Short version — Lambda can't hold state
between invocations, so the loop's state (message history, step count)
has to live in DynamoDB, and the loop's SHAPE has to live in Step
Functions instead of a Python `for`.

Input (from Step Functions):
    {"session_id": "..."}

Output:
    {
      "stop_reason": "tool_use" | "end_turn" | "budget_exceeded",
      "tool_calls": [{"name": ..., "input": ..., "tool_use_id": ...}, ...],
      "answer": "..." | null,
      "step_count": <int>,
      "needs_approval": <bool>   # true if the write-action tool was requested
    }
"""

import os
import json
import boto3
import anthropic

from agent.schemas import TOOLS

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["SESSIONS_TABLE"])
client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from Lambda env var — see pipeline_stack.py

MODEL = "claude-sonnet-5"
MAX_STEPS = int(os.environ.get("MAX_STEPS", "10"))

# The one write action. Anything else the model requests goes through
# DispatchTools normally; this specific name routes to the approval gate.
WRITE_ACTION_NAME = "flag_finding_for_remediation"


def handler(event, context):
    session_id = event["session_id"]

    item = table.get_item(Key={"session_id": session_id}).get("Item")
    if item is None:
        raise ValueError(f"No session found for {session_id} — InitSession should have created it")

    messages = json.loads(item["messages_json"])
    step_count = int(item.get("step_count", 0)) + 1

    if step_count > MAX_STEPS:
        table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET step_count = :s, #st = :status",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":s": step_count, ":status": "BUDGET_EXCEEDED"},
        )
        return {"stop_reason": "budget_exceeded", "tool_calls": [], "answer": None,
                "step_count": step_count, "needs_approval": False}

    response = client.messages.create(model=MODEL, max_tokens=2048, tools=TOOLS, messages=messages)
    messages.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})

    table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET messages_json = :m, step_count = :s",
        ExpressionAttributeValues={":m": json.dumps(messages), ":s": step_count},
    )

    if response.stop_reason == "tool_use":
        tool_calls = [
            {"name": b.name, "input": b.input, "tool_use_id": b.id}
            for b in response.content if b.type == "tool_use"
        ]
        needs_approval = any(tc["name"] == WRITE_ACTION_NAME for tc in tool_calls)
        return {"stop_reason": "tool_use", "tool_calls": tool_calls, "answer": None,
                "step_count": step_count, "needs_approval": needs_approval}

    answer = "".join(b.text for b in response.content if b.type == "text")
    return {"stop_reason": "end_turn", "tool_calls": [], "answer": answer,
            "step_count": step_count, "needs_approval": False}
