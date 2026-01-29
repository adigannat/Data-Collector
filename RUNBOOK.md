RUNBOOK

Setup
- Create venv: python -m venv .venv
- Activate: .\.venv\Scripts\Activate.ps1  (if blocked, Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned)
- Install deps: pip install -r requirements.txt
- Install browsers: python -m playwright install

Run order (recommended)
1) Dubai Chamber
   python agents\scrape_dubai_chamber.py

2) Sharjah SEDD (manual reCAPTCHA per search)
   python agents\scrape_sharjah_sedd.py

3) Dubai DED (keyword gap filler)
   python agents\scrape_dubai_ded.py

4) Merge and clean
   python agents\merge_and_clean.py

MoE Growth
- Requires UAE Pass; no automation. If you obtain an authenticated export manually, place CSV under raw/moe_growth and rerun merge. Otherwise leave as limitation note.

Notes
- Adjust selectors in agents\config.py if the portals change.
- Raw HTML snapshots are saved under raw\<source>\html for auditability.
- Merge output is written to output\uae_oil_companies.csv.
- No CAPTCHA or authentication bypassing; human-in-loop only where required.
