"""Email sender checks: look-alike domains, free-mail senders, reply-to tricks,
and SPF/DMARC posture via checkdmarc (Apache-2.0)."""
import os
from functools import lru_cache

from ..models import Finding

FREE_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
             "icloud.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "gmx.de", "mail.com", "yandex.com"}

# Characters fraudsters swap to fool the eye.
HOMOGLYPHS = {"rn": "m", "vv": "w", "0": "o", "1": "l", "3": "e", "5": "s", "|": "l", "cl": "d"}


def domain_of(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].strip().strip(">").lower()


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def skeleton(d: str) -> str:
    s = d.lower()
    for k, v in HOMOGLYPHS.items():
        s = s.replace(k, v)
    return s


def split_name_tld(d: str) -> tuple[str, str]:
    parts = d.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "ac"}:
        return ".".join(parts[:-2]), ".".join(parts[-2:])
    return ".".join(parts[:-1]), parts[-1]


def is_lookalike(candidate: str, real: str) -> str | None:
    """Return a human explanation if candidate imitates real, else None."""
    if candidate == real or candidate.endswith("." + real):
        return None
    c_name, c_tld = split_name_tld(candidate)
    r_name, r_tld = split_name_tld(real)
    if c_name == r_name and c_tld != r_tld:
        return f"same name, different ending (.{c_tld} instead of .{r_tld})"
    if skeleton(candidate) == skeleton(real):
        return "uses look-alike characters (e.g. 'rn' for 'm', '1' for 'l', '0' for 'o')"
    dist = levenshtein(c_name, r_name)
    if 0 < dist <= 2 and len(r_name) >= 4:
        return f"only {dist} character(s) different from the real domain"
    if r_name in c_name and c_name != r_name:
        return "contains the real company name with extra words added"
    return None


@lru_cache(maxsize=256)
def email_auth_posture(domain: str) -> tuple[str, str] | None:
    """Live DNS lookup of SPF/DMARC. Disabled with PAYCHECK_OFFLINE=1."""
    if os.environ.get("PAYCHECK_OFFLINE") == "1":
        return None
    try:
        import checkdmarc
        res = checkdmarc.check_domains([domain], timeout=3.0)
        dmarc = res.get("dmarc", {}) if isinstance(res, dict) else {}
        if not dmarc.get("valid"):
            return ("medium", f"{domain} has no valid DMARC record, so anyone can send email pretending to be this domain.")
        policy = (dmarc.get("tags", {}).get("p", {}) or {}).get("value")
        if policy == "none":
            return ("low", f"{domain} has DMARC set to 'none' (monitor only), so spoofed emails are not blocked.")
        return None
    except Exception:
        return None  # network blocked or DNS failure: never fail the whole check


def check_sender(invoice: dict, supplier: dict | None) -> list[Finding]:
    out: list[Finding] = []
    sender = domain_of(invoice.get("sender_email"))
    reply = domain_of(invoice.get("reply_to"))
    if not sender:
        return [Finding(check_name="email", severity="info", title="No email to check",
                        detail="Invoice was not received by email, or the sender wasn't provided.")]
    real = supplier["email_domain"].lower() if supplier else None

    if real:
        why = is_lookalike(sender, real)
        if why:
            out.append(Finding(check_name="email", severity="critical", title=f"Look-alike sender domain: {sender}",
                               detail=f"The real supplier domain is {real}; this one {why}. Classic impersonation."))
        elif sender != real and not sender.endswith("." + real):
            sev = "high" if sender in FREE_MAIL else "medium"
            out.append(Finding(check_name="email", severity=sev, title="Email from an unknown domain",
                               detail=f"Expected @{real}, got @{sender}."))
    elif sender in FREE_MAIL:
        out.append(Finding(check_name="email", severity="medium", title="Sent from a free email account",
                           detail=f"Businesses rarely invoice from @{sender}."))

    if reply and reply != sender:
        why = is_lookalike(reply, real) if real else None
        out.append(Finding(check_name="email", severity="high" if (why or reply in FREE_MAIL) else "medium",
                           title="Replies go to a different address",
                           detail=f"Email is from @{sender} but replies are redirected to @{reply}"
                                  + (f" ({why})" if why else "") + ". Fraudsters use this to hijack the conversation."))

    posture = email_auth_posture(sender)
    if posture:
        out.append(Finding(check_name="email", severity=posture[0], title="Weak email protection on sender domain", detail=posture[1]))

    if not out:
        out.append(Finding(check_name="email", severity="info", title="Sender domain matches records", detail=f"@{sender} is the known supplier domain."))
    return out
