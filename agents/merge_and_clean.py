import csv
import logging
from collections import Counter
from pathlib import Path

from config import DUBAI_CHAMBER_CODES_CSV, OUTPUT_COLUMNS, RAW_DIR, SOURCE_DUBAI_CHAMBER
from utils import (
    merge_notes,
    normalize_company_name,
    normalize_phone,
    run_stamp,
    setup_logger,
    utc_now_iso,
    validate_email,
    write_csv,
)


def read_raw_csvs():
    rows = []
    for source_dir in [RAW_DIR / "dubai_chamber", RAW_DIR / "sharjah_sedd", RAW_DIR / "dubai_ded"]:
        if not source_dir.exists():
            continue
        for path in source_dir.glob("*.csv"):
            with path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row["_raw_path"] = str(path)
                    rows.append(row)
    return rows


def best_activity(existing, new, new_source):
    if not existing:
        return new
    if new_source == SOURCE_DUBAI_CHAMBER and existing:
        return new or existing
    if new and len(new) > len(existing):
        return new
    return existing


def merge_rows(existing, incoming):
    existing_source = existing.get("source", "")
    incoming_source = incoming.get("source", "")

    existing_phone = existing.get("phone", "")
    incoming_phone = incoming.get("phone", "")
    if not existing_phone:
        existing["phone"] = incoming_phone
    elif existing_source != SOURCE_DUBAI_CHAMBER and incoming_source == SOURCE_DUBAI_CHAMBER:
        existing["phone"] = incoming_phone or existing_phone

    existing_email = existing.get("email", "")
    incoming_email = incoming.get("email", "")
    if not existing_email:
        existing["email"] = incoming_email
    elif existing_source != SOURCE_DUBAI_CHAMBER and incoming_source == SOURCE_DUBAI_CHAMBER:
        existing["email"] = incoming_email or existing_email

    existing["business_activity"] = best_activity(
        existing.get("business_activity", ""), incoming.get("business_activity", ""), incoming_source
    )

    if not existing.get("activity_code") and incoming.get("activity_code"):
        existing["activity_code"] = incoming.get("activity_code")

    if not existing.get("source_url") and incoming.get("source_url"):
        existing["source_url"] = incoming.get("source_url")

    if incoming_source == SOURCE_DUBAI_CHAMBER:
        existing["source"] = incoming_source

    existing["notes"] = merge_notes(existing.get("notes", ""), incoming.get("notes", ""))

    # last_seen_utc: pick latest
    existing_last = existing.get("last_seen_utc", "")
    incoming_last = incoming.get("last_seen_utc", "")
    if incoming_last and (not existing_last or incoming_last > existing_last):
        existing["last_seen_utc"] = incoming_last

    return existing


def main():
    stamp = run_stamp()
    log_path = Path("logs") / f"run_{stamp}.log"
    setup_logger(log_path)

    chamber_codes = []
    if DUBAI_CHAMBER_CODES_CSV.exists():
        with DUBAI_CHAMBER_CODES_CSV.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            field_map = {name.lstrip("\\ufeff").lower().strip(): name for name in (reader.fieldnames or []) if name}
            code_field = field_map.get("activity_code")
            if code_field:
                for row in reader:
                    code = (row.get(code_field) or "").strip()
                    if code:
                        chamber_codes.append(code)

    raw_rows = read_raw_csvs()
    if not raw_rows:
        logging.warning("No raw CSV files found in raw/ directories")
        return

    cleaned = []
    source_counts = Counter()
    chamber_code_counts = Counter()

    for row in raw_rows:
        company = (row.get("company_name") or "").strip()
        if not company:
            continue
        row["company_name"] = company

        original_email = (row.get("email") or "").strip()
        row["email"] = validate_email(original_email)
        if original_email and not row["email"]:
            row["notes"] = merge_notes(row.get("notes", ""), "email_invalid_removed")

        row["phone"] = (row.get("phone") or "").strip()

        row["last_seen_utc"] = row.get("last_seen_utc") or utc_now_iso()

        source = row.get("source", "")
        source_counts[source] += 1

        if source == SOURCE_DUBAI_CHAMBER:
            code = row.get("activity_code", "")
            if code:
                chamber_code_counts[code] += 1

        cleaned.append(row)

    merged = {}
    seen_exact = set()
    for idx, row in enumerate(cleaned):
        norm_name = normalize_company_name(row.get("company_name", ""))
        norm_email = row.get("email", "").lower().strip()
        norm_phone = normalize_phone(row.get("phone", ""))

        # Exact duplicate guard: only remove rows that are identical across key fields.
        exact_sig = (
            norm_name,
            norm_email,
            norm_phone,
            (row.get("business_activity") or "").strip().lower(),
            (row.get("source") or "").strip().lower(),
            (row.get("activity_code") or "").strip().lower(),
            (row.get("source_url") or "").strip().lower(),
            (row.get("emirate") or "").strip().lower(),
        )
        if exact_sig in seen_exact:
            continue
        seen_exact.add(exact_sig)

        # Safer dedupe: only merge when company name AND (email OR phone) match.
        if norm_name and norm_email:
            key = f"{norm_name}|{norm_email}"
        elif norm_name and norm_phone:
            key = f"{norm_name}|{norm_phone}"
        else:
            # No strong identifiers, keep as unique row.
            key = f"unique|{idx}"

        if key in merged:
            merged[key] = merge_rows(merged[key], row)
        else:
            merged[key] = row

    output_rows = []
    for row in merged.values():
        filtered = {col: (row.get(col, "") or "").strip() for col in OUTPUT_COLUMNS}
        output_rows.append(filtered)

    output_path = Path("output") / "uae_oil_companies.csv"
    write_csv(output_rows, output_path, OUTPUT_COLUMNS)

    logging.info("Merged %s rows into %s", len(output_rows), output_path)
    for source, count in source_counts.items():
        logging.info("Source %s: %s rows", source or "(unknown)", count)

    if chamber_codes:
        for code in chamber_codes:
            if chamber_code_counts.get(code, 0) == 0:
                logging.warning(
                    "No rows captured for code %s (verify portal availability or update selectors)", code
                )


if __name__ == "__main__":
    main()
