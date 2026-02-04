import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_DIR = PROJECT_ROOT / "input"
RAW_DIR = PROJECT_ROOT / "raw"
OUTPUT_DIR = PROJECT_ROOT / "output"
LOGS_DIR = PROJECT_ROOT / "logs"

DUBAI_CHAMBER_CODES_CSV = INPUT_DIR / "dubai_chamber_oil_codes.csv"

DUBAI_CHAMBER_URL = (
    "https://dcdigitalservices.dubaichamber.com/siebel/app/pseservicesso/enu"
    "?SWECmd=GotoView&SWEBHWND=&SWEView=DC+Commercial+Directory+Landing+View"
)
DUBAI_DED_URL = "https://eservices.dubaided.gov.ae/pages/anon/gsthme.aspx?dedqs=PM671p6QBb0lV1okx2JABgxoLLKXOgPx"
SHARJAH_SEDD_URL = (
    "https://eservices.sedd.ae/eservicesweb/license-transactions/search_license/main-inq-lic.xhtml?lang=en"
)
MOE_GROWTH_URL = "https://www.growth.gov.ae/G2C/"

SOURCE_DUBAI_CHAMBER = "dubai_chamber"
SOURCE_DUBAI_DED = "dubai_ded"
SOURCE_SHARJAH_SEDD = "sharjah_sedd"
SOURCE_MOE_GROWTH = "moe_growth_manual"

KEYWORDS = [
    "oil",
    "petroleum",
    "petro",
    "gas",
    "drilling",
    "refinery",
    "oilfield",
]

REQUIRED_COLUMNS = ["company_name", "business_activity", "phone", "email"]
RECOMMENDED_COLUMNS = [
    "source",
    "emirate",
    "activity_code",
    "source_url",
    "last_seen_utc",
    "notes",
]
OUTPUT_COLUMNS = REQUIRED_COLUMNS + RECOMMENDED_COLUMNS

# Playwright selector hints. Update these if the portals change.
DUBAI_CHAMBER_SELECTORS = {
    # Commercial Directory form fields
    "activity_code_inputs": [
        "input[aria-label='Activity Code']",
        "input[name='s_1_1_0_0']",
    ],
    "search_buttons": [
        "button#s_1_1_10_0_Ctrl",
        "button[aria-label*='Search']",
        "button[id*='_Ctrl'][aria-label*='Search']",
        "button:has-text('Search')",
    ],
    "results_tables": [
        "table#s_2_l",
        "table.siebui-applet-table",
        "div[id^='SWEApplet'] table",
        "table",
    ],
    "next_buttons": [
        "a[aria-label*='Next Set']",
        "button:has-text('Next')",
        "a:has-text('Next')",
    ],
    # Restrict detail links to links inside the result table rows
    "detail_links": [
        "tr td a.siebui-link",
        "tr td a:has-text('View')",
    ],
    "field_labels": {
        "company_name": ["Company", "Company Name", "Trade Name"],
        "business_activity": ["Activity", "Business Activity", "Category"],
        "phone": ["Phone", "Telephone", "Tel"],
        "email": ["Email", "E-mail"],
    },
}

SHARJAH_SEDD_SELECTORS = {
    "search_inputs": [
        "input[name*='filterTrdNameEn']",
        "input[placeholder*='Trade Name (English)']",
        "input[aria-label*='Trade Name (English)']",
        "input[type='text']",
    ],
    "search_buttons": [
        "button:has-text('Search')",
        "input[type='submit']",
    ],
    "results_tables": ["table"],
    "next_buttons": [
        "a.ui-paginator-next",
        "button.ui-paginator-next",
        "span.ui-paginator-next",
        "a[aria-label*='Next']",
        "button:has-text('Next')",
        "a:has-text('Next')",
        "a:has-text('>')",
    ],
    "field_labels": {
        "company_name": ["Trade Name", "Company Name"],
        "business_activity": ["Activity", "Business"],
        "phone": ["Phone", "Telephone", "Tel"],
        "email": ["Email", "E-mail"],
    },
}

DUBAI_DED_SELECTORS = {
    "search_inputs": [
        "input[id*='Activity']",
        "input[name*='Activity']",
        "input[type='text']",
        "input[name*='search']",
        "input[placeholder*='Activity']",
        "input[placeholder*='Business']",
        "input[aria-label*='Activity']",
        "input[aria-label*='Business']",
    ],
    "search_buttons": [
        "button:has-text('Search')",
        "input[type='submit'][value*='Search']",
        "input[type='submit']",
        "button:has-text('Find')",
    ],
    "results_tables": ["table"],
    "next_buttons": [
        ".paging-arrows a.next",
        "a:has-text('Next')",
        "button:has-text('Next')",
    ],
    "field_labels": {
        "company_name": ["Company", "Trade Name", "Commercial Name"],
        "business_activity": ["Activity", "Business", "License Activity"],
        "phone": ["Phone", "Telephone", "Tel"],
        "email": ["Email", "E-mail"],
    },
}
