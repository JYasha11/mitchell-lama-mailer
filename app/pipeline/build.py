"""Fetch PDFs, parse, merge, enrich emails, geocode, and load SQLite.

Run:  python -m app.pipeline.build [--skip-fetch] [--skip-geocode]
"""
import argparse
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app import db
from app.pipeline import parse

RAW = Path("data/raw")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

PDF_SOURCES = {
    "mllist.pdf": "https://www.nyc.gov/assets/hpd/downloads/pdfs/services/MLLIST.pdf",
    "hpd_open_waitlists.pdf": "https://www.nyc.gov/assets/hpd/downloads/pdfs/services/ML-waiting-Lists-Status.pdf",
    "hpd_short_waitlists.pdf": "https://www.nyc.gov/assets/hpd/downloads/pdfs/services/Short-waiting-Lists.pdf",
}
# HCR consolidated list URL is date-versioned; scrape it from the applicant page.
HCR_PAGE = "https://hcr.ny.gov/mitchell-lama-applicant-information"
HCR_PDF_RE = re.compile(r'href="(/system/files/documents/[^"]*consolidated[^"]*\.pdf)"', re.I)

MIDTOWN = (40.7549, -73.9840)  # Times Square-ish
NYC_COUNTIES = {"Bronx": "Bronx", "Kings": "Brooklyn", "New York": "Manhattan",
                "Queens": "Queens", "Richmond": "Staten Island"}
COMMUTABLE_COUNTIES = set(NYC_COUNTIES) | {"Westchester", "Nassau"}


def fetch_pdfs():
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=60) as c:
        for fname, url in PDF_SOURCES.items():
            r = c.get(url)
            r.raise_for_status()
            (RAW / fname).write_bytes(r.content)
            print(f"fetched {fname} ({len(r.content)//1024} KB)")
        page = c.get(HCR_PAGE).text
        m = HCR_PDF_RE.search(page)
        if not m:
            print("WARN: could not find HCR consolidated PDF link; keeping existing file")
        else:
            r = c.get("https://hcr.ny.gov" + m.group(1))
            r.raise_for_status()
            (RAW / "hcr_consolidated.pdf").write_bytes(r.content)
            print(f"fetched hcr_consolidated.pdf ({len(r.content)//1024} KB) from {m.group(1)}")


def norm_name(s):
    s = s.upper()
    s = re.sub(r"\b(II|2)\b", "2", s)
    s = re.sub(r"\b(III|3)\b", "3", s)
    s = re.sub(r"\b(I|1)\b", "1", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_company(s):
    if not s:
        return ""
    s = s.upper()
    s = re.sub(r"\b(INC|LLC|CORP|CO|COMPANY|MANAGEMENT|MGMT|SERVICES|REAL|ESTATE|"
               r"REALTY|GROUP|ASSOCIATES|DEVELOPMENT|DEV|THE)\b\.?", " ", s)
    s = re.sub(r"[^A-Z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def haversine_miles(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def est_transit_min(miles):
    # rough door-to-door subway/bus estimate: base wait+walk plus ~4.5 min/mile
    return int(round(12 + miles * 4.5))


def geocode_all(con, client):
    rows = con.execute(
        "SELECT id, address, borough, county, source FROM developments WHERE lat IS NULL"
    ).fetchall()
    for r in rows:
        addr = r["address"] or ""
        addr = addr.replace(" l0", " 10")  # HPD PDF typo: lowercase L in zips
        is_nyc = (r["county"] in NYC_COUNTIES) if r["source"] == "HCR" \
            else (r["borough"] in NYC_COUNTIES.values())
        lat = lng = None

        def try_geosearch():
            resp = client.get("https://geosearch.planninglabs.nyc/v2/search",
                              params={"text": addr, "size": 1}, timeout=20)
            feats = resp.json().get("features", [])
            return (feats[0]["geometry"]["coordinates"][1],
                    feats[0]["geometry"]["coordinates"][0]) if feats else (None, None)

        def try_census():
            resp = client.get(
                "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
                params={"address": addr, "benchmark": "Public_AR_Current",
                        "format": "json"}, timeout=30)
            matches = resp.json().get("result", {}).get("addressMatches", [])
            if matches:
                c = matches[0]["coordinates"]
                return c["y"], c["x"]
            return None, None

        try:
            attempts = [try_geosearch, try_census] if is_nyc else [try_census]
            for attempt in attempts:
                lat, lng = attempt()
                if lat is not None:
                    break
        except Exception as e:
            print(f"  geocode error id={r['id']} {addr[:40]!r}: {e}")
        if lat is not None:
            miles = haversine_miles((lat, lng), MIDTOWN)
            con.execute(
                "UPDATE developments SET lat=?, lng=?, miles_to_midtown=?, est_transit_min=? WHERE id=?",
                (lat, lng, round(miles, 2), est_transit_min(miles), r["id"]))
        else:
            print(f"  no geocode match: id={r['id']} {addr!r}")
        con.commit()
        time.sleep(0.4)
    print(f"geocoded {len(rows)} addresses")


def build(skip_fetch=False, skip_geocode=False):
    if not skip_fetch:
        fetch_pdfs()

    ml = parse.parse_mllist()
    hcr = parse.parse_hcr()
    open_wl = parse.parse_open_waitlists()
    short_wl = parse.parse_short_waitlists()
    print(f"parsed: HPD={len(ml)} HCR={len(hcr)} open={len(open_wl)} short={len(short_wl)}")

    # company -> most common official email (from the HCR list, which has emails)
    company_emails = defaultdict(Counter)
    for r in hcr:
        if r["email"]:
            company_emails[norm_company(r["agent_name"])][r["email"]] += 1
    company_best = {k: c.most_common(1)[0][0] for k, c in company_emails.items() if k}

    con = db.connect()
    # waitlist flags are re-derived from the current PDFs each run
    con.execute("UPDATE developments SET on_open_list=0, on_short_list=0")

    def insert(rec):
        """Upsert on (source, name, address), preserving row id and geocode."""
        cols = ", ".join(rec)
        q = ", ".join("?" * len(rec))
        updates = ", ".join(f"{k}=excluded.{k}" for k in rec
                            if k not in ("source", "name", "address"))
        con.execute(
            f"INSERT INTO developments ({cols}) VALUES ({q}) "
            f"ON CONFLICT(source, name, address) DO UPDATE SET {updates}",
            list(rec.values()))
        return con.execute(
            "SELECT id FROM developments WHERE source=? AND name=? AND address IS ?",
            (rec["source"], rec["name"], rec.get("address"))).fetchone()["id"]

    # --- HPD master list
    hpd_ids = {}
    for r in ml:
        email = company_best.get(norm_company(r["agent_name"]))
        rid = insert({
            "source": "HPD", "name": r["name"], "address": r["address"],
            "borough": r["borough"], "county": None, "kind": r["kind"],
            "senior_only": int(r["senior_only"]), "units": r["units"],
            "agent_name": r["agent_name"], "agent_address": r["agent_address"],
            "phone": r["phone"],
            "email": email, "email_source": "company-match" if email else None,
        })
        hpd_ids[norm_name(r["name"])] = rid

    # --- HCR consolidated list
    for r in hcr:
        borough = NYC_COUNTIES.get(r["county"], r["county"])
        insert({
            "source": "HCR", "hid": r["hid"], "name": r["name"], "address": r["address"],
            "borough": borough, "county": r["county"], "kind": r["kind"],
            "senior_only": int(r["tenant_type"] == "Senior"), "units": r["units"],
            "agent_name": r["agent_name"], "phone": r["phone"],
            "email": r["email"], "email_source": "official" if r["email"] else None,
            "agency": r["agency"],
        })

    # --- HPD open external waitlists: match by name, else insert
    for r in open_wl:
        key = norm_name(r["name"])
        rid = hpd_ids.get(key)
        if rid is None:  # fuzzy: match on street number + zip
            zips = set(re.findall(r"\b\d{5}\b", r["address"] or ""))
            num = re.match(r"(\S+)", r["address"] or "")
            for row in con.execute("SELECT id, address FROM developments WHERE source='HPD'"):
                a = row["address"] or ""
                if num and a.startswith(num.group(1)) and zips & set(re.findall(r"\b\d{5}\b", a)):
                    rid = row["id"]
                    break
        if rid is None:
            rid = insert({
                "source": "HPD", "name": r["name"].title(), "address": r["address"],
                "borough": None, "kind": r["kind"],
                "senior_only": int(r["senior_only"]), "phone": r["phone"],
            })
        con.execute(
            """UPDATE developments SET on_open_list=1, federally_subsidized=?,
               wl_studio=?, wl_1br=?, wl_2br=?, wl_3br=?, wl_4br=?,
               senior_only=CASE WHEN ? THEN 1 ELSE senior_only END WHERE id=?""",
            (r["federally_subsidized"], r["studio"], r["one_br"], r["two_br"],
             r["three_br"], r["four_plus"], int(r["senior_only"]), rid))

    # --- HPD short waitlists
    for r in short_wl:
        rid = hpd_ids.get(norm_name(r["name"]))
        if rid:
            con.execute("UPDATE developments SET on_short_list=1 WHERE id=?", (rid,))
        else:
            rid = insert({"source": "HPD", "name": r["name"], "address": r["address"],
                          "kind": r["kind"], "phone": r["phone"], "on_short_list": 1})

    con.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', ?)",
                (datetime.now(timezone.utc).isoformat(),))
    con.commit()

    n = con.execute("SELECT COUNT(*) c FROM developments").fetchone()["c"]
    ne = con.execute("SELECT COUNT(*) c FROM developments WHERE email IS NOT NULL").fetchone()["c"]
    print(f"db: {n} developments, {ne} with an email")

    if not skip_geocode:
        with httpx.Client(headers={"User-Agent": UA}) as client:
            geocode_all(con, client)
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--skip-geocode", action="store_true")
    a = ap.parse_args()
    build(skip_fetch=a.skip_fetch, skip_geocode=a.skip_geocode)
