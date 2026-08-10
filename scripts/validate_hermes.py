#!/usr/bin/env python3
"""Validate Hermes research candidates without touching official market state."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE = ROOT / "hermes_candidate.json"
DEFAULT_MARKET = ROOT / "data" / "latest.json"
DEFAULT_OUTPUT = ROOT / "data" / "hermes" / "latest.json"
DEFAULT_HISTORY = ROOT / "data" / "hermes" / "history.jsonl"
DEFAULT_REPORT = ROOT / "data" / "hermes" / "validation.json"
REQUIRED = {
    "top": ("schema_version", "run", "sources", "metrics", "evidence", "theses", "constraints", "cycle_assessment", "risk_flags", "agent_change_summary", "quality"),
    "run": ("run_id", "generated_at", "research_cutoff", "previous_run_id", "agent", "status"),
    "source": ("id", "title", "publisher", "url", "published_at", "tier"),
    "metric": ("id", "entity", "metric", "unit", "period", "period_type", "classification", "basis", "as_of", "source_ids", "comparability"),
    "evidence": ("id", "classification", "source_id", "summary", "published_at"),
    "thesis": ("id", "pillar", "title", "claim", "status", "prior_status", "direction", "raw_confidence", "evidence_ids", "watch_trigger", "confirmation_trigger", "invalidation_trigger"),
}
THESIS_STATUSES = {"confirmed", "watch", "invalidated", "indeterminate"}
CYCLE_STATES = {"expansion", "late_expansion", "financial_strain", "contraction", "recovery", "indeterminate"}


def issue(code: str, message: str, **context: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **context}


def missing_fields(item: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    # An initial run legitimately has no predecessor; required here means present.
    return [field for field in fields if field not in item or (item[field] in (None, "") and field != "previous_run_id")]


def confidence_cap(evidence: list[dict[str, Any]], sources: dict[str, dict[str, Any]], contradiction: bool) -> float:
    tiers = [sources.get(item.get("source_id"), {}).get("tier") for item in evidence]
    tier_2_groups = {
        str(sources[item["source_id"]].get("independence_group") or sources[item["source_id"]].get("publisher")).lower()
        for item in evidence if sources.get(item.get("source_id"), {}).get("tier") == 2
    }
    cap = 1.0 if 1 in tiers else 0.85 if len(tier_2_groups) >= 2 else 0.35 if tiers and all(tier == 4 for tier in tiers) else 0.65
    return min(cap, 0.50) if contradiction else cap


def confirmed_gate(evidence: list[dict[str, Any]], sources: dict[str, dict[str, Any]]) -> bool:
    tier_1_fact = any(item.get("classification") == "C" and sources.get(item.get("source_id"), {}).get("tier") == 1 for item in evidence)
    tier_2_groups = {
        str(sources[item["source_id"]].get("independence_group") or sources[item["source_id"]].get("publisher")).lower()
        for item in evidence if sources.get(item.get("source_id"), {}).get("tier") == 2
    }
    return tier_1_fact or len(tier_2_groups) >= 2


def market_research_synthesis(market: dict[str, Any], theses: list[dict[str, Any]]) -> dict[str, Any]:
    credit = next((driver for driver in market.get("drivers", []) if driver.get("key") == "credit"), {})
    research = next((thesis for thesis in theses if str(thesis.get("pillar", "")).lower() == "credit stress"), None)
    if not credit or not research:
        return {"state": "INSUFFICIENT_DATA", "interpretation": "Broad-credit or validated Credit Stress research data is unavailable."}
    market_status = str(credit.get("status", "")).upper()
    research_status = research.get("validated_status", research.get("status"))
    research_rising = research_status in {"watch", "confirmed"} and research.get("direction") in {"rising", "worsening"}
    market_active = market_status not in {"", "NORMAL", "UNMONITORED"}
    if research_rising and not market_active:
        state = "RESEARCH_LEADS"
        text = "Issuer-specific / AI financing concern has appeared, but broad IG/HY markets have not confirmed it."
    elif research_rising and market_active:
        state = "MARKET_CONFIRMED"
        text = "Research concern and broad market credit pressure are both present."
    elif market_active and research_status in {"indeterminate", "invalidated"}:
        state = "MARKET_LEADS"
        text = "Broad market credit is moving before the validated research monitor confirms the same concern."
    elif not market_active and research_status in {"indeterminate", "invalidated"}:
        state = "ALIGNED_NORMAL"
        text = "Neither broad credit nor validated research currently confirms an AI financing concern."
    else:
        state = "DIVERGENT"
        text = "Market and research signals are not directionally aligned."
    return {"state": state, "interpretation": text, "official_market_credit": {"score": credit.get("score"), "status": credit.get("status")}, "research_credit_status": research_status}


def compute_changes(previous: dict[str, Any] | None, current: list[dict[str, Any]], metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not previous:
        return [{"type": "new_thesis", "thesis_id": item["id"], "summary": f"New {item['pillar']} thesis.", "material": item["validated_status"] != "indeterminate"} for item in current]
    old_theses = {item.get("id"): item for item in previous.get("theses", [])}
    old_metrics = {(item.get("entity"), item.get("metric"), item.get("period")): item for item in previous.get("metrics", [])}
    changes: list[dict[str, Any]] = []
    for item in current:
        old = old_theses.get(item["id"])
        if not old:
            changes.append({"type": "new_thesis", "thesis_id": item["id"], "summary": f"New {item['pillar']} thesis.", "material": item["validated_status"] != "indeterminate"})
            continue
        old_status = old.get("validated_status", old.get("status"))
        if old_status != item["validated_status"]:
            changes.append({"type": "invalidated" if item["validated_status"] == "invalidated" else "status_change", "thesis_id": item["id"], "from": old_status, "to": item["validated_status"], "material": True})
        if abs(float(old.get("validated_confidence", 0)) - item["validated_confidence"]) >= .15:
            changes.append({"type": "confidence_change", "thesis_id": item["id"], "from": old.get("validated_confidence"), "to": item["validated_confidence"], "material": True})
        added = sorted(set(item.get("evidence_ids", [])) - set(old.get("evidence_ids", [])))
        if added:
            changes.append({"type": "new_material_evidence", "thesis_id": item["id"], "evidence_ids": added, "material": True})
    for metric in metrics:
        old = old_metrics.get((metric.get("entity"), metric.get("metric"), metric.get("period")))
        if old and metric.get("value") is not None and old.get("value") != metric.get("value"):
            changes.append({"type": "metric_revision", "metric_id": metric.get("id"), "from": old.get("value"), "to": metric.get("value"), "material": True})
    return changes


def validate_candidate(candidate: dict[str, Any], market: dict[str, Any], previous: dict[str, Any] | None = None, validated_at: str | None = None) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for name, fields in REQUIRED.items():
        items = [candidate] if name == "top" else candidate.get(f"{name}s", []) if name not in {"run"} else [candidate.get("run", {})]
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(issue("malformed_required_fields", f"{name} must be an object.", index=index))
                continue
            absent = missing_fields(item, fields)
            if absent:
                errors.append(issue("malformed_required_fields", f"{name} is missing required fields.", index=index, fields=absent))
    if candidate.get("schema_version") != "hermes-research-v1":
        errors.append(issue("schema_version", "Expected hermes-research-v1."))
    run = candidate.get("run", {})
    if run.get("status") not in {"complete", "partial", "failed"}:
        errors.append(issue("run_status", "Invalid run status."))
    if run.get("status") == "failed":
        errors.append(issue("agent_run_failed", "A failed agent run is never publishable."))
    if run.get("status") == "partial":
        warnings.append(issue("partial_research", "Candidate is partial."))

    sources = {item.get("id"): item for item in candidate.get("sources", []) if isinstance(item, dict)}
    evidence = {item.get("id"): item for item in candidate.get("evidence", []) if isinstance(item, dict)}
    for source in sources.values():
        if source.get("tier") not in {1, 2, 3, 4}:
            errors.append(issue("source_tier", "Source tier must be 1–4.", source_id=source.get("id")))
    for item in evidence.values():
        if item.get("classification") not in {"C", "G", "E", "I"}:
            errors.append(issue("evidence_classification", "Evidence classification must be C, G, E, or I.", evidence_id=item.get("id")))
        if item.get("source_id") not in sources:
            errors.append(issue("unknown_source", "Evidence references an unknown source.", evidence_id=item.get("id")))

    for metric in candidate.get("metrics", []):
        if not isinstance(metric, dict):
            continue
        if metric.get("classification") not in {"C", "G", "E", "I"}:
            errors.append(issue("metric_classification", "Metric classification must be C, G, E, or I.", metric_id=metric.get("id")))
        if metric.get("comparability") not in {"comparable", "partial", "not_comparable"}:
            errors.append(issue("metric_comparability", "Metric comparability is invalid.", metric_id=metric.get("id")))
        if "value" not in metric and "range" not in metric:
            errors.append(issue("ambiguous_metric", "Numeric metric requires value or range.", metric_id=metric.get("id")))
        if any(source_id not in sources for source_id in metric.get("source_ids", [])):
            errors.append(issue("unknown_source", "Metric references an unknown source.", metric_id=metric.get("id")))
        label = f"{metric.get('entity', '')} {metric.get('metric', '')}".lower()
        if "capex" in label and metric.get("capex_basis") not in {"cash_capex", "pp&e_additions", "including_finance_leases", "company_defined", "unknown"}:
            errors.append(issue("capex_basis", "Capex metric requires capex_basis.", metric_id=metric.get("id")))
        if metric.get("aggregation") and "capex" in label and metric.get("comparability") == "not_comparable":
            errors.append(issue("incomparable_capex_aggregation", "Not-comparable capex definitions cannot be aggregated.", metric_id=metric.get("id")))
        elif metric.get("aggregation") and "capex" in label and metric.get("comparability") != "comparable":
            warnings.append(issue("incomparable_capex_aggregation", "Capex aggregate is partial and must not imply a precise total.", metric_id=metric.get("id")))
        if any(term in label for term in ("rubin", "gpu", "hbm")) and metric.get("measurement_scope") not in {"production_target", "shipment", "rack_units", "gpu_units"}:
            warnings.append(issue("ambiguous_unit_period", "GPU/Rubin/HBM metric lacks a production/shipment/rack/GPU scope.", metric_id=metric.get("id")))

    validated_theses: list[dict[str, Any]] = []
    for thesis in candidate.get("theses", []):
        if not isinstance(thesis, dict):
            continue
        thesis_evidence = [evidence[evidence_id] for evidence_id in thesis.get("evidence_ids", []) if evidence_id in evidence]
        if len(thesis_evidence) != len(thesis.get("evidence_ids", [])):
            errors.append(issue("unknown_evidence", "Thesis references unknown evidence.", thesis_id=thesis.get("id")))
        if thesis.get("status") not in THESIS_STATUSES or thesis.get("prior_status") not in THESIS_STATUSES:
            errors.append(issue("thesis_status", "Thesis status is invalid.", thesis_id=thesis.get("id")))
        try:
            raw = float(thesis.get("raw_confidence"))
            if not 0 <= raw <= 1:
                raise ValueError
        except (TypeError, ValueError):
            raw = 0
            errors.append(issue("raw_confidence", "raw_confidence must be 0–1.", thesis_id=thesis.get("id")))
        contradiction = bool(thesis.get("unresolved_material_contradiction"))
        if contradiction:
            warnings.append(issue("unresolved_contradiction", "Material contradiction limits confidence.", thesis_id=thesis.get("id")))
        if len(thesis.get("inference_entities", [])) > 1 and not thesis.get("cross_entity_evidence_ids"):
            warnings.append(issue("unsupported_cross_entity_inference", "Cross-entity inference has no direct supporting evidence.", thesis_id=thesis.get("id")))
        if thesis.get("status") == "confirmed" and (contradiction or not confirmed_gate(thesis_evidence, sources)):
            errors.append(issue("confirmed_promotion_gate", "Confirmed thesis lacks required independent support or has a contradiction.", thesis_id=thesis.get("id")))
        tiers = [sources.get(item.get("source_id"), {}).get("tier") for item in thesis_evidence]
        if tiers and all(tier == 4 for tier in tiers):
            warnings.append(issue("low_quality_source_dependency", "Thesis depends only on Tier-4 material.", thesis_id=thesis.get("id")))
        validated = copy.deepcopy(thesis)
        validated["validated_status"] = thesis.get("status")
        validated["validated_confidence"] = round(min(raw, confidence_cap(thesis_evidence, sources, contradiction)), 2)
        validated_theses.append(validated)

    pillars = {item.get("pillar") for item in validated_theses}
    expected = {"Hyperscaler Capex", "GPUs", "HBM", "Networking", "AI Monetisation", "Credit Stress", "China AI"}
    if expected - pillars:
        warnings.append(issue("incomplete_pillars", "One or more seven-pillar topics is absent.", missing=sorted(expected - pillars)))
    if candidate.get("cycle_assessment", {}).get("state") not in CYCLE_STATES:
        errors.append(issue("cycle_state", "Cycle assessment state is invalid."))
    status = "fail" if errors else "pass_with_warnings" if warnings else "pass"
    output = {
        "schema_version": "hermes-validated-v1",
        "validation": {"status": status, "validated_at": validated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"), "candidate_run_id": run.get("run_id"), "errors": errors, "warnings": warnings, "stale": status == "fail"},
        "run": run,
        "sources": candidate.get("sources", []),
        "metrics": candidate.get("metrics", []),
        "evidence": candidate.get("evidence", []),
        "theses": validated_theses,
        "constraints": candidate.get("constraints", {}),
        "cycle_assessment": candidate.get("cycle_assessment", {}),
        "risk_flags": candidate.get("risk_flags", []),
        "agent_change_summary": candidate.get("agent_change_summary", ""),
        "quality": candidate.get("quality", {}),
    }
    output["changes"] = compute_changes(previous, validated_theses, output["metrics"])
    output["market_research_synthesis"] = market_research_synthesis(market, validated_theses)
    return output


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def write_validation_report(path: Path, result: dict[str, Any], previous: dict[str, Any] | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    report = dict(result["validation"])
    report["last_validated_at"] = previous.get("validation", {}).get("validated_at") if previous else None
    path.write_text(json.dumps(report, indent=2) + "\n")


def promote(candidate_path: Path, market_path: Path, output_path: Path, history_path: Path, report_path: Path) -> dict[str, Any]:
    candidate = json.loads(candidate_path.read_text())
    market = json.loads(market_path.read_text())
    previous = load_json(output_path)
    result = validate_candidate(candidate, market, previous)
    write_validation_report(report_path, result, previous)
    if result["validation"]["status"] == "fail":
        return result
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    history_path.parent.mkdir(parents=True, exist_ok=True)
    seen = history_path.read_text().splitlines() if history_path.exists() else []
    if not any(json.loads(line).get("run", {}).get("run_id") == result["run"].get("run_id") for line in seen if line.strip()):
        with history_path.open("a") as handle:
            handle.write(json.dumps(result, separators=(",", ":")) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    result = promote(args.candidate, args.market, args.output, args.history, args.report)
    print(f"Hermes validation {result['validation']['status']}: {result['run'].get('run_id')}")
    if result["validation"]["status"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
