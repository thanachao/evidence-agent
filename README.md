# Evidence agent

An agent that answers compliance questions about AWS environments by planning
a multi-step investigation, calling read-only tools to gather evidence, and
producing a citable evidence package. One write action sits behind a human
approval gate.

Not a scanner. Prowler and Security Hub already detect misconfigurations
better than an LLM will — this calls them as tools and does the decomposition,
historical correlation, and evidence-citation work on top. The question it can
answer that they can't: *"was this true throughout Q2"*, not *"is this true now"*.

## Status

| Phase | What | State |
|---|---|---|
| 1 | Agent loop, stub tools | **Working, verified** — including a deliberate step-budget cutoff test |
| 2 | Fixture stack | **Deployed.** 4/5 findings verified by hand; CloudTrail historical-gap check (Finding 4) deliberately deferred |
| 3 | Real boto3 tools (6, incl. TLS enforcement) | **Verified** against the live fixture. One real bug found and fixed: the IAM role check originally missed inline policies, only checked attached (managed) ones |
| 4 | Step Functions + DynamoDB + Object Lock | **Deployed and run end-to-end** |
| 5 | Human approval gate | **Deployed and exercised live** — a real execution paused, a human approved it, a real AWS mutation followed, independently verified by hand |
| 6 | MCP server | **Verified from 3 independent hosts** — MCP Inspector, Claude Desktop, and a separate Claude session calling it directly |
| 7 | Eval harness | **6/6 implemented scenarios passing** (trajectory + LLM-as-judge). 2 CloudTrail-dependent scenarios honestly skipped, not faked |
| 8 | Strands / AgentCore port | **Run and verified** (direct-tools mode). Found a real, checked gap: Strands has no built-in step-budget guardrail the hand-built loop already has. MCP-consumption mode is built but not yet executed |
| — | Agent security (prompt injection) | **Run** — 4/4 adversarial payloads resisted. Documented nuance: imperative-phrased injections were flagged explicitly, a passive-phrased one wasn't (though still not complied with) |
| — | ADRs 0001 & 0003 | **Written**, argued through, not pre-filled |

## Layout

```
agent/
  schemas.py        # what the model sees — 6 tool contracts
  tools_stub.py     # fake implementations
  tools_aws.py      # real boto3 implementations
  loop.py           # the hand-built loop
  strands_agent.py  # Phase 8 — same agent on AWS's managed SDK
infra/
  fixture_stack.py  # the seeded findings (deployed)
  pipeline_stack.py # Step Functions, DynamoDB, Object Lock, approval gate
  lambda_handlers/  # plan / dispatch / approval / write
mcp_server/
  server.py         # same tools over MCP
security/
  injection_test.py # prompt injection via tool output
evals/
  scenarios.yaml        # derived from findings.md
  test_trajectories.py  # trajectory + LLM-as-judge
scripts/
  approve.py         # the human in human-in-the-loop
  run_pipeline.py     # starts a real Step Functions execution
docs/adr/            # 0001 and 0003 — architecture and security posture, written and defended
findings.md           # ground truth, written before the infra
```

## The one idea worth understanding

`schemas.py` is what the model sees. `tools_stub.py` / `tools_aws.py` are what
runs. The model never sees the implementations. That separation is why the same
six functions appear unchanged in the hand-built loop, in Step Functions, over
MCP, and in Strands — four hosts, one implementation.

## Run order

```bash
source .venv/bin/activate
export AWS_PROFILE=personal

python -m agent.loop                # stub mode, then flip USE_REAL_TOOLS=True
python -m security.injection_test   # security — run before trusting anything
python -m pytest evals/ -v          # score against labeled ground truth
python -m mcp_server.server         # MCP, standalone
python -m agent.strands_agent       # managed stack, both modes

# Deployed pipeline (separate from the above — requires infra/pipeline_stack.py deployed):
python scripts/run_pipeline.py
python scripts/approve.py           # list pending, then <session_id> --approve
```

## Known gaps

- **CloudTrail Lake historical query** (`query_cloudtrail_history`) — deliberately deferred. No proper high-level CDK construct exists for the Event Data Store; scoped, not built, documented as a real engineering call rather than rushed.
- **`ANTHROPIC_API_KEY` in `pipeline_stack.py`** reads from an environment variable at deploy time now, not a hardcoded literal — but it's still not in Secrets Manager, which is the real fix.
- **A step containing both read tools and the write tool in the same turn silently drops the read calls** — the approval gate currently assumes a pure step (all reads, or the one write), not a mixed one. Never triggered in a real run, found by direct code review.
- **Only the first of multiple write proposals in one turn gets captured** — `approval_handler.py` uses `next()` to grab one `flag_finding_for_remediation` call; a second one in the same turn is silently dropped. Discovered from a real run that proposed two.
- **The state machine's 15-minute timeout undercuts part of ADR 0001's own argument** — the pause mechanism can hold for days, but this specific deployment would kill the whole execution at 15 minutes regardless.
- **No approver identity is captured** — anyone with the AWS profile's IAM permissions can call `approve.py`; the evidence trail records *that* something was approved, not *who* approved it.
- **Cost and latency per investigation have never been measured.**
- **Eval suite consistency across repeated runs has never been checked** — no run-to-run variance testing done yet.
