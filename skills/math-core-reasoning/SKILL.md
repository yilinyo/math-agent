---
name: math-core-reasoning
description: Plan, execute, and present rigorous olympiad-style mathematical reasoning across domains. Use after routing a proof, classification, construction, optimization, or derivation problem; use to coordinate domain-specific strategies, control case splits, and turn exploratory work into a self-contained final solution.
---

# Math Core Reasoning

Maintain a separation between discovery and proof. Use domain skills for specialized moves and this workflow to control the whole solve.

## Build the proof state

1. Restate the target with exact quantifiers and domains.
2. Extract hypotheses, definitions, legal transformations, and degenerate cases.
3. Normalize notation and introduce only variables that reduce ambiguity.
4. Record a short strategy ledger using [references/reasoning-protocol.md](references/reasoning-protocol.md).
5. Select one primary line and at most one backup line. State the bridge lemma each line must establish.

## Execute deliberately

- Derive consequences in small justified steps.
- Label conjectures as conjectures until proved.
- Test small or boundary cases to falsify ideas, not to replace proof.
- Track every condition introduced by division, roots, logarithms, inversion, or coordinate normalization.
- When a line stalls, diagnose the missing bridge before switching methods.
- Preserve useful facts from failed attempts, but discard notation that no longer serves the proof.

## Consolidate the solution

1. Choose the shortest complete argument, not the shortest-looking one.
2. Order lemmas so every statement uses only established facts.
3. Close all cases and verify equality or existence conditions.
4. Remove exploratory branches, unsupported claims, and irrelevant computation.
5. Ensure the final response independently contains the conclusion and the reasoning required to grade it.
6. Invoke `math-proof-verifier` on derivation-heavy or proof answers.

## Stop conditions

Do not declare completion when only a pattern, numerical check, necessary condition, or unproved “well-known” claim has been found. Stop only after the original target follows for the full stated domain.
