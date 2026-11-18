"""Statistical and language checks against the supplier's own history."""
import re
from statistics import mean, pstdev

from ..models import Finding

PRESSURE = [
    r"\burgent(ly)?\b", r"\bimmediate(ly)?\b", r"\btoday\b", r"\bwithin 24 hours\b", r"\bas soon as possible\b",
    r"\bconfidential\b", r"\bdo not (discuss|share|call)\b", r"\bkeep this (quiet|between us)\b",
    r"\bnew (bank|account|banking) (details|information)\b", r"\b(changed|updated|new) (our )?bank\b",
    r"\baudit\b.*\baccount\b", r"\bdon'?t call\b", r"\bunreachable\b", r"\bceo\b.*\brequest", r"\bgift cards?\b",
]


def check_amount(invoice: dict, history: list[dict]) -> list[Finding]:
    out: list[Finding] = []
    amt = float(invoice["amount"])
    amounts = [h["amount"] for h in history]
    if len(amounts) >= 3:
        m, sd = mean(amounts), pstdev(amounts) or max(1.0, mean(amounts) * 0.1)
        z = (amt - m) / sd
        if amt > max(amounts) * 2 or z > 4:
            out.append(Finding(check_name="amount", severity="high", title="Amount far above normal",
                               detail=f"{amt:,.2f} vs. a usual {m:,.2f} (highest ever {max(amounts):,.2f})."))
        elif z > 2.5:
            out.append(Finding(check_name="amount", severity="medium", title="Amount higher than usual",
                               detail=f"{amt:,.2f} is well above the usual {m:,.2f} for this supplier."))
    elif not amounts:
        out.append(Finding(check_name="amount", severity="low", title="First invoice from this supplier",
                           detail="No payment history yet. First payments to new suppliers deserve a check."))
    if amt >= 1000 and amt == int(amt) and amt % 500 == 0:
        out.append(Finding(check_name="amount", severity="low", title="Suspiciously round amount",
                           detail=f"{amt:,.0f} is a perfectly round number; real invoices usually include tax and odd cents."))
    num = (invoice.get("invoice_number") or "").strip()
    if num:
        for h in history:
            if (h.get("invoice_number") or "").strip() == num:
                out.append(Finding(check_name="duplicate", severity="high", title="Duplicate invoice number",
                                   detail=f"Invoice {num} was already received on {h['received_at'][:10]}."))
                break
    for h in history:
        if abs(h["amount"] - amt) < 0.005 and h["status"] in ("approved", "paid") and h.get("invoice_number") != num:
            out.append(Finding(check_name="duplicate", severity="low", title="Same amount already paid",
                               detail=f"An invoice for exactly {amt:,.2f} was paid on {h['received_at'][:10]}. Could be a resubmission."))
            break
    return out


def check_language(invoice: dict) -> list[Finding]:
    text = " ".join(filter(None, [invoice.get("email_body"), invoice.get("invoice_text")])).lower()
    if not text:
        return []
    hits = sorted({m.group(0) for p in PRESSURE for m in re.finditer(p, text)})
    if not hits:
        return []
    sev = "high" if len(hits) >= 3 else "medium"
    return [Finding(check_name="language", severity=sev, title="Pressure or secrecy language",
                    detail="Found: " + ", ".join(f"“{h}”" for h in hits[:8]) +
                           ". Scammers create urgency so you skip checks.")]
