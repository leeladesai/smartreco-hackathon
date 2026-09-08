import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy import select

from app.config import Settings
from app.db import build_session_factory
from app.models import Event, Model, Recommendation, User
from app.schemas import (
    AuthCredentials,
    BulkImportResponse,
    ModelCreate,
    ModelResponse,
    UserResponse,
)
from app.security import (
    create_session_token,
    make_role_dependency,
    verify_password,
)
from app.services.admin_overview import (
    event_type_counts,
    feedback_sentiment,
    recent_activity,
    usage_totals,
)
from app.services.catalog import (
    create_model as create_model_service,
    delete_model as delete_model_service,
    update_model as update_model_service,
)
from app.services.catalog_import import (
    CatalogParseError,
    import_catalog_rows,
    parse_catalog_file,
)
from app.services.agent_graph import STRONG_RETRIEVAL_DISTANCE, WEAK_RETRIEVAL_DISTANCE
from app.services.digest import build_notifier
from app.services.recommendation import mesh_cost_rollup
from app.services.mesh import MeshNarrativeGenerator
from app.services.observability import (
    ObservabilityUnavailable,
    fetch_recent_runs,
    fetch_run_detail,
)
from app.services.tracing import configure_langsmith
from app.vector import ModelVectorStore, build_embedding_function
from seed_data import seed_demo_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = PROJECT_ROOT / "app" / "templates"
BULK_UPLOAD_MAX_BYTES = 2 * 1024 * 1024  # plenty for a few hundred catalog rows
TEMPLATES = Jinja2Templates(directory=TEMPLATE_ROOT)
TEMPLATES.env.loader = ChoiceLoader(
    [FileSystemLoader(TEMPLATE_ROOT), FileSystemLoader(PROJECT_ROOT)]
)


def model_response(model: Model) -> ModelResponse:
    return ModelResponse.model_validate(model)


def as_utc(value):
    """SQLite's CURRENT_TIMESTAMP (via func.now()) is UTC but comes back tz-naive, so
    datetime.isoformat() serializes it with no 'Z'/offset — the browser's Date parser then
    reads it as local time instead of converting it, silently corrupting every displayed
    timestamp by the viewer's UTC offset. Stamping tzinfo here makes the API's timestamps
    unambiguous for any client, rather than papering over it in one frontend render call.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()
    configure_langsmith(app_settings)
    session_factory = build_session_factory(app_settings)
    vector_store = ModelVectorStore(
        app_settings.chroma_db_path,
        collection_name=app_settings.chroma_collection_name,
        embedding_function=build_embedding_function(app_settings),
    )
    mesh_generator = MeshNarrativeGenerator(app_settings)
    notifier = build_notifier(app_settings)
    # AI-engineer accounts/session (self-registration, event tracking, dashboard,
    # activity) were removed as part of the platform pivot to a multi-tenant,
    # embeddable-widget product (docs/design/09-Platform-Pivot-Decision.md) — the
    # reference tenant's own end-user surface returns with the tracker SDK phase,
    # built on anonymous visitor identity rather than this cookie-session `user` role.
    # `admin` is (for now) the only role; tenant-admin/platform-admin generalization
    # lands with tenant onboarding (TEN-1..8).
    current_admin = make_role_dependency(
        session_factory, app_settings, required_role="admin"
    )

    # DLV-3 (bonus scheduled digest) is disabled, not redesigned, now that the
    # AI-engineer `user` role it iterated over is gone — app/services/digest.py stays
    # in place, unregistered, for whenever anonymous-visitor digest delivery is
    # actually specified.
    scheduler = BackgroundScheduler()

    def run_seed() -> None:
        try:
            seed_demo_data(session_factory, vector_store)
        except Exception:
            # Best-effort: demo accounts/catalog staying stale (or briefly missing)
            # on a slow/unreachable DB is far better than taking the whole service
            # down for it — request handlers below still work against whatever's
            # already in the DB. Logged so a broken seed doesn't go unnoticed.
            logging.exception("Background seed_demo_data failed")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler.start()
        # Fire-and-forget, not awaited: uvicorn should start accepting requests
        # (including /health) immediately rather than waiting on this — see
        # seed_demo_data's docstring for why it used to block startup entirely.
        app.state.seed_task = asyncio.create_task(asyncio.to_thread(run_seed))
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)

    app = FastAPI(
        title="TrailMind",
        description="Multi-tenant embeddable behavioral recommendation platform",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.session_factory = session_factory
    app.state.vector_store = vector_store
    app.state.mesh_generator = mesh_generator
    app.state.notifier = notifier
    app.state.scheduler = scheduler
    app.state.pipeline_locks = {}
    app.state.pipeline_locks_guard = asyncio.Lock()
    app.mount(
        "/static",
        StaticFiles(directory=PROJECT_ROOT / "app" / "static"),
        name="static",
    )

    def asset_version(relative_path: str) -> int:
        """Cache-busts static CSS/JS by mtime, not just server restart — otherwise a
        browser can keep serving a stale cached copy after an edit even on a normal reload.
        """
        return int((PROJECT_ROOT / "app" / "static" / relative_path).stat().st_mtime)

    def render_page(request: Request, page: str, template: str, session_role=None):
        return TEMPLATES.TemplateResponse(
            template,
            {
                "request": request,
                "initial_page": page,
                "session_role": session_role,
                "css_version": asset_version("css/app.css"),
                "js_version": asset_version("js/app.js"),
            },
        )

    def render_admin_page(
        request: Request, page: str = "admin", template: str = "admin.html"
    ):
        try:
            current_admin(request)
        except HTTPException:
            return RedirectResponse(
                "/admin/login", status_code=status.HTTP_303_SEE_OTHER
            )
        return render_page(request, page, template, session_role="admin")

    @app.get("/admin/login", include_in_schema=False)
    async def admin_login_page(request: Request):
        return render_page(request, "admin-auth", "admin_login.html")

    @app.get("/admin", include_in_schema=False)
    async def admin_page(request: Request):
        return render_admin_page(request, "admin-overview", "overview.html")

    @app.get("/admin/models", include_in_schema=False)
    async def admin_models_page(request: Request):
        return render_admin_page(request, "admin-models", "admin.html")

    @app.get("/admin/observability", include_in_schema=False)
    async def admin_observability_page(request: Request):
        return render_admin_page(request, "observability", "observability.html")

    @app.get("/admin/users", include_in_schema=False)
    async def admin_users_page(request: Request):
        return render_admin_page(request, "admin-users", "users.html")

    @app.get("/health")
    async def health(response: Response) -> dict[str, str]:
        # Allows the standalone Vercel warm-up page (see warmup-page/) to poll this
        # cross-origin while the Render free-tier instance wakes from sleep.
        response.headers["Access-Control-Allow-Origin"] = "*"
        return {"status": "ok", "service": "trailmind"}

    @app.post("/api/admin/login", response_model=UserResponse)
    async def admin_login(
        credentials: AuthCredentials, response: Response
    ) -> UserResponse:
        with session_factory() as session:
            user = session.scalar(
                select(User).where(User.email == credentials.email.lower())
            )
            valid = user and verify_password(credentials.password, user.password_hash)
            if not valid or user.role != "admin":
                raise HTTPException(status_code=401, detail="Invalid email or password")
            token = create_session_token(user, app_settings)
            response.set_cookie(
                app_settings.session_cookie_name,
                token,
                httponly=True,
                samesite="lax",
                secure=app_settings.session_cookie_secure,
                max_age=60 * 60 * 12,
            )
            return UserResponse.model_validate(user)

    @app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(response: Response) -> None:
        response.delete_cookie(app_settings.session_cookie_name)

    @app.get("/api/admin/me", response_model=UserResponse)
    async def current_admin_profile(
        admin: User = Depends(current_admin),
    ) -> UserResponse:
        return UserResponse.model_validate(admin)

    @app.get("/api/models", response_model=list[ModelResponse])
    async def list_models(
        admin: User = Depends(current_admin),
        q: str | None = Query(default=None),
        modality: str | None = Query(default=None),
        provider: str | None = Query(default=None),
    ) -> list[ModelResponse]:
        with session_factory() as session:
            statement = (
                select(Model)
                .where(Model.tenant_id == admin.tenant_id)
                .order_by(Model.title)
            )
            if q:
                statement = statement.where(
                    Model.title.ilike(f"%{q}%") | Model.description.ilike(f"%{q}%")
                )
            if modality:
                statement = statement.where(Model.modality == modality)
            if provider:
                statement = statement.where(Model.provider == provider)
            return [model_response(model) for model in session.scalars(statement).all()]

    @app.get("/api/models/{model_id}", response_model=ModelResponse)
    async def get_model(
        model_id: int, admin: User = Depends(current_admin)
    ) -> ModelResponse:
        with session_factory() as session:
            model = session.get(Model, model_id)
            if not model or model.tenant_id != admin.tenant_id:
                raise HTTPException(status_code=404, detail="Model not found")
            return model_response(model)

    def content_similarity_reason(distance: float, source_title: str) -> str:
        """Same distance thresholds as retrieval_reason (AGT-4), but worded for content-based
        similarity to a specific model rather than a match to the user's activity — using
        retrieval_reason's "your recent activity" phrasing here would misattribute why this
        model showed up."""
        if distance <= STRONG_RETRIEVAL_DISTANCE:
            return f"Strong match to {source_title}"
        if distance <= WEAK_RETRIEVAL_DISTANCE:
            return f"Similar to {source_title}"
        return "Broader catalog match"

    @app.get("/api/models/{model_id}/related")
    async def related_models(
        model_id: int, admin: User = Depends(current_admin), limit: int = 3
    ) -> list[dict[str, object]]:
        """Content-based "you might also be interested in": queries the same Chroma vector
        store the recommendation pipeline uses, but keyed on *this model's own* embedding
        text (title/provider/modality/description/tags — see ModelVectorStore.document)
        rather than a user's activity summary. Grounded in real similarity, not activity.
        """
        with session_factory() as session:
            model = session.get(Model, model_id)
            if not model or model.tenant_id != admin.tenant_id:
                raise HTTPException(status_code=404, detail="Model not found")
            query_text = ModelVectorStore.document(model)
            # Prefer same-modality matches first — the deterministic hashed bag-of-words
            # embedding (app/vector.py) has weak semantics, so an unfiltered query can surface
            # a cross-modality "match" (e.g. an LLM as "similar to" an image model) purely on
            # shared generic words. Only fall back to an unfiltered query if same-modality
            # doesn't yield enough candidates (e.g. this modality has too few catalog entries).
            same_modality = vector_store.query_scored(
                query_text,
                admin.tenant_id,
                limit=limit + 1,
                where={"modality": model.modality},
            )
            seen_ids = {model_id}
            results: list[dict[str, object]] = []

            def _add_candidates(scored: list[tuple[int, float]]) -> None:
                for candidate_id, distance in scored:
                    if len(results) >= limit or candidate_id in seen_ids:
                        continue
                    seen_ids.add(candidate_id)
                    candidate = session.get(Model, candidate_id)
                    if not candidate or candidate.tenant_id != admin.tenant_id:
                        continue
                    results.append(
                        {
                            **model_response(candidate).model_dump(mode="json"),
                            "why_this": content_similarity_reason(
                                distance, model.title
                            ),
                        }
                    )

            _add_candidates(same_modality)
            if len(results) < limit:
                _add_candidates(
                    vector_store.query_scored(
                        query_text, admin.tenant_id, limit=limit + 1
                    )
                )
            return results

    @app.post(
        "/api/admin/models",
        response_model=ModelResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_model(
        payload: ModelCreate, admin: User = Depends(current_admin)
    ) -> ModelResponse:
        with session_factory() as session:
            model = create_model_service(
                session, vector_store, admin.tenant_id, payload
            )
            return model_response(model)

    @app.put("/api/admin/models/{model_id}", response_model=ModelResponse)
    async def update_model(
        model_id: int, payload: ModelCreate, admin: User = Depends(current_admin)
    ) -> ModelResponse:
        with session_factory() as session:
            model = session.get(Model, model_id)
            if not model or model.tenant_id != admin.tenant_id:
                raise HTTPException(status_code=404, detail="Model not found")
            update_model_service(session, vector_store, admin.tenant_id, model, payload)
            return model_response(model)

    @app.delete("/api/admin/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_model(model_id: int, admin: User = Depends(current_admin)) -> None:
        with session_factory() as session:
            model = session.get(Model, model_id)
            if not model or model.tenant_id != admin.tenant_id:
                raise HTTPException(status_code=404, detail="Model not found")
            delete_model_service(session, vector_store, admin.tenant_id, model)

    @app.post("/api/admin/models/bulk-upload", response_model=BulkImportResponse)
    async def bulk_upload_models(
        file: UploadFile = File(...), admin: User = Depends(current_admin)
    ) -> BulkImportResponse:
        content = await file.read()
        if len(content) > BULK_UPLOAD_MAX_BYTES:
            raise HTTPException(status_code=413, detail="File too large (max 2MB).")
        try:
            raw_rows = parse_catalog_file(file.filename or "", content)
        except CatalogParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        with session_factory() as session:
            rows = import_catalog_rows(session, vector_store, admin.tenant_id, raw_rows)
        return BulkImportResponse(
            inserted=sum(1 for row in rows if row["status"] == "inserted"),
            skipped_duplicate=sum(
                1 for row in rows if row["status"] == "skipped_duplicate"
            ),
            invalid=sum(1 for row in rows if row["status"] == "invalid"),
            rows=rows,
        )

    @app.get("/api/admin/observability/runs")
    async def observability_runs(
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        user_id: int | None = Query(default=None),
        _: User = Depends(current_admin),
    ) -> dict[str, object]:
        """OBS-2: surfaces recent agent-pipeline traces inside the admin portal
        itself, so a curator never needs their own LangSmith login to see whether
        recent runs succeeded and how long they took. Read-only proxy over the
        LangSmith API — this app never writes trace data, `@traceable` (OBS-1)
        already does that."""
        try:
            runs, has_more = fetch_recent_runs(
                app_settings, limit=limit, offset=offset, user_id=user_id
            )
        except ObservabilityUnavailable as exc:
            return {
                "available": False,
                "message": str(exc),
                "runs": [],
                "has_more": False,
            }
        return {
            "available": True,
            "message": None,
            "has_more": has_more,
            "runs": [
                {
                    "id": run.id,
                    "name": run.name,
                    "run_type": run.run_type,
                    "status": run.status,
                    "start_time": as_utc(run.start_time).isoformat()
                    if run.start_time
                    else None,
                    "latency_ms": run.latency_ms,
                    "pipeline_latency_ms": run.pipeline_latency_ms,
                    "user_id": run.user_id,
                    "error": run.error,
                    "url": run.url,
                }
                for run in runs
            ],
        }

    @app.get("/api/admin/observability/runs/{run_id}")
    async def observability_run_detail(
        run_id: str,
        _: User = Depends(current_admin),
    ) -> dict[str, object]:
        """The step-by-step breakdown of a single run — brings the trace itself into
        the admin portal instead of only linking out to LangSmith (OBS-2 follow-up)."""
        try:
            detail = fetch_run_detail(app_settings, run_id)
        except ObservabilityUnavailable as exc:
            return {"available": False, "message": str(exc), "run": None}
        return {
            "available": True,
            "message": None,
            "run": {
                "id": detail.id,
                "name": detail.name,
                "status": detail.status,
                "start_time": as_utc(detail.start_time).isoformat()
                if detail.start_time
                else None,
                "latency_ms": detail.latency_ms,
                "pipeline_latency_ms": detail.pipeline_latency_ms,
                "url": detail.url,
                "steps": [
                    {
                        "name": step.name,
                        "run_type": step.run_type,
                        "status": step.status,
                        "start_time": as_utc(step.start_time).isoformat()
                        if step.start_time
                        else None,
                        "latency_ms": step.latency_ms,
                        "error": step.error,
                        "depth": step.depth,
                        "inputs": step.inputs,
                        "outputs": step.outputs,
                    }
                    for step in detail.steps
                ],
            },
        }

    @app.get("/api/admin/overview")
    async def admin_overview(
        admin: User = Depends(current_admin),
    ) -> dict[str, object]:
        """Platform-usage summary for the admin landing page — totals, event-type
        breakdown, and explicit-feedback sentiment. Distinct from
        /api/admin/observability/*, which is AI-pipeline/LangSmith technical health;
        this is business/usage metrics, computed straight from our own tables."""
        with session_factory() as session:
            return {
                "totals": usage_totals(session, admin.tenant_id),
                "event_type_counts": event_type_counts(session, admin.tenant_id),
                "feedback": feedback_sentiment(session, admin.tenant_id),
            }

    @app.get("/api/admin/overview/activity")
    async def admin_overview_activity(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        admin: User = Depends(current_admin),
    ) -> dict[str, object]:
        """The admin-wide live activity feed — every visitor's events, newest first."""
        with session_factory() as session:
            events, has_more = recent_activity(
                session, admin.tenant_id, limit=limit, offset=offset
            )
        return {
            "events": [
                {**event, "created_at": as_utc(event["created_at"])} for event in events
            ],
            "has_more": has_more,
        }

    @app.get("/api/admin/users")
    async def list_users(
        limit: int = Query(default=500, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        admin: User = Depends(current_admin),
    ) -> dict[str, object]:
        """Newest-registered first. `limit` defaults high enough that the
        Observability page's "filter by user" dropdown (which wants every user, not
        a page of them) can keep calling this with no params; the Users table page
        passes an explicit limit=20 for real pagination."""
        with session_factory() as session:
            rows = session.scalars(
                select(User)
                .where(User.tenant_id == admin.tenant_id)
                .order_by(User.created_at.desc(), User.id.desc())
                .offset(offset)
                .limit(limit + 1)
            ).all()
            has_more = len(rows) > limit
            page = rows[:limit]
            return {
                "users": [
                    {
                        "id": user.id,
                        "email": user.email,
                        "role": user.role,
                        "telegram_chat_id": user.telegram_chat_id,
                        "created_at": as_utc(user.created_at).isoformat(),
                    }
                    for user in page
                ],
                "has_more": has_more,
            }

    @app.delete("/api/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_user(user_id: int, admin: User = Depends(current_admin)) -> None:
        if user_id == admin.id:
            raise HTTPException(
                status_code=400, detail="Cannot delete the account you're signed in as"
            )
        with session_factory() as session:
            user = session.get(User, user_id)
            if not user or user.tenant_id != admin.tenant_id:
                raise HTTPException(status_code=404, detail="User not found")
            # No ORM cascade is configured for Event/Recommendation.user_id (plain FK
            # columns, not relationships) and SQLite doesn't enforce FKs by default —
            # deleting the row alone would leave that user's behavioral history and
            # past recommendations orphaned rather than actually gone.
            session.query(Event).filter(Event.user_id == user_id).delete()
            session.query(Recommendation).filter(
                Recommendation.user_id == user_id
            ).delete()
            session.delete(user)
            session.commit()

    @app.get("/api/admin/observability/costs")
    async def observability_costs(
        admin: User = Depends(current_admin),
    ) -> dict[str, object]:
        """Mesh cost/latency/token rollup, aggregated straight from our own DB
        (`Recommendation.mesh_*` columns, captured in app/services/mesh.py at
        generation time) — deliberately not another LangSmith query, so this stays
        available even without tracing configured, and demonstrates the "efficiency"
        story with real numbers rather than a trace count."""
        with session_factory() as session:
            rollup = mesh_cost_rollup(session, admin.tenant_id)
        return {
            "call_count": rollup["call_count"],
            "avg_latency_ms": rollup["avg_latency_ms"],
            "total_prompt_tokens": rollup["total_prompt_tokens"],
            "total_completion_tokens": rollup["total_completion_tokens"],
            "total_cost_usd": rollup["total_cost_usd"],
            "recent": [
                {
                    "id": row["id"],
                    "created_at": as_utc(row["created_at"]).isoformat()
                    if row["created_at"]
                    else None,
                    "latency_ms": row["latency_ms"],
                    "prompt_tokens": row["prompt_tokens"],
                    "completion_tokens": row["completion_tokens"],
                    "cost_usd": row["cost_usd"],
                }
                for row in rollup["recent"]
            ],
        }

    return app
