"""Bank-detail checks, built on schwifty (MIT) for IBAN/BIC validation."""
from datetime import datetime, timedelta, timezone

from schwifty import IBAN
from schwifty.exceptions import SchwiftyException

from ..models import Finding


def normalize(iban: str | None) -> str | None:
    return iban.replace(" ", "").upper() if iban else None


def check_bank(invoice: dict, supplier: dict | None, known_bad: set[str], recent_changes: int = 0) -> list[Finding]:
    out: list[Finding] = []
    raw = normalize(invoice.get("iban"))
    if not raw:
        out.append(Finding(check_name="bank", severity="low", title="No bank account on invoice",
                           detail="We could not find an IBAN to check. Pay only to the account in your supplier master data."))
        return out

    try:
        iban = IBAN(raw)
    except SchwiftyException as e:
        out.append(Finding(check_name="bank", severity="high", title="Invalid IBAN",
                           detail=f"The IBAN {raw} fails validation ({e}). Typos happen, but forged invoices often contain broken account numbers."))
        return out

    if raw in known_bad:
        out.append(Finding(check_name="bank", severity="critical", title="Account is on the fraud list",
                           detail="This IBAN was previously reported as used in a fraud attempt. Do not pay."))

    bank = iban.bank_name or "unknown bank"
    if supplier:
        verified = normalize(supplier.get("verified_iban"))
        if verified and raw != verified:
            out.append(Finding(check_name="bank", severity="critical", title="Bank details differ from verified account",
                               detail=f"Invoice asks for payment to {raw} ({bank}, {iban.country_code}), but the verified account for "
                                      f"{supplier['name']} is {verified}. This is the #1 sign of supplier-impersonation fraud. "
                                      f"Call the supplier on the phone number in your records, not one from the invoice or email."))
        elif not verified:
            out.append(Finding(check_name="bank", severity="medium", title="No verified bank account on file",
                               detail="This supplier has no verified IBAN yet. Verify it once by phone before the first payment."))
        if iban.country_code != supplier["country"].upper():
            out.append(Finding(check_name="bank", severity="high", title="Bank country doesn't match supplier country",
                               detail=f"Supplier is registered in {supplier['country'].upper()}, but the account is in {iban.country_code} ({bank})."))
        verified_at = supplier.get("iban_verified_at")
        if verified and raw == verified and verified_at:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(verified_at)
            if age < timedelta(days=14):
                out.append(Finding(check_name="bank", severity="low", title="Bank details changed recently",
                                   detail=f"The verified account was updated {age.days} day(s) ago. Fraudsters often strike right after a change."))
    if recent_changes >= 2:
        out.append(Finding(check_name="bank", severity="medium", title="Several different accounts used recently",
                           detail=f"{recent_changes} different IBANs have been paid or requested for this supplier in the last 90 days."))
    if supplier and raw == normalize(supplier.get("verified_iban")):
        out.append(Finding(check_name="bank", severity="info", title="Bank account matches records",
                           detail=f"{raw} ({bank}) matches the verified account."))
    return out
