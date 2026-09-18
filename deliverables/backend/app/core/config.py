from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite by default so the whole backend runs in a plain venv -- no Postgres
    # server to install or run. Point this at a real postgresql+psycopg:// URL
    # once Postgres is actually provisioned; nothing in app/db/ is SQLite-specific.
    database_url: str = "sqlite:///./opptrack.db"

    anthropic_api_key: str | None = None
    judgment_mode: str = "mock"  # "mock" or "live"
    judgment_model: str = "claude-opus-5"
    # When a LIVE call fails (truncation, refusal, off-schema reply, network),
    # local dev scores the row with MOCK and records the error on the run so
    # the run is marked mixed. Production should set this false: decision #35
    # says a failed call fails loudly and creates no proposal for the row.
    judgment_fallback_to_mock: bool = True
    auth_issuer: str | None = None
    auth_audience: str | None = None
    # OIDC (WBS 9.4): when auth_issuer is set, a Bearer token is required and the
    # header stand-in below is ignored. JWKS is fetched from the issuer's
    # discovery document unless auth_jwks_url is given.
    auth_jwks_url: str | None = None
    # A dev issuer may sign HS256 with this shared secret; production uses the
    # issuer's JWKS (RS256).
    auth_hs256_secret: str | None = None
    # How a caller becomes an Actor when no OIDC issuer is configured:
    #   headers -- the development stand-in (X-OppTrack-* headers, no password)
    #   local   -- email + password with a one-time code by mail (app/security/local_auth.py);
    #              role and scope still come from the admin-provisioned app_user row
    auth_mode: str = "headers"
    auth_session_hours: int = 12
    otp_ttl_minutes: int = 10
    # Where the one-time code goes: "console" logs it (development), "smtp"
    # sends it with the SMTP settings below (Gmail: smtp.gmail.com:587,
    # STARTTLS, an App Password).
    otp_delivery: str = "console"
    # Browser origins allowed once SSO is on (comma-separated). Ignored in dev.
    cors_origins: str = ""

    # Notifications (WBS 11.7): "log" needs nothing; "smtp" needs the host below;
    # "webhook" posts to the subscriptions in the webhook_subscription table.
    notification_channel: str = "log"  # log | smtp | webhook
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_starttls: bool = False
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_sender: str = "opptrack@localhost"

    # Model hosting (WBS 13.3): "anthropic" is the hosted primary path; "vllm"
    # is the local fallback on the shared RTX PRO 6000, Western weights only.
    judgment_backend: str = "anthropic"  # anthropic | vllm
    vllm_base_url: str = "http://localhost:8000/v1"
    vllm_model: str = "meta-llama/Llama-3.3-70B-Instruct"

    # Cost and quota (WBS 13.6): live calls stop when the month's estimated
    # spend crosses the budget; 0 disables the cap.
    monthly_budget_usd: float = 0.0
    live_price_input_per_mtok: float = 5.0
    live_price_output_per_mtok: float = 25.0

    # Where the canonical workbook lives, for the findings report endpoint.
    workbook_path: str = "../../data/TrackF (1).xlsx"
    # Connector drop folder (WBS 13.2 connector_sync): one sub-folder per connector.
    connector_drop_dir: str = "data/drops"
    backup_dir: str = "data/backups"

    # Identity stand-in until SSO lands (WBS 9.4). app/security/roles.py reads
    # role and region scope from request headers; these are what an unauthenticated
    # caller gets, chosen so every route built before that module behaves as it
    # did. "director" + all regions is the widest human role, which is honest
    # about the fact that nothing is actually authenticated yet -- it is not a
    # permission grant, it is the absence of authentication.
    dev_default_actor: str = "dev-user"
    dev_default_role: str = "director"
    dev_default_regions: str = "*"  # "*" = every region; otherwise a comma-separated list

    # /dev/* (app/api/v1/dev.py): unauthenticated DB/log introspection, on by
    # default so it works out of the box for local development. A production
    # .env MUST set this to false -- the deploy docs and prod compose override
    # do -- since the router has no auth check of its own and would otherwise
    # hand the whole database to anyone who can reach the public IP.
    dev_tools_enabled: bool = True

    # Redis (WBS 9.6): "fake" runs fakeredis in-process, no server, no Docker --
    # this is what runs today. Set REDIS_BACKEND=real once an actual Redis
    # instance exists; redis_url governs where to find it at that point.
    redis_backend: str = "fake"  # "fake" | "real"
    redis_url: str = "redis://localhost:6379/0"

    # Object storage (WBS 9.6): "local" writes/reads files under a data/
    # directory on disk, no S3 or MinIO required -- this is what runs today.
    # Set STORAGE_BACKEND=s3 once a real S3-compatible endpoint exists.
    storage_backend: str = "local"  # "local" | "s3"
    s3_endpoint_url: str | None = None  # None selects real AWS S3; set for MinIO
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    s3_bucket: str = "opptrack"


settings = Settings()
