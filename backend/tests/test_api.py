"""HTTP API: поиск внутри профиля и отметки пользователей (модель CLIP подменена)."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


class FakeClip:
    def embed_text(self, texts):
        v = np.zeros((len(texts), 4), dtype=np.float32)
        v[:, 0] = 1
        return v


@pytest.fixture()
def client(tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "prewarm", False)
    monkeypatch.setattr(s, "cache_dir", str(tmp_path))
    import app.vision.clip_model as cm
    monkeypatch.setattr(cm, "get_clip", lambda: FakeClip())
    from app import main
    from app.pipeline.events import EventLog
    log = EventLog(key="Q1")
    log.finished = True
    log.embeddings = {"a" * 16: np.array([1, 0, 0, 0], np.float16), "b" * 16: np.array([0, 1, 0, 0], np.float16)}
    log.feature_rows = [{"id": "a" * 16, "features": {"geo": 1.0}}]
    main.registry.put(log)
    with TestClient(main.app) as c:
        yield c


def test_find(client):
    r = client.get("/api/profile/Q1/find", params={"q": "бассейн"})
    body = r.json()
    assert r.status_code == 200 and body["english"] and body["results"][0]["id"] == "a" * 16
    assert len(body["results"]) == 1
    assert client.get("/api/profile/Q999/find", params={"q": "pool"}).status_code == 404
    assert client.get("/api/profile/Q1/find", params={"q": "ыыыы"}).json()["results"] == []


def test_feedback(client, tmp_path):
    ok = client.post("/api/feedback", json={"qid": "Q1", "photo_id": "a" * 16, "kind": "wrong_university"})
    assert ok.status_code == 200
    saved = (tmp_path / "feedback.jsonl").read_text(encoding="utf-8")
    assert '"label": 0' in saved and '"geo": 1.0' in saved
    bad = client.post("/api/feedback", json={"qid": "Q1", "photo_id": "zzz", "kind": "wrong_university"})
    assert bad.status_code == 400


def test_health_reports_heads(client):
    body = client.get("/api/health").json()
    assert "heads" in body and "calibrator" in body
