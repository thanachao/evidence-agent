# ADR 0003 — Agent security posture

Status: proposed — YOURS TO WRITE after running security/injection_test.py

## Context
The agent reads attacker-controllable text (object keys, tags, role
descriptions) and has one write action plus IAM permissions.

## What to record here
Run `python -m security.injection_test` first, then write down:
  - which payloads succeeded undefended, which failed
  - whether the defended variants actually changed behaviour, and how much
  - your conclusion on prompt-level vs architectural defences

## Decision
TODO(chao) — this is the one an interviewer will push hardest on, because
almost no candidate has tested it. Cover why least-privilege IAM per tool,
the approval gate, and the immutable trail are the real controls, and what
residual risk remains after all three.

## Consequences
TODO(chao)
