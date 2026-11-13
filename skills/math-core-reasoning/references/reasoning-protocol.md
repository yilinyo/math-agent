# Reasoning protocol

## Strategy ledger

Keep this compact working record:

```text
target:
domain and quantifiers:
normalized facts:
structural signals:
primary strategy:
bridge lemma:
backup strategy:
introduced conditions:
open cases:
```

## Representation choice

Prefer a representation when it makes the target or a decisive invariant simpler:

- Algebraic normalization: expose symmetry, homogeneity, factors, or recurrence.
- Modular/local view: eliminate impossible integer cases.
- Graph model: turn pairwise constraints into degrees, paths, cuts, or matchings.
- Geometric transformation: preserve the relevant angles, ratios, or incidence.
- Coordinates/vectors/complex numbers: use when a small parameter set controls the figure.

Reject a representation when it adds more free variables than relations, hides sign/domain conditions, or makes the desired statement less visible.

## Failure diagnostics

| Symptom | Diagnosis | Response |
|---|---|---|
| Algebra expands without structure | wrong normalization | search for symmetry, invariants, or a better variable |
| Many congruences but no finite conclusion | only necessary conditions | add bounds, valuation, factorization, or descent |
| Geometry chase accumulates angles | missing configuration lemma | seek cyclicity, similarity, homothety, or transformation |
| Case tree grows rapidly | weak partition | split by a structural invariant or extremal object |
| Equality conditions cannot be met | bound is non-sharp or direction is wrong | revise the inequality chain |

## Final proof standard

- State the result explicitly.
- Justify each nontrivial implication.
- Cover every case and endpoint.
- Verify constructed objects satisfy all requirements.
- Distinguish “if,” “only if,” and “if and only if.”
- Keep computation exact unless approximation is part of the statement.
