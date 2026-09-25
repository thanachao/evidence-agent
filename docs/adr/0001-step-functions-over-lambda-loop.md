# ADR 0001 — Step Functions over a plain Lambda loop

Status: proposed (Phase 4)

## Context
An agent run is long-lived, stateful, and resumable. Lambda is stateless with
a 15-minute ceiling.

## Decision
TODO(chao): write this yourself. This is the decision you will be asked to
defend in an interview, and it is the one where your instinct (serverless by
default) is being deliberately tested. Cover:
  - why not a single Lambda running the whole loop
  - why not ECS/Fargate long-running
  - what waitForTaskToken buys you in Phase 5 that you'd otherwise hand-build
  - what you gave up

## Consequences
TODO(chao)
