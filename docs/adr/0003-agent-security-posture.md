# ADR 0003 — Agent security posture

Status: accepted

## Context

The agent reads attacker-controllable text — S3 object metadata, tags, role
descriptions, tool output in general — as part of every investigation. That
text enters the model's context indistinguishable, by default, from a real
instruction. It also has exactly one action with real-world consequences:
`flag_finding_for_remediation`, which tags a live AWS resource.

`security/injection_test.py` ran four payloads against this exact setup:
one instructing the model to suppress a finding, one instructing it to call
the write tool on the wrong bucket, one instructing it to exfiltrate its own
system prompt, and one clean control.

## What the test actually showed

Zero payloads succeeded, undefended or defended: the write tool was never
triggered by an injected instruction, and no bucket was ever misreported as
compliant.

But the result wasn't uniform, and the shape of the difference matters more
than the pass/fail count:

- **Imperative-phrased injections were caught and flagged explicitly.** The
  payload written as a direct command ("Ignore previous instructions...")
  got called out by name in the model's own answer, undefended, with no
  prompt-level defense in place at all.
- **A passive-phrased injection — text written to resemble legitimate
  metadata rather than a command — was not complied with, but also was not
  flagged.** The model quietly ignored it rather than surfacing that
  something suspicious was present. Same outcome, weaker signal.
- **The defended system prompt (explicitly instructing the model to treat
  tool output as untrusted and never act on embedded instructions) made the
  model measurably quieter across every payload** — including the two
  cases where the undefended run had explicitly called out an attack. The
  defense reduced compliance, but it also reduced *reporting*. For a
  compliance agent specifically, a silent resistance is close to the worst
  outcome: nothing bad happens, but there's also no signal in the evidence
  trail that anything was attempted.

## Decision

Prompt-level defenses reduce injection success. They cannot be proven to
eliminate it, and this project doesn't claim otherwise — the four payloads
tested here are the four an implementer already thought of. A defense that
passes every test you wrote yourself says nothing about the attack you
didn't think to write, and there is no way to close that gap from inside
the prompt.

So the actual security boundary is architectural, not linguistic, and it
was already built into this project before it was framed as a security
decision:

- **Least-privilege IAM per tool** (`infra/pipeline_stack.py`) means even a
  successful injection is capped by what that specific Lambda's role can
  reach. The write role can tag a bucket. It cannot do anything else,
  regardless of what the model is convinced to want.
- **The human approval gate** (Phase 5) means a successful injection that
  gets the model to *propose* the write tool still has to get a human to
  approve it before anything executes. The prompt failing doesn't matter,
  because nothing happens without a person in the loop.
- **The immutable evidence trail** (Phase 4, S3 Object Lock) means that
  even in a worst case, the full record of what was proposed, by whom, and
  when is preserved and can't be quietly edited away afterward.

None of these three depend on the model behaving correctly. That's the
actual point: prompt engineering is the first, weakest line of defense —
it can be argued with, reworded around, or simply missed for a case nobody
tested. IAM scope and a human approval gate can't be talked into anything;
they don't parse language at all.

## A related, separate finding worth recording here

During real use (not the injection test itself), the agent produced a
written summary that stated `BlockPublicAcls=True, IgnorePublicAcls=True`
for a bucket independently confirmed, repeatedly, across CLI checks,
`agent/loop.py`, the deployed pipeline, and the eval suite, to actually be
`False, False`. The underlying tool call was correct — this was the
model's own narrative synthesis drifting from the source data it was
given, not a tool returning bad data (contrast with the `check_iam_role_scope`
bug in Phase 3, which *was* a tool problem).

This is a different failure mode from prompt injection, but it reinforces
the same conclusion from a different angle: free-text model output,
however well-reasoned it reads, is not itself a source of truth. It has to
be checked against the actual tool output or actual account state before
being trusted — which is exactly why Phase 7's evals grade on trajectory
(which tools were called) and a scoped judge call, not on the prose alone,
and why every finding in this project was independently confirmed by hand
before being trusted.

## Consequences

- Security here means "the model's mistakes and manipulations are capped
  by architecture," not "the model can be made reliable." That's a bet
  worth stating explicitly, not implying.
- Any new write-capable tool added to this project needs its own scoped
  IAM role and its own approval-gate branch by default — the pattern from
  `flag_finding_for_remediation` is the template, not a one-off.
- Any report the agent writes — including the finding text itself, not
  just the trigger for a write action — should be treated as a draft to
  verify against structured tool output, not a final answer, especially
  before it's used to justify a real remediation action.
- Out of scope, deliberately, for this version: this agent has no RAG
  component, so injection via retrieved document content is not a live
  threat surface here and isn't covered above. If a future version adds
  retrieval, that's new attack surface requiring its own analysis, not an
  extension of this one.
