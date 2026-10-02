# ADR 0001 — Step Functions over a plain Lambda loop

Status: accepted

## Context

`agent/loop.py` already works as a single Python process: `messages` and
`step_count` live in local variables for the life of the run. The question
this ADR answers is why that same loop, unmodified, isn't just deployed as
one long-lived process instead of being split across Step Functions,
DynamoDB, and four separate Lambdas.

Two single-process alternatives were considered: one Lambda running the
whole loop, and a long-lived process on EC2/Fargate.

## Decision

**One Lambda running the whole loop doesn't survive Phase 5's requirement.**
Lambda has a hard 15-minute execution ceiling, and this agent's approval
gate can legitimately pause for hours or days waiting on a human. There's
no version of "wait for approval" that fits inside a single Lambda
invocation — the platform kills the process before a slow human ever gets
to it. This isn't a performance tradeoff to optimize around; it's a hard
constraint that rules the option out entirely.

**EC2 or Fargate can hold the pause, but at a cost that scales with exactly
the thing that makes this agent worth building.** A process that stays up
waiting for approval is billed for compute the entire time it's idle,
regardless of whether a human is anywhere near a keyboard — and the whole
point of a human-in-the-loop gate is that the wait time is unpredictable
and can be long. Worse than the cost: that pause is held in one process's
memory, on one machine. If that instance goes down mid-pause — a spot
reclaim, a patch cycle, an AZ issue, any ordinary infrastructure event —
the entire in-progress investigation disappears with it, silently, with no
record that it was ever running. For a tool whose actual product is an
auditable evidence trail, losing the trail to an unrelated infrastructure
hiccup is a specifically bad failure, not just an inconvenient one.

**Step Functions' `WAIT_FOR_TASK_TOKEN` solves both problems for the same
reason.** The pause costs nothing while paused — no process is running,
AWS is just holding a token until `SendTaskSuccess` is called against it,
same as `scripts/approve.py` does. And the state the pause depends on
(the conversation, the step count, the proposed action) already lives in
DynamoDB, not in any one machine's memory, so no single instance failing
can lose it. The durability problem and the cost-while-waiting problem
turn out to be the same problem, and moving state out of process memory
solves both at once.

A secondary, smaller benefit: Step Functions renders the state machine as
an inspectable graph, and each execution shows exactly which state ran,
when, and with what input/output. A single long Lambda log, or a stream of
prints from an EC2 process, gives you one undifferentiated stream to
search through when something goes wrong. Traceability wasn't the primary
reason for this decision, but it's a real, free byproduct of it.

## Consequences

- **A deployment gap that undercuts the main argument:** the case above
  rests on the approval pause being able to last hours or days, but the
  deployed state machine has an overall timeout of 15 minutes
  (`timeout=Duration.minutes(15)` in `pipeline_stack.py`). The task-token
  mechanism can wait far longer than that, so the architecture supports
  the claim, but this configuration doesn't yet. The fix is a larger
  timeout value and a redeploy. It is also listed under known gaps in the
  README.
- **What this cost:** real visibility into the loop's own logic is now
  spread across `plan_handler.py`, `tool_dispatch_handler.py`, and the
  state machine definition in `pipeline_stack.py`, rather than sitting in
  one readable file the way `agent/loop.py` does. Understanding the
  system now requires reading the state machine graph alongside the code,
  not just the code.
- **What this cost, concretely:** this project's hardest debugging day —
  the recursive `cdk.out` packaging bug, the Docker permissions dead end,
  the missing `InitSession` state, the broken task-token handoff — was a
  direct tax of choosing a distributed architecture over a single process.
  A single-process version would not have produced any of those bugs. That
  cost was worth paying for what Phase 5 requires; it would not have been
  worth paying for a version of this agent with no approval gate at all.
- **Vendor lock-in, accepted deliberately:** this architecture is AWS-
  native. A team using LangGraph or Temporal instead would solve the same
  durability problem with a different, non-AWS-specific primitive. That's
  a legitimate different answer to the same problem, not a wrong one — the
  choice here was made because the rest of this project's stack (fixture,
  IAM, the target environment being investigated) is already AWS-native,
  not because Step Functions is objectively superior to every alternative.
- **The actual test to apply before repeating this pattern:** would this
  process ever legitimately need to pause for longer than 15 minutes, or
  outlive a single machine? If not, a single Lambda or a plain long-running
  process is simpler and this entire architecture is over-engineering for
  the problem. It was the right call here specifically because of Phase
  5's approval gate — not as a general default for "any agent."
