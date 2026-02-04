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


def input_by_label(page, label_text):
    label = page.locator(f"label:has-text('{label_text}')").first
    if label.count() == 0:
        return None
    label_for = label.get_attribute("for")
    if not label_for:
        return None
    # Some ids include ':' which is not valid in CSS selectors; use attribute selector.
    field = page.locator(f"[id='{label_for}']").first
    try:
        return field if field.count() > 0 else None
    except Exception:
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
        if any(token in header_text for token in ["Trade", "Company", "License", "Expire", "Expiry"]):
            return table
    if count > 0:
        return tables.first
    return None


def dismiss_map_popup(page):
    try:
        ok_button = page.locator("button:has-text('OK')").first
        if ok_button.count() > 0 and ok_button.is_visible():
            ok_button.click()
            page.wait_for_timeout(500)
    except Exception:
        pass


def paginator_next(page):
    # Prefer PrimeFaces widget paginator if available
    try:
        worked = page.evaluate(
            """
() => {
  try {
    if (window.PF && PF('trdNameDT')) {
      PF('trdNameDT').paginator.next();
      return true;
    }
  } catch (e) {}
  return false;
}
"""
        )
        if worked:
            return True
    except Exception:
        pass

    for selector in SHARJAH_SEDD_SELECTORS["next_buttons"]:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            classes = locator.get_attribute("class") or ""
            if "ui-state-disabled" in classes or "disabled" in classes:
                return None
            locator.scroll_into_view_if_needed()
            locator.click()
            return True
        except Exception:
            continue
    return None


def extract_table_rows(page):
    rows = []
    body = page.locator("[id='licForm:licTbl_data']")
    if body.count() == 0:
        return rows
    for row in body.locator("tr").all():
        cells = [c.inner_text().strip() for c in row.locator("td").all()]
        if cells:
            rows.append(cells)
    return rows


def extract_table_rows_generic(table):
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


def clean_cell(text):
    if not text:
        return ""
    for label in ["Trade name", "License Number", "Expire date"]:
        text = text.replace(label, "")
    return text.strip()


def first_row_key(rows_data):
    if not rows_data:
        return ""
    row = rows_data[0]
    return "|".join([clean_cell(val) for val in row[:3]])


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

            # Clear any residual inputs.
            try:
                for field in page.locator("input[type='text']").all():
                    field.fill("")
            except Exception:
                pass

            input_box = input_by_label(page, "Trade Name (English)")
            if input_box:
                logging.info("Using Trade Name (English) field by label.")
            else:
                input_box = first_visible(page, SHARJAH_SEDD_SELECTORS["search_inputs"])
            if not input_box:
                logging.warning("Search input not found for keyword %s", keyword)
                continue
            # SEDD requires minimum 4 characters; pad short terms (e.g., "oil").
            term = keyword
            if len(term) < 4:
                term = term + " "
            input_box.fill(term)

            logging.info("Complete reCAPTCHA if present, then press Enter in this console...")
            input()

            search_button = first_visible(page, SHARJAH_SEDD_SELECTORS["search_buttons"])
            if search_button:
                search_button.click()
            else:
                input_box.press("Enter")

            page.wait_for_timeout(2000)

            page_number = 1
            total_rows_for_keyword = 0
            seen_page_keys = set()
            while True:
                dismiss_map_popup(page)
                page.wait_for_timeout(1000)
                save_html(html_dir, keyword, page_number, page.content())

                rows_data = extract_table_rows(page)
                if not rows_data:
                    table = guess_table(page)
                    if not table:
                        logging.warning("No results table detected for keyword %s", keyword)
                        break
                    # Fallback to generic table parsing
                    rows_data = []
                    for values, header_map in extract_table_rows_generic(table):
                        rows_data.append(values)

                logging.info("Keyword %s page %s: rows=%s", keyword, page_number, len(rows_data))
                for values in rows_data:
                    # Columns: License Number, Trade name, Expire date, (button)
                    company = clean_cell(values[1]) if len(values) > 1 else clean_cell(values[0])
                    activity = ""
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
                total_rows_for_keyword += len(rows_data)

                # Break if the page repeats (prevents infinite loop).
                page_key = f"{keyword}|{len(rows_data)}|{first_row_key(rows_data)}"
                if page_key and page_key in seen_page_keys:
                    logging.info("Page content repeated for keyword %s; stopping pagination.", keyword)
                    break
                if page_key:
                    seen_page_keys.add(page_key)

                if args.max_pages and page_number >= args.max_pages:
                    break

                next_clicked = paginator_next(page)
                if not next_clicked:
                    break
                try:
                    prev_key = first_row_key(rows_data)
                    page.wait_for_function(
                        """
(prev) => {
  const row = document.querySelector(\"[id='licForm:licTbl_data'] tr\");
  if (!row) return false;
  return row.innerText.trim() !== prev;
}
""",
                        prev_key,
                        timeout=15000,
                    )
                except Exception:
                    page.wait_for_timeout(1500)

                page_number += 1

            logging.info("Keyword %s total rows captured: %s", keyword, total_rows_for_keyword)

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
