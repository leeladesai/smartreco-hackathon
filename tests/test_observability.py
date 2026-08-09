from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import User
from app.security import hash_password


def _admin_client(tmp_path, monkeypatch, langsmith_api_key=None):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
        secret_key="test-secret",
        mesh_api_key=None,
        langsmith_api_key=langsmith_api_key,
    )
    app = create_app(settings)
    with app.state.session_factory() as session:
        session.add(
            User(
                email="curator@test.dev",
                password_hash=hash_password("password123"),
                role="admin",
            )
        )
        session.commit()
    test_client = TestClient(app)
    test_client.post(
        "/api/admin/login",
        json={"email": "curator@test.dev", "password": "password123"},
    )
    return test_client


def test_observability_requires_admin(client: TestClient) -> None:
    client.post(
        "/api/auth/register", json={"email": "user@test.dev", "password": "password123"}
    )
    client.post(
        "/api/auth/login", json={"email": "user@test.dev", "password": "password123"}
    )
    response = client.get("/api/admin/observability/runs")
    assert response.status_code == 403


def test_observability_unavailable_without_langsmith_key(tmp_path, monkeypatch) -> None:
    admin_client = _admin_client(tmp_path, monkeypatch, langsmith_api_key=None)
    response = admin_client.get("/api/admin/observability/runs")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["runs"] == []
    assert "LANGSMITH_API_KEY" in body["message"]


def test_observability_returns_recent_runs(tmp_path, monkeypatch) -> None:
    class FakeRun:
        def __init__(self, id_, name, status, error=None):
            self.id = id_
            self.name = name
            self.run_type = "chain"
            self.status = status
            self.error = error
            self.start_time = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
            self.end_time = datetime(2026, 8, 8, 12, 0, 2, tzinfo=timezone.utc)
            self.session_id = "fake-session"

    class FakeClient:
        def __init__(self, api_key=None):
            self.api_key = api_key

        def list_runs(self, **kwargs):
            return iter(
                [
                    FakeRun("1", "agent_pipeline", "success"),
                    FakeRun("2", "agent_pipeline", "error", error="Mesh timeout"),
                ]
            )

        def get_run_url(self, *, run):
            return f"https://smith.langchain.com/fake/{run.id}"

    import app.services.observability as observability_module

    monkeypatch.setattr(observability_module, "Client", FakeClient)

    admin_client = _admin_client(tmp_path, monkeypatch, langsmith_api_key="fake-key")
    response = admin_client.get("/api/admin/observability/runs")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert len(body["runs"]) == 2
    assert body["runs"][0]["name"] == "agent_pipeline"
    assert body["runs"][0]["latency_ms"] == 2000
    assert body["runs"][1]["error"] == "Mesh timeout"
    assert body["runs"][0]["url"] == "https://smith.langchain.com/fake/1"


def test_observability_paginates_runs(tmp_path, monkeypatch) -> None:
    class FakeRun:
        def __init__(self, id_, name, status, start_time):
            self.id = id_
            self.name = name
            self.run_type = "chain"
            self.status = status
            self.error = None
            self.start_time = start_time
            self.end_time = start_time + timedelta(seconds=2)
            self.session_id = "fake-session"

    t0 = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)

    class FakeClient:
        def __init__(self, api_key=None):
            self.api_key = api_key

        def list_runs(self, **kwargs):
            # Deliberately yielded oldest-first (run "1" has the earliest start_time)
            # — fetch_recent_runs must sort newest-first itself before paging, so the
            # page order can't just be trusting this iterator's own order.
            return iter(
                [
                    FakeRun("1", "agent_pipeline", "success", t0),
                    FakeRun(
                        "2", "agent_pipeline", "success", t0 + timedelta(minutes=1)
                    ),
                    FakeRun(
                        "3", "agent_pipeline", "success", t0 + timedelta(minutes=2)
                    ),
                ]
            )

        def get_run_url(self, *, run):
            return f"https://smith.langchain.com/fake/{run.id}"

    import app.services.observability as observability_module

    monkeypatch.setattr(observability_module, "Client", FakeClient)

    admin_client = _admin_client(tmp_path, monkeypatch, langsmith_api_key="fake-key")

    first_page = admin_client.get("/api/admin/observability/runs?limit=2&offset=0")
    body = first_page.json()
    assert [run["id"] for run in body["runs"]] == ["3", "2"]
    assert body["has_more"] is True

    second_page = admin_client.get("/api/admin/observability/runs?limit=2&offset=2")
    body = second_page.json()
    assert [run["id"] for run in body["runs"]] == ["1"]
    assert body["has_more"] is False


def test_observability_runs_scopes_to_one_user_via_native_tag_filter(
    tmp_path, monkeypatch
) -> None:
    """Each agent_pipeline run is tagged user:<id> at trace time
    (prepare_retrieval_recommendation) — a user_id query param must turn into a real
    server-side LangSmith filter (has(tags, "user:<id>")), not a client-side filter
    over the unscoped run list, so this only asserts on what list_runs was actually
    called with."""

    class FakeRun:
        def __init__(self, id_):
            self.id = id_
            self.name = "agent_pipeline"
            self.run_type = "chain"
            self.status = "success"
            self.error = None
            self.start_time = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
            self.end_time = self.start_time + timedelta(seconds=1)
            self.session_id = "fake-session"

    captured_kwargs = {}

    class FakeClient:
        def __init__(self, api_key=None):
            pass

        def list_runs(self, **kwargs):
            captured_kwargs.update(kwargs)
            return iter([FakeRun("only-this-users-run")])

        def get_run_url(self, *, run):
            return f"https://smith.langchain.com/fake/{run.id}"

    import app.services.observability as observability_module

    monkeypatch.setattr(observability_module, "Client", FakeClient)

    admin_client = _admin_client(tmp_path, monkeypatch, langsmith_api_key="fake-key")

    response = admin_client.get("/api/admin/observability/runs?user_id=42")
    assert response.status_code == 200
    assert captured_kwargs.get("filter") == 'has(tags, "user:42")'
    assert [run["id"] for run in response.json()["runs"]] == ["only-this-users-run"]

    # Without user_id, no filter is sent at all — the unscoped "all users" view.
    captured_kwargs.clear()
    admin_client.get("/api/admin/observability/runs")
    assert "filter" not in captured_kwargs


def test_observability_reports_api_failure(tmp_path, monkeypatch) -> None:
    class FailingClient:
        def __init__(self, api_key=None):
            pass

        def list_runs(self, **kwargs):
            raise RuntimeError("connection refused")

    import app.services.observability as observability_module

    monkeypatch.setattr(observability_module, "Client", FailingClient)

    admin_client = _admin_client(tmp_path, monkeypatch, langsmith_api_key="fake-key")
    response = admin_client.get("/api/admin/observability/runs")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "connection refused" in body["message"]


def test_observability_run_detail_requires_admin(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        json={"email": "detailuser@test.dev", "password": "password123"},
    )
    client.post(
        "/api/auth/login",
        json={"email": "detailuser@test.dev", "password": "password123"},
    )
    response = client.get("/api/admin/observability/runs/some-id")
    assert response.status_code == 403


def test_observability_run_detail_unavailable_without_langsmith_key(
    tmp_path, monkeypatch
) -> None:
    admin_client = _admin_client(tmp_path, monkeypatch, langsmith_api_key=None)
    response = admin_client.get("/api/admin/observability/runs/some-id")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["run"] is None


class _FakeRun:
    def __init__(
        self,
        id_,
        name,
        run_type="chain",
        status="success",
        error=None,
        start_time=None,
        end_time=None,
        inputs=None,
        outputs=None,
        child_runs=None,
    ):
        self.id = id_
        self.name = name
        self.run_type = run_type
        self.status = status
        self.error = error
        self.start_time = start_time
        self.end_time = end_time
        self.inputs = inputs or {}
        self.outputs = outputs or {}
        self.child_runs = child_runs or []
        self.session_id = "fake-session"


def test_observability_run_detail_filters_noise_and_orders_steps(
    tmp_path, monkeypatch
) -> None:
    t0 = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)

    def at(seconds):
        return t0 + timedelta(seconds=seconds)

    # analyze_activity started before retrieve_models, but is listed second in
    # child_runs — the response must still order steps by start_time, not list order.
    retrieve = _FakeRun(
        "retrieve-id",
        "retrieve_models",
        run_type="retriever",
        start_time=at(2),
        end_time=at(3),
        inputs={"state": {"a": 1}},
        outputs={"candidates_scored": []},
    )
    analyze = _FakeRun(
        "analyze-id",
        "analyze_activity",
        start_time=at(0),
        end_time=at(1),
        inputs={"state": {"user_id": 5}},
        outputs={"behavior_summary": "x"},
    )
    # A LangGraph-internal "noise" node wrapping the two named ones — must be skipped,
    # but its children must still surface, at depth 0 (not nested under the noise).
    langgraph_noise = _FakeRun("noise-id", "LangGraph", child_runs=[retrieve, analyze])
    root = _FakeRun(
        "root-id",
        "agent_pipeline",
        start_time=at(0),
        end_time=at(5),
        child_runs=[langgraph_noise],
    )

    class FakeClient:
        def __init__(self, api_key=None):
            pass

        def read_run(self, run_id, load_child_runs=False):
            assert run_id == "root-id"
            assert load_child_runs is True
            return root

        def get_run_url(self, *, run):
            return f"https://smith.langchain.com/fake/{run.id}"

    import app.services.observability as observability_module

    monkeypatch.setattr(observability_module, "Client", FakeClient)

    admin_client = _admin_client(tmp_path, monkeypatch, langsmith_api_key="fake-key")
    response = admin_client.get("/api/admin/observability/runs/root-id")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    run = body["run"]
    assert run["id"] == "root-id"
    assert run["name"] == "agent_pipeline"
    assert [step["name"] for step in run["steps"]] == [
        "analyze_activity",
        "retrieve_models",
    ]
    assert all(step["depth"] == 0 for step in run["steps"])
    assert run["steps"][0]["outputs"] == {"behavior_summary": "x"}
    assert run["url"] == "https://smith.langchain.com/fake/root-id"


def test_observability_run_detail_sorts_across_separate_top_level_branches(
    tmp_path, monkeypatch
) -> None:
    """Regression test: real traces can have multiple separate top-level branches
    (e.g. each grade_refine retry under its own internal wrapper span rather than a
    single shared parent) — sorting only within each branch doesn't produce a globally
    chronological list. The response must sort the fully flattened step list."""
    t0 = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)

    def at(seconds):
        return t0 + timedelta(seconds=seconds)

    # Second branch (listed first in child_runs) starts *later* than the first branch
    # (listed second) — a per-branch-only sort would emit retrieve_models before
    # analyze_activity.
    branch_two = _FakeRun(
        "branch-two",
        "grade_refine",
        start_time=at(10),
        end_time=at(11),
    )
    branch_one = _FakeRun(
        "branch-one",
        "analyze_activity",
        start_time=at(0),
        end_time=at(1),
    )
    root = _FakeRun(
        "root-id",
        "agent_pipeline",
        start_time=at(0),
        end_time=at(11),
        child_runs=[branch_two, branch_one],
    )

    class FakeClient:
        def __init__(self, api_key=None):
            pass

        def read_run(self, run_id, load_child_runs=False):
            return root

        def get_run_url(self, *, run):
            return f"https://smith.langchain.com/fake/{run.id}"

    import app.services.observability as observability_module

    monkeypatch.setattr(observability_module, "Client", FakeClient)

    admin_client = _admin_client(tmp_path, monkeypatch, langsmith_api_key="fake-key")
    response = admin_client.get("/api/admin/observability/runs/root-id")
    body = response.json()
    assert [step["name"] for step in body["run"]["steps"]] == [
        "analyze_activity",
        "grade_refine",
    ]


def test_observability_run_detail_reports_api_failure(tmp_path, monkeypatch) -> None:
    class FailingClient:
        def __init__(self, api_key=None):
            pass

        def read_run(self, run_id, load_child_runs=False):
            raise RuntimeError("not found")

    import app.services.observability as observability_module

    monkeypatch.setattr(observability_module, "Client", FailingClient)

    admin_client = _admin_client(tmp_path, monkeypatch, langsmith_api_key="fake-key")
    response = admin_client.get("/api/admin/observability/runs/missing-id")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "not found" in body["message"]
