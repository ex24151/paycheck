# PayCheck: the complete workflow

There are two workflows. The **payment workflow** is what a finance team does with every invoice, and it's built into the app. The **business workflow** takes PayCheck from this prototype to paying customers.

---

## A. Payment workflow (inside the app)

```
 ┌──────────┐   ┌────────────────────────────┐   ┌───────────┐
 │ 1 RECEIVE│──►│ 2 CHECK (automatic, ~2 sec)│──►│ 3 SCORE   │
 │ email /  │   │ • bank details  (schwifty) │   │ 0–100     │
 │ upload / │   │ • sender domain (checkdmarc│   │           │
 │ API      │   │   + look-alike detection)  │   │ 🟢 <25    │
 └──────────┘   │ • amount vs history        │   │ 🟡 25–59  │
                │ • duplicates               │   │ 🔴 60+ or │
                │ • pressure language        │   │ any       │
                │ • sanctions (yente)        │   │ critical  │
                │ • Claude AI analyst        │   └─────┬─────┘
                └────────────────────────────┘         │
        ┌──────────────────────────────────────────────┼─────────────────────────┐
        ▼                                              ▼                         ▼
 🟢 READY TO PAY                              🟡 VERIFY BY PHONE          🔴 ON HOLD
 one person approves                          call number ON FILE         call number ON FILE
        │                                              │                         │
        │                                              ▼                         ▼
        │                                         APPROVED            VERIFIED → 2nd person
        │                                              │              approves (four-eyes)
        ▼                                              ▼                         ▼
     APPROVED ───────────────────────────────────► PAID ◄────────────────── APPROVED

 At any open step: BLOCK & REPORT → IBAN added to the fraud list → every future
 invoice to that account is stopped automatically (for all customers, once the shared network is built).
```

### The rules the app enforces
1. **Nobody pays a red invoice alone.** Red needs a phone verification plus a *different* second approver.
2. **Call-backs use the number on file only.** The app rejects the verification if the number entered doesn't match the supplier's master record. Fraudsters put their own phone numbers on fake invoices.
3. **A confirmed new bank account becomes the verified account.** The change is logged, and the next 14 days get extra scrutiny.
4. **Blocking feeds the fraud list**, but it never blacklists the supplier's genuine verified account.
5. **Everything is in the audit trail:** who, what, when, and which number was called. Auditors and cyber insurers ask for this.

### Day-to-day routine for a finance team
| When | Who | What |
|---|---|---|
| Daily | AP clerk | Open the **Payment queue**. Approve greens, call suppliers for ambers and reds. |
| Daily | Finance manager | Second-approve verified reds. Review anything blocked. |
| Weekly | Finance manager | Check the **Suppliers** page: every supplier should have a verified IBAN and call-back number. |
| On new supplier | AP clerk | Add the supplier with the bank details and phone number from the **signed contract or official website**, never from an email. |
| Monthly | Controller | Export the audit trail for the month-end file. |

---

## B. Business workflow: prototype → product → revenue

### Phase 1: Validate (weeks 1–4)
- [ ] Demo this prototype to **10 accounting firms + 10 small-business finance managers**.
- [ ] Ask: "Has anyone tried to get you to pay a fake invoice?", "What do you do today when a supplier changes bank details?", "Would you pay €49–199/month for this?"
- [ ] **Go signal:** at least 5 people agree to a free pilot.

### Phase 2: Pilot-ready product (weeks 4–10)
- [ ] **Accounting-system sync:** pull bills and suppliers from **Xero** ([XeroAPI/xero-mcp-server](https://github.com/XeroAPI/xero-mcp-server), MIT) and **QuickBooks** ([intuit/quickbooks-online-mcp-server](https://github.com/intuit/quickbooks-online-mcp-server), Apache-2.0). Add a "Hold in Xero" action so red bills can't be paid there.
- [ ] **Email inbox ingestion:** a forwarding address (e.g. `invoices@yourcompany.paycheck.app`) that reads the real email headers (SPF/DKIM results, true sender, reply-to).
- [ ] **Scanned PDFs:** switch extraction to [docling](https://github.com/docling-project/docling) (MIT).
- [ ] **Sanctions:** self-host [yente](https://github.com/opensanctions/yente) (MIT) and buy an OpenSanctions commercial data licence.
- [ ] **Accounts and security:** login (SSO), one workspace per company, encryption at rest, Postgres instead of SQLite.
- [ ] **Hosting:** EU region (GDPR). Sign data-processing agreements with customers and with Anthropic.

### Phase 3: Launch (weeks 10–16)
- [ ] List on the **Xero App Store** and **QuickBooks App Store**, both free distribution channels.
- [ ] **Pricing:** Starter €49/mo (up to 100 invoices), Pro €149/mo (1,000 invoices + AI analyst), **Accounting firm** €15 per client per month.
- [ ] **Partner with cyber insurers:** offer them the audit trail as evidence of controls, in exchange for premium discounts for your customers.
- [ ] Content marketing: "The 7 signs of a fake invoice" guide, plus LinkedIn posts with anonymized catches.

### Phase 4: Moat (months 4–12)
- [ ] **Shared fraud network:** anonymized IBANs and domains reported by any customer protect all customers. Gets stronger with every signup.
- [ ] **Supplier self-verification portal:** suppliers confirm their own bank details through a secure link, sold to both sides.
- [ ] Add products from the same dashboard: **e-invoicing compliance** and **late-payment chasing** (see FINANCE-solutions.md).

### Legal and compliance checklist
- [ ] GDPR: DPA template, records of processing, EU hosting, retention policy.
- [ ] Terms: PayCheck **assists** decisions; the customer remains responsible for payments. Have a lawyer review the liability cap.
- [ ] Professional indemnity + cyber insurance for your company.
- [ ] Trademark the product name (check conflicts first: "PayCheck" is a common word, so expect to need a more distinctive brand).
