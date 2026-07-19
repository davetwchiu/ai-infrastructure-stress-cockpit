#!/usr/bin/env python3
"""Enrich data/latest.json with hyperscaler funding and cash-flow stress signals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
LATEST_PATH = ROOT / "data" / "latest.json"
MANUAL_PATH = ROOT / "config" / "hyperscaler_credit_signals.json"
CACHE_PATH = ROOT / "data" / "hyperscaler_credit.json"
CACHE_MAX_AGE_HOURS = 6
SEC_COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{}.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{}.json"
SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}"
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "AIInfrastructureStressCockpit/1.1 contact: no-email",
)
HYPERSCALERS = {
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "META": "Meta",
    "ORCL": "Oracle",
}
COMPONENT_WEIGHTS = {
    "bond_issuance": 0.15,
    "credit_spreads": 0.25,
    "rating_changes": 0.20,
    "capex_to_ocf": 0.25,
    "fcf_revisions": 0.15,
}
OCF_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForAdditionsToPropertyPlantAndEquipment",
]
DEBT_TERMS = (
    "senior notes",
    "notes due",
    "debt securities",
    "term loan",
    "credit agreement",
    "revolving credit facility",
)


def clamp(value: float) -> int:
    return round(max(0, min(100, value)))


def score_label(score: int) -> str:
    if score >= 71:
        return "CREDIT STRESS CONFIRMED"
    if score >= 51:
        return "STRESS"
    if score >= 26:
        return "WATCH"
    return "NORMAL"


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return None


def fetch_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": SEC_USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": SEC_USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="ignore")


def get_ciks(fetcher: Callable[[str], dict[str, Any]] = fetch_json) -> tuple[dict[str, str], str]:
    try:
        rows = fetcher(SEC_COMPANY_TICKERS).values()
        wanted = set(HYPERSCALERS)
        mapping = {
            str(row.get("ticker", "")).upper(): str(row["cik_str"]).zfill(10)
            for row in rows
            if str(row.get("ticker", "")).upper() in wanted
        }
        return mapping, "ok" if len(mapping) == len(wanted) else "partial"
    except Exception:
        return {}, "failed"


def fact_rows(companyfacts: dict[str, Any], tags: list[str]) -> list[dict[str, Any]]:
    gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    rows: list[dict[str, Any]] = []
    for tag in tags:
        for unit, unit_rows in gaap.get(tag, {}).get("units", {}).items():
            if unit != "USD":
                continue
            for row in unit_rows:
                if row.get("form") not in {"10-Q", "10-K", "20-F", "6-K"}:
                    continue
                if row.get("val") is None or not row.get("start") or not row.get("end"):
                    continue
                rows.append({**row, "tag": tag})
    return rows


def matched_cashflow_period(companyfacts: dict[str, Any]) -> dict[str, Any] | None:
    ocf_rows = fact_rows(companyfacts, OCF_TAGS)
    capex_rows = fact_rows(companyfacts, CAPEX_TAGS)
    ocf_map: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    capex_map: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def key(row: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(row.get("accn", "")),
            str(row.get("start", "")),
            str(row.get("end", "")),
            str(row.get("form", "")),
        )

    for row in ocf_rows:
        ocf_map[key(row)] = row
    for row in capex_rows:
        capex_map[key(row)] = row

    pairs = []
    for pair_key in set(ocf_map) & set(capex_map):
        ocf = ocf_map[pair_key]
        capex = capex_map[pair_key]
        filed = parse_date(str(ocf.get("filed") or capex.get("filed") or ""))
        end = parse_date(str(ocf.get("end") or ""))
        if not filed or not end:
            continue
        ocf_value = float(ocf["val"])
        capex_value = abs(float(capex["val"]))
        if ocf_value <= 0:
            continue
        pairs.append((filed, end, ocf, capex, ocf_value, capex_value))

    if not pairs:
        return None
    filed, end, ocf, capex, ocf_value, capex_value = max(pairs, key=lambda item: (item[0], item[1]))
    ratio = capex_value / ocf_value
    return {
        "period_start": ocf.get("start"),
        "period_end": ocf.get("end"),
        "filing_date": filed.isoformat(),
        "form": ocf.get("form"),
        "fiscal_year": ocf.get("fy"),
        "fiscal_period": ocf.get("fp"),
        "operating_cash_flow": round(ocf_value, 2),
        "capex": round(capex_value, 2),
        "capex_to_ocf": round(ratio, 3),
        "fcf_proxy": round(ocf_value - capex_value, 2),
        "ocf_tag": ocf.get("tag"),
        "capex_tag": capex.get("tag"),
    }


def capex_ratio_score(ratio: float) -> int:
    if ratio <= 0.40:
        return 15
    if ratio <= 0.60:
        return 30
    if ratio <= 0.80:
        return 45
    if ratio <= 1.00:
        return 60
    if ratio <= 1.25:
        return 75
    if ratio <= 1.50:
        return 85
    return 95


def build_capex_component(
    ciks: dict[str, str],
    fetcher: Callable[[str], dict[str, Any]] = fetch_json,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issuers: list[dict[str, Any]] = []
    scores: list[int] = []
    for ticker, name in HYPERSCALERS.items():
        cik = ciks.get(ticker)
        if not cik:
            issuers.append({"ticker": ticker, "name": name, "data_status": "missing_cik"})
            continue
        try:
            facts = fetcher(SEC_FACTS.format(cik))
            period = matched_cashflow_period(facts)
        except Exception as exc:
            issuers.append({"ticker": ticker, "name": name, "data_status": "failed", "error": str(exc)})
            continue
        if not period:
            issuers.append({"ticker": ticker, "name": name, "data_status": "unavailable"})
            continue
        issuer_score = capex_ratio_score(float(period["capex_to_ocf"]))
        scores.append(issuer_score)
        issuers.append({
            "ticker": ticker,
            "name": name,
            "data_status": "ok",
            "score": issuer_score,
            **period,
        })

    if not scores:
        return {
            "score": None,
            "status": "failed",
            "weight": COMPONENT_WEIGHTS["capex_to_ocf"],
            "evidence_count": 0,
        }, issuers
    aggregate = clamp(sum(scores) / len(scores) * 0.7 + max(scores) * 0.3)
    status = "ok" if len(scores) == len(HYPERSCALERS) else "partial"
    return {
        "score": aggregate,
        "status": status,
        "weight": COMPONENT_WEIGHTS["capex_to_ocf"],
        "evidence_count": len(scores),
    }, issuers


def filing_document_url(cik: str, accession: str, primary_document: str) -> str:
    return SEC_ARCHIVE.format(int(cik), accession.replace("-", ""), primary_document)


def detect_bond_events(
    ciks: dict[str, str],
    today: date,
    json_fetcher: Callable[[str], dict[str, Any]] = fetch_json,
    text_fetcher: Callable[[str], str] = fetch_text,
) -> tuple[list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    failures = 0
    for ticker in HYPERSCALERS:
        cik = ciks.get(ticker)
        if not cik:
            failures += 1
            continue
        try:
            recent = json_fetcher(SEC_SUBMISSIONS.format(cik)).get("filings", {}).get("recent", {})
        except Exception:
            failures += 1
            continue
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        documents = recent.get("primaryDocument", [])
        items = recent.get("items", [])
        for i, raw_form in enumerate(forms):
            form = str(raw_form).upper()
            filing_day = parse_date(dates[i] if i < len(dates) else None)
            if not filing_day or not 0 <= (today - filing_day).days <= 120:
                continue
            item_text = str(items[i] if i < len(items) else "")
            potential = form.startswith("424B") or (form == "8-K" and any(code in item_text for code in ("1.01", "2.03")))
            if not potential:
                continue
            accession = str(accessions[i] if i < len(accessions) else "")
            document = str(documents[i] if i < len(documents) else "")
            text = ""
            if accession and document:
                try:
                    text = re.sub(r"<[^>]+>", " ", text_fetcher(filing_document_url(cik, accession, document))).lower()
                except Exception:
                    text = ""
            matched_terms = [term for term in DEBT_TERMS if term in text]
            item_confirms_debt = form == "8-K" and "2.03" in item_text
            if not matched_terms and not item_confirms_debt:
                continue
            event_type = "bond_issuance_filing" if any(term in text for term in ("senior notes", "notes due", "debt securities")) else "financing_filing"
            events.append({
                "ticker": ticker,
                "category": "bond_issuance",
                "event_type": event_type,
                "date": filing_day.isoformat(),
                "form": form,
                "accession_number": accession,
                "matched_terms": matched_terms[:3],
                "source": "SEC EDGAR filing",
                "summary": "Debt-related prospectus or financing filing detected; review terms before treating it as stress.",
            })
    status = "failed" if failures == len(HYPERSCALERS) else "partial" if failures else "ok"
    return sorted(events, key=lambda item: item["date"], reverse=True)[:20], status


def current_manual_rows(rows: list[dict[str, Any]], today: date, max_age_days: int = 180) -> list[dict[str, Any]]:
    current = []
    for row in rows:
        event_day = parse_date(str(row.get("date") or row.get("as_of") or ""))
        if event_day and 0 <= (today - event_day).days <= max_age_days:
            current.append(row)
    return current


def build_manual_components(manual: dict[str, Any], today: date, broad_ig_change_bps: float | None) -> dict[str, dict[str, Any]]:
    rating_rows = current_manual_rows(list(manual.get("rating_events", [])), today)
    spread_rows = current_manual_rows(list(manual.get("spread_observations", [])), today, 90)
    fcf_rows = current_manual_rows(list(manual.get("fcf_revisions", [])), today, 180)

    if spread_rows:
        changes = [float(row.get("change_30d_bps", 0)) for row in spread_rows]
        spread_score = clamp(20 + max(max(changes), 0) * 2.0)
        spread_status = "manual"
    elif broad_ig_change_bps is not None:
        spread_score = clamp(20 + max(broad_ig_change_bps, 0) * 2.0)
        spread_status = "broad_proxy"
    else:
        spread_score = None
        spread_status = "unmonitored"

    rating_score = None
    if rating_rows:
        points = []
        for row in rating_rows:
            action = str(row.get("action", "")).lower()
            notches = abs(int(row.get("notches", 1) or 1))
            if "downgrade" in action:
                points.append(min(95, 55 + notches * 15))
            elif "negative" in action:
                points.append(50)
            elif "upgrade" in action or "positive" in action:
                points.append(10)
            else:
                points.append(30)
        rating_score = max(points)

    fcf_score = None
    if fcf_rows:
        revisions = [float(row.get("revision_pct", 0)) for row in fcf_rows]
        worst = min(revisions)
        fcf_score = clamp(20 + max(-worst, 0) * 2.5 - max(worst, 0))

    return {
        "credit_spreads": {
            "score": spread_score,
            "status": spread_status,
            "weight": COMPONENT_WEIGHTS["credit_spreads"],
            "evidence_count": len(spread_rows),
            "observations": spread_rows,
            "broad_ig_change_bps": broad_ig_change_bps,
        },
        "rating_changes": {
            "score": rating_score,
            "status": "manual" if rating_rows else "unmonitored",
            "weight": COMPONENT_WEIGHTS["rating_changes"],
            "evidence_count": len(rating_rows),
            "events": rating_rows,
        },
        "fcf_revisions": {
            "score": fcf_score,
            "status": "manual" if fcf_rows else "unmonitored",
            "weight": COMPONENT_WEIGHTS["fcf_revisions"],
            "evidence_count": len(fcf_rows),
            "observations": fcf_rows,
        },
    }


def bond_component(auto_events: list[dict[str, Any]], manual: dict[str, Any], today: date, auto_status: str) -> dict[str, Any]:
    manual_rows = current_manual_rows(list(manual.get("bond_events", [])), today)
    combined = auto_events + [{**row, "source": row.get("source", "Manual review")} for row in manual_rows]
    manual_points = [float(row.get("stress_points", 0)) for row in manual_rows]
    score = None if auto_status == "failed" and not manual_rows else clamp(15 + min(len(auto_events) * 4, 24) + min(sum(manual_points), 40))
    return {
        "score": score,
        "status": auto_status if not manual_rows else "ok" if auto_status == "ok" else "partial",
        "weight": COMPONENT_WEIGHTS["bond_issuance"],
        "evidence_count": len(combined),
        "events": sorted(combined, key=lambda item: str(item.get("date", "")), reverse=True)[:20],
    }


def broad_ig_change_from_latest(latest: dict[str, Any]) -> float | None:
    metric = next((row for row in latest.get("hard_data", []) if row.get("key") == "ig_oas"), None)
    if not metric:
        return None
    try:
        return float(metric.get("change_20d")) * 100
    except (TypeError, ValueError):
        return None


def composite_score(components: dict[str, dict[str, Any]]) -> tuple[int | None, float]:
    numerator = 0.0
    denominator = 0.0
    for key, component in components.items():
        score = component.get("score")
        weight = float(component.get("weight", COMPONENT_WEIGHTS.get(key, 0)))
        if score is None:
            continue
        numerator += float(score) * weight
        denominator += weight
    if denominator == 0:
        return None, 0.0
    return clamp(numerator / denominator), round(denominator, 2)


def build_hyperscaler_credit(
    latest: dict[str, Any],
    manual: dict[str, Any],
    now: datetime | None = None,
    json_fetcher: Callable[[str], dict[str, Any]] = fetch_json,
    text_fetcher: Callable[[str], str] = fetch_text,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    ciks, cik_status = get_ciks(json_fetcher)
    capex, issuers = build_capex_component(ciks, json_fetcher) if ciks else (
        {"score": None, "status": "failed", "weight": COMPONENT_WEIGHTS["capex_to_ocf"], "evidence_count": 0},
        [{"ticker": ticker, "name": name, "data_status": "missing_cik"} for ticker, name in HYPERSCALERS.items()],
    )
    auto_bonds, auto_bond_status = detect_bond_events(ciks, today, json_fetcher, text_fetcher) if ciks else ([], "failed")
    manual_components = build_manual_components(manual, today, broad_ig_change_from_latest(latest))
    components = {
        "bond_issuance": bond_component(auto_bonds, manual, today, auto_bond_status),
        "credit_spreads": manual_components["credit_spreads"],
        "rating_changes": manual_components["rating_changes"],
        "capex_to_ocf": capex,
        "fcf_revisions": manual_components["fcf_revisions"],
    }
    score, coverage = composite_score(components)
    missing = [key for key, value in components.items() if value.get("score") is None]
    caveats = [
        "Bond issuance is a monitoring signal, not proof of distress; terms and use of proceeds still matter.",
        "SEC cash-flow facts are matched within the same filing period; company tagging can still vary.",
        "Issuer credit spreads, rating actions, and analyst FCF revisions require dated manual observations when no stable free feed is available.",
    ]
    if missing:
        caveats.append("Unmonitored components: " + ", ".join(missing) + ".")
    if cik_status != "ok":
        caveats.append("SEC ticker mapping or issuer coverage is partial.")
    status = score_label(score) if score is not None else "UNMONITORED"
    data_status = "ok" if coverage >= 0.99 and all(value.get("status") in {"ok", "manual"} for value in components.values()) else "partial" if coverage > 0 else "failed"
    return {
        "score": score,
        "status": status,
        "data_status": data_status,
        "coverage_ratio": coverage,
        "generated_at": now.isoformat(timespec="seconds"),
        "manual_reviewed_through": manual.get("reviewed_through"),
        "manual_input_hash": manual_hash(manual),
        "components": components,
        "issuers": issuers,
        "events": components["bond_issuance"].get("events", []) + components["rating_changes"].get("events", []),
        "caveats": caveats,
        "source_summary": "SEC EDGAR companyfacts and filings, broad IG OAS fallback, and dated manual observations.",
    }


def manual_hash(manual: dict[str, Any]) -> str:
    payload = json.dumps(manual, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def load_cached_credit(path: Path, manual: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text())
        generated = datetime.fromisoformat(str(cached.get("generated_at", "")))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        age_hours = (now - generated.astimezone(timezone.utc)).total_seconds() / 3600
        if 0 <= age_hours < CACHE_MAX_AGE_HOURS and cached.get("manual_input_hash") == manual_hash(manual):
            return cached
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return None


def load_manual(path: Path = MANUAL_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def enrich(
    latest_path: Path = LATEST_PATH,
    manual_path: Path = MANUAL_PATH,
    cache_path: Path = CACHE_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    latest = json.loads(latest_path.read_text())
    manual = load_manual(manual_path)
    credit = load_cached_credit(cache_path, manual, now)
    if credit is None:
        credit = build_hyperscaler_credit(latest, manual, now=now)
        cache_path.parent.mkdir(exist_ok=True)
        cache_path.write_text(json.dumps(credit, indent=2) + "\n")
    latest["hyperscaler_credit"] = credit
    sources = list(latest.get("sources", []))
    for source in (
        "SEC EDGAR hyperscaler filings",
        "SEC EDGAR hyperscaler companyfacts",
        "config/hyperscaler_credit_signals.json",
    ):
        if source not in sources:
            sources.append(source)
    latest["sources"] = sources
    latest_path.write_text(json.dumps(latest, indent=2) + "\n")
    return latest


def self_test() -> None:
    facts = {
        "facts": {
            "us-gaap": {
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {"USD": [{
                        "val": 1000,
                        "start": "2026-01-01",
                        "end": "2026-03-31",
                        "filed": "2026-04-25",
                        "form": "10-Q",
                        "fy": 2026,
                        "fp": "Q1",
                        "accn": "0001",
                    }]}
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {"USD": [{
                        "val": 800,
                        "start": "2026-01-01",
                        "end": "2026-03-31",
                        "filed": "2026-04-25",
                        "form": "10-Q",
                        "fy": 2026,
                        "fp": "Q1",
                        "accn": "0001",
                    }]}
                },
            }
        }
    }
    period = matched_cashflow_period(facts)
    assert period is not None
    assert period["capex_to_ocf"] == 0.8
    assert period["fcf_proxy"] == 200
    assert capex_ratio_score(0.39) == 15
    assert capex_ratio_score(0.8) == 45
    assert capex_ratio_score(1.6) == 95

    manual = {
        "spread_observations": [{"issuer": "ORCL", "as_of": "2026-07-01", "change_30d_bps": 20}],
        "rating_events": [{"issuer": "ORCL", "date": "2026-07-01", "action": "downgrade", "notches": 1}],
        "fcf_revisions": [{"issuer": "AMZN", "as_of": "2026-07-01", "revision_pct": -20}],
    }
    components = build_manual_components(manual, date(2026, 7, 19), 3)
    assert components["credit_spreads"]["score"] == 60
    assert components["rating_changes"]["score"] == 70
    assert components["fcf_revisions"]["score"] == 70

    score, coverage = composite_score({
        "bond_issuance": {"score": 20, "weight": .15},
        "credit_spreads": {"score": 60, "weight": .25},
        "rating_changes": {"score": None, "weight": .20},
        "capex_to_ocf": {"score": 60, "weight": .25},
        "fcf_revisions": {"score": None, "weight": .15},
    })
    assert score == 51
    assert coverage == .65

    assert manual_hash({"a": 1}) == manual_hash({"a": 1})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    enrich()


if __name__ == "__main__":
    main()
