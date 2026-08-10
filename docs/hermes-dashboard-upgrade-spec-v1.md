# Hermes Dashboard Upgrade v1

The dashboard has two visibly separate layers. The existing close-based Market
Sensor and Regime Engine remains authoritative and unchanged. Hermes is a
research-only intelligence layer, read exclusively from `data/hermes/latest.json`.
It never changes the official stress score, regime, or market data.

The homepage adds a compact Intelligence Layer containing:

1. **What Changed?** — deterministic changes against the preceding validated run.
2. **Seven-Pillar Thesis Monitor** — Hyperscaler Capex, GPUs, HBM, Networking,
   AI Monetisation, Credit Stress, and China AI; details expand in place.
3. **AI Infrastructure Constraint Map** — current/emerging/normal technical and
   financial bottlenecks.
4. **CAPEX → Monetisation → Cash Flow** — normalized issuer metrics, not a
   synthetic score. This fills the existing CAPEX-return coverage gap.

The deterministic Market × Research synthesis is one of `RESEARCH_LEADS`,
`MARKET_CONFIRMED`, `MARKET_LEADS`, `ALIGNED_NORMAL`, `DIVERGENT`, or
`INSUFFICIENT_DATA`. For example, a rising Hermes Credit Stress `watch` while
the official Credit Pressure remains `NORMAL` renders `RESEARCH_LEADS`: an
issuer-specific concern is present but broad IG/HY has not confirmed it.

Hermes may show its cycle assessment (`expansion`, `late_expansion`,
`financial_strain`, `contraction`, `recovery`, or `indeterminate`) only as
“Hermes research view.” It is not a market score or traffic light.

When validation fails or no research exists, the market cockpit still renders.
The intelligence layer uses the last valid research state when available and
clearly labels it stale/failed; it never invents a replacement state.

## Trigger and promotion boundary

Hermes' existing weekly research schedule remains separate from the dashboard.
The dashboard's **Run Hermes research** control links to a manual GitHub
Actions workflow. GitHub, rather than the static page, holds the webhook
secret and requests a Hermes research pass. The page never calls Hermes
directly and never contains a credential.

Hermes writes only `incoming/hermes_candidate.json` and
`incoming/hermes_digest.md` to the restricted `hermes-candidates` branch. A
second GitHub Actions workflow reads that branch, runs
`scripts/validate_hermes.py`, and may promote only `data/hermes/` to `main`.
Failed candidates retain the preceding `data/hermes/latest.json` and publish a
validation report marking the research layer stale. Hermes has no authority to
write market data, scoring code, configuration, or `main`.

Repository secrets required for the manual trigger are `HERMES_WEBHOOK_URL`
and `HERMES_WEBHOOK_SECRET`. Their values are configured in GitHub, never
committed to this repository.
