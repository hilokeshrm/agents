# Ten tables hanging off opportunity by foreign key (WBS 9.1), per the data model
# in docs/02-architecture/OppTrack_Layer_Diagrams.html (Plate 5) and
# docs/02-architecture/OppTrack_Complete_Architecture.html (section 12), plus one
# eleventh table added for the UI build: `contact`, which links to opportunities
# by account name (a string, matching Opportunity.customer), not by foreign key --
# there is no Account table, since accounts are a computed rollup over
# opportunities (app/api/v1/accounts.py), not a stored entity -- and one
# twelfth, `run`, added with the Runs & audit screen (WBS 10.9): a run's
# ten-step trace has to live somewhere for the screen to be a reading of what
# happened rather than a re-enactment of it.
#
# Imported here so Base.metadata sees every model -- required for both
# metadata.create_all() and Alembic autogenerate.

from app.db.models.actual import Actual
from app.db.models.app_user import AppUser
from app.db.models.auth_account import AuthAccount, AuthSession
from app.db.models.calibration import Calibration
from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.contact import Contact
from app.db.models.conversation import Conversation
from app.db.models.field_value import FieldValue
from app.db.models.finding import Finding
from app.db.models.forecast import Forecast
from app.db.models.market_programme import MarketProgramme
from app.db.models.memory_chunk import MemoryChunk
from app.db.models.notification import Notification
from app.db.models.opportunity import Opportunity
from app.db.models.opportunity_sequence import OpportunitySequence
from app.db.models.owner_history import OwnerHistory
from app.db.models.proposal import Proposal
from app.db.models.run import Run
from app.db.models.rubric_version import RubricVersion
from app.db.models.snapshot import Snapshot
from app.db.models.state_history import StateHistory
from app.db.models.target import Target
from app.db.models.webhook import WebhookDelivery, WebhookSubscription

__all__ = [
    "Actual",
    "AppUser",
    "AuthAccount",
    "AuthSession",
    "Calibration",
    "ConfidenceEvent",
    "Contact",
    "Conversation",
    "FieldValue",
    "Finding",
    "Forecast",
    "MarketProgramme",
    "MemoryChunk",
    "Notification",
    "Opportunity",
    "OpportunitySequence",
    "OwnerHistory",
    "Proposal",
    "Run",
    "RubricVersion",
    "Snapshot",
    "StateHistory",
    "Target",
    "WebhookDelivery",
    "WebhookSubscription",
]

# Append-only enforcement for the audit tables (WBS 8.2). Imported last so the
# listeners attach to fully-declared mappers.
from app.db import immutable as _immutable  # noqa: E402,F401
