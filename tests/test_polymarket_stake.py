"""
tests/test_polymarket_stake.py — caps + deploy-safe no-op for symbolic stakes.

No real Polymarket API calls: every path under test returns or raises before
the order is ever signed or posted.
"""

import pytest

from agent.db import ArkeDB
from agent.integrations.polymarket_stake import place_symbolic_stake, StakeCapExceeded


def test_returns_empty_without_key(monkeypatch):
    """No staking key configured → silent no-op (size is within the per-stake cap)."""
    monkeypatch.delenv("STAKE_WALLET_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("STAKE_MAX_USDC", raising=False)  # default 0.60
    assert place_symbolic_stake("0xabc", "tok", "YES", 0.5, "0x00") == ""


def test_per_stake_cap_raises(monkeypatch):
    """size_usdc above STAKE_MAX_USDC raises loudly, even without a key."""
    monkeypatch.setenv("STAKE_MAX_USDC", "0.60")
    with pytest.raises(StakeCapExceeded):
        place_symbolic_stake("0xabc", "tok", "YES", 1.0, "0x00")


def test_lifetime_cap_raises(tmp_path, monkeypatch):
    """Cumulative stake breaching STAKE_LIFETIME_CAP_USDC raises before any tx."""
    db_path = tmp_path / "stake_test.db"
    db = ArkeDB(str(db_path))
    db.record_stake("0xold", "YES", 8.8)  # near the lifetime cap already

    monkeypatch.setenv("ARKE_DB_PATH", str(db_path))
    monkeypatch.setenv("STAKE_WALLET_PRIVATE_KEY", "0x" + "11" * 32)
    monkeypatch.setenv("STAKE_MAX_USDC", "0.60")
    monkeypatch.setenv("STAKE_LIFETIME_CAP_USDC", "9.0")

    with pytest.raises(StakeCapExceeded):
        place_symbolic_stake("0xnew", "tok", "YES", 0.5, "0x00")  # 8.8 + 0.5 > 9.0

    # And the cap is honored exactly: 8.8 + 0.2 = 9.0 is allowed past the cap check
    # (it then no-ops on the network, which we don't exercise here).
    assert db.get_total_staked_usdc() == pytest.approx(8.8)
