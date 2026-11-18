"""Demo data: three suppliers with payment history, plus incoming invoices
that show each kind of attack. Run: python -m app.seed"""
from datetime import datetime, timedelta, timezone

from . import db
from .engine import check_and_store

SUPPLIERS = [
    # name, country, domain, verified IBAN, verified phone
    ("Nordwind Logistics GmbH", "DE", "nordwind-logistics.de", "DE89370400440532013000", "+49 30 1234 5678"),
    ("Brightline Office Supplies Ltd", "GB", "brightline.co.uk", "GB29NWBK60161331926819", "+44 20 7946 0018"),
    ("Atelier Lumière SARL", "FR", "atelier-lumiere.fr", "FR1420041010050500013M02606", "+33 1 42 68 53 00"),
]

HISTORY = {
    "Nordwind Logistics GmbH": [4180.50, 3925.00, 4410.20, 4055.75, 3990.10, 4302.40],
    "Brightline Office Supplies Ltd": [312.40, 298.15, 355.90, 287.60, 330.05],
    "Atelier Lumière SARL": [1250.00, 1189.90, 1312.45, 1275.30],
}

INCOMING = [
    dict(supplier_name="Brightline Office Supplies Ltd", invoice_number="BL-20931", amount=318.70, currency="GBP",
         iban="GB29NWBK60161331926819", sender_email="accounts@brightline.co.uk",
         email_body="Hi, please find attached our invoice for November stationery. Thanks, Brightline Accounts"),
    dict(supplier_name="Nordwind Logistics GmbH", invoice_number="NW-2026-1187", amount=48500.00,
         iban="LT121000011101001000", sender_email="billing@nordwind-logistlcs.de", reply_to="nordwind.finance@gmail.com",
         email_body="Dear customer,\nDue to an ongoing audit our bank account has changed. Please use our new bank details below "
                    "and pay this invoice urgently, today if possible. Please do not call our office, the phone lines are being "
                    "migrated. Keep this confidential until the audit is complete.\nKind regards, Nordwind Billing"),
    dict(supplier_name="Atelier Lumière SARL", invoice_number="AL-0457", amount=1298.00,
         iban="FR1420041010050500013M02606", sender_email="facturation@atelier-lumiere.com",
         email_body="Bonjour, veuillez trouver ci-joint notre facture. Merci de procéder au paiement dès que possible."),
    dict(supplier_name="Nordwind Logistics GmbH", invoice_number="NW-2026-1191", amount=4125.30,
         iban="DE89370400440532013000", sender_email="billing@nordwind-logistics.de",
         email_body="Hello, attached is invoice NW-2026-1191 for October freight. Payment terms 30 days. Best, Nordwind Billing"),
    dict(supplier_name="Swiftserve Consulting", invoice_number="SS-001", amount=9500.00,
         iban="NL91ABNA0417164300", sender_email="ceo.swiftserve@outlook.com",
         email_body="Hi, as agreed with your CEO please process this consulting invoice immediately. He is in meetings and unreachable."),
]


def seed(use_ai: bool = False) -> None:
    db.init_db()
    with db.tx() as c:
        for t in ("findings", "audit_log", "invoices", "suppliers", "known_bad_accounts"):
            c.execute(f"DELETE FROM {t}")
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(timespec="seconds")
        for name, country, domain, iban, phone in SUPPLIERS:
            cur = c.execute(
                "INSERT INTO suppliers (name, country, email_domain, verified_iban, verified_phone, iban_verified_at, created_at) "
                "VALUES (?,?,?,?,?,?,?)", (name, country, domain, iban, phone, old, old))
            sid = cur.lastrowid
            for i, amt in enumerate(HISTORY[name]):
                when = (datetime.now(timezone.utc) - timedelta(days=30 * (len(HISTORY[name]) - i) + 5)).isoformat(timespec="seconds")
                c.execute(
                    "INSERT INTO invoices (supplier_id, supplier_name, invoice_number, amount, currency, iban, sender_email, status, "
                    "risk_score, risk_level, received_at, decided_at, decided_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, name, f"H-{sid}-{i:03d}", amt, "GBP" if country == "GB" else "EUR", iban, f"billing@{domain}",
                     "paid", 0, "green", when, when, "history-import"))
        c.execute("INSERT INTO known_bad_accounts (iban, reason, reported_at) VALUES (?,?,?)",
                  ("NL91ABNA0417164300", "Reported by another customer (shared network)", db.now()))
    for inv in INCOMING:
        with db.tx() as c:
            cur = c.execute(
                "INSERT INTO invoices (supplier_name, invoice_number, amount, currency, iban, sender_email, reply_to, email_body, "
                "invoice_text, status, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (inv["supplier_name"], inv["invoice_number"], inv["amount"], inv.get("currency", "EUR"), inv["iban"],
                 inv["sender_email"], inv.get("reply_to"), inv["email_body"], None, "received", db.now()))
            db.audit(c, cur.lastrowid, "email-inbox", "received", inv["sender_email"])
            iid = cur.lastrowid
        check_and_store(iid, use_ai=use_ai)


if __name__ == "__main__":
    import os
    seed(use_ai=os.environ.get("PAYCHECK_SEED_AI") == "1")
    print("Seeded demo data into", os.path.abspath(db.DB_PATH))
