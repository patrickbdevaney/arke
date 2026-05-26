# ARKE — Component Verification Proof

**Rigorous, evidence-based proof of verified functionality across all components.**
Every claim below is backed by a command that hit **real infrastructure** (live VPS,
live feed, live Arc testnet RPC, live Vercel dashboard, live X API) — no mocks, no
stubs. Each section states the verification method, the exact command, the observed
output, and a verdict.

| | |
|---|---|
| **Date (UTC)** | 2026-05-26 |
| **Verified commit** | `821ebe0` — *fix(feed): 402 body returns the x402-compliant challenge* |
| **Remote `main`** | `821ebe0` (matches local) |
| **VPS `HEAD`** | `821ebe0` (matches) |
| **Production VPS** | `root@<VPS_IP>` — actual host in `OPERATIONS.local.md` (redacted: public repo) |
| **Live feed** | `http://feed.arke.live:8402` |
| **Live dashboard** | `https://arke.live` |
| **Oracle (immutable)** | `0x767D0eD2850D57C4EF969976088Be44A5Adcfa07` (Arc testnet, chainId 5042002) |
| **Procedure source** | `ARKE_LIVE_DEPLOY_VERIFY.MD` (11 gates) |

> **Security note.** This is a public repository. The VPS IP and SSH target are
> deliberately redacted to `<VPS_IP>`; the real values live only in the gitignored
> `OPERATIONS.local.md`. All other identifiers in this document (feed/dashboard URLs,
> oracle/wallet addresses, the published tweet URL, on-chain tx hashes, block heights)
> are already public on-chain or on the open web.

---

## Executive summary

**RESULT: PASS** — all 11 verification gates green against live infrastructure, with
three caveats documented in full (§5, §6, §8). Two of the caveats are *corrections to
the verification script itself* (it referenced an API shape and a function name that do
not exist in the code); one is a *real side effect* (the push auto-deployed and the
scheduler posted a resolution tweet).

| # | Component | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Test suite (unit/integration) | ✅ | §1 — 119 passed |
| 2 | x402 feed server (`feed_server.py`) | ✅ | §2 — calibration 200, track-record 402 |
| 3 | Payment layer / x402 challenge (`payments.py`) | ✅ | §3, §5 — 402 advertises `exact` + Gateway scheme |
| 4 | MCP server (8 tools) | ✅ | §4 — 8 tools registered on VPS |
| 5 | Oracle on-chain reads (Arc RPC) | ✅ | §6 — 23 predictions / 4 resolved @ block 44,055,512 |
| 6 | Resolver (scoring + on-chain write + post) | ✅ | §7 — resolved 1 market, wrote tx, posted |
| 7 | Council (signal/forecaster/adversary/filter) | ✅ | §8 — full loop ran, ensemble + filter scored |
| 8 | Posting path (X API v2 / tweepy) | ✅ | §7 — live tweet posted; §8 — dry run suppressed post |
| 9 | Provenance (sha256 reasoning bundle) | ✅ | §8 — bundle written, `reasoning_cid` emitted |
| 10 | Calibration endpoint + data | ✅ | §2 — scores dict + 10 reliability bins |
| 11 | Dashboard (Next.js on Vercel) | ✅ | §9 — all 5 routes 200 |
| 12 | Deploy pipeline (GitHub Actions → VPS) | ✅ | §6 — CI pulled + restarted; **see live-post caveat** |
| — | ERC-8004 reputation `giveFeedback` | ⚠️ | §7 — on-chain tx **reverted** (known issue) |
| — | Real paid nanopayment settlement (e2e) | ◻️ not re-run | §10 — verified in a prior session; needs funded buyer |

Legend: ✅ verified live this run · ⚠️ verified-with-issue · ◻️ out of scope this run

---

## §1 — Test suite (local)

**Method.** Run the full pytest suite in the project venv (`arke_env/`).

```bash
arke_env/bin/python -m pytest tests/ -q
```

**Evidence.**
```
118 passed, 5 warnings in 2.09s     # baseline, before the fix
...
119 passed, 5 warnings in 2.24s     # after adding the 402-challenge regression test
```

**Verdict.** ✅ 119/119 pass (baseline 118 + 1 new regression test added with the
feed fix — `test_402_body_advertises_x402_accepts_challenge`).

---

## §2 — x402 feed server (live)

**Method.** Hit the live feed (not localhost). Free endpoint must 200 with real data;
the paid endpoint must 402 without payment.

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://feed.arke.live:8402/v1/arke/calibration
curl -s http://feed.arke.live:8402/v1/arke/calibration | python3 -c \
  "import sys,json;d=json.load(sys.stdin);print('scores:',d['scores']);print('bins:',len(d['reliability_bins']))"
curl -s -o /dev/null -w "%{http_code}\n" http://feed.arke.live:8402/v1/arke/track-record
```

**Evidence.**
```
# calibration
200
scores: {'directional_pct': 40, 'skill_bps': -2260, 'brier': 0.3065, 'n_resolved': 5,
         'by_category': {'other': {'n': 5, 'brier': 0.3065}}}
bins: 10

# track-record (no payment)
402
```

> A pre-fix observation caught a real issue: `/v1/arke/calibration` initially returned
> **404** because the running `arke-feed` process predated the calibration route. A
> `systemctl restart arke-feed` (the sanctioned restart) reloaded the current code and
> the route returned **200**. This is why the restart gate exists.

**Verdict.** ✅ Free endpoint 200 with real scores + 10 reliability bins; paid endpoint
correctly demands payment (402).

---

## §3 — Payment layer & the x402 challenge (live)

**Method.** Inspect the **full 402 body** from the live feed and confirm it is a
spec-compliant x402 v2 challenge advertising the payment scheme.

```bash
curl -s http://feed.arke.live:8402/v1/arke/track-record | python3 -c "
import sys,json; d=json.load(sys.stdin)
print('keys:', list(d.keys()))
print('x402Version:', d.get('x402Version'))
print('schemes:', [a.get('scheme') for a in d.get('accepts',[])])
print('payTo:', d.get('payTo'), '| gateway:', d.get('gateway'))
print('extra.name:', d['accepts'][0]['extra']['name'],
      '| verifyingContract:', d['accepts'][0]['extra']['verifyingContract'])
print('recipient (legacy):', d.get('recipient'))"
```

**Evidence.**
```
keys: ['x402Version', 'error', 'price', 'currency', 'network', 'payTo', 'gateway', 'accepts', 'recipient']
x402Version: 2
schemes: ['exact']
payTo: 0xa515451E34b3c61965A312Bd38ebE3a65c6EbBBa        # Circle Gateway seller wallet
gateway: True
extra.name: GatewayWalletBatched | verifyingContract: 0x0077777d7eba4688bdef3e311b846f25870a19b9
recipient (legacy): 0x35a894fd32f05F5B7f00D8940718f7aDb4D2D8fE   # legacy field preserved
```

**Verdict.** ✅ The live 402 is a valid x402 v2 challenge. Because Circle Gateway is
configured on the VPS, the requirements carry the **`GatewayWalletBatched`** scheme
metadata (verifyingContract `0x0077…19b9`, Circle's published GatewayWallet) — so the
same 402 doubles as a Circle Nanopayments challenge, x402-compatible. The legacy
`recipient` field and `X-*` headers are preserved for backward compatibility. The real
x402 scheme name is **`exact`** (see §5).

---

## §4 — MCP server (live, on VPS)

**Method.** On the VPS, import the FastMCP server and the module-level DB accessors,
count registered tools.

```bash
# (run on VPS, cwd /opt/arke, timeout-guarded against the stdio server blocking)
timeout 25 venv/bin/python -c "
from agent.mcp_server import mcp
from agent.db import get_dual_scores, get_latest_prediction
print('dual scores:', get_dual_scores())
print('latest prediction exists:', bool(get_latest_prediction()))
print('MCP tools registered:', len(mcp._tool_manager._tools))"
```

**Evidence.**
```
dual scores: {'directional_pct': 33, 'skill_bps': -6233, 'brier': 0.4058, 'n_resolved': 6,
              'by_category': {'other': {'n': 5, 'brier': 0.3065},
                              'geopolitics': {'n': 1, 'brier': 0.9025}}}
latest prediction exists: True
MCP tools registered: 8
```

Also confirmed the `arke-mcp` console entry point installs via `pip install -e .`:
```
-rwxr-xr-x 1 root root 173 ... venv/bin/arke-mcp
```

**Verdict.** ✅ MCP server imports cleanly, **8 tools** registered (5 free + 3 paid),
console entry point present, DB accessors return live data.

---

## §5 — Feed-402 fix (the one code change) — before / after

**Defect found.** `feed_server._payment_gate` captured the challenge from
`payments.verify_payment()` into a discarded variable and returned a hand-rolled legacy
body, so the live 402 advertised **no payment scheme** — a real x402/Nanopayments buyer
had no machine-readable way to discover how to pay.

**Before (live, pre-fix):**
```
keys: ['error', 'price', 'currency', 'recipient']
schemes in accepts: []      # no `accepts` array at all
```

**Fix (`821ebe0`).** Return the x402 challenge `verify_payment()` already builds, while
preserving the legacy `recipient` field + `X-*` headers:
```python
ok, challenge = verify_payment(proof, price, resource=resource)
if ok:
    return None
body = dict(challenge) if isinstance(challenge, dict) else {}
body.setdefault("error", "payment required")
body.setdefault("price", str(price)); body.setdefault("currency", "USDC")
body["recipient"] = receive
return JSONResponse(status_code=402, content=body, headers={...})
```

**After (live, post-fix):** see §3 — `accepts:[{scheme:'exact', ...}]`, `x402Version:2`.

**Script correction.** `ARKE_LIVE_DEPLOY_VERIFY.MD` Step 6 asserts the scheme is
`'x402'` or `'nanopayments-gateway'`. That is **incorrect** — the x402 v2 scheme name is
`'exact'`, and the test suite explicitly asserts `"nanopayments-gateway" not in schemes`
(`tests/test_payments.py`). Verification was performed against the correct scheme name.

**Verdict.** ✅ Fixed, tested (`+1` regression test, §1), pushed, and confirmed live (§3).

---

## §6 — Oracle on-chain reads (live Arc testnet RPC)

**Method.** Connect to Arc testnet, read the immutable oracle's view functions.
*(The script's `get_prediction_count` import does not exist; the real contract view is
`getPredictionCount()`, read via `_get_web3_and_contract()`. `.env` is loaded as the app
does. The oracle was only **read** — never modified.)*

```bash
# (run on VPS, cwd /opt/arke)
timeout 45 venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv()
from agent.integrations.oracle import _get_web3_and_contract
w3, c = _get_web3_and_contract()
print('RPC connected:', w3.is_connected(), '| block:', w3.eth.block_number)
print('prediction count:', c.functions.getPredictionCount().call())
print('totalResolved:', c.functions.totalResolved().call())"
```

**Evidence.**
```
ORACLE_CONTRACT_ADDRESS: 0x767D0eD2850D57C4EF969976088Be44A5Adcfa07
RPC connected: True | block: 44055512
oracle prediction count: 23
oracle totalResolved: 4
oracle read: OK
```

**Verdict.** ✅ Arc testnet RPC reachable (block 44,055,512); the immutable oracle holds
**23 predictions, 4 resolved**. Contract address matches the canonical immutable oracle.

---

## §7 — Resolver, on-chain write, and posting path (observed live)

During this run the deploy pipeline (§12) restarted the scheduler, which exercised the
**resolver end-to-end against production**. Captured from `journalctl -u arke`:

```
=== Resolver Starting ===
[Resolver] 2 unresolved markets past end_date
[Resolver] 0xa743ce4a2a resolved NO | correct=False | Will the Iran ceasefire continue through May 25?
[Oracle] Resolved onchain: 0xe050c8e08c879094f0779562be09c7b07b22a752202bd8313351fd6c70345fca
[Resolver] onchain resolution 0xa743ce4a2a -> 0xe050c8e08c879094f0
[X] Posted successfully: https://x.com/arke_ai/status/2059114166544126256
[Resolver] RESOLUTION posted for 0xa743ce4a2a (quote)
[ERC8004Rep] tx reverted: 0x84de943a81ba399b7bc3b06c7eafc03ad9a8ce75d86e4b03ee3e5f4edd005aa7
=== Resolver complete in 4.9s: checked=2 resolved=1 ===
```

**Verdict.**
- ✅ **Resolver scoring**: resolved `0xa743ce4a2a` as NO (`correct=False`), `checked=2 resolved=1`.
- ✅ **On-chain resolution write**: tx `0xe050c8e0…345fca` confirmed on Arc.
- ✅ **Posting path (X API v2 / tweepy)**: live tweet posted — `x.com/arke_ai/status/2059114166544126256`.
- ⚠️ **ERC-8004 `giveFeedback`**: on-chain tx `0x84de943a…05aa7` **reverted**. This is a
  pre-existing known issue, non-fatal (the resolver continues). Not a regression from the
  feed fix. *Flagged for follow-up — this component is NOT proven functional.*

---

## §8 — Council (signal/forecaster/adversary/filter) + provenance + post suppression

**Method.** Run the agent loop as a **dry run** (no `--post` flag — a safe dry run per
CLAUDE.md; runs standalone, does not restart the systemd scheduler).

```bash
# (run on VPS, cwd /opt/arke)
venv/bin/python prove_the_loop.py > /tmp/dryrun.log 2>&1; echo "exit: $?"; tail -25 /tmp/dryrun.log
```

**Evidence.**
```
exit: 0
DEBUG: DRY_RUN = True
[3/4] Forecaster Agent — generating probability estimate...
TWEET:
  The Polymarket question "Will WTI Crude Oil hit $110 in May?" currently shows a 5% market probability.
  Arke estimates 12% — WTI has closed above $110 in May only 3 times since 2000 (3/26 ≈ 12%).
  Bet: polymarket.com/event/what-price-will-wti-hit-in-may-2026?ref=0x310072d29a53...
Length: 307 | Market: 5% | Arke: 12% | Edge: +7pts | BULL
[3.5/4] Adversary Agent + Quality Filter...
  Adversary: PASS
  Filter attempt 1: score=0.97 passed=True
  Calibration: 12% → 10%
  Provenance bundle written to /opt/arke/dashboard/public/traces/0x4bab360a81b570.json
  reasoning_cid: sha256:c96f85a74fffafb692ebf9a264990e203fa81782069411c9fca51c3e51c29581
[4/4] Posting to X...
  DRY RUN — no post sent, no DB write
Done. (42379ms)
```

The council models were also observed live during the scheduler loop (each a separate
Groq model = separate rate-limit bucket):
```
[Ensemble:superforecaster]  openai/gpt-oss-120b      → 12%
[Ensemble:base-rate-first]  llama-3.3-70b-versatile  → 7%
[Ensemble:devil's-advocate] qwen/qwen3-32b           → 30%
[Ensemble] estimates=[12,7,30] median=12 spread=23pts
[Adversary] REWRITE — corrected tweet
[Filter] score=0.62 ... passed=False    # quality gate (threshold 0.65) correctly blocked a weak take
```

**Verdict.** ✅ Full council pipeline functional end-to-end: forecaster produced a
calibrated estimate with citations, adversary reviewed, quality filter scored
(0.97 pass in the dry run; 0.62 *blocks* below the 0.65 gate in the live loop —
proving the gate both passes and rejects), calibration adjusted 12%→10%, and a
**sha256-pinned provenance bundle** was written with a `reasoning_cid`.
✅ **Post suppression** confirmed: dry run prints `DRY RUN — no post sent, no DB write`,
exit 0.

---

## §9 — Dashboard (live, Vercel)

**Method.** Smoke-test every dashboard route.

```bash
for p in "/" "/oracle" "/track-record" "/calibration" "/about"; do
  echo "$p: $(curl -s -o /dev/null -w '%{http_code}' https://arke.live$p)"; done
```

**Evidence.**
```
/: 200
/oracle: 200
/track-record: 200
/calibration: 200
/about: 200
```

**Verdict.** ✅ All 5 routes serve 200 after the feed restart.

---

## §10 — What was NOT proven this run (honest scope)

Rigor requires stating the boundary. The following were **not** exercised live in this
run and are therefore **not** claimed as proven here:

1. **Real paid nanopayment settlement (full A2A money movement).** Verifying an actual
   sub-cent USDC settlement requires a funded Gateway buyer wallet and the local-only
   `TEST_BUYER_PRIVATE_KEY` (never on the VPS). Per project memory this was settled in a
   prior session (live `…/v1/x402/verify` returned 200 / `isValid`), but it was **not
   re-run here**. This run proves the *challenge* side (§3), not a fresh settlement.
2. **ERC-8004 `giveFeedback`** — exercised but **reverted** on-chain (§7). Open issue.
3. **A deliberate live forecast tweet** — never automated; the dry run (§8) stops at the
   post boundary by design.
4. **Vercel project env vars** (`ARKE_FEED_URL`, `INTERNAL_SECRET`) — assumed correct
   because the dashboard renders; not independently inspected in the Vercel console.

---

## §11 — Reproducibility

All gates are re-runnable from a clean checkout at `821ebe0`:

```bash
# Local
arke_env/bin/python -m pytest tests/ -q

# Live feed
curl -s http://feed.arke.live:8402/v1/arke/calibration | python3 -m json.tool
curl -s http://feed.arke.live:8402/v1/arke/track-record | python3 -m json.tool   # 402 challenge

# Live oracle (Arc RPC) — no key needed for reads
python3 - <<'PY'
from web3 import Web3
w3 = Web3(Web3.HTTPProvider("https://rpc.testnet.arc.network"))
import json; abi = json.load(open("deploy/oracle_abi.json"))
c = w3.eth.contract(address=Web3.to_checksum_address("0x767D0eD2850D57C4EF969976088Be44A5Adcfa07"), abi=abi)
print("block:", w3.eth.block_number, "| predictions:", c.functions.getPredictionCount().call(),
      "| resolved:", c.functions.totalResolved().call())
PY

# Live dashboard
for p in / /oracle /track-record /calibration /about; do echo "$p $(curl -s -o /dev/null -w '%{http_code}' https://arke.live$p)"; done
```

VPS-side gates (MCP import, dry run) require SSH access — see `OPERATIONS.local.md`.

---

## §12 — Deploy pipeline & the live-post side effect (must-read operational caveat)

**Pipeline (verified).** `.github/workflows/deploy.yml` (appleboy/ssh-action) fires on
**every push to `main`** and runs, on the VPS:
```
git pull origin main
venv/bin/pip install -q -r requirements.txt
systemctl restart arke          # ← restarts the SCHEDULER
```

**Side effect observed this run.** Pushing the feed fix (`821ebe0`) triggered the
workflow → `systemctl restart arke` → the scheduler ran its startup loop. The forecast
was **filter-blocked** (no forecast tweet), but the **resolver posted a real resolution
quote-tweet** (`x.com/arke_ai/status/2059114166544126256`, §7) and wrote its on-chain
resolution.

**⚠️ Operational lesson.** `ARKE_LIVE_DEPLOY_VERIFY.MD` **Step 2 ("git push origin
main") is NOT post-safe**, even though Step 5 warns "Do NOT restart the arke scheduler."
The push restarts the scheduler *via CI*. Any task that must avoid live posts should
warn the operator before pushing to `main`, or land the change without pushing to `main`.

The posted resolution is itself **accurate and legitimate** (the agent's normal 24h
resolver behavior, fired early); it was left in place.

---

*Prepared by Claude Code. All evidence captured live on 2026-05-26 against commit
`821ebe0`. Sensitive host detail redacted per the public-repo security policy in
`CLAUDE.md`; see `OPERATIONS.local.md` for operational specifics.*
