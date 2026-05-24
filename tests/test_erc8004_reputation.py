"""
tests/test_erc8004_reputation.py — ERC-8004 Reputation Registry writer.

web3 is fully mocked: no key → no-op; RPC failure → None (never raises); a
configured key drives giveFeedback() with the right agent id and value.
"""

import web3 as web3_mod

import agent.integrations.erc8004_reputation as rep


def _make_fake_web3(captured, *, fail=False, status=1):
    class FakeOnion:
        def inject(self, *a, **k):
            return None

    class FakeCall:
        def build_transaction(self, tx):
            captured["tx"] = tx
            return dict(tx, data="0x")

    class FakeFns:
        def giveFeedback(self, agent_id, value, decimals, tag1, tag2):
            captured["give"] = (agent_id, value, decimals, tag1, tag2)
            return FakeCall()

    class FakeContract:
        functions = FakeFns()

    class FakeAcct:
        address = "0x000000000000000000000000000000000000dEaD"

    class FakeAccount:
        def from_key(self, key):
            return FakeAcct()

        def sign_transaction(self, tx, key):
            class S:
                raw_transaction = b"\x01\x02"
            return S()

    class FakeHash:
        def hex(self):
            return "0xfeed"

    class FakeEth:
        account = FakeAccount()
        gas_price = 1_000_000

        def get_transaction_count(self, addr):
            return 0

        def contract(self, address, abi):
            captured["abi"] = abi
            captured["address"] = address
            return FakeContract()

        def send_raw_transaction(self, raw):
            return FakeHash()

        def wait_for_transaction_receipt(self, h, timeout):
            r = type("R", (), {})()
            r.status = status
            return r

    class FakeWeb3:
        def __init__(self, provider):
            if fail:
                raise RuntimeError("rpc down")
            self.eth = FakeEth()
            self.middleware_onion = FakeOnion()

        @staticmethod
        def HTTPProvider(url):
            return object()

        @staticmethod
        def to_checksum_address(a):
            return a

        @staticmethod
        def keccak(text=None):
            return b"\x11" * 32

    return FakeWeb3


def test_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("ARC_PRIVATE_KEY", raising=False)
    assert rep.write_reputation(5100, 75) is None


def test_returns_none_when_rpc_fails(monkeypatch):
    monkeypatch.setenv("ARC_PRIVATE_KEY", "0x" + "11" * 32)
    captured = {}
    monkeypatch.setattr(web3_mod, "Web3", _make_fake_web3(captured, fail=True))
    # Fails open: returns None, never raises.
    assert rep.write_reputation(5100, 75) is None


def test_calls_givefeedback_with_agent_id(monkeypatch):
    monkeypatch.setenv("ARC_PRIVATE_KEY", "0x" + "11" * 32)
    captured = {}
    monkeypatch.setattr(web3_mod, "Web3", _make_fake_web3(captured))
    tx = rep.write_reputation(5100, 75)
    assert tx == "0xfeed"
    agent_id, value, decimals, _tag1, _tag2 = captured["give"]
    assert agent_id == 20360
    assert value == 5100
    assert decimals == 0


def test_reverted_tx_returns_none(monkeypatch):
    monkeypatch.setenv("ARC_PRIVATE_KEY", "0x" + "11" * 32)
    captured = {}
    monkeypatch.setattr(web3_mod, "Web3", _make_fake_web3(captured, status=0))
    assert rep.write_reputation(5100, 75) is None
