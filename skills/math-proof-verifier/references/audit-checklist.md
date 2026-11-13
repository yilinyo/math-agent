# Proof audit checklist

## Universal checks

- Are variables quantified and in the stated domains?
- Were zero denominators, signs, parity, and branch choices handled?
- Did an implication accidentally become an equivalence?
- Were squaring, taking roots, logarithms, or inverses made reversible?
- Does induction prove the base case and the exact inductive transition?
- Are all cases mutually sufficient and collectively exhaustive?
- Does a construction prove both existence and every required property?
- Are equality cases compatible across every inequality in the chain?

## Algebra and inequalities

- Check coefficient comparisons require a polynomial identity, not equality at a few points.
- Track signs before multiplication or division in inequalities.
- Check convexity/concavity domain and direction.
- Verify substitutions are surjective onto the claimed domain or account for excluded values.

## Number theory

- Check coprimality before Euclid's lemma, inverses, CRT, or multiplicativity.
- Distinguish congruence from equality and local solvability from global solvability.
- Check valuations prime by prime and handle the zero case separately.
- Verify descent reaches a strictly smaller positive object.

## Combinatorics and graphs

- Define what is counted and show each object has the claimed multiplicity.
- Check recurrences' initial conditions and state partition.
- Verify an invariant is truly preserved under every legal move.
- Check graph assumptions: simple/multigraph, directed/undirected, finite, connected.

## Geometry

- Check directed versus undirected angles and segment signs.
- Verify cyclicity, tangency, similarity, and collinearity criteria in both direction and order.
- Handle parallel lines, coincident points, zero-length segments, and points at infinity when relevant.
- In coordinate proofs, prove the normalization is without loss of generality and denominators are nonzero.
