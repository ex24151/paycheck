"""PayCheck API + dashboard. Run: uvicorn app.main:app --reload"""
import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, workflow
from .checks.ai import ai_enabled
from .checks.bank import normalize
from .engine import check_and_store
from .extract import fields_from_text, pdf_text
from .models import Decision, InvoiceIn, SupplierIn

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
app = FastAPI(title="PayCheck", description="Stop fake invoices before you pay them.")
db.init_db()


def invoice_detail(invoice_id: int) -> dict:
    inv = db.row("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if not inv:
        raise HTTPException(404, "Invoice not found")
    order = "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END"
    inv["findings"] = db.rows(f"SELECT * FROM findings WHERE invoice_id = ? ORDER BY {order}, id", (invoice_id,))
    inv["audit"] = db.rows("SELECT * FROM audit_log WHERE invoice_id = ? ORDER BY id", (invoice_id,))
    inv["supplier"] = db.row("SELECT * FROM suppliers WHERE id = ?", (inv["supplier_id"],)) if inv["supplier_id"] else None
    return inv


@app.get("/api/status")
def status():
    return {"ai_enabled": ai_enabled(), "model": os.environ.get("PAYCHECK_MODEL", "claude-opus-5-5")}


@app.get("/api/stats")
def stats():
    q = lambda sql: db.row(sql)["n"]
    return {
        "checked": q("SELECT COUNT(*) n FROM invoices WHERE decided_by IS NOT 'history-import' OR decided_by IS NULL"),
        "open": q("SELECT COUNT(*) n FROM invoices WHERE status IN ('ready_to_pay','needs_verification','on_hold','verified')"),
        "blocked": q("SELECT COUNT(*) n FROM invoices WHERE status='blocked'"),
        "protected": db.row("SELECT COALESCE(SUM(amount),0) n FROM invoices WHERE status='blocked' OR (risk_level='red' AND status='on_hold')")["n"],
        "fraud_list": q("SELECT COUNT(*) n FROM known_bad_accounts"),
    }


@app.get("/api/invoices")
def list_invoices(include_history: bool = False):
    where = "" if include_history else "WHERE decided_by IS NOT 'history-import' OR decided_by IS NULL"
    return db.rows(f"SELECT * FROM invoices {where} ORDER BY id DESC")


@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: int):
    return invoice_detail(invoice_id)


def _create(inv: InvoiceIn, actor: str) -> dict:
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO invoices (supplier_name, invoice_number, amount, currency, iban, sender_email, reply_to, email_body, "
            "invoice_text, status, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (inv.supplier_name.strip(), inv.invoice_number, inv.amount, inv.currency.upper(), normalize(inv.iban),
             inv.sender_email, inv.reply_to, inv.email_body, inv.invoice_text, "received", db.now()))
        db.audit(c, cur.lastrowid, actor, "received", inv.sender_email)
        iid = cur.lastrowid
    check_and_store(iid, actor=actor)
    return invoice_detail(iid)


@app.post("/api/invoices")
def create_invoice(inv: InvoiceIn):
    return _create(inv, "web")


@app.post("/api/invoices/upload")
async def upload_invoice(
    file: UploadFile = File(...),
    supplier_name: str = Form(...),
    sender_email: str | None = Form(None),
    reply_to: str | None = Form(None),
    email_body: str | None = Form(None),
):
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 15 MB).")
    try:
        text = pdf_text(data) if data[:5] == b"%PDF-" else data.decode("utf-8", "ignore")
    except Exception:
        raise HTTPException(400, "Could not read that file. Upload a text-based PDF or .txt.")
    f = fields_from_text(text)
    if "amount" not in f:
        raise HTTPException(422, "Couldn't find the invoice total in the document. Enter the details manually instead.")
    inv = InvoiceIn(supplier_name=supplier_name, amount=f["amount"], invoice_number=f.get("invoice_number"),
                    iban=f.get("iban"), sender_email=sender_email or None, reply_to=reply_to or None,
                    email_body=email_body or None, invoice_text=text)
    return _create(inv, "upload")


@app.post("/api/invoices/{invoice_id}/recheck")
def recheck(invoice_id: int):
    inv = db.row("SELECT status FROM invoices WHERE id=?", (invoice_id,))
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv["status"] not in workflow.OPEN:
        raise HTTPException(409, "Only open invoices can be re-checked.")
    check_and_store(invoice_id, actor="web")
    return invoice_detail(invoice_id)


@app.post("/api/invoices/{invoice_id}/{action}")
def act(invoice_id: int, action: str, d: Decision):
    if action == "approve":
        workflow.approve(invoice_id, d.actor, d.note)
    elif action == "verify":
        workflow.verify_callback(invoice_id, d.actor, d.phone_used, d.note)
    elif action == "second-approve":
        workflow.second_approve(invoice_id, d.actor, d.note)
    elif action == "pay":
        workflow.mark_paid(invoice_id, d.actor, d.note)
    elif action == "block":
        workflow.block(invoice_id, d.actor, d.note)
    else:
        raise HTTPException(404, "Unknown action")
    return invoice_detail(invoice_id)


@app.get("/api/suppliers")
def suppliers():
    return db.rows("SELECT s.*, (SELECT COUNT(*) FROM invoices i WHERE i.supplier_id = s.id) AS invoice_count "
                   "FROM suppliers s ORDER BY name")


@app.post("/api/suppliers")
def add_supplier(s: SupplierIn):
    if db.row("SELECT id FROM suppliers WHERE lower(name)=lower(?)", (s.name.strip(),)):
        raise HTTPException(409, "A supplier with that name already exists.")
    with db.tx() as c:
        c.execute("INSERT INTO suppliers (name, country, email_domain, verified_iban, verified_phone, iban_verified_at, created_at) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (s.name.strip(), s.country.upper(), s.email_domain.lower().lstrip("@"), normalize(s.verified_iban),
                   s.verified_phone, db.now() if s.verified_iban else None, db.now()))
    return suppliers()


@app.get("/api/fraud-list")
def fraud_list():
    return db.rows("SELECT * FROM known_bad_accounts ORDER BY reported_at DESC")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))
