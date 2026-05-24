"""
tests/test_oracle_unit.py — unit tests for the onchain oracle integration.

No chain, no env vars required. Every web3 interaction is mocked. The critical
invariant under test: log_prediction_onchain and resolve_prediction_onchain
derive the SAME bytes32 from a condition_id, so a resolution keys the exact
contract slot the prediction wrote.
"""

from unittest.mock import patch, MagicMock

from agent.integrations.oracle import (
    log_prediction_onchain,
    resolve_prediction_onchain,
    _get_web3_and_contract,
    _condition_id_to_bytes32,
)

_DUMMY_KEY = "0x" + "11" * 32


def test_log_returns_empty_without_private_key(monkeypatch):
    monkeypatch.delenv("ARC_PRIVATE_KEY", raising=False)
    assert log_prediction_onchain("0xabc123", "question?", 50, 60) == ""


def test_resolve_returns_empty_when_contract_unset(monkeypatch):
    # Private key present but no contract → _get_web3_and_contract bails early.
    monkeypatch.setenv("ARC_PRIVATE_KEY", _DUMMY_KEY)
    monkeypatch.delenv("ORACLE_CONTRACT_ADDRESS", raising=False)
    assert resolve_prediction_onchain("0xabc123", True) == ""


def test_get_web3_and_contract_none_without_address(monkeypatch):
    monkeypatch.delenv("ORACLE_CONTRACT_ADDRESS", raising=False)
    assert _get_web3_and_contract() == (None, None)


def test_condition_id_padding_is_deterministic_and_32_bytes():
    a = _condition_id_to_bytes32("0xabcdef")
    b = _condition_id_to_bytes32("0xabcdef")
    assert a == b
    assert len(a) == 32
    # A bare (no-0x) id pads to the same width.
    assert len(_condition_id_to_bytes32("abcdef")) == 32


def _fake_web3():
    """A MagicMock w3 whose signing path yields a tx hash with .hex()."""
    w3 = MagicMock()
    acct = MagicMock()
    acct.address = "0x0000000000000000000000000000000000000001"
    w3.eth.account.from_key.return_value = acct
    w3.eth.get_transaction_count.return_value = 0
    w3.eth.gas_price = 1

    signed = MagicMock()
    signed.raw_transaction = b"\x01\x02"
    acct.sign_transaction.return_value = signed

    txh = MagicMock()
    txh.hex.return_value = "0xdeadbeef"
    w3.eth.send_raw_transaction.return_value = txh

    # _send_and_confirm waits for the receipt and requires status == 1.
    receipt = MagicMock()
    receipt.status = 1
    w3.eth.wait_for_transaction_receipt.return_value = receipt
    return w3


def test_log_and_resolve_key_the_same_slot(monkeypatch):
    """The bytes32 passed to logPrediction and resolvePrediction must match."""
    monkeypatch.setenv("ARC_PRIVATE_KEY", _DUMMY_KEY)
    w3 = _fake_web3()
    contract = MagicMock()

    cid = "0xfeedface1234"
    with patch(
        "agent.integrations.oracle._get_web3_and_contract",
        return_value=(w3, contract),
    ):
        log_tx = log_prediction_onchain(cid, "q", 50, 60)
        resolve_tx = resolve_prediction_onchain(cid, True)

    assert log_tx == "0xdeadbeef"
    assert resolve_tx == "0xdeadbeef"

    log_bytes32 = contract.functions.logPrediction.call_args.args[0]
    resolve_bytes32 = contract.functions.resolvePrediction.call_args.args[0]
    assert log_bytes32 == resolve_bytes32
    assert len(log_bytes32) == 32
