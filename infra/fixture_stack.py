"""
Fixture stack — Phase 2. SKELETON, decisions still open.

Creates the five seeded findings from findings.md so the agent has labeled
ground truth to be tested against.

DECIDED:
  Region: us-east-1 (set in app.py).
  Finding 4: two sequential deploys. DATA_EVENTS_ENABLED below controls
  which deploy you're doing — see the block near the CloudTrail trail.

STILL OPEN:
  TODO(chao): decide whether to enable IAM Access Analyzer on the account.
    If yes, check_iam_role_scope can call the real scanner instead of
    hand-parsing policy JSON — better architecture, small extra cost.

Cost: keep CloudTrail Lake retention short. Run `cdk destroy` between sessions.
"""

from aws_cdk import (
    Stack, RemovalPolicy, Duration,
    aws_s3 as s3,
    aws_kms as kms,
    aws_iam as iam,
    aws_cloudtrail as cloudtrail,
)
from constructs import Construct

# --- Finding 4 deploy toggle ---
# Deploy 1: leave this True. Creates the trail WITH data events on.
# Run it, confirm Findings 1-3 are in place, note the wall-clock time.
# Then flip this to False and `cdk deploy` again — that second deploy's
# timestamp is the gap start. Write the real timestamp into findings.md,
# replacing the placeholder "2026-05-14" once you know it.
DATA_EVENTS_ENABLED = True


class FixtureStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Finding 2: KMS key with rotation DISABLED ---
        key = kms.Key(
            self, "FinanceDataKey",
            alias="alias/finance-data-key",
            enable_key_rotation=False,          # the finding
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- Target bucket. Bucket-level BPA stays ON deliberately, so that
        # --- Finding 1 (object-level ACL) is the only public-access finding.
        reports = s3.Bucket(
            self, "FinanceReportsProd",
            bucket_name=f"finance-reports-prod-{self.account}",   # account suffix guarantees global uniqueness
            encryption=s3.BucketEncryption.KMS,
            encryption_key=key,
            # NOT block_public_access=BLOCK_ALL. If BlockPublicAcls were on,
            # AWS refuses to let a public object ACL be set at all — you'd
            # get AccessDenied trying to seed Finding 1, which is exactly
            # what happened the first time this was deployed with BLOCK_ALL.
            # This partial config is the realistic misconfiguration: policy
            # side hardened, ACL side missed.
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=False,
                ignore_public_acls=False,
                block_public_policy=True,
                restrict_public_buckets=True,
            ),
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,  # required for object ACLs to apply
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # --- Finding 1: object-level public ACL ---
        # TODO(chao): CDK cannot set an object ACL directly. Options:
        #   (a) BucketDeployment + a custom resource that calls put_object_acl
        #   (b) upload it manually with: aws s3api put-object-acl --acl public-read
        # (b) is honest and faster for a fixture. Document whichever you pick.

        # --- Finding 3: over-broad IAM role ---
        iam.Role(
            self, "FixtureReportProcessorRole",
            role_name="fixture-report-processor-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            inline_policies={
                "OverBroad": iam.PolicyDocument(statements=[
                    iam.PolicyStatement(actions=["s3:*"], resources=["*"])   # the finding
                ])
            },
        )

        # --- Finding 4: CloudTrail with data events ---
        trail = cloudtrail.Trail(self, "FixtureTrail")
        if DATA_EVENTS_ENABLED:
            trail.add_s3_event_selector(
                [cloudtrail.S3EventSelector(bucket=reports)],
                read_write_type=cloudtrail.ReadWriteType.ALL,
            )
        # else: this is deploy 2. The trail still exists, but data events for
        # `reports` stop being logged from THIS deploy's timestamp onward —
        # that gap is Finding 4. Note the timestamp when you run this deploy.

        # --- Finding 5: the decoy. Looks suspicious, is actually correct. ---
        # Must be compliant on EVERY surface the tools check, or a thorough
        # agent will correctly find something and the decoy stops being one.
        # It used to share `key` (rotation off — Finding 2) and scope the TLS
        # Deny to objects only, so it was really a finding on two counts.
        archive_key = kms.Key(
            self, "FinanceArchiveKey",
            alias="alias/finance-archive-key",
            enable_key_rotation=True,           # not shared with Finding 2's key
            removal_policy=RemovalPolicy.DESTROY,
        )
        archive = s3.Bucket(
            self, "FinanceArchiveProd",
            bucket_name=f"finance-archive-prod-{self.account}",   # account suffix guarantees global uniqueness
            encryption=s3.BucketEncryption.KMS,
            encryption_key=archive_key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        archive.add_to_resource_policy(iam.PolicyStatement(
            effect=iam.Effect.DENY,               # Deny, not Allow — the decoy
            principals=[iam.AnyPrincipal()],
            actions=["s3:*"],
            # Bucket ARN AND objects: an objects-only Deny leaves bucket-level
            # calls (e.g. ListObjects) reachable without TLS.
            resources=[archive.bucket_arn, archive.arn_for_objects("*")],
            conditions={"Bool": {"aws:SecureTransport": "false"}},
        ))
