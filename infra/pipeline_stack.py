"""
Pipeline stack — Phase 4 + 5. Step Functions orchestration, DynamoDB
session state, S3 Object Lock evidence trail, human approval gate.

Deploy separately from FixtureStack — this creates the AGENT's
infrastructure, not the AWS environment it investigates. Two different
lifecycles: you'll tear down and redeploy the fixture repeatedly as you
adjust findings; this stack is meant to stay up.

TODO(chao): before deploying — set ANTHROPIC_API_KEY as a real secret via
Secrets Manager, not a plaintext Lambda environment variable as scaffolded
below. Plaintext env vars are fine for getting this running once, wrong
for anything you'd call "done." This is a known gap, not an oversight —
fix it before treating this as a finished artifact.
"""

import os
from aws_cdk import (
    Stack, RemovalPolicy, Duration,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_iam as iam,
)
from constructs import Construct


class PipelineStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- State: DynamoDB, since Lambda holds nothing between invocations ---
        sessions_table = dynamodb.Table(
            self, "SessionsTable",
            partition_key=dynamodb.Attribute(name="session_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        approvals_table = dynamodb.Table(
            self, "ApprovalsTable",
            partition_key=dynamodb.Attribute(name="session_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- Evidence: S3 with Object Lock. Must be set at bucket creation —
        # --- cannot be retrofitted onto an existing bucket. ---
        evidence_bucket = s3.Bucket(
            self, "EvidenceBucket",
            object_lock_enabled=True,
            versioned=True,  # required for Object Lock
            removal_policy=RemovalPolicy.RETAIN,  # deliberately NOT auto-delete — this is the audit trail
            # Governance mode: even account admins need a special permission to
            # override, vs Compliance mode where NOTHING can override until the
            # retention period expires, including the root user. Governance is
            # the reasonable default for a portfolio project; note in your ADR
            # that a real regulated deployment would likely use Compliance mode.
            object_lock_default_retention=s3.ObjectLockRetention.governance(Duration.days(90)),
        )
        # TODO(chao): enable a CloudTrail trail with data events ON for this
        # specific bucket, same pattern as FixtureStack's Finding 4. The
        # evidence store needs its own tamper record — that's the point.

        # --- Lambda execution roles: least privilege, one per function. ---
        # This is the architectural point of Phase 4 as much as durability is.

        plan_role = iam.Role(self, "PlanRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        sessions_table.grant_read_write_data(plan_role)
        plan_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"))

        dispatch_role = iam.Role(self, "DispatchRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        sessions_table.grant_read_write_data(dispatch_role)
        evidence_bucket.grant_write(dispatch_role)
        # Read-only AWS access for the actual investigation tools — this is
        # the IAM equivalent of TOOLS/TOOL_IMPL: broad enough to run every
        # tool in schemas.py, but nothing here can ever WRITE to the
        # environment being investigated.
        dispatch_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("ReadOnlyAccess"))
        dispatch_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"))

        approval_role = iam.Role(self, "ApprovalRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        approvals_table.grant_write_data(approval_role)
        approval_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"))

        # The ONLY role in this entire project that can write to the
        # environment. Deliberately narrow: bucket tagging only, on
        # nothing else. This is Finding 3's lesson applied to your own
        # system, not just detected in someone else's.
        write_role = iam.Role(self, "ExecuteWriteRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        sessions_table.grant_read_write_data(write_role)
        evidence_bucket.grant_write(write_role)
        write_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:PutBucketTagging", "s3:GetBucketTagging"],
            resources=["arn:aws:s3:::*"],  # TODO(chao): scope to the fixture bucket ARNs specifically, not all buckets
        ))
        write_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"))

        # --- Lambdas ---
        # Deployment package is pre-built by build_lambda_package.sh — run
        # that BEFORE `cdk deploy`, every time agent/ or lambda_handlers/
        # change. CDK just zips the already-prepared folder here; no
        # Docker, no bundling step, no recursive-copy risk.
        common_kwargs = dict(
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset("../lambda_build"),
            timeout=Duration.seconds(60),
            environment={
                "SESSIONS_TABLE": sessions_table.table_name,
                "EVIDENCE_BUCKET": evidence_bucket.bucket_name,
                # TODO(chao): replace with Secrets Manager reference before this is "done" — see module docstring
                "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
            },
        )

        plan_fn = lambda_.Function(self, "PlanFn", handler="infra.lambda_handlers.plan_handler.handler", role=plan_role, **common_kwargs)
        dispatch_fn = lambda_.Function(self, "DispatchFn", handler="infra.lambda_handlers.tool_dispatch_handler.handler", role=dispatch_role, **common_kwargs)
        approval_fn = lambda_.Function(self, "ApprovalFn", handler="infra.lambda_handlers.approval_handler.handler",
                                        role=approval_role,
                                        environment={**common_kwargs["environment"], "APPROVALS_TABLE": approvals_table.table_name},
                                        runtime=common_kwargs["runtime"], code=common_kwargs["code"], timeout=Duration.minutes(5))
        write_fn = lambda_.Function(self, "ExecuteWriteFn", handler="infra.lambda_handlers.execute_write_handler.handler", role=write_role, **common_kwargs)

        # --- State machine ---

        plan_step = tasks.LambdaInvoke(
            self, "PlanStep", lambda_function=plan_fn,
            payload=sfn.TaskInput.from_object({"session_id": sfn.JsonPath.string_at("$.session_id")}),
            result_path="$.plan_result", payload_response_only=True,
        )

        dispatch_tools = tasks.LambdaInvoke(
            self, "DispatchTools", lambda_function=dispatch_fn,
            payload=sfn.TaskInput.from_object({
                "session_id": sfn.JsonPath.string_at("$.session_id"),
                "tool_calls": sfn.JsonPath.string_at("$.plan_result.tool_calls"),
            }),
            result_path="$.dispatch_result", payload_response_only=True,
        )

        request_approval = tasks.LambdaInvoke(
            self, "RequestApproval", lambda_function=approval_fn,
            integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
            payload=sfn.TaskInput.from_object({
                "session_id": sfn.JsonPath.string_at("$.session_id"),
                "tool_calls": sfn.JsonPath.string_at("$.plan_result.tool_calls"),
                "TaskToken": sfn.JsonPath.task_token,
            }),
            result_path="$.approval_result",
        )

        execute_write = tasks.LambdaInvoke(
            self, "ExecuteWrite", lambda_function=write_fn,
            payload=sfn.TaskInput.from_object({
                "session_id": sfn.JsonPath.string_at("$.session_id"),
                "proposed_action": sfn.JsonPath.string_at("$.approval_result.proposed_action"),
            }),
            result_path="$.write_result", payload_response_only=True,
        )

        finalize = sfn.Pass(self, "Finalize")
        budget_exceeded = sfn.Fail(self, "BudgetExceeded", cause="Agent exhausted MAX_STEPS without reaching end_turn")

        # The loop: DispatchTools always transitions back to PlanStep. This
        # IS the loop — Step Functions has no `for`, a loop is just a state
        # transitioning back to an earlier state. MAX_STEPS is enforced
        # inside plan_handler.py itself (see its step_count check), not by
        # Step Functions — Step Functions just keeps transitioning until
        # the Lambda tells it to stop.
        dispatch_tools.next(plan_step)
        execute_write.next(finalize)

        choice = (
            sfn.Choice(self, "CheckStopReason")
            .when(sfn.Condition.string_equals("$.plan_result.stop_reason", "budget_exceeded"), budget_exceeded)
            .when(sfn.Condition.boolean_equals("$.plan_result.needs_approval", True), request_approval)
            .when(sfn.Condition.string_equals("$.plan_result.stop_reason", "tool_use"), dispatch_tools)
            .otherwise(finalize)
        )
        request_approval.next(execute_write)
        plan_step.next(choice)

        # --- InitSession: seeds the FIRST DynamoDB item. -----------------
        # Without this, PlanStep's very first read finds nothing and raises
        # ValueError("No session found") — this was missing from the first
        # draft of this file. The execution's input must supply both
        # session_id and initial_messages_json (a JSON-encoded message
        # list) — see scripts/run_pipeline.py, which builds that input.
        init_session = tasks.DynamoPutItem(
            self, "InitSession",
            table=sessions_table,
            item={
                "session_id": tasks.DynamoAttributeValue.from_string(sfn.JsonPath.string_at("$.session_id")),
                "messages_json": tasks.DynamoAttributeValue.from_string(sfn.JsonPath.string_at("$.initial_messages_json")),
                "step_count": tasks.DynamoAttributeValue.from_number(0),
            },
            result_path=sfn.JsonPath.DISCARD,  # don't let DynamoDB's raw response clutter state going forward
        )
        init_session.next(plan_step)

        definition = init_session

        self.state_machine = sfn.StateMachine(
            self, "EvidenceAgentStateMachine",
            definition=definition,
            timeout=Duration.minutes(15),
        )

        from aws_cdk import CfnOutput
        CfnOutput(self, "StateMachineArnOutput", value=self.state_machine.state_machine_arn)
        CfnOutput(self, "ApprovalsTableOutput", value=approvals_table.table_name)
