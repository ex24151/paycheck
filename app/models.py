from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["info", "low", "medium", "high", "critical"]


class Finding(BaseModel):
    check_name: str
    severity: Severity
    title: str
    detail: str


class InvoiceIn(BaseModel):
    supplier_name: str
    amount: float = Field(gt=0)
    currency: str = "EUR"
    invoice_number: Optional[str] = None
    iban: Optional[str] = None
    sender_email: Optional[str] = None
    reply_to: Optional[str] = None
    email_body: Optional[str] = None
    invoice_text: Optional[str] = None


class SupplierIn(BaseModel):
    name: str
    country: str = Field(min_length=2, max_length=2)
    email_domain: str
    verified_iban: Optional[str] = None
    verified_phone: Optional[str] = None


class Decision(BaseModel):
    actor: str = Field(min_length=1)
    note: Optional[str] = None
    phone_used: Optional[str] = None  # for call-back verification


class AIReview(BaseModel):
    """Structured output Claude must return."""
    risk_level: Literal["low", "medium", "high"]
    summary: str
    red_flags: list[str]
    recommended_action: Literal["approve", "verify_by_phone", "block"]
