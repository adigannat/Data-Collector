import argparse
import logging
import re

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError

from config import (
    DUBAI_DED_SELECTORS,
    DUBAI_DED_URL,
    KEYWORDS,
    OUTPUT_COLUMNS,
    RAW_DIR,
    SOURCE_DUBAI_DED,
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


def open_search_business_activities(page):
    # Try to click the "Search Business Activities" tile on the landing page.
    tile = page.locator("text=Search Business Activities").first
    if tile.count() == 0:
        return page
    try:
        # Sometimes opens in a new page/tab.
        with page.context.expect_page(timeout=3000) as new_page_info:
            tile.click()
        new_page = new_page_info.value
        new_page.wait_for_load_state("networkidle")
        return new_page
    except Exception:
        try:
            tile.click()
            page.wait_for_timeout(1500)
        except Exception:
            pass
        return page


def ensure_english(page):
    # Best-effort: if current UI is Arabic, switch to English.
    try:
        # If an Arabic toggle is visible (العربي), UI is likely English already.
        arabic_toggle = page.locator("a:has-text('العربي'), button:has-text('العربي')").first
        if arabic_toggle.count() > 0 and arabic_toggle.is_visible():
            return
        eng = page.locator("a:has-text('English'), button:has-text('English')").first
        if eng.count() > 0 and eng.is_visible():
            eng.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass


def input_by_label(page, label_text):
    label = page.locator(f"label:has-text('{label_text}')").first
    if label.count() == 0:
        return None
    label_for = label.get_attribute("for")
    if not label_for:
        return None
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
        if "Activity Code" in header_text or "Activity Group" in header_text or "License Type" in header_text:
            return table
    if count > 0:
        return tables.first
    return None


def parse_results_from_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    target = None
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if "Activity Code" in headers and "Activity" in headers:
            target = table
            break
    if not target:
        return []
    rows = []
    for tr in target.find_all("tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) >= 4 and re.match(r"^\d+", tds[0] or ""):
            rows.append(tds[:4])
    return rows


def parse_paging_info(html: str):
    soup = BeautifulSoup(html, "html.parser")
    current = None
    total = None
    current_span = soup.select_one(".paging-numbers .current")
    total_span = soup.select_one(".paging-numbers .total")
    if current_span and total_span:
        try:
            current = int(current_span.get_text(strip=True))
            total = int(total_span.get_text(strip=True))
        except Exception:
            current = None
            total = None
    next_link = soup.select_one(".paging-arrows a.next")
    next_target = None
    if next_link and next_link.get("href"):
        match = re.search(r"__doPostBack\('([^']+)'", next_link.get("href"))
        if match:
            next_target = match.group(1)
    return current, total, next_target


def first_row_key(rows):
    if not rows:
        return ""
    return "|".join(rows[0][:2])


def last_row_key(rows):
    if not rows:
        return ""
    return "|".join(rows[-1][:2])


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


def captcha_present(page):
    try:
        if page.locator("iframe[src*='recaptcha']").count() > 0:
            return True
        if page.locator("div.g-recaptcha, textarea#g-recaptcha-response").count() > 0:
            return True
        if page.locator("text=I'm not a robot").count() > 0:
            return True
    except Exception:
        return False
    return False


def wait_for_captcha(page):
    if captcha_present(page):
        logging.info("Captcha detected. Please complete it in the browser, then press Enter here.")
        input()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--keyword", action="append")
    parser.add_argument("--slowmo", type=int, default=0)
    args = parser.parse_args()

    stamp = run_stamp()
    log_path = RAW_DIR / "dubai_ded" / f"run_{stamp}.log"
    setup_logger(log_path)

    keywords = args.keyword or KEYWORDS

    out_rows = []
    html_dir = RAW_DIR / "dubai_ded" / "html"
    ensure_dir(html_dir)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, slow_mo=args.slowmo)
        page = browser.new_page()

        for keyword in keywords:
            logging.info("Searching keyword %s", keyword)
            page.goto(DUBAI_DED_URL, wait_until="networkidle")

            page = open_search_business_activities(page)
            ensure_english(page)

            # Wait a moment for the search form to render
            try:
                page.wait_for_timeout(1000)
            except Exception:
                pass
            wait_for_captcha(page)

            input_box = input_by_label(page, "Activity")
            if not input_box:
                input_box = first_visible(page, DUBAI_DED_SELECTORS["search_inputs"], timeout=5000)
            if not input_box:
                logging.warning("Search input not found for keyword %s", keyword)
                continue
            input_box.fill(keyword)

            search_button = first_visible(page, DUBAI_DED_SELECTORS["search_buttons"], timeout=5000)
            if search_button:
                search_button.click()
            else:
                input_box.press("Enter")

            page.wait_for_timeout(2000)
            wait_for_captcha(page)

            page_number = 1
            total_rows_for_keyword = 0
            seen_page_keys = set()
            while True:
                page.wait_for_timeout(1000)
                html = page.content()
                save_html(html_dir, keyword, page_number, html)

                rows_data = parse_results_from_html(html)
                if not rows_data:
                    table = guess_table(page)
                    if not table:
                        logging.warning("No results table detected for keyword %s", keyword)
                        break
                    # Fallback to Playwright table parsing; filter to valid rows.
                    rows_data = []
                    for values, _ in extract_table_rows(table):
                        if len(values) >= 4 and re.match(r"^\d+", values[0] or ""):
                            rows_data.append(values[:4])

                logging.info("Keyword %s page %s: rows=%s", keyword, page_number, len(rows_data))
                for values in rows_data:
                    # Columns: Activity Code, Activity, Activity Group, License Type
                    activity_code = values[0] if len(values) > 0 else ""
                    activity = values[1] if len(values) > 1 else ""
                    company = activity  # DED activities search doesn't list companies
                    record = {
                        "company_name": company,
                        "business_activity": activity,
                        "phone": "",
                        "email": "",
                        "source": SOURCE_DUBAI_DED,
                        "emirate": "Dubai",
                        "activity_code": activity_code,
                        "source_url": page.url,
                        "last_seen_utc": utc_now_iso(),
                        "notes": "ded_activity_search_no_company",
                    }
                    out_rows.append(record)
                total_rows_for_keyword += len(rows_data)

                current, total, next_target = parse_paging_info(html)
                page_key = f"{keyword}|{current or ''}|{first_row_key(rows_data)}|{last_row_key(rows_data)}"
                if page_key in seen_page_keys:
                    logging.info("Page content repeated for keyword %s; stopping pagination.", keyword)
                    break
                seen_page_keys.add(page_key)

                if total and current and current >= total:
                    break
                if args.max_pages and page_number >= args.max_pages:
                    break

                prev_current = current
                if next_target:
                    try:
                        page.evaluate("t => __doPostBack(t, '')", next_target)
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass
                else:
                    next_button = first_visible(page, DUBAI_DED_SELECTORS["next_buttons"], timeout=1000)
                    if not next_button:
                        break
                    try:
                        next_button.click()
                        page.wait_for_timeout(1500)
                    except Exception:
                        break

                if prev_current is not None:
                    try:
                        page.wait_for_function(
                            "prev => { const el=document.querySelector('.paging-numbers .current'); return el && el.textContent.trim() !== String(prev); }",
                            prev_current,
                            timeout=10000,
                        )
                    except Exception:
                        pass

                page_number += 1

            logging.info("Keyword %s total rows captured: %s", keyword, total_rows_for_keyword)

        browser.close()

    out_path = RAW_DIR / "dubai_ded" / f"dubai_ded_{stamp}.csv"
    if out_rows:
        from utils import write_csv

        write_csv(out_rows, out_path, OUTPUT_COLUMNS)
        logging.info("Saved %s rows to %s", len(out_rows), out_path)
    else:
        logging.warning("No rows captured")


if __name__ == "__main__":
    main()
