#!/usr/bin/env python3
"""
Starts one execution of the Step Functions pipeline. This is the piece that
was missing before — pipeline_stack.py defines the state machine, but
nothing actually kicked one off.

    python scripts/run_pipeline.py "Check bucket X for public access issues"

Prints the execution ARN — watch it live in the AWS Console under
Step Functions, or poll it:
    aws stepfunctions describe-execution --execution-arn <arn>
"""

import sys
import json
import uuid
import boto3

sfn = boto3.client("stepfunctions")

# TODO(chao): read from `cdk deploy` outputs instead of hardcoding.
# After deploying, run:  aws cloudformation describe-stacks --stack-name EvidenceAgentPipeline \
#   --query "Stacks[0].Outputs"
STATE_MACHINE_ARN = "arn:aws:states:us-east-1:556957334146:stateMachine:EvidenceAgentStateMachineE09CAAE8-tmK8I6obuvQa"


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else (
        "Check bucket 'finance-reports-prod-556957334146' for encryption "
        "and public access issues. Cite the evidence."
    )

    session_id = str(uuid.uuid4())
    initial_messages = [{"role": "user", "content": question}]

    resp = sfn.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=session_id,
        input=json.dumps({
            "session_id": session_id,
            "initial_messages_json": json.dumps(initial_messages),
        }),
    )

    print(f"Started session {session_id}")
    print(f"Execution ARN: {resp['executionArn']}")
    print(f"\nCheck status with:\n  aws stepfunctions describe-execution --execution-arn {resp['executionArn']}")
    print(f"\nIf it pauses awaiting approval:\n  python scripts/approve.py {session_id}")


if __name__ == "__main__":
    main()
