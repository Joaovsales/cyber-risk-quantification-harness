"""The ``--n`` and ``--seed`` bounds that ``rqh run confirm`` and ``rqh finalize`` share.

An out-of-range argument is a usage error (exit 2, issue at ``argv.<flag>``) from every
command, checked before anything is read or written. The bounds come from the run schema,
the one source ``run.yaml`` is validated against.
"""

from __future__ import annotations

from rqharness.outcomes import Usage, issue
from rqharness.schemas import load_schema

_BOUNDS = load_schema("run")["properties"]
MIN_N, MAX_N = _BOUNDS["n"]["minimum"], _BOUNDS["n"]["maximum"]
MIN_SEED, MAX_SEED = _BOUNDS["seed"]["minimum"], _BOUNDS["seed"]["maximum"]
assert (MIN_SEED, MAX_SEED) == (0, 2**63 - 1), "the --seed message below names these bounds"


def require_in_range(n: int | None, seed: int | None) -> None:
    """Raise :class:`Usage` for a given ``n`` or ``seed`` outside the run schema's bounds; ``None`` is not given."""
    if n is not None and not MIN_N <= n <= MAX_N:
        raise Usage([issue("argv.n", "range", f"--n must be between {MIN_N} and {MAX_N:,}")])
    if seed is not None and not MIN_SEED <= seed <= MAX_SEED:
        raise Usage([issue("argv.seed", "range", "--seed must be between 0 and 2**63 - 1")])
