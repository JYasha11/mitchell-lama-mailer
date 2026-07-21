# Mitchell-Lama Mailer

**Find every Mitchell-Lama building in and around NYC, see whose waitlist is
open, and email them all — without losing your mind.**

Mitchell-Lama is NYC's middle-income housing program: co-ops you buy into for
roughly $15–30k plus monthly maintenance, and rentals with regulated rents.
The catch is that it was built in the 1960s and still runs like it. There is
no central application. Every building keeps its own waitlist. Openings are
announced in newspapers and building lobbies. Contact info lives in PDFs
scattered across two government agencies, and half the buildings don't
publish an email address at all.

This app turns that mess into one screen: an interactive map and table of
**every development** (city- and state-supervised), filters for what you
actually want, and a review-then-send email queue that asks each management
office the only questions that matter — *is your waitlist open, how do I
apply, and how do I find out when it opens?*

> **Reality check before you start:** an email never gets you on a waitlist.
> Every building requires a mailed paper application and a **$75 non-refundable
> fee**. The emails tell you *which* buildings are worth that $75. Also make a
> free [NYC Housing Connect](https://housingconnect.nyc.gov) account — when a
> closed city waitlist reopens, the lottery runs there, and it emails you about
> new Mitchell-Lama lotteries automatically.

---

## Quick start

You need Python 3.10+ and a Gmail account.

```bash
git clone <this-repo>
cd mitchell-lama-mailer

# 1. Install  (check `python3 --version` — if it's below 3.10, e.g. macOS's
#    default 3.9, use a newer one: `brew install python` then `python3.12 -m venv .venv`)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Configure — put in your name, phone, and Gmail
cp .env.example .env
open .env   # edit it

# 3. Build the database (downloads the current official PDFs, ~4 min with geocoding)
.venv/bin/python -m app.pipeline.build

# 4. Run
.venv/bin/uvicorn app.server:app --port 8877
```

Open **http://localhost:8877**. Everything happens in the browser from here.

### The Gmail app password

The app sends from *your* Gmail so replies land in *your* inbox. It never sees
your real password — you give it a single-purpose **app password** you can
revoke anytime:

1. Google Account → **Security** → turn on **2-Step Verification** (required)
2. Security → **App passwords** → create one, name it anything
3. Paste the 16-character code into `.env` as `GMAIL_APP_PASSWORD`

`.env` is gitignored; nothing personal ever leaves your machine except the
emails you approve.

---

## Using the app

### 1. Filter

The left sidebar narrows the universe: co-op vs rental, borough/county,
senior-only (62+) buildings on or off, buildings with a known email only, and
a rough transit-time-to-Midtown slider. The headline filter is **"Open
waitlist only"** — buildings the city currently confirms have open lists,
straight from HPD's own published status sheet.

### 2. Pick buildings

Everything is selectable, everywhere:

- **Click a dot on the map.** Blue = has an email, green = confirmed open
  waitlist, gray = phone only. Selected dots get a **gold ring**. Hover for
  details first: type, units, which apartment sizes are open, transit
  estimate, and where the email would go.
- **Click a row in the table** — anywhere on the row. The **⌖** icon pans the
  map to that building; the **Maps** link opens real Google transit
  directions (the sidebar's transit number is a rough distance-based guess —
  trust Google, not the guess).
- **"Select all visible"** grabs every emailable building that passes your
  current filters.

As soon as you select anything, a **tray appears at the bottom listing
exactly what you've picked**, as chips with an ✕ on each. Your selection
survives closing the browser.

### 3. Draft, review, send

Hit **Draft emails (n)** in the tray. A queue panel slides in with one
personalized draft per building, each tagged **`new`**. The email asks the
three questions, mentions what you're looking for, and signs with your info
from `.env` — edit any draft freely, or edit the template for everyone (see
below).

Then work the queue: **Approve all shown** (or approve/skip individually) →
**Send approved**. Sends go out **one every 20 seconds** — a hundred
identical emails in one burst is how you end up in spam folders — with live
progress. Status chips (`draft / approved / sent / skipped`) track everything,
and the badge on the **Email queue** button follows you around the app.

Replies arrive in your normal Gmail inbox, threaded under
"Waiting list inquiry — {Building}".

### 4. The buildings you can't email

"Phone only" buildings are mostly city-supervised ones — the city publishes no
email addresses for them. Those rows are your **call sheet**: sort by the
Waitlist column and start dialing the open ones. (This app recovers emails for
about two-thirds of city buildings anyway — see *Where the data comes from*.)

### Keeping it fresh

```bash
.venv/bin/python -m app.pipeline.build
```

Re-run every month or so. It re-downloads the official PDFs and updates the
database **in place** — your drafts, sent history, and selections all survive.
The main thing a refresh catches is buildings appearing on (or falling off)
the city's open-waitlist sheet.

---

## Where the data comes from

No machine-readable list of Mitchell-Lama buildings exists anywhere — this app
builds one by parsing four official PDFs on every refresh:

| Source | What it provides |
|---|---|
| [HPD master list](https://www.nyc.gov/assets/hpd/downloads/pdfs/services/MLLIST.pdf) | All ~91 city-supervised developments: address, units, co-op/rental, managing agent, phone. **No emails.** |
| [HPD open waitlists](https://www.nyc.gov/assets/hpd/downloads/pdfs/services/ML-waiting-Lists-Status.pdf) | Which lists are open right now, **per apartment size** |
| [HPD short waitlists](https://www.nyc.gov/assets/hpd/downloads/pdfs/services/Short-waiting-Lists.pdf) | Buildings saying "call for an application today" |
| [HCR consolidated list](https://hcr.ny.gov/mitchell-lama-applicant-information) | All ~131 state-supervised developments — **with management office emails** |

The trick that makes the city side emailable: the same management companies
(Metro, Prestige, Century, Rose…) run buildings in both systems. Where a city
building's management company appears on the state list with an email, that
email is reused — marked with **≈** in the UI, and the email text politely
discloses how the address was found.

Addresses are geocoded with NYC's free [GeoSearch](https://geosearch.planninglabs.nyc)
API (US Census geocoder as fallback).

**Good-faith notes:** the parsed PDFs are official public information; the
send throttle and the disclose-your-source email text are deliberate. This
tool sends short, personalized inquiries to offices whose job is answering
exactly these questions — use it that way. One email per building; call, don't
re-blast, if nobody answers.

---

## How the code works

```
app/
  pipeline/parse.py    PDF parsers (the hard part)
  pipeline/build.py    fetch → parse → merge → enrich → geocode → SQLite
  db.py                schema: developments + drafts tables
  emailer.py           email template + throttled SMTP send worker
  config.py            reads .env
  server.py            FastAPI: ~7 small JSON endpoints + serves the UI
ui/index.html          entire frontend — vanilla JS + Leaflet, no build step
data/raw/*.pdf         source PDFs (committed, so the parsers are reproducible)
data/ml.sqlite         the database (gitignored; rebuild with one command)
```

Data flows one way — PDFs → SQLite → browser — and the only writes coming
back are draft edits and send status.

**`parse.py`** is where the effort went. The PDFs are multi-column layouts,
so naive text extraction merges columns into garbage. Instead, every parser
works from pdfplumber's word *coordinates*: group words into visual rows by
y-position, slice rows into columns by x-ranges measured off the real
documents. The weird-looking constants and special cases each encode a real
quirk (senior buildings flagged by a `*Age 62 +` suffix, page numbers that
look exactly like unit counts, one building whose name is truncated in the
government's own PDF). Debug any of it with:

```bash
.venv/bin/python app/pipeline/parse.py all
```

**`build.py`** merges everything into SQLite, **upserting** on
`(source, name, address)` so row IDs — and therefore your draft history —
are stable across refreshes. It fetches with a browser User-Agent (both
government sites 403 anything that looks like a script) and scrapes the HCR
PDF's current URL from their site because it's date-versioned. The email
cross-matching lives here too: management-company names are normalized
(strip Inc/LLC/Management/…) and joined across the two lists.

**`emailer.py`** — the template is the `BODY` string at the top; edit it to
change every future draft. Drafts move through `draft → approved → sent`
(or `skipped`/`error`), and only `approved` ever sends. Sending runs in a
background thread: one SMTP session, mark each draft as it goes, sleep
between sends, per-building failures don't stop the batch. Sent drafts are
locked forever — regenerating can never cause a double-send.

**`server.py` + `ui/index.html`** — the API is thin CRUD over the two tables.
The frontend has no framework and no build step: one `render()` pass reflects
the selection set (`SEL`) into table rows, map marker styles, and the tray;
markers are persistent objects restyled in place (that's what makes
hover-linking and click-to-select smooth). Selection persists in
`localStorage`. Below 900px wide, the sidebar becomes a drawer and the queue
goes full-width.

### Things you'll most likely want to change

| What | Where |
|---|---|
| Email wording / what you're looking for | `BODY` in `app/emailer.py` |
| Send speed | `SEND_INTERVAL_SECONDS` in `.env` |
| Transit-estimate formula | `est_transit_min()` in `app/pipeline/build.py` |
| Selected-marker look | `markerStyle()` in `ui/index.html` |
| Default-checked boroughs | the `nyc` list in `ui/index.html` |

---

## Troubleshooting

- **"Sending isn't configured" banner** — `GMAIL_APP_PASSWORD` is empty in
  `.env`, or you edited `.env` after starting the server (restart it).
- **SMTP login fails** — app passwords require 2-Step Verification to be on;
  paste the 16 characters without spaces.
- **A draft shows `error`** — hover/expand the card for the reason (usually a
  dead mailbox). Fix the address on the card and re-approve, or skip it and
  call instead.
- **Build fails downloading PDFs** — the agencies occasionally move files.
  Check the four URLs above; update them in `app/pipeline/build.py`
  (`PDF_SOURCES`). If HPD *revises a layout*, run the parser debug command
  above and adjust the x-ranges in `parse.py`.
- **Map dots but no table rows (or vice versa)** — a filter is doing what you
  asked; check "Has email only" and the transit slider first.

## Fine print

Not affiliated with HPD, HCR, or NYC. Data is parsed from public documents
and can lag reality — waitlist status is only as fresh as the government's
PDFs, and "unknown" means *unknown*, not closed (that's what the emails are
for). Verify anything important with the building before mailing $75.
