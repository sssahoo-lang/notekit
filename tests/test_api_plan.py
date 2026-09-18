"""Plan first, write after approval."""

import pytest
from fastapi.testclient import TestClient

from notekit import api
from notekit.models import Module, Syllabus


def outline(n=2):
    return Syllabus(
        title="T", topic_slug="t", summary="s", corpus_query="cq",
        modules=[Module(title=f"M{i}", query=f"q{i}", learning_goals=["g"]) for i in range(n)],
    )


@pytest.fixture
def client(monkeypatch):
    api._rate_windows.clear()
    monkeypatch.delenv("SITE_PASSWORD", raising=False)
    return TestClient(api.app)


def test_plan_takes_json_and_passes_the_stated_level(client, monkeypatch):
    seen = {}
    def fake_plan(goal, *, level=None):
        seen.update(goal=goal, level=level); return outline()
    monkeypatch.setattr(api, "plan_syllabus", fake_plan)
    r = client.post("/api/plan", json={"goal": "teach me x", "user": "u",
                                       "preferences": {"level": "beginner"}})
    assert r.status_code == 200
    assert r.json()["modules"][0]["title"] == "M0"
    assert seen == {"goal": "teach me x", "level": "beginner"}


def test_plan_is_rate_limited_on_its_own_bucket(client, monkeypatch):
    monkeypatch.setattr(api, "plan_syllabus", lambda goal, *, level=None: outline())
    monkeypatch.setattr(api.config, "RATE_LIMITS", {**api.config.RATE_LIMITS, "plan": (1, 3600)})
    body = {"goal": "x", "user": "u"}
    assert client.post("/api/plan", json=body).status_code == 200
    assert client.post("/api/plan", json=body).status_code == 429


def test_a_reviewed_syllabus_is_handed_to_generation(client, monkeypatch):
    seen = {}
    async def capture(request):
        seen["syllabus"] = request.syllabus
        yield {"type": "done"}
    monkeypatch.setattr(api, "_course_events_saving", capture)
    monkeypatch.setattr(api.courses, "spent_today", lambda u: 0.0)
    edited = outline().model_dump(); edited["modules"][1]["title"] = "Renamed by the reader"
    r = client.post("/api/course", json={"goal": "x", "user": "u", "syllabus": edited})
    assert r.status_code == 200
    assert seen["syllabus"].modules[1].title == "Renamed by the reader"


def test_a_syllabus_with_too_many_sections_is_refused(client, monkeypatch):
    monkeypatch.setattr(api.courses, "spent_today", lambda u: 0.0)
    r = client.post("/api/course", json={"goal": "x", "user": "u", "syllabus": outline(9).model_dump()})
    assert r.status_code == 422
