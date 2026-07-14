# AGENTS.md

This repo builds the AI Infrastructure Stress Cockpit.

Rules:
- Build a static dashboard only.
- Use GitHub Actions as the scheduled data pipeline.
- No Streamlit.
- No backend server.
- No database.
- No paid data dependency.
- Keep the MVP small, readable, and auditable.
- Use the mock-up at docs/design/ai_infrastructure_stress_cockpit_mockup.png as the UI design source of truth.
- Do not create a generic finance dashboard.
- Do not add extra features unless requested.
- All dashboard values must come from data/latest.json and data/history.csv.
- Rule-based scoring only. No machine learning.

## Shared loop-engineering baseline

A Codex turn ending is not completion. Completion requires evidence from the applicable gates below.

Use this execution loop for every task:
1. Inspect the repo instructions and relevant files.
2. Restate the acceptance criteria, exact edit surface, and out-of-scope areas.
3. Implement the smallest coherent change.
4. Run targeted checks for the changed behavior.
5. Run the full applicable test suite and relevant formatter, lint, type-check, schema, build, or generated-file checks.
6. Review the complete diff against every acceptance criterion and project constraint.
7. Repair failures and re-test, with at most three repair cycles.
8. If the same failure repeats twice without meaningful new evidence, stop and report the exact blocker, commands run, relevant failing output, and likely root cause. Do not claim completion.

Completion gates:
- All acceptance criteria are implemented, including relevant error and edge paths.
- Targeted tests pass.
- The full applicable suite and relevant validation checks pass; explain anything unavailable or intentionally skipped.
- `git diff --check` passes.
- Documentation, schemas, fixtures, and generated files are updated when affected.
- The final diff contains no unintended changes and the working tree is in the expected state.
- Commit or push only when explicitly requested and only after the gates pass.

Keep the active context concise. Save long logs to `/tmp` or a repo-local report, quote only relevant failing lines, and after each repair cycle summarize the current state, remaining failure, and next hypothesis. Use the fewest clear tools needed and keep repeatable actions idempotent where practical.

The final report must include changed files, checks and results, branch, commit SHA when committed, push status when requested, working-tree state, manual verification when relevant, and residual risks.
