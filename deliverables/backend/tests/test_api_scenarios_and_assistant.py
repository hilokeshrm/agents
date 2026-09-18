"""
Scenario recompute (WBS 5.7), the forecast feed, and the read-only assistant.

The assistant tests run in reader mode -- settings.judgment_mode defaults to
"mock" -- which is the mode that has to be right anyway: it is what a person
sees when no key is configured, and it must answer from the tables or say it
cannot, never split the difference.
"""

import pytest

from tests.test_api_review import DRAFT_FACTORS, publish, seed
from tests.test_roles_and_scope import EU_PAYLOAD, PAYLOAD, headers


def test_scenario_is_pure_and_uses_the_same_engine(client):
    korea, _ = seed(client)
    before = client.get(f"/api/v1/opportunities/{korea['id']}").json()

    result = client.post("/api/v1/scenarios/recompute", json={
        "overrides": [{"opportunity_id": korea["id"], "confidence": 0.5}]
    }).json()

    row = result["changed_rows"][0]
    assert row["scenario_confidence"] == 0.5
    assert row["base_adjusted_revenue_k"] == pytest.approx(before["adjusted_revenue_k"])
    assert row["scenario_adjusted_revenue_k"] == pytest.approx(before["sales_revenue_k"] * 0.5)
    assert result["delta_k"] == pytest.approx(row["delta_k"])

    # Nothing was written.
    assert client.get(f"/api/v1/opportunities/{korea['id']}").json() == before


def test_scenario_can_fold_in_the_whole_review_queue(client):
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))

    result = client.post("/api/v1/scenarios/recompute",
                         json={"include_pending_proposals": True}).json()
    assert result["changed_rows"]
    assert all(r["source"] == "pending proposal" for r in result["changed_rows"])


def test_scenario_respects_region_scope(client):
    seed(client)
    scoped = client.post("/api/v1/scenarios/recompute", json={},
                         headers=headers("owner", "Korea", "jdoe")).json()
    assert scoped["rows_considered"] == 1
    assert set(scoped["base_by_region"]) == {"Korea"}


def test_forecast_feed_uses_deterministic_mp_date_ramp(client):
    """M/P revenue is spread 10/20/30/40 across four quarters; missing dates stay unphased."""
    client.post("/api/v1/opportunities", json={**PAYLOAD, "mp_date": "2026-12-01"},
                headers=headers("director"))
    client.post("/api/v1/opportunities", json=EU_PAYLOAD, headers=headers("director"))  # no M/P date

    feed = client.get("/api/v1/forecast-feed", headers=headers("finance")).json()
    assert feed["phasing_rule"] == "programme_profile > mp_date_ramp_10_20_30_40 > unphased"
    assert [q["label"] for q in feed["quarters"]] == ["2026 Q4", "2027 Q1", "2027 Q2", "2027 Q3"]
    assert [q["weighted_revenue_k"] for q in feed["quarters"]] == pytest.approx([330, 660, 990, 1320])
    assert feed["unphased_count"] == 1
    assert feed["total_weighted_k"] == pytest.approx(
        sum(q["weighted_revenue_k"] for q in feed["quarters"]) + feed["unphased_weighted_k"]
    )


def test_an_owner_cannot_pull_the_forecast_feed(client):
    assert client.get("/api/v1/forecast-feed", headers=headers("owner")).status_code == 403
    assert client.get("/api/v1/forecast-feed", headers=headers("finance")).status_code == 200


# --------------------------------------------------------------------------- #
# Assistant
# --------------------------------------------------------------------------- #

def ask(client, question, **kw):
    return client.post("/api/v1/assistant/ask", json={"question": question}, **kw).json()


def test_the_assistant_exposes_no_write_tool(client):
    surface = client.get("/api/v1/assistant/surface").json()
    assert surface["writes"] == []
    names = {t["name"] for t in surface["tools"]}
    assert names and not any(n.startswith(("set_", "create_", "update_", "delete_")) for n in names)
    assert "set_confidence" not in names


def test_it_refuses_to_write_and_says_where_to_do_it(client):
    seed(client)
    answer = ask(client, "set Hercules confidence to 0.4")
    assert answer["mode"] == "refused" and answer["intent"] == "refuse_write"
    assert "there is no tool here that writes" in answer["answer"]
    assert "Review queue" in answer["answer"]


def test_it_reports_the_pipeline_from_the_calc_engine(client):
    seed(client)
    answer = ask(client, "what is the weighted pipeline by region?")
    assert "app/calc/engine.py" in answer["answer"]
    assert "Korea" in answer["answer"] and "Europe" in answer["answer"]
    assert [c["name"] for c in answer["tool_calls"]] == ["get_rollup"]


def test_it_answers_the_queue_what_if_by_recomputing(client):
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))

    answer = ask(client, "what happens to the pipeline if I approve everything in the queue?")
    assert "weighted pipeline" in answer["answer"]
    assert "Nothing was written" in answer["answer"]
    assert {c["name"] for c in answer["tool_calls"]} == {"compute_scenario", "get_review_queue"}


def test_it_explains_a_proposal_from_the_stored_factors(client):
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))

    answer = ask(client, "why does Hercules have that proposal?")
    assert "Hercules" in answer["answer"]
    assert "rubric version 2026.1" in answer["answer"]
    assert "Not assessable on this row" in answer["answer"]
    assert "not re-derived" in answer["answer"]


def test_it_computes_win_rate_from_the_event_stream(client):
    seed(client)  # both seeded rows are design wins
    answer = ask(client, "what is our win rate?")
    assert "2 won, 0 lost, 2 resolved -- 100%" in answer["answer"]
    assert "not estimated" in answer["answer"]


def test_an_absent_win_rate_is_reported_as_absent_not_zero(client):
    client.post("/api/v1/opportunities",
                json={**PAYLOAD, "design_status": "Evaluation", "stage": "EVT", "confidence": 0.5},
                headers=headers("director"))
    answer = ask(client, "what is our win rate?")
    assert "no win rate to report" in answer["answer"]
    assert "not a rate of zero" in answer["answer"]


def test_it_is_region_scoped_like_every_other_reader(client):
    seed(client)
    answer = ask(client, "what is the weighted pipeline?", headers=headers("owner", "Korea", "jdoe"))
    assert "Korea" in answer["answer"]
    assert "Europe" not in answer["answer"]


def test_an_unrecognised_question_says_so_rather_than_guessing(client):
    answer = ask(client, "should we hire another field applications engineer?")
    assert answer["mode"] == "refused" and answer["intent"] == "refuse_scope"
    assert "only answer questions about the pipeline" in answer["answer"]
