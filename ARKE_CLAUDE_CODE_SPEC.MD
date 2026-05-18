# ARKE — Claude Code Build Spec
## Autonomous Prediction Market Intelligence Agent

**For Claude Code to execute autonomously in `~/arke/`**
**Working directory:** `~/arke/`
**Existing proven files:** `prove_the_loop.py`, `agent/db.py`, `.env`

---

## CONTEXT: What Already Works

These files are proven and must not be broken:

- `prove_the_loop.py` — end-to-end loop: fetches Polymarket feed → picks market → generates tweet via Groq → posts via OpenTweet → records to SQLite
- `agent/db.py` — production SQLite persistence with WAL, migration-safe, full schema
- `.env` — all secrets loaded via python-dotenv

**The existing `.env` contains:**
```
GROQ_API_KEY=REDACTED_GROQ_KEY
GROQ_MODEL=openai/gpt-oss-120b
CEREBRAS_API_KEY=csk-jcdt6ej39vckrc9h3t3jdrwr9ktt8vhn9dctxtdj6w33y85f
CEREBRAS_MODEL=qwen-3-235b-a22b-instruct-2507
OPENTWEET_API_KEY=ot_c0b06e80d957e89371f875fcb71cc20fab9fd30bf2f1546d
DASHBOARD_URL=arke.markets
POLY_BUILDER_CODE=0xa194a8b0700911c9bf8788615b8be84b29149cc50a5e2889ea022221d3557e64
POLY_BUILDER_ADDRESS=[base wallet address - to be filled]
POLY_BUILDER_API_KEY=[new key - to be filled]
POLY_BUILDER_SECRET=[new secret - to be filled]
POLY_BUILDER_PASSPHRASE=[new passphrase - to be filled]
CRYPTOPANIC_API_KEY=[to be filled]
CIRCLE_API_KEY=[to be filled]
CIRCLE_ENTITY_SECRET=[to be filled]
```

---

## TARGET REPOSITORY STRUCTURE

Build every file listed below. All Python code must be async-compatible, use dotenv, and import cleanly. All files must work together as one system.

```
arke/
├── .env                          # EXISTS — do not touch
├── .env.example                  # CREATE — template with all vars documented
├── .gitignore                    # CREATE
├── requirements.txt              # CREATE — full dependency list
├── prove_the_loop.py             # EXISTS — do not touch
│
├── agent/
│   ├── __init__.py               # CREATE — empty
│   ├── db.py                     # EXISTS — do not touch
│   ├── scheduler.py              # CREATE — autonomous 6-hour cron loop
│   │
│   ├── integrations/
│   │   ├── __init__.py           # CREATE — empty
│   │   ├── polymarket.py         # CREATE — Gamma API feed + market selection
│   │   ├── opentweet.py          # CREATE — OpenTweet posting
│   │   ├── cryptopanic.py        # CREATE — crypto news signal source
│   │   ├── gdelt.py              # CREATE — geopolitical news (no auth)
│   │   ├── snapshot.py           # CREATE — DAO governance GraphQL
│   │   └── circle.py             # CREATE — Circle agent wallet stub
│   │
│   └── agents/
│       ├── __init__.py           # CREATE — empty
│       ├── generator.py          # CREATE — Groq tweet generation (extracted from prove_the_loop)
│       ├── filter.py             # CREATE — Cerebras adversarial quality filter
│       └── resolver.py           # CREATE — market resolution checker
│
├── contracts/
│   └── PredictionMarketLog.sol   # CREATE — Arc testnet audit trail contract
│
├── dashboard/
│   ├── package.json              # CREATE — Next.js 14 project
│   ├── next.config.js            # CREATE
│   ├── tailwind.config.js        # CREATE
│   ├── tsconfig.json             # CREATE
│   └── src/
│       └── app/
│           ├── layout.tsx        # CREATE — root layout
│           ├── page.tsx          # CREATE — live feed dashboard
│           ├── globals.css       # CREATE
│           └── api/
│               └── feed/
│                   └── route.ts  # CREATE — serves feed from Gamma API + db
│
└── infra/
    ├── server-setup.sh           # CREATE — Hetzner/Ubuntu VPS bootstrap
    ├── arke.service              # CREATE — systemd unit
    └── .github/
        └── workflows/
            └── deploy.yml        # CREATE — GitHub Actions CI/CD
```

---

## FILE SPECIFICATIONS

### `requirements.txt`

```
httpx==0.27.0
groq==0.9.0
python-dotenv==1.0.1
schedule==1.2.2
cerebras-cloud-sdk>=1.0.0
web3==6.20.0
```

Do NOT include py-clob-client (archived May 11 2026). Do NOT include supabase. Use SQLite only (already in stdlib via db.py).

---

### `agent/scheduler.py`

**Purpose:** Autonomous agent loop. Runs `prove_the_loop.main(post=True)` every 6 hours. Runs `resolver.check_resolutions()` every 24 hours. Must survive exceptions without crashing.

**Spec:**
```python
"""
agent/scheduler.py — Arke autonomous scheduler

Runs the full pipeline every 6 hours.
Runs the resolution checker every 24 hours.
Survives all exceptions — logs and continues.

Usage:
  python agent/scheduler.py         # start autonomous agent
  python agent/scheduler.py --once  # run once and exit (for testing)
"""
```

**Implementation requirements:**
- Import `schedule` library
- Import `asyncio`
- Import `logging` — configure with timestamp, level, message format
- Import `sys`, `os`
- Load dotenv at top
- Add parent dir to sys.path so `prove_the_loop` is importable
- Import `main` from `prove_the_loop` as `loop_main`
- Import `check_resolutions` from `agent.agents.resolver`
- Define `run_loop()` — wraps `asyncio.run(loop_main(post=True))` in try/except, logs duration and outcome
- Define `run_resolver()` — wraps `asyncio.run(check_resolutions())` in try/except
- `schedule.every(6).hours.do(run_loop)`
- `schedule.every(24).hours.do(run_resolver)`
- If `--once` in sys.argv: call `run_loop()` and exit
- Otherwise: call `run_loop()` immediately on startup, then enter `while True: schedule.run_pending(); time.sleep(60)`
- Print startup banner with next scheduled run time

---

### `agent/integrations/polymarket.py`

**Purpose:** Clean module wrapping all Polymarket Gamma API interactions. Extracted and improved from `prove_the_loop.py`.

**Spec:**
```python
"""
agent/integrations/polymarket.py — Polymarket Gamma API integration

Provides:
  fetch_arke_feed() -> list[dict]   — top non-sports markets with genuine uncertainty
  pick_best_market(feed) -> dict    — urgency-weighted selection with dedup
  get_market_url(market) -> str     — correct polymarket.com/event/{slug} URL with ?ref=
  get_event_context(market) -> str  — Polymarket's own AI context for the market
"""
```

**Implementation requirements:**
- SPORTS_KEYWORDS list — minimum 35 keywords covering all major sports, esports, Eurovision, FIFA
- `is_sports(q: str) -> bool` — case-insensitive any() check
- `fetch_arke_feed() -> list[dict]` — async, GET gamma-api.polymarket.com/markets with params active=true, limit=100, order=volume24hr, ascending=false. Filter: vol>50000, 20<=pct<=80, not is_sports. Sort by volume24hr desc. Return list.
- `pick_best_market(feed, db=None) -> dict | None` — prefer markets ending in 0-30 days that aren't in db cooldown. Fallback to any not in cooldown. Final fallback: top market ignoring cooldown with warning log.
- `get_market_url(market) -> str` — use events[0].slug if available, else market.slug. Prepend `polymarket.com/event/`. Append `?ref={POLY_BUILDER_ADDRESS}` if env var set.
- `get_event_context(market) -> str` — extract events[0].eventMetadata.context_description, truncate to 400 chars, return empty string if missing.
- All functions must handle missing keys gracefully with .get() and defaults.

---

### `agent/integrations/opentweet.py`

**Purpose:** Clean module for OpenTweet API posting, extracted from prove_the_loop.py.

**Spec:**
```python
"""
agent/integrations/opentweet.py — OpenTweet API integration

Provides:
  post_tweet(tweet: str) -> dict   — posts to @arke_ai, returns response
  remaining_credits() -> int       — checks remaining URL post credits
"""
```

**Implementation requirements:**
- `post_tweet(tweet: str) -> dict` — async, POST https://opentweet.io/api/v1/posts with Authorization Bearer, Content-Type application/json, body `{"text": tweet, "publish_now": True}`. Return resp.json() on 200/201, empty dict on failure. Log HTTP status always.
- `remaining_credits() -> int` — GET https://opentweet.io/api/v1/me, return limits.remaining_posts_today from response. Return -1 on failure.
- Both functions read OPENTWEET_API_KEY from env. Return gracefully if not set.

---

### `agent/integrations/cryptopanic.py`

**Purpose:** CryptoPanic news API for signal detection. Returns keywords from trending crypto news to cross-reference against Polymarket feed.

**Spec:**
```python
"""
agent/integrations/cryptopanic.py — CryptoPanic news signal source

Free tier: https://cryptopanic.com/api/free/v1/posts/
Requires CRYPTOPANIC_API_KEY env var.

Provides:
  fetch_signals() -> list[str]          — trending keywords from hot news
  fetch_news(limit=20) -> list[dict]    — raw news items with title, url, votes
  match_news_to_market(news, market) -> float  — relevance score 0-1
"""
```

**Implementation requirements:**
- `fetch_signals(filter="hot", limit=20) -> list[str]` — async, GET https://cryptopanic.com/api/free/v1/posts/ with auth_token=CRYPTOPANIC_API_KEY, filter=filter, kind=news. Extract all words from title fields, deduplicate, filter out stopwords (the, a, an, is, of, in, to, for, etc.), return list of unique keywords. Return empty list if API key not set or request fails.
- `fetch_news(limit=20) -> list[dict]` — same endpoint, return results array with fields: title, url, published_at, votes.bullish, votes.bearish, panic_score.
- `match_news_to_market(news_items: list[dict], market: dict) -> float` — score 0-1. Check how many words from market question appear in news titles. Return fraction of question words found in news corpus. Used by pick_best_market to elevate news-matched markets.
- Graceful failure: if CRYPTOPANIC_API_KEY not set, log warning and return empty lists.

---

### `agent/integrations/gdelt.py`

**Purpose:** GDELT global news API — no auth required, massive coverage of geopolitical events.

**Spec:**
```python
"""
agent/integrations/gdelt.py — GDELT global news signal source

No API key required. Public REST API.
Base URL: https://api.gdeltproject.org/api/v2/

Provides:
  fetch_trending_topics() -> list[str]   — trending global news keywords
  fetch_geopolitical_events() -> list[dict]  — recent high-coverage events
"""
```

**Implementation requirements:**
- `fetch_trending_topics() -> list[str]` — async, GET https://api.gdeltproject.org/api/v2/summary/summary?d=web&t=summary — parse response for trending terms. If that fails, use GET https://api.gdeltproject.org/api/v2/tv/search?query=politics&mode=timelinevol&format=json as fallback. Return list of keyword strings. Return empty list on any failure — GDELT can be slow.
- `fetch_geopolitical_events(hours_back=6) -> list[dict]` — fetch recent news articles from GDELT doc API: GET https://api.gdeltproject.org/api/v2/doc/doc?query=geopolitics&mode=ArtList&maxrecords=10&format=json. Return list of dicts with title, url, datetime fields.
- Add 5-second timeout to all requests — GDELT is sometimes slow.
- Return empty lists on any exception — never crash the pipeline.

---

### `agent/integrations/snapshot.py`

**Purpose:** Snapshot GraphQL API for DAO governance proposals. Free, no auth.

**Spec:**
```python
"""
agent/integrations/snapshot.py — Snapshot DAO governance signal source

GraphQL endpoint: https://hub.snapshot.org/graphql
No authentication required.

Provides:
  fetch_active_proposals(limit=10) -> list[dict]   — live governance votes
  proposal_to_signal(proposal) -> str              — human-readable signal string
"""
```

**Implementation requirements:**
- `fetch_active_proposals(limit=10) -> list[dict]` — async, POST https://hub.snapshot.org/graphql with GraphQL query:
```graphql
{
  proposals(first: 10, where: {state: "active"}, orderBy: "created", orderDirection: desc) {
    id title body state start end scores_total votes space { id name }
  }
}
```
Parse response.data.proposals. Return list of dicts. Return empty list on failure.
- `proposal_to_signal(proposal: dict) -> str` — return "{space.name}: {title} — {votes} votes, ends {end_datetime}". Used to give the LLM context about DAO activity.

---

### `agent/integrations/circle.py`

**Purpose:** Circle Developer Platform wallet stub. Covers Circle hackathon rubric.

**Spec:**
```python
"""
agent/integrations/circle.py — Circle Developer Platform integration

Covers Circle primitives for hackathon rubric:
  - Developer Wallet (agent treasury)
  - Balance queries

Requires: CIRCLE_API_KEY, CIRCLE_ENTITY_SECRET env vars.
If not set, all functions return gracefully with logged warnings.

Provides:
  get_wallet_balance() -> dict    — USDC balance of agent wallet
  log_market_to_circle(market_data) -> str  — logs market to Circle wallet memo
"""
```

**Implementation requirements:**
- `get_wallet_balance() -> dict` — async, GET https://api.circle.com/v1/w3s/wallets/{CIRCLE_WALLET_ID}/balances with Authorization Bearer CIRCLE_API_KEY. Return dict with usdc_balance field. Return {"usdc_balance": "0", "error": "not_configured"} if env vars missing.
- `log_market_to_circle(market_data: dict) -> str` — logs a memo/note to the Circle wallet. In the absence of a true memo API, this function logs to the ArkeDB and prints a formatted string. Return a confirmation string. This demonstrates Circle wallet awareness without requiring complex transaction signing.
- If CIRCLE_API_KEY not set: log warning "Circle not configured" and return graceful defaults.

---

### `agent/agents/generator.py`

**Purpose:** Tweet generation via Groq. Extracted and improved from prove_the_loop.py.

**Spec:**
```python
"""
agent/agents/generator.py — Tweet generation via Groq LLM

Uses openai/gpt-oss-120b (120B MoE, MMLU 90%) on Groq.
Falls back to llama-3.3-70b-versatile if primary model returns empty.

Provides:
  generate_tweet(market: dict, news_context: str = "") -> str
"""
```

**Implementation requirements:**
- `generate_tweet(market: dict, news_context: str = "") -> str` — sync function (Groq client is sync).
- Extract: price/pct, question, vol24, end_date, market_url from market dict.
- Get event context via `get_event_context(market)` from polymarket integration.
- Build prompt with the following structure (use exact format from prove_the_loop.py — it is proven to produce good output):
  - Identity: "You are Arke, an autonomous prediction market intelligence agent..."
  - Market data block
  - TWEET STRUCTURE: Line 1 (fact), Line 2 (take starting with "I think" or "I disagree —"), Line 3 (Bet: URL)
  - RULES: under 240 chars, specific data-grounded reason, no hashtags/exclamations/emojis, no comma splices
  - GOOD EXAMPLES and BAD EXAMPLES from proven prompt
- Call `client.chat.completions.create(model="openai/gpt-oss-120b", messages=[...], temperature=0.7)` with NO max_tokens (removes the vLLM empty-response bug)
- If response is empty or len < 20: retry once with model="llama-3.3-70b-versatile" and max_tokens=180
- Return stripped content string

---

### `agent/agents/filter.py`

**Purpose:** Adversarial quality filter via Cerebras qwen-3-235b. Blocks factual hallucinations before posting.

**Spec:**
```python
"""
agent/agents/filter.py — Adversarial quality filter via Cerebras

Uses qwen-3-235b-a22b-instruct-2507 on Cerebras (235B MoE, different family from Groq model).
Different model family = genuine adversarial disagreement possible.

Provides:
  quality_check(tweet: str, market: dict) -> tuple[float, bool, str]
    Returns: (score 0-1, passed bool, reason string)
"""
```

**Implementation requirements:**
- Import cerebras SDK: `from cerebras.cloud.sdk import Cerebras`
- `quality_check(tweet: str, market: dict) -> tuple[float, bool, str]` — async-compatible but sync Cerebras call.
- Build evaluation prompt:
```
You are a strict fact-checker for prediction market analysis tweets.

Tweet to evaluate:
{tweet}

Market: {question} — {pct}% YES probability, ${vol24:,.0f} daily volume

Score this tweet 0.0-1.0 on three dimensions:
1. Factual accuracy of any specific claims made (0-1). Penalize invented statistics, wrong dates, fabricated events.
2. Specificity of reasoning (0-1). Does it cite a named mechanism, historical pattern, or real data point?
3. Analytical credibility (0-1). Would a sophisticated prediction market trader find this credible?

IMPORTANT: If the tweet contains a specific numerical claim (e.g. "sold 0.4% of BTC", "12% of Bitcoin holdings"), that claim MUST be verifiable from public knowledge about the subject. If you cannot verify it, score factual accuracy as 0.2 or lower.

Return ONLY valid JSON: {"score": 0.0, "factual": 0.0, "specific": 0.0, "credible": 0.0, "reason": "one sentence explanation"}
```
- Parse JSON response. Calculate weighted score: factual*0.5 + specific*0.25 + credible*0.25.
- Threshold: score >= 0.65 → passed=True.
- If CEREBRAS_API_KEY not set: return (0.8, True, "filter_skipped_no_key") — fail open so posting continues.
- If Cerebras call fails: return (0.75, True, "filter_error_fail_open") — fail open, log warning.
- Log score, passed, reason at INFO level.

---

### `agent/agents/resolver.py`

**Purpose:** Checks whether posted markets have resolved and marks them in the db.

**Spec:**
```python
"""
agent/agents/resolver.py — Market resolution checker

Runs daily. Finds all markets past their end_date that aren't marked resolved.
Checks Gamma API for resolution status. Updates db with outcome and whether Arke was correct.

Provides:
  check_resolutions() -> dict   — returns count of markets checked and resolved
"""
```

**Implementation requirements:**
- `check_resolutions() -> dict` — async.
- Import ArkeDB from agent.db
- db = ArkeDB()
- Get unresolved markets: `db.get_unresolved_past_enddate()`
- For each market: GET https://gamma-api.polymarket.com/markets?conditionId={condition_id}
- Parse response: if market.closed==True and market.outcomePrices is [1,0] → resolved YES. If [0,1] → resolved NO.
- Determine was_correct: if arke_position=="AGREE" and market probability was >50% and resolved YES → correct. If arke_position=="DISAGREE" and market probability was >50% and resolved NO → correct. Else incorrect.
- Call `db.mark_resolved(condition_id, resolution, was_correct)`
- Return dict with markets_checked, markets_resolved counts.
- Log each resolution at INFO level.

---

### `contracts/PredictionMarketLog.sol`

**Purpose:** Minimal Solidity contract for Arc testnet. Logs every market Arke identifies as an immutable onchain audit trail.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title PredictionMarketLog
 * @notice Arke's immutable audit trail on Arc testnet.
 * @dev Every market the agent identifies is logged here with probability estimate and tweet URL.
 *      This proves the agent has been operating continuously and transparently.
 */
contract PredictionMarketLog {
    struct MarketEntry {
        bytes32 conditionId;
        string  question;
        uint8   probabilityPct;
        uint256 loggedAt;
        string  tweetUrl;
        bool    resolved;
        bool    wasCorrect;
    }

    MarketEntry[] public entries;
    address public immutable owner;
    uint256 public totalCorrect;
    uint256 public totalResolved;

    event MarketLogged(
        uint256 indexed entryId,
        bytes32 indexed conditionId,
        uint8   probabilityPct,
        uint256 loggedAt
    );

    event MarketResolved(
        uint256 indexed entryId,
        bool    wasCorrect,
        uint256 resolvedAt
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    function logMarket(
        bytes32       conditionId,
        string calldata question,
        uint8         probabilityPct,
        string calldata tweetUrl
    ) external onlyOwner returns (uint256 entryId) {
        require(probabilityPct <= 100, "Invalid probability");
        entryId = entries.length;
        entries.push(MarketEntry({
            conditionId:    conditionId,
            question:       question,
            probabilityPct: probabilityPct,
            loggedAt:       block.timestamp,
            tweetUrl:       tweetUrl,
            resolved:       false,
            wasCorrect:     false
        }));
        emit MarketLogged(entryId, conditionId, probabilityPct, block.timestamp);
    }

    function resolveMarket(
        uint256 entryId,
        bool    wasCorrect
    ) external onlyOwner {
        require(entryId < entries.length, "Invalid entry");
        require(!entries[entryId].resolved, "Already resolved");
        entries[entryId].resolved   = true;
        entries[entryId].wasCorrect = wasCorrect;
        totalResolved++;
        if (wasCorrect) totalCorrect++;
        emit MarketResolved(entryId, wasCorrect, block.timestamp);
    }

    function totalEntries() external view returns (uint256) {
        return entries.length;
    }

    function accuracyBps() external view returns (uint256) {
        if (totalResolved == 0) return 0;
        return (totalCorrect * 10000) / totalResolved;
    }

    function getEntry(uint256 entryId) external view returns (MarketEntry memory) {
        require(entryId < entries.length, "Invalid entry");
        return entries[entryId];
    }
}
```

---

### `dashboard/src/app/page.tsx`

**Purpose:** Live Arke feed dashboard. Shows top Polymarket markets with Arke's takes, accuracy stats, and working bet links.

**Design direction:** Dark terminal aesthetic. Monospace font. Amber/green on black. Data-dense. Feels like Bloomberg terminal meets crypto trading desk. NOT a generic SaaS dashboard.

**Spec:**
- Fetch feed from Gamma API directly on the server (no db dependency — dashboard is stateless read-only)
- Show stats bar: total markets surfaced (from a static counter or query param), accuracy % (hardcoded or from an API route that reads db)
- Show market cards in a grid: question, probability bar, 24hr volume, Arke's tweet text if available, "Bet on Polymarket →" button
- Bet button links to `https://polymarket.com/event/{event_slug}?ref={BUILDER_ADDRESS}`
- Real-time feel: show "Last updated: X seconds ago" with client-side counter
- Mobile responsive
- No framework beyond Next.js + Tailwind + shadcn/ui

**Key components:**
- `MarketCard` — dark card, amber probability number large, green volume, monospace question text
- `StatsBar` — fixed top bar: "ARKE — autonomous prediction market intelligence | {N} markets surfaced | {accuracy}% accuracy | @arke_ai on X"
- `BetButton` — amber button, opens Polymarket with builder attribution in URL

---

### `dashboard/src/app/api/feed/route.ts`

**Purpose:** Server-side API route that fetches Polymarket feed and returns cleaned market data.

**Spec:**
- GET handler that fetches `https://gamma-api.polymarket.com/markets?active=true&limit=100&order=volume24hr&ascending=false`
- Filter: vol24hr > 50000, 20 <= probability <= 80, not sports
- Add SPORTS_KEYWORDS filter (same list as Python agent)
- Add builder ref URL to each market
- Return JSON array of cleaned market objects
- Cache with `revalidate = 300` (5 minutes)
- Handle errors gracefully

---

### `infra/server-setup.sh`

**Purpose:** One-shot VPS provisioning script for any Ubuntu 22.04 server.

```bash
#!/bin/bash
# Arke VPS bootstrap — Ubuntu 22.04
# Run as root once after provisioning
# Usage: bash server-setup.sh

set -euo pipefail

echo "=== Arke VPS Bootstrap ==="

# System deps
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git curl wget htop

# Create arke user
if ! id -u arke >/dev/null 2>&1; then
    useradd -m -s /bin/bash arke
    echo "Created arke user"
fi

# Clone repo (assumes GITHUB_REPO env var set, or edit inline)
REPO_URL="${GITHUB_REPO:-https://github.com/your-handle/arke}"
INSTALL_DIR="/opt/arke"

if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR" && git pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

chown -R arke:arke "$INSTALL_DIR"

# Python venv
sudo -u arke python3 -m venv "$INSTALL_DIR/venv"
sudo -u arke "$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

echo "=== Copy your .env file ==="
echo "Run: scp .env root@SERVER_IP:$INSTALL_DIR/.env"
echo "Then run: bash $INSTALL_DIR/infra/install-service.sh"
```

---

### `infra/install-service.sh`

**Purpose:** Installs systemd service after .env is in place.

```bash
#!/bin/bash
set -euo pipefail

INSTALL_DIR="/opt/arke"

cat > /etc/systemd/system/arke.service << EOF
[Unit]
Description=Arke Prediction Market Intelligence Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=arke
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python agent/scheduler.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
EnvironmentFile=$INSTALL_DIR/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable arke
systemctl start arke
systemctl status arke
echo "=== Arke agent started ==="
echo "Monitor: journalctl -u arke -f"
```

---

### `.github/workflows/deploy.yml`

**Purpose:** GitHub Actions CI/CD. On push to main, SSH to VPS, pull, reinstall deps, restart service.

```yaml
name: Deploy to VPS

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.VPS_IP }}
          username: root
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            set -e
            cd /opt/arke
            git pull origin main
            venv/bin/pip install -q -r requirements.txt
            systemctl restart arke
            systemctl status arke --no-pager
            echo "Deploy complete: $(date)"
```

**GitHub Secrets required:**
- `VPS_IP` — server IP address
- `SSH_PRIVATE_KEY` — private key for SSH access

---

### `.gitignore`

```
.env
*.pyc
__pycache__/
arke.db
arke.db-wal
arke.db-shm
venv/
arke_env/
node_modules/
.next/
dist/
.DS_Store
*.log
```

---

### `.env.example`

Document every variable with source and description. Include all variables from existing .env plus new ones.

---

## BUILD INSTRUCTIONS FOR CLAUDE CODE

Execute these steps in order. After each step, verify it works before continuing.

### Step 1 — Create directory structure
```bash
mkdir -p ~/arke/agent/{integrations,agents}
mkdir -p ~/arke/contracts
mkdir -p ~/arke/dashboard/src/app/api/feed
mkdir -p ~/arke/infra/.github/workflows
```

### Step 2 — Create all Python modules
Write every Python file in `agent/` per specs above. After writing each file, run:
```bash
cd ~/arke && python -c "from agent.integrations.polymarket import fetch_arke_feed; print('OK')"
```
Fix any import errors before continuing.

### Step 3 — Verify scheduler imports cleanly
```bash
cd ~/arke && python -c "import agent.scheduler; print('scheduler OK')"
```

### Step 4 — Run scheduler in once mode to verify full pipeline
```bash
cd ~/arke && source arke_env/bin/activate && python agent/scheduler.py --once
```
This should run the full pipeline once: fetch → pick → generate → filter → post (if --post) → db → log.

### Step 5 — Create dashboard files
Write all dashboard TypeScript files. Run:
```bash
cd ~/arke/dashboard && npm install && npm run build
```
Fix any TypeScript errors.

### Step 6 — Create infra files
Write server-setup.sh, install-service.sh, deploy.yml.

### Step 7 — Final integration test
```bash
cd ~/arke && python prove_the_loop.py --dry-run
# Should show: feed fetched, market picked, tweet generated, quality score printed, dry run confirmed
```

---

## CRITICAL CONSTRAINTS

1. **Never break prove_the_loop.py** — it is the ground truth, already working.
2. **Never break agent/db.py** — production SQLite schema, already deployed.
3. **All Python must be compatible with Python 3.12** (user's system version).
4. **All imports must be relative within the package** — `from agent.integrations.polymarket import ...` from root, `from ..db import ArkeDB` from within agent package.
5. **Groq calls must NOT pass max_tokens** — causes empty response bug with gpt-oss-120b.
6. **Every integration must fail gracefully** — if API key missing or request fails, log warning and return empty/default. Never crash the pipeline.
7. **The scheduler must restart automatically** — `Restart=always` in systemd unit.
8. **CI/CD must be deployable** — push to main triggers deploy. No manual steps required after initial setup.

---

## WHAT SUCCESS LOOKS LIKE

When done, this command should work:
```bash
cd ~/arke
source arke_env/bin/activate
python agent/scheduler.py --once
```

And produce output like:
```
2026-05-18 03:00:00 INFO  === Arke Agent Starting ===
2026-05-18 03:00:00 INFO  DB: 3 posts, 0 resolved, last: MicroStrategy...
2026-05-18 03:00:01 INFO  [CryptoPanic] 12 signals: bitcoin, fed, iran, ...
2026-05-18 03:00:02 INFO  [Polymarket] 5 actionable markets fetched
2026-05-18 03:00:02 INFO  [Polymarket] Selected: Strait of Hormuz... (not in cooldown)
2026-05-18 03:00:03 INFO  [Generator] Tweet generated: 198 chars
2026-05-18 03:00:04 INFO  [Filter] Score: 0.82 | passed: True | Reason: Specific historical claim about Hormuz closures
2026-05-18 03:00:04 INFO  [DRY RUN] Would post: "Strait of Hormuz traffic..."
2026-05-18 03:00:04 INFO  === Run complete in 4.2s ===
```

And with `--post`:
```
2026-05-18 03:00:05 INFO  [OpenTweet] HTTP 201 — posted successfully
2026-05-18 03:00:05 INFO  [DB] Recorded post row 4, builder code 0xa194...
2026-05-18 03:00:05 INFO  === Run complete in 5.1s — POSTED ===
```

That is the complete system. Build it.