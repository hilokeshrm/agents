"""
Intake and normalisation (WBS 3.0, Layer 2). Turns whatever arrives -- a form
submission, a workbook row, a CRM record -- into canonical values with provenance.
Nothing here interprets: coercion and canonicalisation only, so a wrong value
stays visibly wrong rather than being quietly repaired. No database, no auth, no
model (that is what makes this package demonstrable before any platform decision
is made).
"""
