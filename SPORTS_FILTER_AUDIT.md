# Sports exclusion audit — 2026-05-25

Audit of `is_sports()` in the live loop, prompted by the Juventus / West Ham /
Getafe calls. Question: were those sports markets posted because the filter was
*inactive*, or because they *slipped through* an active filter?

## What the filter is and when it landed

- `is_sports()` + `SPORTS_KEYWORDS` were introduced in the **initial commit**
  `e6494dc` — **2026-05-15 22:58:42 -0400**.
- `is_sports(q)` has gated `fetch_arke_feed()` **continuously since that
  commit** (`... and not is_sports(q)` in the feed filter). It has never been
  removed.
- Before this audit, `is_sports()` was **not** called in `pick_best_market()`.
  That was a defense-in-depth gap, not an active leak: the feed handed to
  `pick_best_market()` was already sports-filtered.

## Were the Juventus / West Ham / Getafe calls before or after the filter?

**Cannot be timestamped from any local artifact — they are not recorded
locally.** Searched exhaustively:

| Source | Result |
| --- | --- |
| `arke.db` → `posted_markets` | 3 rows only: *Iran closes airspace* (2026-05-18), *MicroStrategy sells BTC* (2026-05-18), *US×Iran peace deal* (2026-05-22). None sports. |
| `arke.db` → `feed_snapshots` (24 snapshots, 34 distinct questions) | No sports questions; no `juventus` / `west ham` / `getafe` / ` vs ` / league names. |
| `dashboard/public/traces/*.json` | No sports calls. |
| Tracked repo + untracked `repo_dump.txt` / `requests` | No occurrence of the three club names. |

The earliest local record of any kind is **2026-05-18**, three days *after* the
filter shipped. The three calls predate the local DB / traces entirely, which is
consistent with their having been posted during pre-`e6494dc` development —
i.e. **before the filter existed** — rather than slipping past it.

## Why the keyword list still needed tightening

Even though we cannot show the filter was bypassed, the list as it stood would
**not** have caught the single-team soccer phrasings those clubs typically
appear in:

- `"Team A vs Team B"` markets **were** caught (via the `"vs "` keyword).
- But `"Will Getafe avoid relegation?"` or `"Juventus to win the league?"` had
  **no matching keyword** — `Juventus`, `West Ham`, `Getafe` were absent, and
  the live-loop list (`prove_the_loop.py`) was also missing `La Liga`,
  `Premier League`, `Champions League`, `NBA`, `NFL`, `MLB`, `NHL`, `UFC`
  (these existed only in the broader helper list in
  `agent/integrations/polymarket.py`).

So whether or not the historical calls slipped through, the **current** list had
a real hole for single-team soccer markets.

## Changes made (this commit)

1. **Tightened `SPORTS_KEYWORDS`** in `prove_the_loop.py`: added the named clubs
   (`Juventus`, `West Ham`, `Getafe`, `Real Madrid`, `Barcelona`, `Man City`,
   `Man United`, `Bayern`, `PSG`, `Tottenham`, `Chelsea`) plus the
   leagues/competitions and major US leagues the live-loop list was missing
   (`Premier League`, `La Liga`, `Champions League`, `Europa League`, `NBA`,
   `NFL`, `MLB`, `NHL`, `UFC`, `Formula 1`, `Grand Prix`). Ambiguous bare words
   (e.g. `Arsenal` — "nuclear arsenal") were deliberately **not** added.
2. **Kept the helper list in sync** (`agent/integrations/polymarket.py`) with
   the named clubs so the generator and tests agree.
3. **Added `is_sports()` to `pick_best_market()`** as defense in depth: a sports
   market can now never reach the council even if a new phrasing slips past the
   feed filter.
