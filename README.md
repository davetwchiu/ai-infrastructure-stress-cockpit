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
- Yahoo Finance chart API: SOXX, QQQ, NVDA daily closes.
- Yahoo Finance quote API: best-effort SOXX, QQQ, NVDA pre-market / after-market quote fields.
- `config/manual_signals.json`: small manual inputs for compute / financing signals.

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

The Extended-hours Equity Overlay is provisional. It watches whether SOXX is materially lagging QQQ and whether NVDA is materially lagging SOXX during pre-market or after-market trading. It does not change `stress.score`, and it does not by itself confirm credit stress. The official stress score remains close-based.

## Limitations

- Market data can lag, revise, or fail if a public source is unavailable.
- Extended-hours data may be unavailable or stale; when that happens the dashboard shows the overlay as unavailable and keeps the official close-based score unchanged.
- Manual compute / financing signals are intentionally simple and auditable.
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
