import os, tempfile

os.environ["PAYCHECK_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["PAYCHECK_OFFLINE"] = "1"
os.environ["PAYCHECK_AI"] = "0"

import pytest
from fastapi.testclient import TestClient

from app import db
from app.checks.domain import is_lookalike
from app.extract import fields_from_text
from app.main import app
from app.seed import seed

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    seed(use_ai=False)


def open_invoices():
    return {i["invoice_number"]: i for i in client.get("/api/invoices").json()}


@pytest.mark.parametrize("cand,real,hit", [
    ("nordwind-logistlcs.de", "nordwind-logistics.de", True),
    ("atelier-lumiere.com", "atelier-lumiere.fr", True),
    ("brightline-payments.co.uk", "brightline.co.uk", True),
    ("rnicrosoft.com", "microsoft.com", True),
    ("brightline.co.uk", "brightline.co.uk", False),
    ("mail.brightline.co.uk", "brightline.co.uk", False),
    ("totally-different.com", "brightline.co.uk", False),
])
def test_lookalike(cand, real, hit):
    assert bool(is_lookalike(cand, real)) is hit


def test_seed_scores():
    inv = open_invoices()
    assert inv["BL-20931"]["risk_level"] == "green"
    assert inv["NW-2026-1191"]["risk_level"] == "green"
    assert inv["NW-2026-1187"]["risk_level"] == "red"   # changed bank + look-alike domain
    assert inv["AL-0457"]["risk_level"] == "red"        # .com instead of .fr
    assert inv["SS-001"]["risk_level"] == "red"         # account on fraud list


def test_green_flow_approve_and_pay():
    iid = open_invoices()["BL-20931"]["id"]
    assert client.post(f"/api/invoices/{iid}/approve", json={"actor": "Ana"}).json()["status"] == "approved"
    assert client.post(f"/api/invoices/{iid}/pay", json={"actor": "Ana"}).json()["status"] == "paid"


def test_red_cannot_be_approved_directly():
    iid = open_invoices()["NW-2026-1187"]["id"]
    r = client.post(f"/api/invoices/{iid}/approve", json={"actor": "Ana"})
    assert r.status_code == 409


def test_callback_must_use_number_on_file_and_four_eyes():
    iid = open_invoices()["AL-0457"]["id"]
    bad = client.post(f"/api/invoices/{iid}/verify", json={"actor": "Ana", "phone_used": "+33 9 99 99 99 99"})
    assert bad.status_code == 400
    ok = client.post(f"/api/invoices/{iid}/verify", json={"actor": "Ana", "phone_used": "+33 1 42 68 53 00"})
    assert ok.json()["status"] == "verified"
    same = client.post(f"/api/invoices/{iid}/second-approve", json={"actor": "ana"})
    assert same.status_code == 400
    assert client.post(f"/api/invoices/{iid}/second-approve", json={"actor": "Ben"}).json()["status"] == "approved"


def test_block_adds_iban_to_fraud_list_and_future_invoice_is_red():
    iid = open_invoices()["NW-2026-1187"]["id"]
    client.post(f"/api/invoices/{iid}/block", json={"actor": "Ana", "note": "fake"})
    assert "LT121000011101001000" in {r["iban"] for r in client.get("/api/fraud-list").json()}
    new = client.post("/api/invoices", json={"supplier_name": "Brightline Office Supplies Ltd", "amount": 300.10,
                                             "iban": "LT12 1000 0111 0100 1000", "sender_email": "accounts@brightline.co.uk"}).json()
    assert new["risk_level"] == "red"
    assert any(f["title"] == "Account is on the fraud list" for f in new["findings"])


def test_block_never_blacklists_genuine_account():
    iid = open_invoices()["AL-0457"]["id"]  # uses the real verified IBAN
    client.post(f"/api/invoices/{iid}/block", json={"actor": "Ana"})
    assert "FR1420041010050500013M02606" not in {r["iban"] for r in client.get("/api/fraud-list").json()}


def test_extract_fields():
    text = "INVOICE\nInvoice No: NW-2026-2000\nIBAN: DE89 3704 0044 0532 0130 00\nSubtotal 1.000,00\nTotal due: 1.190,00 EUR"
    f = fields_from_text(text)
    assert f["iban"] == "DE89370400440532013000"
    assert f["amount"] == 1190.00
    assert f["invoice_number"] == "NW-2026-2000"


def test_upload_txt():
    body = b"Invoice number: X-77\nIBAN GB29 NWBK 6016 1331 9268 19\nTotal: 305.20"
    r = client.post("/api/invoices/upload", files={"file": ("inv.txt", body, "text/plain")},
                    data={"supplier_name": "Brightline Office Supplies Ltd", "sender_email": "accounts@brightline.co.uk"})
    assert r.status_code == 200, r.text
    assert r.json()["risk_level"] == "green"


def test_ai_review_parses_structured_output(monkeypatch):
    from types import SimpleNamespace
    from app.checks import ai

    captured = {}

    class FakeMessages:
        def create(self, **kw):
            captured.update(kw)
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(
                type="text", text='{"risk_level":"high","summary":"Bank change plus look-alike domain.",'
                                  '"red_flags":["Domain uses l instead of i"],"recommended_action":"block"}')])

    fake = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    monkeypatch.setattr(ai, "client", lambda: fake)
    monkeypatch.setattr(ai, "ai_enabled", lambda: True)
    inv = db.row("SELECT * FROM invoices WHERE invoice_number='NW-2026-1187'")
    r, err = ai.review(inv, None, [], [])
    assert err is None and r.recommended_action == "block"
    assert captured["model"] == "claude-opus-5-5"
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert "<email_body>" in captured["messages"][0]["content"]
    f = ai.to_findings(r)
    assert f[0].severity == "critical" and len(f) == 2


def test_ai_refusal_is_handled(monkeypatch):
    from types import SimpleNamespace
    from app.checks import ai
    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(stop_reason="refusal", content=[]))))
    monkeypatch.setattr(ai, "client", lambda: fake)
    monkeypatch.setattr(ai, "ai_enabled", lambda: True)
    r, err = ai.review({"supplier_name": "x"}, None, [], [])
    assert r is None and "declined" in err
