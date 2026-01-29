import argparse
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright

from config import (
    KEYWORDS,
    OUTPUT_COLUMNS,
    RAW_DIR,
    SHARJAH_SEDD_SELECTORS,
    SHARJAH_SEDD_URL,
    SOURCE_SHARJAH_SEDD,
)
from utils import ensure_dir, run_stamp, setup_logger, utc_now_iso


def first_visible(page, selectors, timeout=2000):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.wait_for(state="visible", timeout=timeout)
                return locator
        except Exception:
            continue
    return None


def guess_table(page):
    tables = page.locator("table")
    count = tables.count()
    for idx in range(count):
        table = tables.nth(idx)
        try:
            header_text = " ".join(table.locator("th").all_inner_texts())
        except Exception:
            header_text = ""
        if "Trade" in header_text or "Company" in header_text:
            return table
    if count > 0:
        return tables.first
    return None


def extract_table_rows(table):
    rows = []
    header_cells = table.locator("tr th")
    header_map = {}
    if header_cells.count() > 0:
        headers = [h.strip() for h in header_cells.all_inner_texts()]
        for i, header in enumerate(headers):
            header_map[header.lower()] = i
    data_rows = table.locator("tr")
    for i in range(data_rows.count()):
        row = data_rows.nth(i)
        cells = row.locator("td")
        if cells.count() == 0:
            continue
        values = [c.inner_text().strip() for c in cells.all()]
        rows.append((values, header_map))
    return rows


def find_row_value(values, header_map, candidates):
    if header_map:
        for header, idx in header_map.items():
            for candidate in candidates:
                if candidate.lower() in header:
                    if idx < len(values):
                        return values[idx]
    if values:
        return values[0]
    return ""


def save_html(raw_dir, keyword, page_number, content):
    ensure_dir(raw_dir)
    path = raw_dir / f"{keyword}_page_{page_number:03d}.html"
    path.write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--keyword", action="append")
    parser.add_argument("--slowmo", type=int, default=0)
    args = parser.parse_args()

    stamp = run_stamp()
    log_path = RAW_DIR / "sharjah_sedd" / f"run_{stamp}.log"
    setup_logger(log_path)

    keywords = args.keyword or KEYWORDS

    out_rows = []
    html_dir = RAW_DIR / "sharjah_sedd" / "html"
    ensure_dir(html_dir)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, slow_mo=args.slowmo)
        page = browser.new_page()

        for keyword in keywords:
            logging.info("Searching keyword %s", keyword)
            page.goto(SHARJAH_SEDD_URL, wait_until="networkidle")

            input_box = first_visible(page, SHARJAH_SEDD_SELECTORS["search_inputs"])
            if not input_box:
                logging.warning("Search input not found for keyword %s", keyword)
                continue
            input_box.fill(keyword)

            logging.info("Complete reCAPTCHA if present, then press Enter in this console...")
            input()

            search_button = first_visible(page, SHARJAH_SEDD_SELECTORS["search_buttons"])
            if search_button:
                search_button.click()
            else:
                input_box.press("Enter")

            page.wait_for_timeout(2000)

            page_number = 1
            while True:
                page.wait_for_timeout(1000)
                save_html(html_dir, keyword, page_number, page.content())

                table = guess_table(page)
                if not table:
                    logging.warning("No results table detected for keyword %s", keyword)
                    break

                for values, header_map in extract_table_rows(table):
                    company = find_row_value(values, header_map, ["Trade", "Company"])
                    activity = find_row_value(values, header_map, ["Activity", "Business"])
                    record = {
                        "company_name": company,
                        "business_activity": activity,
                        "phone": "",
                        "email": "",
                        "source": SOURCE_SHARJAH_SEDD,
                        "emirate": "Sharjah",
                        "activity_code": "",
                        "source_url": page.url,
                        "last_seen_utc": utc_now_iso(),
                        "notes": "contact_not_listed_in_sedd_public_view",
                    }
                    out_rows.append(record)

                page_number += 1
                if args.max_pages and page_number > args.max_pages:
                    break

                next_button = first_visible(page, SHARJAH_SEDD_SELECTORS["next_buttons"], timeout=1000)
                if not next_button:
                    break
                try:
                    next_button.click()
                    page.wait_for_timeout(1500)
                except Exception:
                    break

        browser.close()

    out_path = RAW_DIR / "sharjah_sedd" / f"sharjah_sedd_{stamp}.csv"
    if out_rows:
        from utils import write_csv

        write_csv(out_rows, out_path, OUTPUT_COLUMNS)
        logging.info("Saved %s rows to %s", len(out_rows), out_path)
    else:
        logging.warning("No rows captured")


if __name__ == "__main__":
    main()
