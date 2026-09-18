import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

from app.api.v1.accounts import router as accounts_router
from app.api.v1.auth import router as auth_router
from app.api.v1.access import router as access_router
from app.api.v1.analyses import router as analyses_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.assistant import router as assistant_router
from app.api.v1.connectors import router as connectors_router
from app.api.v1.contacts import router as contacts_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.dev import router as dev_router
from app.api.v1.imports import router as imports_router
from app.api.v1.opportunities import router as opportunities_router
from app.api.v1.products import router as products_router
from app.api.v1.registry import router as registry_router
from app.api.v1.reports import router as reports_router
from app.api.v1.review import router as review_router
from app.api.v1.rubric import router as rubric_router
from app.api.v1.scenarios import router as scenarios_router
from app.api.v1.users import router as users_router
from app.api.v1.webhooks import router as webhooks_router

app = FastAPI(
    title="Opportunity Tracking Agent API", version="0.2.0",
    description="Design-win pipeline from promotion to mass production or loss. The arithmetic is "
                "plain Python; the model may propose a change to exactly one field, Confidence Level, "
                "under a cap, with a citation, into a queue a person has to clear.",
    openapi_tags=[
        {"name": "opportunities", "description": "Intake (direct entry is primary), lifecycle transitions, provenance"},
        {"name": "review", "description": "Proposals, the human gate, runs, the append-only audit feed"},
        {"name": "rubric", "description": "Matrix A and Matrix B as published, versioned config"},
        {"name": "analyses", "description": "Deterministic reports, targets, actuals, sweeps, notifications"},
        {"name": "imports", "description": "Workbook and CSV import: dry run, findings, commit against a sealed snapshot"},
        {"name": "connectors", "description": "CRM, ERP, POS/POR and market-data pulls with provenance and reconciliation"},
        {"name": "users", "description": "Admin provisioning; no self-registration"},
        {"name": "webhooks", "description": "Outbound subscriptions and exports"},
        {"name": "assistant", "description": "Read-only, grounded question answering over the pipeline"},
    ],
)

# CORS: wide open only while the dev header stand-in is in use. Once either
# real auth is configured -- SSO (auth_issuer) or AUTH_MODE=local's
# email+password -- and CORS_ORIGINS is set, the browser origin allowlist is
# the configured one (e.g. the RTX box's own origin plus a GitHub Pages URL
# serving the SPA separately). No cookies are used (the token travels in an
# Authorization header), so a wildcard is not a credential-theft risk by
# itself, but a public deployment should still set this.
_locks_down_cors = settings.cors_origins and (settings.auth_issuer or settings.auth_mode == "local")
app.add_middleware(
    CORSMiddleware,
    allow_origins=(settings.cors_origins.split(",") if _locks_down_cors else ["*"]),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_id(request: Request, call_next):
    """WBS 10.1: every response carries a request id, echoed from the caller
    when supplied, so a log line, an audit note and a support ticket can name
    the same request."""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response

app.include_router(opportunities_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(analyses_router, prefix="/api/v1")
app.include_router(accounts_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(contacts_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")
app.include_router(rubric_router, prefix="/api/v1")
app.include_router(access_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(registry_router, prefix="/api/v1")
app.include_router(imports_router, prefix="/api/v1")
app.include_router(scenarios_router, prefix="/api/v1")
app.include_router(assistant_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(connectors_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
# Unauthenticated DB/log introspection -- local dev only. See dev.py and
# Settings.dev_tools_enabled; a production .env must set DEV_TOOLS_ENABLED=false.
if settings.dev_tools_enabled:
    app.include_router(dev_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
