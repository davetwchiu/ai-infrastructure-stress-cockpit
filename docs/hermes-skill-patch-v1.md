# Proposed Hermes Skill Patch v1

Keep the existing seven pillars and all research-only constraints. Add:

- Emit `hermes_digest.md` and a candidate conforming to the v1 contract.
- Apply the source tiers and C/G/E/I evidence labels; Tier 4 is a watch lead only.
- Normalize each metric with period, basis, units, sources, and comparability;
  use the explicit capex and GPU/Rubin/HBM fields.
- Treat candidate status and confidence as provisional. The deterministic
  validator decides promotion, validated confidence, and changes.
- Never modify dashboard market scoring, `data/latest.json`, configuration, or
  any production state; never generate trade implications or execute trades.
