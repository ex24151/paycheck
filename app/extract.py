"""Pull text and key fields out of an invoice PDF or pasted text.

pypdf handles text-based PDFs. For scanned PDFs, swap in docling
(docling-project/docling, MIT) - see README.
"""
import io
import re

from pypdf import PdfReader
from schwifty import IBAN

IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30})\b")
AMOUNT_RE = re.compile(r"(?:total|amount due|balance due|grand total|to pay)[^\d]{0,30}([\d.,]+\d)", re.I)
INVNO_RE = re.compile(r"invoice\s*(?:no\.?|number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/]{2,})", re.I)


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def parse_amount(s: str) -> float | None:
    s = s.strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) == 2 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def fields_from_text(text: str) -> dict:
    out: dict = {}
    for m in IBAN_RE.finditer(text.upper()):
        cand = m.group(1).replace(" ", "")
        for end in range(len(cand), 14, -1):  # trim trailing words glued on by the regex
            try:
                out["iban"] = str(IBAN(cand[:end]).compact)
                break
            except Exception:
                continue
        if "iban" in out:
            break
    amounts = [a for a in (parse_amount(m.group(1)) for m in AMOUNT_RE.finditer(text)) if a]
    if amounts:
        out["amount"] = max(amounts)
    m = INVNO_RE.search(text)
    if m:
        out["invoice_number"] = m.group(1)
    return out
