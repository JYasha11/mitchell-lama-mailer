# mitchell-lama-mailer

Map every Mitchell-Lama development in/around NYC, filter to the ones you'd
actually live in, and send each management office a short waiting-list inquiry
email — drafted per building, reviewed by you, sent from your Gmail.

## Why this exists

Mitchell-Lama has no central application. The city (HPD) and state (HCR) each
publish PDF lists of developments; waitlist openings are announced in
newspapers and building lobbies. This tool parses the official PDFs into a
database so you can work the whole list systematically:

- **HPD master list** (~91 NYC developments) — no emails published, phone/mail only
- **HCR state list** (~131 developments) — includes management office emails
- **HPD open-waitlist + short-waitlist PDFs** — which lists are open right now, per apartment size
- Emails for HPD buildings are recovered where the same management company
  appears on the HCR list (marked ≈ in the UI)

An email never gets you on a list — every building requires a mailed paper
application + $75 fee. The emails ask whether the list is open, how to apply,
and how openings are announced. Also: make an [NYC Housing Connect](https://housingconnect.nyc.gov)
account — Mitchell-Lama waitlist-reopening lotteries run through it and it
emails you when new ones open.

## Setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install pdfplumber fastapi "uvicorn[standard]" httpx jinja2
cp .env.example .env   # then fill in GMAIL_APP_PASSWORD
```

Gmail app password: Google Account → Security → 2-Step Verification → App passwords.

## Use

```bash
# 1. build/refresh the database (downloads the current PDFs, geocodes new addresses)
.venv/bin/python -m app.pipeline.build

# 2. run the app
.venv/bin/uvicorn app.server:app --port 8877
# open http://localhost:8877
```

Buildings tab: filter by borough, co-op/rental, senior-only, waitlist status,
rough transit time to Midtown; select buildings → **Draft emails**.
Email queue tab: review/edit each draft, approve, **Send approved** — sent via
your Gmail, throttled (default one per 20s), replies land in your inbox.

Buildings without an email show as "phone only" — that's your call sheet.

## Data notes

- Sources re-download on every `build` run; HPD revises the PDFs periodically.
- The HCR consolidated-list URL is date-versioned; the build scrapes the
  current link from hcr.ny.gov's applicant page.
- Transit times are a rough distance-based estimate; the Maps link per
  building opens real Google transit directions.
- HCR's waitlist system is migrating to housingsearch.hcr.ny.gov during 2026;
  worth re-checking that site for per-building waitlist status.
