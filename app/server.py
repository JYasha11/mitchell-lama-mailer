"""Local web app: browse/filter developments, build and send the email queue.

Run:  uvicorn app.server:app --port 8877
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app import config, db, emailer

app = FastAPI(title="mitchell-lama-mailer")
UI = Path(__file__).resolve().parent.parent / "ui" / "index.html"


def rows(q, *args):
    con = db.connect()
    try:
        return [dict(r) for r in con.execute(q, args).fetchall()]
    finally:
        con.close()


@app.get("/")
def index():
    return FileResponse(UI)


@app.get("/api/config")
def get_config():
    return {
        "sender_name": config.SENDER_NAME,
        "gmail_user": config.GMAIL_USER,
        "smtp_configured": bool(config.GMAIL_USER and config.GMAIL_APP_PASSWORD),
        "send_interval": config.SEND_INTERVAL_SECONDS,
    }


@app.get("/api/developments")
def developments():
    devs = rows("""
        SELECT d.*, dr.status AS draft_status
        FROM developments d LEFT JOIN drafts dr ON dr.development_id = d.id
        ORDER BY d.on_open_list DESC, d.on_short_list DESC, d.name
    """)
    return {"developments": devs}


class DraftReq(BaseModel):
    ids: list[int]


@app.post("/api/drafts/generate")
def gen_drafts(req: DraftReq):
    con = db.connect()
    try:
        made = emailer.generate_drafts(con, req.ids)
        ids = [r["id"] for r in con.execute(
            "SELECT id FROM drafts WHERE development_id IN (%s)"
            % ",".join("?" * len(req.ids)), req.ids)] if req.ids else []
    finally:
        con.close()
    return {"generated": made, "draft_ids": ids}


@app.get("/api/drafts")
def drafts():
    return {"drafts": rows("""
        SELECT dr.*, d.name AS dev_name, d.borough, d.kind, d.email_source
        FROM drafts dr JOIN developments d ON d.id = dr.development_id
        ORDER BY dr.status, d.name
    """)}


class BulkStatus(BaseModel):
    ids: list[int]
    status: str


# NOTE: must be declared before the /api/drafts/{draft_id} route, or FastAPI
# tries to parse "bulk" as a draft_id and returns 422
@app.post("/api/drafts/bulk/status")
def bulk_status(req: BulkStatus):
    if req.status not in ("draft", "approved", "skipped"):
        return JSONResponse({"error": "bad status"}, status_code=400)
    con = db.connect()
    try:
        con.executemany(
            "UPDATE drafts SET status=? WHERE id=? AND status != 'sent'",
            [(req.status, i) for i in req.ids])
        con.commit()
    finally:
        con.close()
    return {"ok": True}


class DraftEdit(BaseModel):
    subject: str | None = None
    body: str | None = None
    to_email: str | None = None
    status: str | None = None  # draft | approved | skipped


@app.post("/api/drafts/{draft_id}")
def edit_draft(draft_id: int, req: DraftEdit):
    con = db.connect()
    try:
        cur = con.execute("SELECT status FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if not cur:
            return JSONResponse({"error": "not found"}, status_code=404)
        if cur["status"] == "sent":
            return JSONResponse({"error": "already sent"}, status_code=400)
        for field in ("subject", "body", "to_email", "status"):
            v = getattr(req, field)
            if v is not None:
                if field == "status" and v not in ("draft", "approved", "skipped"):
                    return JSONResponse({"error": "bad status"}, status_code=400)
                con.execute(f"UPDATE drafts SET {field}=? WHERE id=?", (v, draft_id))
        con.commit()
    finally:
        con.close()
    return {"ok": True}


@app.post("/api/send")
def send():
    if not (config.GMAIL_USER and config.GMAIL_APP_PASSWORD):
        return JSONResponse(
            {"error": "GMAIL_USER / GMAIL_APP_PASSWORD not set in .env"}, status_code=400)
    started = emailer.start_sending()
    return {"started": started, **emailer.send_state()}


@app.get("/api/send/status")
def send_status():
    return emailer.send_state()
