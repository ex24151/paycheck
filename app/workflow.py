"""Invoice workflow state machine.

received ─► (checks) ─► ready_to_pay ───────────────► approved ─► paid
                     ├► needs_verification ─(call-back)─► approved
                     └► on_hold ─(call-back + 2nd approver)─► approved
any open state ─► blocked (fraud reported → IBAN added to shared fraud list)
"""
from fastapi import HTTPException

from . import db
from .checks.bank import normalize

OPEN = {"ready_to_pay", "needs_verification", "on_hold"}

TRANSITIONS = {
    "approve": {"ready_to_pay"},
    "verify": {"needs_verification", "on_hold"},
    "second_approve": {"verified"},
    "pay": {"approved"},
    "block": OPEN | {"verified", "approved"},
}


def _load(invoice_id: int) -> dict:
    inv = db.row("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


def _guard(inv: dict, action: str) -> None:
    if inv["status"] not in TRANSITIONS[action]:
        raise HTTPException(409, f"Can't '{action}' an invoice that is '{inv['status']}'.")


def approve(invoice_id: int, actor: str, note: str | None) -> dict:
    inv = _load(invoice_id)
    _guard(inv, "approve")
    with db.tx() as c:
        c.execute("UPDATE invoices SET status='approved', decided_at=?, decided_by=? WHERE id=?", (db.now(), actor, invoice_id))
        db.audit(c, invoice_id, actor, "approved", note)
    return _load(invoice_id)


def verify_callback(invoice_id: int, actor: str, phone_used: str | None, note: str | None) -> dict:
    """Record a call-back to the supplier's KNOWN number. Red invoices then need a second approver."""
    inv = _load(invoice_id)
    _guard(inv, "verify")
    supplier = db.row("SELECT * FROM suppliers WHERE id = ?", (inv["supplier_id"],)) if inv["supplier_id"] else None
    if not supplier or not supplier.get("verified_phone"):
        raise HTTPException(400, "No verified phone number for this supplier in master data. Add one from a trusted source first.")
    if not phone_used or phone_used.replace(" ", "") != supplier["verified_phone"].replace(" ", ""):
        raise HTTPException(400, f"Call-back must use the number on file ({supplier['verified_phone']}), never one from the invoice or email.")
    new_status = "verified" if inv["risk_level"] == "red" else "approved"
    with db.tx() as c:
        c.execute("UPDATE invoices SET status=?, decided_at=?, decided_by=? WHERE id=?", (new_status, db.now(), actor, invoice_id))
        # A confirmed new IBAN becomes the verified account.
        if inv["iban"] and normalize(inv["iban"]) != normalize(supplier.get("verified_iban")):
            c.execute("UPDATE suppliers SET verified_iban=?, iban_verified_at=? WHERE id=?", (normalize(inv["iban"]), db.now(), supplier["id"]))
            db.audit(c, invoice_id, actor, "supplier_iban_updated", f"{supplier.get('verified_iban')} → {normalize(inv['iban'])}")
        db.audit(c, invoice_id, actor, "callback_verified", f"called {phone_used}. {note or ''}".strip())
    return _load(invoice_id)


def second_approve(invoice_id: int, actor: str, note: str | None) -> dict:
    inv = _load(invoice_id)
    _guard(inv, "second_approve")
    if actor.strip().lower() == (inv["decided_by"] or "").strip().lower():
        raise HTTPException(400, "Four-eyes rule: the second approver must be a different person.")
    with db.tx() as c:
        c.execute("UPDATE invoices SET status='approved', decided_at=?, decided_by=? WHERE id=?", (db.now(), actor, invoice_id))
        db.audit(c, invoice_id, actor, "second_approval", note)
    return _load(invoice_id)


def mark_paid(invoice_id: int, actor: str, note: str | None) -> dict:
    inv = _load(invoice_id)
    _guard(inv, "pay")
    with db.tx() as c:
        c.execute("UPDATE invoices SET status='paid' WHERE id=?", (invoice_id,))
        db.audit(c, invoice_id, actor, "paid", note)
    return _load(invoice_id)


def block(invoice_id: int, actor: str, note: str | None, report_fraud: bool = True) -> dict:
    inv = _load(invoice_id)
    _guard(inv, "block")
    with db.tx() as c:
        c.execute("UPDATE invoices SET status='blocked', decided_at=?, decided_by=? WHERE id=?", (db.now(), actor, invoice_id))
        db.audit(c, invoice_id, actor, "blocked", note)
        if report_fraud and inv["iban"]:
            supplier_iban = None
            if inv["supplier_id"]:
                s = db.row("SELECT verified_iban FROM suppliers WHERE id=?", (inv["supplier_id"],))
                supplier_iban = normalize(s["verified_iban"]) if s else None
            # Never blacklist the supplier's genuine verified account.
            if normalize(inv["iban"]) != supplier_iban:
                c.execute("INSERT OR IGNORE INTO known_bad_accounts (iban, reason, reported_at) VALUES (?,?,?)",
                          (normalize(inv["iban"]), f"Reported on invoice #{invoice_id}: {note or 'fraud attempt'}", db.now()))
                db.audit(c, invoice_id, actor, "fraud_reported", normalize(inv["iban"]))
    return _load(invoice_id)
