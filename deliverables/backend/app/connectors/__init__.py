"""
Connectors (WBS 11.x): each supplies named parameters at a declared trust and
cadence, through the one framework in _framework.py. Registered here so the
catalogue, the scheduler and the pull endpoint read one list.

Every connector reads a file drop or an API export; none holds credentials.
Credentials for a live CRM/ERP/POS endpoint are a service-account matter
(app/api/v1/users.py) and a deployment secret, not code.
"""

from app.connectors import crm, disty_pos, erp, market_data

CONNECTORS = {c.spec.name: c for c in (crm.CRMConnector(), erp.ERPConnector(), disty_pos.POSConnector(),
                                        market_data.MarketDataConnector())}


def catalogue() -> list[dict]:
    return [
        {"name": c.spec.name, "label": c.spec.label, "supplies": sorted(c.spec.supplies), "trust": c.spec.trust,
         "cadence": c.spec.cadence, "source": c.spec.source, "description": c.spec.description}
        for c in CONNECTORS.values()
    ]
