# Fixture Stack — Findings Specification

Written before any CDK exists. This is the ground truth: every finding here
must be independently confirmable by hand (CLI/console) before the agent is
ever pointed at it. This file is used twice — as the answer key when the
real tools replace the stubs (Phase 3), and as the eval spec, unchanged,
in Phase 7.

Stack name convention: `evidence-agent-fixture`
Region: pick one, stay consistent — findings below assume a single region.

---

## Finding 1 — Object-level public ACL

- **Resource:** `finance-reports-prod` bucket, one specific object
  (e.g. `q2-summary.pdf`), NOT the bucket itself.
- **Configured as:** the object has a public-read ACL applied directly to
  it. This requires a **partial** Block Public Access config —
  `BlockPublicAcls` and `IgnorePublicAcls` off, `BlockPublicPolicy` and
  `RestrictPublicBuckets` on. (Correction: an earlier version of this doc
  said bucket-level BPA could stay fully ON — that's wrong. If
  `BlockPublicAcls` is on, AWS refuses to let a public object ACL be set
  at all; confirmed by hitting `AccessDenied` trying to seed this exact
  finding against a fully-locked-down bucket.) The realistic story here:
  policy-side hardened, ACL-side missed — a common real misconfiguration,
  not a contrived one.
- **Why it's a finding:** matches the object-level blind spot the stub
  tool's own docstring already flagged ("object-level ACLs are not
  evaluated by this check").
- **Detection (real API):** `s3:GetObjectAcl` on the specific key —
  bucket-level `GetPublicAccessBlock` alone will NOT catch this.
- **Expected real tool:** a new tool, `check_object_acls(bucket_name)`,
  since neither existing stub tool actually reaches object level.
- **Maps to:** CIS AWS Foundations Benchmark 2.1.5-family controls
  (S3 public access) — same control family as the Dominion Security Hub
  work, different granularity.

---

## Finding 2 — KMS key rotation disabled

- **Resource:** the KMS key backing `finance-reports-prod`'s default
  encryption (`alias/finance-data-key` in the stub — reuse this alias).
- **Configured as:** customer-managed key, rotation explicitly disabled
  at creation.
- **Why it's a finding:** exactly what the stub already fabricates —
  this finding makes the stub's hardcoded answer real.
- **Detection (real API):** `kms:GetKeyRotationStatus`.
- **Expected real tool:** `check_encryption_status(bucket_name)` — same
  name as the existing stub, real implementation swaps in directly.
- **Maps to:** CIS AWS Foundations Benchmark 3.x key management controls.

---

## Finding 3 — Over-broad IAM role

- **Resource:** a role created for this fixture (e.g.
  `fixture-report-processor-role`).
- **Configured as:** either a trust policy with no principal restriction,
  or an attached policy with `"Action": "s3:*"` / `"Resource": "*"` —
  pick one, not both, so the finding is unambiguous.
- **Why it's a finding:** least-privilege violation — the role can reach
  far more than the workload it's meant to serve needs.
- **Detection (real API):** `iam:GetRole` (trust policy) and
  `iam:ListAttachedRolePolicies` + `iam:GetPolicyVersion` (permissions).
- **Expected real tool:** new tool, `check_iam_role_scope(role_name)`.
- **Maps to:** CIS 1.x IAM controls; also the same class of finding IAM
  Access Analyzer would surface directly via `access-analyzer:ListFindings`
  if you enable an analyzer on the fixture account — worth doing, since it
  lets one tool call the real scanner instead of hand-parsing policy JSON.

---

## Finding 4 — CloudTrail data events gap

- **Resource:** the CloudTrail trail covering `finance-reports-prod`.
- **Configured as:** data events for this bucket enabled at trail
  creation, then explicitly disabled partway through a simulated window —
  do this via two sequential `cdk deploy`s with different data-event
  config, noting the timestamp of the second deploy as the "gap start."
- **Why it's a finding:** this is the finding that makes the whole
  project's premise real — a point-in-time scanner (Config, Security Hub)
  cannot see this. Only a time-ranged historical query can.
- **Detection (real API):** CloudTrail Lake SQL query against the event
  data store, filtering `eventCategory = 'Data'` for this resource across
  the window — NOT `cloudtrail:LookupEvents`, which only covers
  management events well and isn't reliably queryable by arbitrary
  time range for data events.
- **Expected real tool:** `query_cloudtrail_history(resource_arn, start, end, event_name)` —
  matches the tool already sketched back in Phase 2 planning.
- **Note:** this is the hardest finding to seed correctly — verify by hand
  that the gap is actually visible in CloudTrail Lake before trusting it
  as ground truth. If you can't find it manually, it's not a valid fixture
  finding.

---

## Finding 5 — Decoy (must NOT be flagged)

- **Resource:** a second bucket, e.g. `finance-archive-prod`.
- **Configured as:** something that LOOKS like it could be a finding on
  a shallow read, but is actually correct. Best option: a bucket policy
  with an explicit `"Effect": "Deny"` statement blocking anonymous access,
  which some naive checks might flag just for containing a broad
  `"Principal": "*"` without reading that it's a Deny, not an Allow.
- **Why it exists:** proves the eval suite (Phase 7) isn't just flagging
  anything unusual. An agent — or a human — that doesn't read the
  `Effect` field correctly will get this wrong.
- **Detection (real API):** `s3:GetBucketPolicy`, then actually parse
  `Effect`.
- **Expected result:** agent must explicitly conclude "compliant" here,
  not just stay silent about it.
- **Must be compliant on every surface the tools check**, not only the
  policy: its own KMS key with rotation enabled (not Finding 2's key), Block
  Public Access fully on, and a TLS Deny covering the bucket ARN and its
  objects. Otherwise a thorough agent correctly finds something and the
  decoy stops being one.

---

## Finding 6 — TLS (encryption in transit) not enforced

- **Resource:** `finance-reports-prod` bucket. The decoy bucket
  `finance-archive-prod` is TLS-*compliant* — see note.
- **Configured as:** `finance-reports-prod` has a bucket policy, but it is
  only the `Allow` that CDK auto-injects because `auto_delete_objects=True`
  (grants the auto-delete Lambda `s3:DeleteObject*` / `s3:GetBucket*` etc.).
  That policy contains **no** `aws:SecureTransport` Deny, so requests over
  plain HTTP are not rejected. (Verified 2026-09-25 against the deployed
  stack — the bucket is NOT policy-less, as an earlier draft of this doc
  wrongly assumed; the auto-delete policy is always present.)
- **Why it's a finding:** encryption at rest (Finding 2) says nothing about
  data in transit. Enforcing TLS requires an explicit `"Effect": "Deny"` on
  the `aws:SecureTransport": "false"` condition; a policy with no such Deny
  provides zero enforcement.
- **Detection (real API):** `s3:GetBucketPolicy`. The tool must handle two
  finding shapes: (a) no policy at all — the API **raises** `NoSuchBucketPolicy`
  (it does not return empty); and (b) a policy present but with no
  `SecureTransport` Deny covering the bucket, which is what this fixture
  actually has. Both are findings.
- **Expected real tool:** new tool, `check_tls_enforcement(bucket_name)`.
- **Note (decoy interaction):** `finance-archive-prod` (Finding 5) has a
  `SecureTransport` Deny covering **both** the bucket ARN and
  `arn:.../finance-archive-prod-<acct>/*` (its policy also carries the same
  auto-delete `Allow`, irrelevant to TLS), so it is TLS-compliant — the eval
  scenario `f6-tls-archive-enforced` is a negative control. Earlier versions
  scoped that Deny to objects only, which made the decoy a real TLS finding
  (bucket-level calls like `ListObjects` succeeded without TLS) and broke
  Finding 5; fixed so the decoy is compliant on every surface. The condition
  value AWS stores is the string `"false"`, not a boolean — match only the
  string.
- **Maps to:** CIS AWS Foundations Benchmark S3 transport-encryption control
  (`aws-foundational-security-best-practices` S3.5).

---

## Before writing any CDK

Confirm each finding is independently retrievable by hand:

```bash
aws s3api get-object-acl --bucket finance-reports-prod --key q2-summary.pdf
# get-key-rotation-status rejects aliases (InvalidArnException) — resolve the key ID first
aws kms get-key-rotation-status --key-id $(aws kms describe-key --key-id alias/finance-data-key --query KeyMetadata.KeyId --output text)
aws iam get-role --role-name fixture-report-processor-role
aws iam list-attached-role-policies --role-name fixture-report-processor-role
# CloudTrail Lake query — run manually in console first before scripting
aws s3api get-bucket-policy --bucket finance-archive-prod
# Finding 6: target returns an auto-delete Allow with NO SecureTransport Deny
# (finding); archive returns that Allow PLUS a Deny covering the bucket ARN
# and /* (compliant). Neither bucket is policy-less on the deployed stack.
aws kms get-key-rotation-status --key-id $(aws kms describe-key --key-id alias/finance-archive-key --query KeyMetadata.KeyId --output text)   # decoy: ENABLED
aws s3api get-bucket-policy --bucket finance-reports-prod
```

If any of these come back empty or wrong before the stack even exists,
that's a paperwork bug, not an infrastructure bug — fix the plan before
writing CDK.

## Teardown

Write this now, not after deploy:

```bash
cdk destroy --all
```

Cost note: CloudTrail Lake event data stores bill per GB ingested/retained
— keep the fixture's retention window short (7 days is enough for this
exercise) so Finding 4 doesn't quietly run up a bill if the stack sits
deployed longer than intended.
