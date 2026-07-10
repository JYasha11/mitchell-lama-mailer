"""Draft generation and throttled SMTP sending."""
import re
import smtplib
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr

from app import config, db

SUBJECT = "Waiting list inquiry — {name}"

BODY = """\
Hello,

I'm writing to ask about the waiting list for {name}{addr_clause}. Could you let me know:

  1. Is the waiting list for this development currently open?
  2. If it is open, how can I request an application?
  3. If it is closed, how are re-openings announced, and is there any way to be \
notified when the list opens again?

A little about me: I'm a household of one looking for anything from a studio up to \
a two-bedroom apartment.{via_clause}

Thank you very much for your time.

Best regards,
{sender_name}
{sender_email}{sender_phone}
"""

VIA_HCR = (" I found this contact information on HCR's list of state-supervised "
           "Mitchell-Lama developments.")
VIA_MATCH = (" I found your company's contact information on HCR's Mitchell-Lama "
             "list; I understand you are the managing agent for this development, "
             "and I apologize if there is a better address for this inquiry.")


def make_draft(dev):
    addr = dev["address"] or ""
    short_addr = re.sub(r",?\s*(New York|NY)\b.*$", "", addr).strip(" ,")
    via = ""
    if dev["email_source"] == "official":
        via = VIA_HCR
    elif dev["email_source"] == "company-match":
        via = VIA_MATCH
    body = BODY.format(
        name=dev["name"].title() if dev["name"].isupper() else dev["name"],
        addr_clause=f" at {short_addr}" if short_addr else "",
        via_clause=via,
        sender_name=config.SENDER_NAME,
        sender_email=config.GMAIL_USER,
        sender_phone=f"\n{config.SENDER_PHONE}" if config.SENDER_PHONE else "",
    )
    subject = SUBJECT.format(name=dev["name"].title() if dev["name"].isupper() else dev["name"])
    return subject, body


def generate_drafts(con, dev_ids):
    made = 0
    for did in dev_ids:
        dev = con.execute("SELECT * FROM developments WHERE id=?", (did,)).fetchone()
        if not dev or not dev["email"]:
            continue
        subject, body = make_draft(dev)
        con.execute(
            """INSERT INTO drafts (development_id, to_email, subject, body)
               VALUES (?,?,?,?)
               ON CONFLICT(development_id) DO UPDATE SET
                 to_email=excluded.to_email, subject=excluded.subject,
                 body=excluded.body, status='draft', error=NULL
               WHERE drafts.status NOT IN ('sent')""",
            (did, dev["email"], subject, body))
        made += 1
    con.commit()
    return made


# --- sending ---------------------------------------------------------------
_send_state = {"running": False, "sent": 0, "total": 0, "last_error": None}
_lock = threading.Lock()


def send_state():
    with _lock:
        return dict(_send_state)


def _send_one(smtp, draft):
    msg = EmailMessage()
    msg["From"] = formataddr((config.SENDER_NAME, config.GMAIL_USER))
    msg["To"] = draft["to_email"]
    msg["Subject"] = draft["subject"]
    msg.set_content(draft["body"])
    smtp.send_message(msg)


def send_approved_worker():
    """Send every approved draft, throttled. Runs in a thread."""
    con = db.connect()
    drafts = con.execute("SELECT * FROM drafts WHERE status='approved'").fetchall()
    with _lock:
        _send_state.update(running=True, sent=0, total=len(drafts), last_error=None)
    try:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT) as smtp:
            smtp.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            for i, d in enumerate(drafts):
                try:
                    _send_one(smtp, d)
                    con.execute("UPDATE drafts SET status='sent', sent_at=datetime('now') "
                                "WHERE id=?", (d["id"],))
                    with _lock:
                        _send_state["sent"] += 1
                except Exception as e:  # record per-draft failure, keep going
                    con.execute("UPDATE drafts SET status='error', error=? WHERE id=?",
                                (str(e)[:500], d["id"]))
                    with _lock:
                        _send_state["last_error"] = str(e)[:200]
                con.commit()
                if i < len(drafts) - 1:
                    time.sleep(config.SEND_INTERVAL_SECONDS)
    except Exception as e:
        with _lock:
            _send_state["last_error"] = str(e)[:200]
    finally:
        con.close()
        with _lock:
            _send_state["running"] = False


def start_sending():
    with _lock:
        if _send_state["running"]:
            return False
    threading.Thread(target=send_approved_worker, daemon=True).start()
    return True
