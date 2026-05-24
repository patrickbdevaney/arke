"""
agent/provenance.py — reasoning provenance bundle.

For every call, Arke assembles a JSON bundle of the inputs and outputs that
produced its probability estimate (signal report, forecast tweet, source
citations) and hashes it with sha256. The bundle is written to
`dashboard/public/traces/{condition_id[:16]}.json`, served at
`https://arke.live/traces/{condition_id[:16]}.json`, and its hash is stored in
the DB as `sha256:<hex>`.

Storage backend honesty: the hash is prefixed `sha256:` (not `ipfs:`) because
the file is pinned to the site, not to IPFS. The roadmap upgrades this to a
real IPFS pin; the sha256 remains the verifiable content hash regardless of the
storage backend, and a future contract revision can carry the CID on-struct.

`assemble_bundle` is pure and deterministic: identical inputs (including
`generated_at`) yield byte-identical JSON and therefore the same sha256.
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path

# dashboard/public/traces relative to the repo root (agent/ -> repo root)
DEFAULT_TRACES_DIR = (
    Path(__file__).resolve().parent.parent / "dashboard" / "public" / "traces"
)


def assemble_bundle(
    condition_id: str,
    arke_pct: int,
    market_pct: int,
    question: str,
    council_signal: str,
    council_forecast: str,
    citations: list,
    generated_at: str = None,
    raw_arke_pct: int = None,
    calibrated_arke_pct: int = None,
) -> tuple[dict, str, str]:
    """Assemble the provenance bundle.

    Returns (bundle, bundle_json, sha256_hex). Pass `generated_at` to make the
    output deterministic (otherwise it is stamped with the current UTC time).

    `raw_arke_pct` / `calibrated_arke_pct` are only added to the bundle when
    not None (i.e. when calibration ran), so bundles from the default,
    calibration-off path hash exactly as before — the function stays pure and
    deterministic in its inputs.
    """
    if generated_at is None:
        generated_at = datetime.utcnow().isoformat() + "Z"

    bundle = {
        "condition_id": condition_id,
        "arke_pct": arke_pct,
        "market_pct": market_pct,
        "question": question,
        "council_signal": council_signal,
        "council_forecast": council_forecast,
        "citations": citations,
        "generated_at": generated_at,
    }
    if raw_arke_pct is not None:
        bundle["raw_arke_pct"] = raw_arke_pct
    if calibrated_arke_pct is not None:
        bundle["calibrated_arke_pct"] = calibrated_arke_pct
    bundle_json = json.dumps(bundle, sort_keys=True)
    bundle_sha256 = hashlib.sha256(bundle_json.encode()).hexdigest()
    return bundle, bundle_json, bundle_sha256


def write_trace(bundle: dict, condition_id: str, traces_dir: Path = None) -> Path:
    """Write the bundle to {traces_dir}/{condition_id[:16]}.json. Returns the path."""
    traces_dir = Path(traces_dir) if traces_dir else DEFAULT_TRACES_DIR
    traces_dir.mkdir(parents=True, exist_ok=True)
    path = traces_dir / f"{condition_id[:16]}.json"
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True))
    return path
