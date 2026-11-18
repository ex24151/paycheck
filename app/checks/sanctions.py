"""Sanctions screening through a self-hosted yente server (opensanctions/yente, MIT).

Set YENTE_URL (e.g. http://localhost:8000) to enable. Note: OpenSanctions *data*
requires a commercial licence for business use.
"""
import os

import httpx

from ..models import Finding


def check_sanctions(supplier_name: str) -> list[Finding]:
    base = os.environ.get("YENTE_URL")
    if not base:
        return []
    try:
        r = httpx.post(f"{base.rstrip('/')}/match/default",
                       json={"queries": {"q": {"schema": "Company", "properties": {"name": [supplier_name]}}}},
                       timeout=5.0)
        r.raise_for_status()
        results = r.json()["responses"]["q"]["results"]
    except Exception as e:  # screening service down must be visible, not silent
        return [Finding(check_name="sanctions", severity="low", title="Sanctions screening unavailable", detail=str(e)[:200])]
    hits = [x for x in results if x.get("match")]
    if hits:
        top = hits[0]
        return [Finding(check_name="sanctions", severity="critical", title="Possible sanctions match",
                        detail=f"{supplier_name} matches {top.get('caption')} (score {top.get('score'):.2f}). Compliance must review before payment.")]
    return [Finding(check_name="sanctions", severity="info", title="No sanctions match", detail="Screened against OpenSanctions.")]
