## Why

Staged runtime uses the full external 1200-second deadline internally, leaving no time for call cleanup, result formatting, and judge transport. Local runs already exceed the limit slightly.

## What Changes

- Reserve a configurable 300-second external-deadline headroom before creating the staged internal deadline.
- Keep finalization within the reduced internal budget and expose the effective budget in trace data.

## Capabilities

### New Capabilities
- `staged-deadline-headroom`: Ensure staged solve completion has time to return a serializable result before the platform deadline.

### Modified Capabilities
- 无。

## Impact

- Affects staged runtime timing configuration and tests only; no platform API or model protocol changes.
