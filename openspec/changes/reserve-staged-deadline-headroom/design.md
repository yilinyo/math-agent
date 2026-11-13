## Context

See proposal.md. The runtime currently sets its own deadline to the external 1200-second maximum, while model-call cleanup can add up to two seconds.

## Goals / Non-Goals

**Goals:** reserve 300 seconds by default and preserve existing staged phase behavior within the reduced budget.

**Non-Goals:** changing model prompts, repair count, or platform-facing APIs.

## Decisions

Add `custom2_platform_deadline_headroom_seconds` with default 300. Compute `effective_total_budget = max(0, configured_total_budget - min(headroom, configured_total_budget))`, after retaining the existing 1200-second cap. The state deadline uses this effective budget; trace records both values. This is preferable to relying on per-call grace or reducing individual stage timeouts because it protects all paths uniformly.

## Risks / Trade-offs

- [One minute less reasoning time] → protects delivery of already-generated answers and avoids hard-kill invalid records.
- [Very small custom budget] → clamp headroom so the effective budget never becomes negative.

## Migration Plan

1. Add configuration and effective-budget calculation.
2. Add unit tests for defaults and clamping.
3. Run staged configuration and runtime tests.
