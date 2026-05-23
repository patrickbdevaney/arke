"""
tests/test_erc8004_unit.py — register_erc8004 control flow.

No chain: the registry-unset path prints instructions, and the success path is
exercised with `register` mocked. The agent-id file write is checked against a
temp path.
"""

from unittest.mock import patch

import scripts.register_erc8004 as reg


def test_exits_zero_with_instructions_without_registry(monkeypatch, capsys):
    monkeypatch.delenv("ERC8004_REGISTRY_ADDRESS", raising=False)
    rc = reg.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ERC8004_REGISTRY_ADDRESS is not set" in out
    assert "register_erc8004.py" in out


def test_writes_agent_file_on_success(tmp_path, monkeypatch):
    target = tmp_path / "erc8004_agent.txt"
    monkeypatch.setattr(reg, "AGENT_FILE", target)

    with patch.object(reg, "register", return_value=(42, "0xdeadbeef")) as mock_reg:
        rc = reg.main(["--registry", "0xRegistryAddress"])

    assert rc == 0
    mock_reg.assert_called_once_with("0xRegistryAddress")
    assert target.read_text() == "agent_id=42\ntx=0xdeadbeef\n"
