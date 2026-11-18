"""Runs every check, scores the invoice, and stores the result."""
from . import db
from .checks.ai import review as ai_review, to_findings as ai_findings
from .checks.anomaly import check_amount, check_language
from .checks.bank import check_bank, normalize
from .checks.domain import check_sender
from .checks.sanctions import check_sanctions
from .models import Finding

WEIGHTS = {"info": 0, "low": 8, "medium": 20, "high": 35, "critical": 70}


def score(findings: list[Finding]) -> tuple[int, str]:
    total = min(100, sum(WEIGHTS[f.severity] for f in findings))
    if any(f.severity == "critical" for f in findings) or total >= 60:
        return max(total, 60), "red"
    if total >= 25:
        return total, "amber"
    return total, "green"


def find_supplier(name: str) -> dict | None:
    return db.row("SELECT * FROM suppliers WHERE lower(name) = lower(?)", (name.strip(),))


def run_checks(invoice: dict, use_ai: bool = True) -> tuple[list[Finding], int, str, str | None]:
    supplier = find_supplier(invoice["supplier_name"])
    history = db.rows(
        "SELECT * FROM invoices WHERE supplier_id = ? AND id != ? ORDER BY received_at",
        (supplier["id"] if supplier else -1, invoice.get("id") or -1),
    )
    known_bad = {r["iban"] for r in db.rows("SELECT iban FROM known_bad_accounts")}
    recent_ibans = {normalize(h["iban"]) for h in history[-20:] if h.get("iban") and h["status"] in ("approved", "paid")}
    recent_ibans.add(normalize(invoice.get("iban")))
    recent_ibans.discard(None)

    findings: list[Finding] = []
    if not supplier:
        findings.append(Finding(check_name="supplier", severity="high", title="Unknown supplier",
                                detail=f"“{invoice['supplier_name']}” is not in your supplier list. "
                                       "Add and verify the supplier before paying."))
    findings += check_bank(invoice, supplier, known_bad, recent_changes=len(recent_ibans))
    findings += check_sender(invoice, supplier)
    findings += check_amount(invoice, history)
    findings += check_language(invoice)
    findings += check_sanctions(invoice["supplier_name"])

    ai_note = "AI review not run yet. Click Re-check to run it."
    if use_ai:
        r, err = ai_review(invoice, supplier, history, findings)
        if r:
            findings += ai_findings(r)
            ai_note = r.summary
        else:
            ai_note = err
    s, level = score(findings)
    return findings, s, level, ai_note


def check_and_store(invoice_id: int, actor: str = "system", use_ai: bool = True) -> dict:
    inv = db.row("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    findings, s, level, ai_note = run_checks(inv, use_ai=use_ai)
    status = {"green": "ready_to_pay", "amber": "needs_verification", "red": "on_hold"}[level]
    supplier = find_supplier(inv["supplier_name"])
    with db.tx() as c:
        c.execute("DELETE FROM findings WHERE invoice_id = ?", (invoice_id,))
        c.executemany(
            "INSERT INTO findings (invoice_id, check_name, severity, title, detail) VALUES (?,?,?,?,?)",
            [(invoice_id, f.check_name, f.severity, f.title, f.detail) for f in findings],
        )
        c.execute(
            "UPDATE invoices SET risk_score=?, risk_level=?, status=?, ai_summary=?, supplier_id=? WHERE id=?",
            (s, level, status, ai_note, supplier["id"] if supplier else None, invoice_id),
        )
        db.audit(c, invoice_id, actor, "checked", f"score {s} ({level}) → {status}")
    return db.row("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
