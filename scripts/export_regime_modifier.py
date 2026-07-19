#!/usr/bin/env python3
"""Export a compact, stable regime modifier for the AI CAPEX dashboard."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LATEST_PATH = ROOT / "data" / "latest.json"
OUTPUT_PATH = ROOT / "data" / "regime_modifier.json"


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def risk_label(score: float | None) -> str:
    if score is None:
        return "UNMONITORED"
    if score >= 71:
        return "CREDIT STRESS CONFIRMED"
    if score >= 51:
        return "STRESS"
    if score >= 26:
        return "WATCH"
    return "NORMAL"


def build_modifier(latest: dict[str, Any]) -> dict[str, Any]:
    hyperscaler = latest.get("hyperscaler_credit", {})
    neocloud = latest.get("compute_stress", {})
    equity = next(
        (driver for driver in latest.get("drivers", []) if driver.get("key") == "equity"),
        {},
    )
    hyperscaler_score = number(hyperscaler.get("score"))
    neocloud_score = number(neocloud.get("score"))
    equity_score = number(equity.get("score"))
    return {
        "schema_version": 1,
        "as_of": hyperscaler.get("generated_at") or latest.get("updated_at"),
        "source_repo": "davetwchiu/ai-infrastructure-stress-cockpit",
        "hyperscaler_funding": {
            "score": hyperscaler_score,
            "status": hyperscaler.get("status") or risk_label(hyperscaler_score),
            "coverage_ratio": number(hyperscaler.get("coverage_ratio")) or 0.0,
            "data_status": hyperscaler.get("data_status", "unknown"),
        },
        "neocloud_financing": {
            "score": neocloud_score,
            "status": risk_label(neocloud_score),
            "data_status": neocloud.get("status", "unknown"),
        },
        "market_plumbing": {
            "score": equity_score,
            "status": equity.get("status") or risk_label(equity_score),
            "data_status": "ok" if equity_score is not None else "unavailable",
        },
        "source_summary": (
            "Hyperscaler funding and cash stress, neocloud financing stress, and "
            "market-plumbing confirmation from the AI Infrastructure Stress Cockpit."
        ),
        "guardrail": (
            "Diagnostic cross-dashboard input only; the consumer must not use this file "
            "to recalculate market-derived regime scores."
        ),
    }


def export_modifier(
    latest_path: Path = LATEST_PATH,
    output_path: Path = OUTPUT_PATH,
) -> dict[str, Any]:
    latest = json.loads(latest_path.read_text())
    modifier = build_modifier(latest)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(modifier, indent=2) + "\n")
    return modifier


def self_test() -> None:
    modifier = build_modifier({
        "updated_at": "2026-07-19T07:00:00+00:00",
        "hyperscaler_credit": {
            "score": 43,
            "status": "WATCH",
            "coverage_ratio": 0.65,
            "data_status": "partial",
        },
        "compute_stress": {"score": 77, "status": "ok"},
        "drivers": [{"key": "equity", "score": 50, "status": "WATCH"}],
    })
    assert modifier["hyperscaler_funding"]["score"] == 43
    assert modifier["neocloud_financing"]["status"] == "CREDIT STRESS CONFIRMED"
    assert modifier["market_plumbing"]["status"] == "WATCH"
    assert modifier["schema_version"] == 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("regime modifier self-test passed")
    else:
        result = export_modifier()
        print(f"wrote regime modifier as of {result.get('as_of')}")


if __name__ == "__main__":
    main()
