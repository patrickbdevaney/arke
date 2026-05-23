"""
tests/test_provenance.py — provenance bundle determinism, file write, and the
reasoning_cid DB round-trip. No network, temp DB only.
"""

import json

from agent.provenance import assemble_bundle, write_trace
from agent.db import ArkeDB


def _inputs():
    return dict(
        condition_id="0xabc123def4567890aabbcc",
        arke_pct=34,
        market_pct=51,
        question="Will X happen?",
        council_signal="signal report text",
        council_forecast="Arke estimates 34% — base rate.",
        citations=[{
            "claim": "headline",
            "source_url": "",
            "retrieved_at": "2026-05-19T00:00:00+00:00",
            "content_sha256": "abc",
        }],
        generated_at="2026-05-19T14:23:00Z",
    )


def test_bundle_is_deterministic():
    _, json1, sha1 = assemble_bundle(**_inputs())
    _, json2, sha2 = assemble_bundle(**_inputs())
    assert json1 == json2
    assert sha1 == sha2

    # Any change to the inputs changes the hash.
    changed = {**_inputs(), "arke_pct": 35}
    _, _, sha3 = assemble_bundle(**changed)
    assert sha3 != sha1


def test_trace_written_to_correct_path(tmp_path):
    cid = _inputs()["condition_id"]
    bundle, _, _ = assemble_bundle(**_inputs())
    path = write_trace(bundle, cid, traces_dir=tmp_path)

    assert path == tmp_path / f"{cid[:16]}.json"
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["condition_id"] == cid
    assert loaded["arke_pct"] == 34


def test_reasoning_cid_roundtrips_through_db(tmp_path):
    db = ArkeDB(str(tmp_path / "prov.db"))
    market = {
        "conditionId": "0xseedprov",
        "question": "Will Y happen?",
        "slug": "y",
        "events": [{"slug": "y"}],
        "lastTradePrice": 0.40,
    }
    db.record_post(market, tweet_text="take\nBet: x", market_url="x",
                   arke_probability_pct=40)

    db.set_reasoning_cid("0xseedprov", "sha256:deadbeefcafe")

    rows = [r for r in db.get_track_record() if r["condition_id"] == "0xseedprov"]
    assert rows, "seeded row not found in track record"
    assert rows[0]["reasoning_cid"] == "sha256:deadbeefcafe"
