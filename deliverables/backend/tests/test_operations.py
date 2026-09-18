"""
Operations (WBS 13.1-13.6): the scheduler and its jobs, model hosting policy,
observability, backup and restore, cost and quota.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.config import settings
from app.judgment import rubric as rubric_module
from app.services import metrics
from tests.test_judgment_layer import load_nine
from tests.test_roles_and_scope import PAYLOAD, headers

ADMIN = headers("admin", "*", "root")


@pytest.fixture(autouse=True)
def fresh_metrics():
    from app.services.scheduler import EVENT_QUEUE

    r = metrics.get_redis()
    r.delete(metrics._key())
    r.delete(EVENT_QUEUE)     # fakeredis is process-wide; earlier tests' transitions queued here
    yield
    r.delete(metrics._key())
    r.delete(EVENT_QUEUE)


# --------------------------------------------------------------------------- #
# 13.2 -- the seven jobs
# --------------------------------------------------------------------------- #

def test_every_job_in_the_architecture_table_exists_with_a_cron_line(client):
    jobs = {j["name"]: j for j in client.get("/api/v1/jobs").json()}
    assert set(jobs) >= {"monthly_run", "event_runs", "stall_sweep", "embedding_refresh", "calibration_rebuild",
                         "connector_sync", "retention", "dispatch"}
    assert jobs["monthly_run"]["cron"].split()[2] == "1"          # first of the month
    from app.services.scheduler import crontab
    assert "python -m scripts.run_job stall_sweep" in crontab()


def test_a_stage_change_queues_a_targeted_event_run(client):
    ids = load_nine(client)
    client.post("/api/v1/rubric/publish-v1", headers=ADMIN)
    client.post(f"/api/v1/opportunities/{ids['Aphrodite']}/transition",
                json={"field": "stage", "to_value": "PVT", "actor": "marc", "reason_code": "advanced_to_next_stage"},
                headers=headers("director"))
    result = client.post("/api/v1/jobs/event_runs/run", headers=ADMIN).json()
    assert result["ok"] and result["result"]["rows"] == 1 and result["result"]["rows_read"] == 1
    # Drained: a second pass has nothing to do.
    assert client.post("/api/v1/jobs/event_runs/run", headers=ADMIN).json()["result"] == {"rows": 0}


def test_monthly_run_and_retention_jobs_run_end_to_end(client):
    load_nine(client)
    monthly = client.post("/api/v1/jobs/monthly_run/run", headers=ADMIN).json()
    assert monthly["ok"] and monthly["result"]["status"] == "completed" and monthly["result"]["proposals"] == 9
    retention = client.post("/api/v1/jobs/retention/run", headers=ADMIN).json()
    assert retention["result"]["episodic_within_policy"] is True
    assert client.post("/api/v1/jobs/nope/run", headers=ADMIN).status_code == 404
    snap = client.get("/api/v1/metrics", headers=ADMIN).json()
    assert snap["runs"] == 1 and snap["job:monthly_run:ok"] == 1


def test_connector_sync_pulls_a_drop_folder(client, tmp_path, monkeypatch):
    client.post("/api/v1/opportunities", json={**PAYLOAD, "external_id": "CRM-9"}, headers=headers("director"))
    monkeypatch.setattr(settings, "connector_drop_dir", str(tmp_path))
    (tmp_path / "crm").mkdir()
    (tmp_path / "crm" / "nightly.csv").write_text("Opportunity ID,M/P Date\nCRM-9,Jun'27\n")
    (tmp_path / "erp").mkdir()
    (tmp_path / "erp" / "bad.csv").write_text("not,the,right,columns\n1,2,3,4\n")
    result = client.post("/api/v1/jobs/connector_sync/run", headers=ADMIN).json()["result"]
    assert result["crm:nightly.csv"]["applied"] == 1
    assert "error" in result["erp:bad.csv"]
    assert (tmp_path / "crm" / "done" / "nightly.csv").exists() and (tmp_path / "erp" / "failed" / "bad.csv").exists()


# --------------------------------------------------------------------------- #
# 13.3 -- model hosting and fallback
# --------------------------------------------------------------------------- #

def test_local_model_policy_is_western_weights_only():
    assert rubric_module.local_model_allowed("meta-llama/Llama-3.3-70B-Instruct")
    assert rubric_module.local_model_allowed("mistralai/Mistral-Large-Instruct")
    assert rubric_module.local_model_allowed("google/gemma-2-27b-it")
    assert rubric_module.local_model_allowed("CohereForAI/c4ai-command-r-plus")
    assert not rubric_module.local_model_allowed("Qwen/Qwen2.5-72B-Instruct")
    assert not rubric_module.local_model_allowed("deepseek-ai/DeepSeek-V3")
    assert not rubric_module.local_model_allowed("some/unknown-model")


def test_vllm_backend_posts_the_schema_and_records_usage(monkeypatch):
    from tests.test_judgment_layer import bundle_for

    calls = []

    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"factors": []})}}],
                    "usage": {"prompt_tokens": 1200, "completion_tokens": 300}}

    def post(url, json=None, timeout=None):
        calls.append((url, json))
        return Resp()

    import requests
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(settings, "judgment_backend", "vllm")
    monkeypatch.setattr(settings, "vllm_model", "meta-llama/Llama-3.3-70B-Instruct")
    assert rubric_module._live_score(bundle_for("Hugo")) == []
    url, body = calls[0]
    assert url.endswith("/chat/completions") and body["response_format"]["type"] == "json_schema"
    assert body["temperature"] == 0
    snap = metrics.month_snapshot()
    assert snap["live_calls"] == 1 and snap["input_tokens"] == 1200

    monkeypatch.setattr(settings, "vllm_model", "Qwen/Qwen2.5-72B-Instruct")
    with pytest.raises(rubric_module.JudgmentReplyError, match="not an approved family"):
        rubric_module._live_score(bundle_for("Hugo"))


# --------------------------------------------------------------------------- #
# 13.4 / 13.6 -- observability, cost and quota
# --------------------------------------------------------------------------- #

def test_metrics_render_json_and_prometheus(client):
    metrics.record_live_usage(1_000_000, 100_000, model_id="claude-opus-5")
    snap = client.get("/api/v1/metrics", headers=ADMIN).json()
    assert snap["estimated_cost_usd"] == pytest.approx(5.0 + 2.5)
    text = client.get("/api/v1/metrics/prometheus").text
    assert "opptrack_live_calls" in text and 'opptrack_live_calls_by_model{model="claude-opus-5"' in text


def test_quota_refuses_a_live_call_over_budget_and_records_it(monkeypatch):
    from tests.test_judgment_layer import bundle_for

    monkeypatch.setattr(settings, "monthly_budget_usd", 5.0)
    metrics.record_live_usage(1_000_000, 0, model_id="claude-opus-5")     # $5.00 spent
    with pytest.raises(rubric_module.JudgmentReplyError, match="monthly budget"):
        rubric_module._live_score(bundle_for("Hugo"))
    assert metrics.month_snapshot()["quota_refusals"] == 1
    # And through score_confidence_factors the row falls back to MOCK, loudly.
    monkeypatch.setattr(settings, "judgment_mode", "live")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    result = rubric_module.score_confidence_factors(bundle_for("Hugo"))
    assert result["mode"] == "mock" and "monthly budget" in result["fallback_error"]
    assert metrics.month_snapshot()["mock_fallbacks"] == 1


# --------------------------------------------------------------------------- #
# 13.5 -- backup and restore
# --------------------------------------------------------------------------- #

def test_backup_verify_restore_round_trips_the_audit_tables(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.models.confidence_event import ConfidenceEvent
    from app.db.models.opportunity import Opportunity
    from app.db.models.rubric_version import RubricVersion
    from app.services.backup import backup, restore, verify

    db_file = tmp_path / "live.sqlite"
    url = f"sqlite:///{db_file.as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        opp = Opportunity(**PAYLOAD)
        version = RubricVersion(label="t", matrix_a={}, rubric_factors={}, published_by="t")
        db.add_all([opp, version])
        db.flush()
        db.add(ConfidenceEvent(opportunity_id=opp.id, rubric_version_id=version.id, event_type="proposal",
                               base_confidence=1.0, resulting_confidence=0.9, actor="agent"))
        db.commit()
        original = [(e.id, e.resulting_confidence) for e in db.query(ConfidenceEvent).all()]
    engine.dispose()

    objects = tmp_path / "objects"
    (objects / "snapshots").mkdir(parents=True)
    (objects / "snapshots" / "a.csv").write_text("x")
    result = backup(tmp_path / "backups", database_url=url, objects_dir=objects)
    folder = Path(result["backup_dir"])
    assert verify(folder)["ok"] and {"database.sqlite", "objects.zip"} <= set(result["parts"])

    # Disaster: the live database and objects are gone.
    db_file.unlink()
    (objects / "snapshots" / "a.csv").unlink()
    restore(folder, database_url=url, objects_dir=objects)
    engine = create_engine(url)
    with sessionmaker(bind=engine)() as db:
        assert [(e.id, e.resulting_confidence) for e in db.query(ConfidenceEvent).all()] == original
    assert (objects / "snapshots" / "a.csv").read_text() == "x"

    # A tampered backup is refused.
    (folder / "database.sqlite").write_bytes(b"tampered")
    assert verify(folder)["ok"] is False
    with pytest.raises(ValueError, match="verification"):
        restore(folder, database_url=url, objects_dir=objects)
