# PayCheck: stop fake invoices before you pay them

A working prototype that checks every supplier invoice for payment fraud (fake bank details, look-alike email domains, unusual amounts, pressure tactics, sanctions) and adds an **AI analyst (Claude)** that reads the email and invoice like an experienced fraud investigator. A guided workflow means nobody can pay a risky invoice without phone verification and a second approver.

See **[WORKFLOW.md](WORKFLOW.md)** for the full payment workflow and the business plan from prototype to revenue.

## Run it

```bash
cd paycheck
pip install -r requirements.txt
python -m app.seed                       # demo suppliers, history and 5 incoming invoices
uvicorn app.main:app --port 8000         # open http://localhost:8000
```

Turn on the AI analyst by setting an Anthropic API key before starting the server:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Then open an invoice and click **Re-check**. Without a key, all rule-based checks still work.

Run the tests:

```bash
python -m pytest -q tests
```

## Settings (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | Enables the Claude AI analyst |
| `PAYCHECK_MODEL` | `claude-opus-5-5` | Claude model used for the review |
| `PAYCHECK_AI` | `1` | Set `0` to turn the AI review off |
| `PAYCHECK_OFFLINE` | unset | Set `1` to skip live DNS (SPF/DMARC) lookups |
| `YENTE_URL` | unset | URL of a self-hosted yente sanctions server |
| `PAYCHECK_DB` | `paycheck.db` | SQLite file location |

## What it checks

| Check | How | Built on |
|---|---|---|
| Bank details changed / invalid / wrong country / on fraud list | Compares the invoice IBAN to the verified account in supplier master data | [schwifty](https://github.com/mdomke/schwifty) (MIT) |
| Look-alike sender domain | Typo distance, swapped characters (`rn`→`m`, `1`→`l`), same name with a different ending, brand + extra words | own code |
| Reply-to hijack, free-mail senders | Header comparison | own code |
| Weak email protection on sender domain | Live SPF/DMARC lookup | [checkdmarc](https://github.com/domainaware/checkdmarc) (Apache-2.0) |
| Amount far above normal, round amounts, duplicates | Statistics on the supplier's own history | own code |
| Pressure and secrecy language | Pattern library ("urgent", "new bank details", "don't call"…) | own code |
| Sanctions | Optional match against OpenSanctions | [yente](https://github.com/opensanctions/yente) (MIT) |
| AI analyst | Claude reads email + invoice + rule findings and returns a structured verdict (risk, red flags, recommended action) | [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) |
| PDF reading | Text-based PDFs; regex for IBAN, total, invoice number | [pypdf](https://github.com/py-pdf/pypdf) (BSD); swap in [docling](https://github.com/docling-project/docling) for scans |

**Scoring:** each finding has a weight (low 8, medium 20, high 35, critical 70). Under 25 is 🟢, 25–59 is 🟡, and 60+ or any critical finding is 🔴.

## Project layout

```
app/
  main.py        FastAPI routes + serves the dashboard
  engine.py      runs all checks, scores, stores results
  workflow.py    state machine: approve / verify / second-approve / pay / block
  checks/        bank.py, domain.py, anomaly.py, sanctions.py, ai.py
  extract.py     PDF/text → fields
  seed.py        demo data (each incoming invoice shows a different attack)
static/          dashboard (vanilla HTML/CSS/JS, no build step)
tests/           17 tests covering checks, workflow rules, extraction and the AI path
```

## Prototype limits (before real customers)
- Single workspace, no login. Add auth and multi-tenancy first.
- SQLite. Move to Postgres for production.
- Email is pasted or typed in, not read from a real inbox, so true SPF/DKIM pass/fail results aren't available yet (see WORKFLOW.md, Phase 2).
- Invoice and email content is sent to the Anthropic API when the AI analyst is on. Cover this in your data-processing agreements.
