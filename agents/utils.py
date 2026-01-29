import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def write_csv(rows, path: Path, fieldnames):
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def append_csv(rows, path: Path, fieldnames):
    ensure_dir(path.parent)
    file_exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def setup_logger(log_path: Path):
    ensure_dir(log_path.parent)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def validate_email(value: str):
    if not value:
        return ""
    value = value.strip()
    if EMAIL_RE.match(value):
        return value
    return ""


def normalize_company_name(value: str):
    if not value:
        return ""
    lowered = value.strip().lower()
    normalized = NON_ALNUM_RE.sub(" ", lowered)
    return " ".join(normalized.split())


def normalize_phone(value: str):
    if not value:
        return ""
    digits = re.sub(r"\D+", "", value)
    if not digits:
        return ""
    if digits.startswith("00971"):
        digits = "971" + digits[5:]
    if digits.startswith("971"):
        return "+" + digits
    return "+" + digits


def merge_notes(*values):
    parts = []
    for value in values:
        if not value:
            continue
        if isinstance(value, str):
            for item in value.split(";"):
                item = item.strip()
                if item and item not in parts:
                    parts.append(item)
        else:
            for item in value:
                item = str(item).strip()
                if item and item not in parts:
                    parts.append(item)
    return ";".join(parts)
