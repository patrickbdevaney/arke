# Arke — agent guide

Autonomous prediction-market intelligence agent. Pulls Polymarket markets,
runs a multi-agent council, and posts analytical tweets as **@arke_ai**.

## ⚠️ Security — this repo is PUBLIC. Read first.

- **Never commit secrets.** No API keys, tokens, private keys, or `.env` files —
  not in code, not in `*.md` spec files, not in comments. A real key leaked once
  via a spec file committed to history; don't repeat it.
- **Secrets live only in `.env`** (gitignored) and are read via `os.getenv()`.
  Document every new variable — with an **empty** value — in `.env.example`.
- **A pre-commit secret guard is active** (`.githooks/pre-commit`, enabled via
  `core.hooksPath`). After cloning, run `bash scripts/install-hooks.sh` to turn it
  on. It blocks staged `.env` files and known key formats. `--no-verify` bypasses
  it — don't, unless you've confirmed a false positive.
- **Verify history is clean** before worrying or after changes:
  ```bash
  git rev-list --all | while read c; do
    git grep -nIE '(gsk_[A-Za-z0-9]{30}|csk-[a-z0-9]{30}|ot_[a-f0-9]{30}|sk-[A-Za-z0-9]{20})' "$c" 2>/dev/null
  done | sort -u
  ```
- Note: `POLY_BUILDER_CODE` / `POLY_BUILDER_ADDRESS` are **public** (they appear in
  every tweet's `?ref=` URL) — not secrets.

## Architecture

- **Entry point:** `agent/scheduler.py` imports `main` from `prove_the_loop.py`.
  Runs the loop on startup + every 6h; resolver every 24h. systemd `Restart=always`.
- **Council** (all Groq; separate model IDs = separate rate-limit buckets):
  - `agent/agents/signal_agent.py` — `llama-3.3-70b-versatile`, aggregates headlines.
  - `agent/agents/forecaster_agent.py` — `openai/gpt-oss-120b`, emits a calibrated
    Arke probability + tweet (`Arke estimates X%`).
  - `agent/agents/adversary_agent.py` — `qwen/qwen3-32b`, fact-checks / rewrites once.
  - `agent/agents/filter.py` — `openai/gpt-oss-120b` quality gate, threshold 0.65,
    **fails open** on API error.
- **Posting:** `agent/integrations/opentweet.py` → direct X API v2 via tweepy
  (OAuth 1.0a, no expiry). Consumer creds resolve `X_API_KEY`/`X_API_SECRET`, then
  fall back to this `.env`'s actual names `X_API_CONSUMER_KEY`/`X_API_SECRET_KEY`.
- **Oracle (dormant):** `agent/integrations/oracle.py` + `contracts/` + `deploy/`.
  Logs predictions onchain only when `ARC_PRIVATE_KEY` + `ORACLE_CONTRACT_ADDRESS`
  are set; otherwise skips silently. Never blocks posting.

## Gotchas

- `gpt-oss-120b` is a **reasoning model**: budget ≥1024 `max_tokens` or the JSON/
  tweet gets truncated. Its TPM cap is **8000/min** — forecaster + filter share it,
  fine at the 6h cadence but easy to trip with rapid local testing.
- **Never run `prove_the_loop.py --post` during testing.** `python prove_the_loop.py`
  (no flag) is a safe dry run.

## Run / deploy

- Local venv: `arke_env/`. VPS: `root@159.223.102.247:/opt/arke`, venv `venv/`.
- Dry run: `arke_env/bin/python prove_the_loop.py`
- Deploy: push `main`, then on VPS `git pull && venv/bin/pip install -r requirements.txt
  && systemctl restart arke`. **Restarting `arke` triggers an immediate live post.**
