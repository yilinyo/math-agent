from types import SimpleNamespace
from unittest.mock import patch

import pytest

from reasoning_agent.strategy_retrieval import preferred_device


@pytest.mark.parametrize(
    ("cuda", "mps", "expected"),
    [(True, False, "cuda"), (False, True, "mps"), (False, False, "cpu")],
)
def test_preferred_device(cuda, mps, expected):
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
    )
    with patch.dict("sys.modules", {"torch": torch}):
        assert preferred_device() == expected
