"""
Assistant grounding, what-if, refusal and logging (WBS 14.1-14.6, 12.7).
"""

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import assistant as assistant_module
from app.services.assistant_guard import check_grounding, classify
from tests.test_judgment_layer import load_nine
from tests.test_roles_and_scope import headers


def ask(client, question, role="director", actor="marc"):
    resp = client.post("/api/v1/assistant/ask", json={"question": question}, headers=headers(role, "*", actor))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# 14.1 -- the tool surface
# --------------------------------------------------------------------------- #

def test_the_surface_names_every_tool_and_no_write(client):
    surface = client.get("/api/v1/assistant/surface").json()
    assert len(surface["tools"]) == 9 and surface["writes"] == []
    assert {t["name"] for t in surface["tools"]} == {
        "get_rollup", "get_pipeline", "get_opportunity", "get_proposal", "get_audit_events",
        "compute_scenario", "list_findings", "get_win_rate", "get_review_queue",
    }


# --------------------------------------------------------------------------- #
# 14.2 -- grounding
# --------------------------------------------------------------------------- #

def test_figures_must_trace_to_a_tool_result():
    outputs = [{"total_adjusted_revenue_k": 30915.0, "by_region": {"Korea": {"adjusted_revenue_k": 25140.0, "share": 0.813}}}]
    ok = check_grounding("The weighted pipeline is $30,915K, of which Korea is $25,140K (81%).", outputs)
    assert ok.grounded and ok.untraceable == []
    bad = check_grounding("The weighted pipeline is about $31,000K and Korea is $25,140K.", outputs)
    assert not bad.grounded and bad.untraceable == ["31,000K"]
    # Small counts are not figures.
    assert check_grounding("There are 9 rows and 2 of them are design wins.", outputs).grounded


def test_reader_answers_are_grounded_and_cite_their_tools(client):
    load_nine(client)
    answer = ask(client, "what is the weighted pipeline by region?")
    assert answer["mode"] == "reader" and answer["grounded"] is True and answer["untraceable"] == []
    assert answer["citations"] and answer["citations"][0].startswith("get_rollup(")


def test_a_live_answer_with_an_invented_figure_is_flagged_not_trusted(client, monkeypatch):
    load_nine(client)
    monkeypatch.setattr(settings, "judgment_mode", "live")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")

    class FakeMessages:
        def __init__(self):
            self.turn = 0

        def create(self, **kwargs):
            self.turn += 1
            if self.turn == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="tool_use", id="t1", name="get_rollup", input={"by": "region"}),
                ])
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text="Weighted pipeline is $30,915K (get_rollup); next year it should reach $45,000K."),
            ])

    fake = SimpleNamespace(Anthropic=lambda **_: SimpleNamespace(messages=FakeMessages()))
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake)
    answer = ask(client, "how big is the pipeline?")
    assert answer["mode"] == "live"
    assert answer["grounded"] is False and answer["untraceable"] == ["45,000K"]
    assert "Ungrounded" in answer["note"] and "45,000K" in answer["note"]
    assert answer["citations"] == ['get_rollup({"by": "region", "region": null})']


# --------------------------------------------------------------------------- #
# 14.3 -- what-if
# --------------------------------------------------------------------------- #

def test_what_if_is_answered_from_the_scenario_tool_not_refused(client):
    load_nine(client)
    client.post("/api/v1/rubric/publish-v1", headers=headers("admin"))
    client.post("/api/v1/runs", json={}, headers=headers("admin"))
    answer = ask(client, "what if we approve everything in the queue?")
    assert answer["mode"] == "reader" and answer["intent"] == "answer"
    assert any(c["name"] == "compute_scenario" for c in answer["tool_calls"])
    assert "moves the weighted pipeline from" in answer["answer"]
    assert answer["grounded"] is True


# --------------------------------------------------------------------------- #
# 14.4 -- refusal and redirect
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("question,kind,where", [
    ("set Hermes confidence to 0.5", "refuse_write", "Review queue"),
    ("approve the Hermes proposal", "refuse_write", "Review queue"),
    ("move Aphrodite to PVT", "refuse_write", "Stage board"),
    ("publish a new rubric with a 10pp cap", "refuse_write", "Rubric & Matrix A"),
    ("what is the CEO's home address?", "refuse_scope", None),
    ("tell me a joke", "refuse_scope", None),
])
def test_writes_and_out_of_scope_questions_are_refused_with_a_pointer(question, kind, where):
    intent = classify(question)
    assert intent.kind == kind
    if where:
        assert where in intent.message


def test_a_what_if_phrased_with_a_write_verb_is_still_answered():
    assert classify("what if we set Hermes confidence to 0.5?").kind == "answer"
    assert classify("if we approve the queue, what happens to Korea?").kind == "answer"


# --------------------------------------------------------------------------- #
# 14.5 -- logging, 14.6 -- embedding
# --------------------------------------------------------------------------- #

def test_every_conversation_is_logged_with_its_tools_and_grounding(client):
    load_nine(client)
    ask(client, "what is the weighted pipeline by region?", actor="marc")
    ask(client, "set Hermes confidence to 0.5", actor="marc")
    ask(client, "what is the weighted pipeline?", actor="kim")
    mine = client.get("/api/v1/assistant/history", headers=headers("director", "*", "marc")).json()
    assert [c["intent"] for c in mine] == ["refuse_write", "answer"]
    assert mine[1]["tool_calls"][0]["name"] == "get_rollup" and mine[1]["grounded"] is True
    assert mine[1]["request_id"]
    everyone = client.get("/api/v1/assistant/history", headers=headers("admin")).json()
    assert {c["actor"] for c in everyone} == {"marc", "kim"}


def test_embed_contract_describes_the_iframe_and_post_message_shape(client):
    embed = client.get("/api/v1/assistant/embed").json()
    assert embed["iframe_path"] == "/embed/assistant" and embed["writes"] == []
    assert embed["post_message"]["to_panel"]["type"] == "opptrack.identity"
