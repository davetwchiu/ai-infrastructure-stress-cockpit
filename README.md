# AI Infrastructure Stress Cockpit

A static dashboard that monitors whether AI infrastructure pressure is merely rate pressure or has become credit stress.

MVP scope:
- GitHub Actions data pipeline
- Static HTML/CSS/JS dashboard
- Rule-based scoring
- Public data only
- No backend server
- No database
- No Streamlit

Core question:
Is the AI infrastructure trade still under rate pressure, or is credit stress confirmed?

## Data Sources

- FRED public CSV: SOFR, 2Y Treasury, 10Y Treasury, IG OAS, HY OAS.
- Yahoo Finance chart API: SOXX, QQQ, NVDA, neocloud, and infrastructure daily closes.
- Yahoo Finance quote API: best-effort SOXX, QQQ, NVDA pre-market / after-market quote fields.
- SEC EDGAR submissions JSON: best-effort recent financing filing detection.
- SEC EDGAR companyfacts JSON: best-effort XBRL balance-sheet pressure extraction.

The dashboard reads only `data/latest.json` and `data/history.csv`.

The Reload data file button reloads the static page and current data files only. It does not trigger GitHub Actions.

## GitHub Pages Deployment

Public URL:
`https://davetwchiu.github.io/ai-infrastructure-stress-cockpit/`

In the repository settings, set GitHub Pages `Source` to `GitHub Actions`.

The scheduled `Update dashboard data` workflow refreshes `data/latest.json` and `data/history.csv`, commits those files only when they change, and redeploys the static site from the repository root.

During US pre-market and after-hours, the workflow is scheduled approximately every 10 minutes using UTC cron. GitHub Actions schedules can be delayed, so the dashboard shows when the page data and extended-hours quote data were generated instead of promising an exact live tick.

## Scoring

All scoring is rule-based. No machine learning, LLMs, news classification, backend server, database, or paid data feed is used.

The official stress score is close-based. It uses daily closes and must not be treated as an intraday or extended-hours score.

Overall stress state:

- `0-25`: `NORMAL`
- `26-50`: `WATCH`
- `51-70`: `STRESS`
- `71-100`: `CREDIT STRESS CONFIRMED`

Equity Confirmation uses SOXX vs QQQ relative performance and NVDA vs SOXX relative performance. The dashboard charts SOXX / QQQ relative performance only.

Compute Financing Stress Score v1 replaces the old placeholder compute score. It is a rule-based composite:

- 45% SEC filing event detection for CRWV, NBIS, APLD, and IREN.
- 25% SEC/XBRL balance-sheet pressure where usable facts are available.
- 20% neocloud equity confirmation versus 50% QQQ / 50% SOXX.
- 10% infrastructure spillover confirmation in DLR, EQIX, VRT, and ETN.

It does not use machine learning, LLM/news classification, GPU rental price scraping, or paid credit/bond data. SEC data is best-effort and should be treated as an early-warning aid, not legal or accounting advice.

The Extended-hours Equity Overlay is provisional. It watches whether SOXX is materially lagging QQQ and whether NVDA is materially lagging SOXX during pre-market or after-market trading. It does not change `stress.score`, and it does not by itself confirm credit stress. The official stress score remains close-based.

## Limitations

- Market data can lag, revise, or fail if a public source is unavailable.
- Extended-hours data may be unavailable or stale; when that happens the dashboard shows the overlay as unavailable and keeps the official close-based score unchanged.
- SEC filing and XBRL parsing can be partial because issuer filings and tags vary.
- The tool is a stress monitor, not investment advice or a trading system.

## Local Run

```bash
python3 scripts/update_data.py --self-test
python3 -m py_compile scripts/update_data.py
node --check app.js
python3 scripts/update_data.py
python3 -m http.server 8000
```

Then open `http://localhost:8000`.
