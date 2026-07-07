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
