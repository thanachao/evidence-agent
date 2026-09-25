# ADR 0002 — Pin the model version

Status: accepted (Phase 1)

## Context
An unpinned model alias means agent behaviour can change with no code change
on our side. This is a dependency-versioning problem with worse properties
than usual: the output distribution shifts, not the API surface.

## Decision
Pin MODEL explicitly in agent/loop.py. Treat a version bump as a change that
must pass the Phase 7 eval suite before merging.

## Consequences
Requires the eval suite to exist before upgrades are safe — which is part of
why Phase 7 is not optional.
