import argparse
import csv
import logging
from pathlib import Path
from time import sleep

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError

from config import (
    DUBAI_CHAMBER_CODES_CSV,
    DUBAI_CHAMBER_SELECTORS,
    DUBAI_CHAMBER_URL,
    OUTPUT_COLUMNS,
    RAW_DIR,
    SOURCE_DUBAI_CHAMBER,
)
from utils import ensure_dir, run_stamp, setup_logger, utc_now_iso, validate_email


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


def click_search(page, search_selectors):
    search_button = first_visible(page, search_selectors, timeout=5000)
    if not search_button:
        return False
    try:
        search_button.scroll_into_view_if_needed()
    except Exception:
        pass
    # Try normal click, then force, then JS click.
    try:
        search_button.click()
        return True
    except Exception:
        pass
    try:
        search_button.click(force=True)
        return True
    except Exception:
        pass
    try:
        page.evaluate("el => el.click()", search_button)
        return True
    except Exception:
        return False


def guess_table(page):
    preferred = page.locator("table#s_2_l")
    if preferred.count() > 0:
        return preferred.first
    tables = page.locator("table")
    count = tables.count()
    for idx in range(count):
        table = tables.nth(idx)
        try:
            header_text = " ".join(table.locator("th").all_inner_texts())
        except Exception:
            header_text = ""
        if "Company" in header_text or "Activity" in header_text or "Phone" in header_text:
            return table
    if count > 0:
        return tables.first
    return None


def extract_table_rows(table):
    rows = []
    header_map = {}
    table_id = table.get_attribute("id") or ""

    if table_id == "s_2_l":
        header_cells = table.locator("xpath=ancestor::div[@id='gview_s_2_l']//th")
        if header_cells.count() > 0:
            headers = [h.inner_text().strip() for h in header_cells.all()]
            for i, header in enumerate(headers):
                if header:
                    header_map[header.lower()] = i
        data_rows = table.locator("tbody tr:not(.jqgfirstrow)")
    else:
        header_cells = table.locator("tr th")
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
        rows.append((values, row, header_map))
    return rows


def extract_grid_rows_via_dom(page):
    """
    Direct DOM extraction for jqGrid rows; avoids relying on jqGrid API.
    """
    try:
        rows = page.locator("#s_2_l tbody tr:not(.jqgfirstrow)")
        out = []
        for i in range(rows.count()):
            row = rows.nth(i)
            cells = [c.inner_text().strip() for c in row.locator("td").all()]
            out.append(cells)
        return out
    except Exception:
        return []


def parse_rows_from_html(html: str):
    """
    HTML parsing fallback to avoid any locator timing issues.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("#s_2_l")
    out = []
    if not table:
        return out
    for tr in table.select("tbody tr"):
        if "jqgfirstrow" in (tr.get("class") or []):
            continue
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        out.append(cells)
    return out


def extract_grid_rows_via_js(page):
    """
    Use page DOM to pull visible rows; more reliable than jqGrid API.
    """
    try:
        data = page.evaluate(
            """
() => {
  const table = document.querySelector('#s_2_l');
  if (!table) return [];
  const rows = Array.from(table.querySelectorAll('tbody tr:not(.jqgfirstrow)'));
  return rows.map(tr => {
    const cells = Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').trim());
    return {
      member: cells[1] || '',
      email: cells[2] || '',
      phone: cells[3] || '',
      activity: cells[4] || '',
      raw: cells,
    };
  });
}
"""
        )
        return data or []
    except Exception:
        return []


def wait_for_grid_data(page, timeout_ms=20000):
    try:
        page.wait_for_function(
            """
() => {
  const table = document.querySelector('#s_2_l');
  if (!table) return false;
  const rows = table.querySelectorAll('tbody tr:not(.jqgfirstrow)');
  if (rows.length > 0) return true;
  const counter = document.querySelector('#s_2_rc');
  if (!counter) return false;
  const text = (counter.textContent || '').trim().toLowerCase();
  return text && text !== 'no records';
}
""",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


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


def extract_detail_fields(page, label_map):
    result = {"company_name": "", "business_activity": "", "phone": "", "email": ""}
    for field, labels in label_map.items():
        for label in labels:
            try:
                row = page.locator("tr", has_text=label).first
                if row.count() > 0:
                    cells = row.locator("td")
                    if cells.count() >= 2:
                        result[field] = cells.nth(1).inner_text().strip()
                        break
            except Exception:
                continue
    return result


def save_html(raw_dir, code, page_number, content):
    ensure_dir(raw_dir)
    path = raw_dir / f"{code}_page_{page_number:03d}.html"
    path.write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--code", action="append", help="Process only specific activity code(s)")
    parser.add_argument("--slowmo", type=int, default=0)
    parser.add_argument("--pause-after-fill", action="store_true")
    parser.add_argument("--post-search-wait", type=int, default=3000, help="extra wait in ms after search click")
    args = parser.parse_args()

    stamp = run_stamp()
    log_path = RAW_DIR / "dubai_chamber" / f"run_{stamp}.log"
    setup_logger(log_path)

    with DUBAI_CHAMBER_CODES_CSV.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Normalize fieldnames to handle BOM or accidental casing changes.
        field_map = {name.lstrip("\\ufeff").lower().strip(): name for name in (reader.fieldnames or []) if name}
        code_field = field_map.get("activity_code")
        if not code_field:
            logging.error(
                "activity_code column not found in %s. Headers seen: %s",
                DUBAI_CHAMBER_CODES_CSV,
                reader.fieldnames,
            )
            return
        codes = []
        for row in reader:
            code = (row.get(code_field) or "").strip()
            if code:
                codes.append(code)
    if args.code:
        codes = [code for code in codes if code in args.code]

    out_rows = []
    html_dir = RAW_DIR / "dubai_chamber" / "html"
    ensure_dir(html_dir)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, slow_mo=args.slowmo)
        page = browser.new_page()

        for code in codes:
            logging.info("Processing code %s", code)
            try:
                page.goto(DUBAI_CHAMBER_URL, wait_until="load", timeout=60000)
                # Allow any JS redirects/frames to settle without hard timeout failures.
                page.wait_for_load_state("networkidle", timeout=15000)
            except TimeoutError:
                logging.warning("Initial page load timed out; continuing with whatever rendered for code %s", code)
            except Exception as e:
                logging.error("Failed to open portal for code %s: %s", code, e)
                continue

            clear_button = first_visible(page, ["button[aria-label*='Clear']", "button[id*='_5_0_Ctrl']"], timeout=3000)
            if clear_button:
                try:
                    clear_button.click()
                    page.wait_for_timeout(500)
                except Exception:
                    pass

            input_box = first_visible(page, DUBAI_CHAMBER_SELECTORS["activity_code_inputs"], timeout=8000)
            if not input_box:
                logging.warning("Activity code input not found for code %s. Try running with --slowmo 500 (headed).", code)
                continue
            input_box.fill(code)
            # Blur the field to let the portal auto-populate description.
            try:
                input_box.press("Tab")
            except Exception:
                pass

            if args.pause_after_fill:
                logging.info("Paused after fill for code %s. Click Search manually, then press Enter here.", code)
                input()

            if not click_search(page, DUBAI_CHAMBER_SELECTORS["search_buttons"]):
                try:
                    input_box.press("Enter")
                except Exception:
                    logging.warning("Search trigger failed for code %s", code)

            # Try Siebel JS invoke as fallback (sometimes the DOM click is ignored).
            try:
                page.evaluate(
                    """
() => {
  try {
    const app = window.SiebelApp && SiebelApp.S_App;
    if (!app) return false;
    const view = app.GetActiveView && app.GetActiveView();
    if (!view) return false;
    const applet = view.GetApplet && (view.GetApplet('Commercial Directory Form') || view.GetApplet('Commercial Directory'));
    if (!applet) return false;
    const pm = applet.GetPModel && applet.GetPModel();
    if (!pm) return false;
    pm.ExecuteMethod('InvokeMethod', 'Search');
    pm.ExecuteMethod('InvokeMethod', 'ExecuteQuery');
    return true;
  } catch (e) {
    return false;
  }
}
"""
                )
            except Exception:
                pass

            page.wait_for_timeout(args.post_search_wait)
            wait_for_grid_data(page, timeout_ms=25000)

            page_number = 1
            seen_page_keys = set()
            while True:
                page.wait_for_timeout(1000)
                save_html(html_dir, code, page_number, page.content())

                if page_number == 1:
                    if not wait_for_grid_data(page, timeout_ms=15000):
                        logging.warning("No table rendered after search for code %s", code)
                html_rows = parse_rows_from_html(page.content())
                grid_rows = extract_grid_rows_via_js(page)
                dom_rows = extract_grid_rows_via_dom(page)
                logging.info(
                    "Code %s page %s: html_rows=%s dom_rows=%s grid_rows=%s",
                    code,
                    page_number,
                    len(html_rows),
                    len(dom_rows),
                    len(grid_rows),
                )

                # Detect repeated pages to avoid infinite loops.
                page_key = None
                if html_rows:
                    first_row = html_rows[0] if html_rows else []
                    page_key = f"{len(html_rows)}|{first_row}"
                elif dom_rows:
                    first_row = dom_rows[0] if dom_rows else []
                    page_key = f"{len(dom_rows)}|{first_row}"
                elif grid_rows:
                    first_row = grid_rows[0] if grid_rows else {}
                    page_key = f"{len(grid_rows)}|{first_row}"
                if page_key and page_key in seen_page_keys:
                    logging.info("Page content repeated for code %s; stopping pagination.", code)
                    break
                if page_key:
                    seen_page_keys.add(page_key)

                if html_rows:
                    rows_data = [(cells, None, {}) for cells in html_rows]
                elif dom_rows:
                    rows_data = [(cells, None, {}) for cells in dom_rows]
                elif grid_rows:
                    rows_data = [
                        ([r.get("member", ""), r.get("email", ""), r.get("phone", ""), r.get("activity", "")], None, {})
                        for r in grid_rows
                    ]
                else:
                    # Fallback to table scraping
                    table = guess_table(page)
                    if not table:
                        logging.warning("No results table detected for code %s", code)
                        break
                    rows_data = extract_table_rows(table)

                if not rows_data:
                    logging.info("No records found for code %s", code)
                    break

                for values, row, header_map in rows_data:
                    if header_map:
                        company = find_row_value(values, header_map, ["Company", "Trade Name", "Member Name"])
                        activity = find_row_value(
                            values,
                            header_map,
                            ["Activity", "Business", "Product/Service", "Product Description"],
                        )
                    else:
                        company = values[1] if len(values) > 1 else (values[0] if values else "")
                        activity = ""
                    record = {
                        "company_name": company,
                        "business_activity": activity,
                        "phone": values[3] if len(values) > 3 else "",
                        "email": validate_email(values[2]) if len(values) > 2 else "",
                        "source": SOURCE_DUBAI_CHAMBER,
                        "emirate": "Dubai",
                        "activity_code": code,
                        "source_url": page.url,
                        "last_seen_utc": utc_now_iso(),
                        "notes": "",
                    }
                    out_rows.append(record)

                # Pagination handling for jqGrid pager
                next_button = page.locator("#next_pager_s_2_l")
                if next_button.count() > 0:
                    try:
                        classes = next_button.get_attribute("class") or ""
                        if "ui-state-disabled" in classes:
                            break
                        next_button.click()
                        try:
                            page.wait_for_selector("#load_s_2_l", state="visible", timeout=5000)
                        except Exception:
                            pass
                        try:
                            page.wait_for_selector("#load_s_2_l", state="hidden", timeout=15000)
                        except Exception:
                            page.wait_for_timeout(1500)
                        page.wait_for_timeout(1000)
                        page_number += 1
                    except Exception:
                        break
                else:
                    # Fallback to generic "Next" button selectors
                    page_number += 1
                    if args.max_pages and page_number > args.max_pages:
                        break
                    next_button_generic = first_visible(page, DUBAI_CHAMBER_SELECTORS["next_buttons"], timeout=1000)
                    if not next_button_generic:
                        break
                    try:
                        next_button_generic.click()
                        page.wait_for_timeout(1500)
                    except Exception:
                        break

        browser.close()

    out_path = RAW_DIR / "dubai_chamber" / f"dubai_chamber_{stamp}.csv"
    if out_rows:
        from utils import write_csv

        write_csv(out_rows, out_path, OUTPUT_COLUMNS)
        logging.info("Saved %s rows to %s", len(out_rows), out_path)
    else:
        logging.warning("No rows captured")


if __name__ == "__main__":
    main()
