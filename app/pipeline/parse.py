"""Parsers for the four official Mitchell-Lama PDFs.

Each parser returns a list of plain dicts. Layouts are position-based
(pdfplumber word x/y coordinates) because the plain text runs columns together.
"""
import re
import pdfplumber

PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")

BOROUGHS = {"BROOKLYN", "BRONX", "MANHATTAN", "QUEENS", "STATEN ISLAND"}
NYC_COUNTIES = {"Bronx": "Bronx", "Kings": "Brooklyn", "New York": "Manhattan",
                "Queens": "Queens", "Richmond": "Staten Island"}


def _lines(page, tol=3):
    """Group a page's words into visual lines by top coordinate."""
    words = page.extract_words()
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


def _text(words):
    return " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"]))


# --------------------------------------------------------------------------
# 1. HPD master list (MLLIST.pdf) — 3 columns:
#    dev name+address (x<270), unit count (270..380), managing agent (x>=380)
# --------------------------------------------------------------------------
def parse_mllist(path="data/raw/mllist.pdf"):
    devs, current, section = [], None, (None, None)
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for line in _lines(page, tol=6):
                dev_w = [w for w in line if w["x0"] < 268]
                unit_w = [w for w in line if 268 <= w["x0"] < 340]
                agent_w = [w for w in line if w["x0"] >= 340]
                dev_t, unit_t, agent_t = _text(dev_w), _text(unit_w), _text(agent_w)

                # section header e.g. "BROOKLYN CO-OPS" / "STATEN ISLAND RENTALS"
                if dev_t and not unit_t and not agent_t:
                    upper = dev_t.upper()
                    for b in BOROUGHS:
                        if upper.startswith(b) and ("CO-OP" in upper or "RENTAL" in upper):
                            section = (b.title(), "Coop" if "CO-OP" in upper else "Rental")
                            break
                    else:
                        if current and dev_t.startswith("(For Person"):
                            current["senior_only"] = True
                        elif current and not PHONE_RE.search(dev_t):
                            current["address_lines"].append(dev_t)
                    continue

                if unit_t and re.fullmatch(r"[\d,]+", unit_t) and not dev_t and not agent_t:
                    continue  # page number footer
                if unit_t and re.fullmatch(r"[\d,]+", unit_t):
                    # new development record
                    if current:
                        devs.append(current)
                    current = {
                        "name": dev_t, "units": int(unit_t.replace(",", "")),
                        "borough": section[0], "kind": section[1],
                        "senior_only": False, "address_lines": [],
                        "agent_lines": [agent_t] if agent_t else [],
                    }
                    continue

                if current is None:
                    continue
                if dev_t:
                    if dev_t.startswith("(For Person"):
                        current["senior_only"] = True
                    elif not dev_t.startswith("Tel"):
                        current["address_lines"].append(dev_t)
                if agent_t:
                    current["agent_lines"].append(agent_t)
    if current:
        devs.append(current)

    out = []
    for d in devs:
        agent_text = " ".join(d["agent_lines"])
        phone = PHONE_RE.search(agent_text)
        out.append({
            "name": d["name"].strip(),
            "address": ", ".join(d["address_lines"]).strip(),
            "borough": d["borough"],
            "kind": d["kind"],
            "units": d["units"],
            "senior_only": d["senior_only"],
            "agent_name": d["agent_lines"][0].strip() if d["agent_lines"] else None,
            "agent_address": ", ".join(
                l for l in d["agent_lines"][1:] if not l.startswith("Tel")).strip() or None,
            "phone": phone.group(0) if phone else None,
        })
    return out


# --------------------------------------------------------------------------
# 2. HCR consolidated state list — one row per line, columns split by x:
#    HID<74 | name 74-195 | address 195-346 | county 346-389 | units 389-431
#    | article 431-456 | type 456-502 | tenant 502-547 | mgmt 547-849 | agency 849+
# --------------------------------------------------------------------------
def parse_hcr(path="data/raw/hcr_consolidated.pdf"):
    # county + units share x-space (units are right-aligned digits), so parse
    # 346..431 as one zone and split alpha/digits afterwards
    cols = [(0, 74), (74, 194), (194, 346), (346, 431),
            (431, 456), (456, 502), (502, 547), (547, 849), (849, 9999)]
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for line in _lines(page):
                fields = []
                for lo, hi in cols:
                    fields.append(_text([w for w in line if lo <= w["x0"] < hi]))
                hid = fields[0]
                if not re.fullmatch(r"[HU]\d{3}[A-Z]?", hid):
                    continue
                cu = re.match(r"^([A-Za-z .]+?)\s*([\d,]+)?$", fields[3])
                county = cu.group(1).strip() if cu else fields[3]
                units = int(cu.group(2).replace(",", "")) if cu and cu.group(2) else None
                mgmt = fields[7]
                email = EMAIL_RE.search(mgmt)
                phone = PHONE_RE.search(mgmt) or re.search(r"\b\d{10}\b", mgmt)
                mgmt_name = mgmt
                if email:
                    mgmt_name = mgmt_name.replace(email.group(0), " ")
                if phone:
                    mgmt_name = mgmt_name.replace(phone.group(0), " ")
                mgmt_name = re.sub(r"\bx ?\d+\b", " ", mgmt_name)
                mgmt_name = re.sub(r"\s{2,}", " ", mgmt_name).strip(" ,")
                out.append({
                    "hid": hid,
                    "name": fields[1],
                    "address": fields[2],
                    "county": county,
                    "units": units,
                    "article": fields[4],
                    "kind": fields[5],           # Rental | Coop
                    "tenant_type": fields[6],    # Family | Senior | Staff
                    "agent_name": mgmt_name or None,
                    "email": email.group(0).lower() if email else None,
                    "phone": phone.group(0) if phone else None,
                    "agency": fields[8],
                })
    return out


# --------------------------------------------------------------------------
# 3. HPD open external waitlists — blocks per development.
#    dev col 70..268 | type 268..335 | statuses at x≈341/390/440/490/529
#    | agent col >=570 | federally-subsidized Yes/No at x<70
# --------------------------------------------------------------------------
SIZE_SLOTS = [("studio", 335, 385), ("one_br", 385, 434), ("two_br", 434, 483),
              ("three_br", 483, 526), ("four_plus", 526, 570)]
STATUS_WORDS = {"Open", "Closed", "None"}


def parse_open_waitlists(path="data/raw/hpd_open_waitlists.pdf"):
    blocks = []
    current = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for line in _lines(page, tol=5):
                dev_w = [w for w in line if 70 <= w["x0"] < 268]
                dev_t = _text(dev_w)
                has_status = any(w["text"] in STATUS_WORDS and w["x0"] >= 335
                                 for w in line)
                # senior buildings carry a "*Age 62 +" suffix after the name
                base, senior = dev_t, False
                m = re.match(r"^(.*?)\s*\*+\s*Age\s*62.*$", dev_t, re.I)
                if m:
                    base, senior = m.group(1), True
                is_name = (
                    base and base == base.upper() and not has_status
                    and not PHONE_RE.search(base) and not ZIP_RE.search(base)
                    and re.search(r"[A-Z]{3}", base)
                    and "MITCHELL-LAMA" not in base and "Project" not in dev_t
                )
                if is_name:
                    current = {"name": base.strip(), "senior": senior, "lines": []}
                    blocks.append(current)
                if current and not is_name:
                    current["lines"].append(line)

    out = []
    for b in blocks:
        rec = {"name": b["name"], "senior_only": b.get("senior", False),
               "kind": None, "federally_subsidized": None,
               "address": None, "phone": None,
               "studio": None, "one_br": None, "two_br": None,
               "three_br": None, "four_plus": None}
        addr_lines = []
        for line in b["lines"]:
            for w in line:
                x, t = w["x0"], w["text"]
                if t in ("Rental", "Cooperative") and 268 <= x < 335:
                    rec["kind"] = "Coop" if t == "Cooperative" else "Rental"
                if t in ("Yes", "No") and x < 70:
                    rec["federally_subsidized"] = t == "Yes"
                if t in STATUS_WORDS:
                    for key, lo, hi in SIZE_SLOTS:
                        if lo <= x < hi:
                            rec[key] = t
            dev_t = _text([w for w in line if 70 <= w["x0"] < 268])
            dev_t = re.sub(r"\b(Rental|Cooperative|Open|Closed|None)\b", "", dev_t).strip(" ,")
            if dev_t:
                m = PHONE_RE.search(dev_t)
                if m and not rec["phone"]:
                    rec["phone"] = m.group(0)
                    dev_t = dev_t.replace(m.group(0), "").strip(" ,")
                if dev_t:
                    addr_lines.append(dev_t)
        rec["address"] = ", ".join(addr_lines) or None
        out.append(rec)
    return out


# --------------------------------------------------------------------------
# 4. HPD short waitlists — simple text list
# --------------------------------------------------------------------------
def parse_short_waitlists(path="data/raw/hpd_short_waitlists.pdf"):
    with pdfplumber.open(path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    out = []
    pat = re.compile(
        r"^(?P<name>.+?)\s+(?P<kind>Rental|Coop|Cooperative)\s+(?P<phone>[\d-]{12,})\s*$")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = pat.match(line.strip())
        if m:
            addr = []
            for j in range(i + 1, min(i + 4, len(lines))):
                nxt = lines[j].strip()
                if pat.match(nxt) or not nxt:
                    break
                if ZIP_RE.search(nxt) or re.match(r"^\d", nxt):
                    addr.append(nxt)
                    if ZIP_RE.search(nxt):
                        break
            out.append({
                "name": m.group("name").strip(),
                "kind": "Coop" if m.group("kind").startswith("Coop") else "Rental",
                "phone": m.group("phone"),
                "address": ", ".join(addr) or None,
            })
    return out


if __name__ == "__main__":
    import json, sys
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    fns = {"mllist": parse_mllist, "hcr": parse_hcr,
           "open": parse_open_waitlists, "short": parse_short_waitlists}
    for k, fn in fns.items():
        if which not in ("all", k):
            continue
        rows = fn()
        print(f"== {k}: {len(rows)} rows")
        for r in rows[:3]:
            print(json.dumps(r))
