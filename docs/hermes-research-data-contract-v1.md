# Hermes Research Data Contract v1

Hermes is a research-only producer. It writes `hermes_digest.md` for people and
`hermes_candidate.json` for the validator. It must never write `data/latest.json`,
market-score code, configuration, or a dashboard production state.

## Candidate shape

The candidate uses `schema_version: "hermes-research-v1"` and includes `run`,
`sources`, `metrics`, `evidence`, `theses`, `constraints`, `cycle_assessment`,
`risk_flags`, `agent_change_summary`, and `quality`. `run.status` is one of
`complete`, `partial`, or `failed`; its required identifiers are `run_id`,
`generated_at`, `research_cutoff`, `previous_run_id`, and `agent`.

Sources have an `id`, date, URL, publisher, and tier. Tiers describe source
quality, independently of evidence classification:

| Tier | Source |
| --- | --- |
| 1 | SEC/regulator/company filing, official IR, or official technical documentation |
| 2 | Reuters, Bloomberg, FT, WSJ, or comparable independent financial reporting |
| 3 | Named sell-side or credible specialist industry research |
| 4 | Aggregation, uncertain trade press, social, Reddit, X, YouTube, etc. |

Evidence classification is `[C]` confirmed fact, `[G]` management guidance,
`[E]` estimate, or `[I]` inference. Management guidance remains `[G]`, even
when its source is Tier 1. Tier-4 material can create a `watch`, but never alone
supports `confirmed`.

Each thesis has an `id`, `pillar`, `title`, `claim`, `status`, `prior_status`,
`direction`, `raw_confidence`, `evidence_ids`, `watch_trigger`,
`confirmation_trigger`, and `invalidation_trigger`. Statuses are `confirmed`,
`watch`, `invalidated`, and `indeterminate`.

Each numeric metric carries `entity`, `metric`, `value` or `range`, `unit`,
`period`, `period_type`, `classification`, `basis`, `as_of`, `source_ids`, and
`comparability` (`comparable`, `partial`, or `not_comparable`). Capex metrics
also carry `capex_basis`: `cash_capex`, `pp&e_additions`,
`including_finance_leases`, `company_defined`, or `unknown`. A metric for
Rubin/GPU/HBM must state `measurement_scope` such as `production_target`,
`shipment`, `rack_units`, or `gpu_units`.

## Deterministic promotion

The validator, rather than Hermes, determines publishability, status, and
confidence. A `confirmed` thesis requires either a supporting Tier-1 factual
premise or two independent Tier-2 sources, with no unresolved material
contradiction. It caps confidence at 1.00 with Tier 1, 0.85 with two independent
Tier 2 sources, 0.65 for Tier 3 only, 0.35 for Tier 4 only, and 0.50 whenever a
material contradiction is unresolved.

The validator writes only `data/hermes/latest.json` and appends successful,
unique runs to `data/hermes/history.jsonl`. It records attempted validation in
`data/hermes/validation.json`. A failed candidate cannot replace the prior
validated state.

## Automation boundary

No cron, integration, browser automation, messaging, trading simulation, or
financial-account connection is part of v1. Future automation may give Hermes a
restricted candidate-inbox/branch only; a GitHub Action validator may promote
validated research. Hermes must never receive write access to the official
market state or scoring logic.
