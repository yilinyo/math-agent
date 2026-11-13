---
name: math-proof-verifier
description: Audit proposed olympiad solutions and mathematical proofs for logical gaps, domain errors, missing cases, invalid transformations, unmet equality conditions, and mismatch with the original claim. Use after drafting a proof, when comparing candidate solutions, or when a derivation appears plausible but uncertain. Return a verdict and minimal repairs rather than silently rewriting an invalid proof.
---

# Math Proof Verifier

Verify the proof against the original statement, not against the author's intended argument.

## Audit in passes

1. **Claim alignment:** Restate the required quantifiers, domain, conclusion, and proof direction.
2. **Dependency audit:** Number the substantive steps and identify the facts each step uses.
3. **Local validity:** Check every implication, equivalence, lemma invocation, computation, and construction.
4. **Global completeness:** Check case exhaustion, existence, uniqueness, endpoints, and equality cases.
5. **Adversarial check:** Try boundary, degenerate, and small counterexamples against the weakest step.
6. **Presentation check:** Confirm the final conclusion is explicit and independently gradeable.

Read [references/audit-checklist.md](references/audit-checklist.md) for domain-specific failure patterns.

## Return a verdict

Use one of:

- `VALID`: complete as written, aside from optional exposition improvements.
- `REPAIRABLE`: central approach works, but listed local gaps must be repaired.
- `INVALID`: a central inference fails or the approach cannot establish the claim.
- `INCOMPLETE`: no false step is identified, but required cases or conclusions remain open.

For every issue, report the exact claim, why it is unsupported or false, and the smallest acceptable repair. Never upgrade a proof because the final answer happens to be correct.

## Verification constraints

- Do not accept a theorem name without checking its hypotheses.
- Do not use numerical sampling as proof.
- Do not treat necessary conditions as sufficient.
- Do not repair a gap by assuming the desired conclusion.
- If a repair materially changes the approach, mark the original `INVALID`, then offer the alternative separately.
