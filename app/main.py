import asyncio
from contextlib import asynccontextmanager
from datetime import timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import build_session_factory
from app.models import DemoModeSetting, Event, Model, Recommendation, User
from app.schemas import (
    AuthCredentials,
    DemoModeResponse,
    DemoModeUpdate,
    EventBatch,
    ModelCreate,
    ModelResponse,
    UserResponse,
)
from app.security import (
    create_session_token,
    hash_password,
    make_role_dependency,
    verify_password,
)
from app.services.catalog import (
    create_model as create_model_service,
    delete_model as delete_model_service,
    update_model as update_model_service,
)
from app.services.agent_graph import (
    STRONG_RETRIEVAL_DISTANCE,
    WEAK_RETRIEVAL_DISTANCE,
    contextual_reason,
    prepare_retrieval_recommendation,
)
from app.services.digest import build_notifier, run_digest
from app.services.recommendation import (
    activity_summary,
    recent_events,
    session_evidence,
    should_trigger,
)
from app.services.mesh import MeshNarrativeGenerator
from app.services.tracing import configure_langsmith
from app.vector import ModelVectorStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = PROJECT_ROOT / "app" / "templates"
TEMPLATES = Jinja2Templates(directory=TEMPLATE_ROOT)
TEMPLATES.env.loader = ChoiceLoader(
    [FileSystemLoader(TEMPLATE_ROOT), FileSystemLoader(PROJECT_ROOT)]
)


def model_response(model: Model) -> ModelResponse:
    return ModelResponse.model_validate(model)


def get_or_create_demo_setting(session) -> DemoModeSetting:
    setting = session.get(DemoModeSetting, 1)
    if not setting:
        setting = DemoModeSetting(id=1, enabled=False)
        session.add(setting)
        session.commit()
        session.refresh(setting)
    return setting


def as_utc(value):
    """SQLite's CURRENT_TIMESTAMP (via func.now()) is UTC but comes back tz-naive, so
    datetime.isoformat() serializes it with no 'Z'/offset — the browser's Date parser then
    reads it as local time instead of converting it, silently corrupting every displayed
    timestamp by the viewer's UTC offset. Stamping tzinfo here makes the API's timestamps
    unambiguous for any client, rather than papering over it in one frontend render call."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()
    configure_langsmith(app_settings)
    session_factory = build_session_factory(app_settings)
    vector_store = ModelVectorStore(app_settings.chroma_db_path)
    mesh_generator = MeshNarrativeGenerator(app_settings)
    notifier = build_notifier(app_settings)
    current_user = make_role_dependency(session_factory, app_settings)
    current_admin = make_role_dependency(
        session_factory, app_settings, required_role="admin"
    )

    # DLV-3: a real cron scheduler, not a manual trigger — `/api/admin/digest/run` below
    # exists only so the sprint-review demo doesn't have to wait for the next cron fire.
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_digest,
        trigger=CronTrigger(
            hour=app_settings.digest_cron_hour, minute=app_settings.digest_cron_minute
        ),
        args=[session_factory, vector_store, mesh_generator, notifier],
        id="scheduled_digest",
        replace_existing=True,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)

    app = FastAPI(
        title="SmartReco",
        description="Behavioral AI model catalog MVP",
        version="0.1.0",
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
        browser can keep serving a stale cached copy after an edit even on a normal reload."""
        return int((PROJECT_ROOT / "app" / "static" / relative_path).stat().st_mtime)

    def render_page(
        request: Request,
        page: str,
        template: str,
        model_id: int | None = None,
        session_role: str | None = None,
    ):
        return TEMPLATES.TemplateResponse(
            template,
            {
                "request": request,
                "initial_page": page,
                "model_id": model_id,
                "session_role": session_role,
                "css_version": asset_version("css/app.css"),
                "js_version": asset_version("js/app.js"),
            },
        )

    def render_user_page(request: Request, page: str, template: str):
        try:
            user = current_user(request)
        except HTTPException:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        return render_page(request, page, template, session_role=user.role)

    def render_optional_session_page(request: Request, page: str, template: str):
        # The catalog is browsable while signed out, but a signed-in visitor's session must
        # still be recognized here — it's the page most view/search/compare activity starts
        # from, and until now it silently rendered as "not signed in" even with a valid
        # session cookie, which meant none of that activity ever got tracked.
        try:
            role = current_user(request).role
        except HTTPException:
            role = None
        return render_page(request, page, template, session_role=role)

    def render_admin_page(request: Request):
        try:
            current_admin(request)
        except HTTPException:
            return RedirectResponse(
                "/admin/login", status_code=status.HTTP_303_SEE_OTHER
            )
        return render_page(request, "admin", "admin.html", session_role="admin")

    @app.get("/", include_in_schema=False)
    async def landing_page(request: Request):
        return render_optional_session_page(request, "catalog", "catalog.html")

    @app.get("/login", include_in_schema=False)
    async def login_page(request: Request):
        return render_page(request, "auth", "login.html")

    @app.get("/admin/login", include_in_schema=False)
    async def admin_login_page(request: Request):
        return render_page(request, "admin-auth", "admin_login.html")

    @app.get("/catalog", include_in_schema=False)
    async def catalog_page(request: Request):
        return render_optional_session_page(request, "catalog", "catalog.html")

    @app.get("/models/{model_id}", include_in_schema=False)
    async def model_detail_page(request: Request, model_id: int):
        try:
            current_user(request)
        except HTTPException:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        return render_page(
            request, "detail", "model_detail.html", model_id, session_role="user"
        )

    @app.get("/compare", include_in_schema=False)
    async def compare_page(request: Request):
        return render_user_page(request, "compare", "compare.html")

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard_page(request: Request):
        return render_user_page(request, "dashboard", "dashboard.html")

    @app.get("/activity", include_in_schema=False)
    async def activity_page(request: Request):
        return render_user_page(request, "activity", "activity.html")

    @app.get("/admin", include_in_schema=False)
    async def admin_page(request: Request):
        return render_admin_page(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "smartreco"}

    @app.post(
        "/api/auth/register",
        response_model=UserResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def register(credentials: AuthCredentials) -> UserResponse:
        with session_factory() as session:
            user = User(
                email=credentials.email.lower(),
                password_hash=hash_password(credentials.password),
                role="user",
            )
            session.add(user)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                raise HTTPException(
                    status_code=409, detail="Email already registered"
                ) from None
            session.refresh(user)
            return UserResponse.model_validate(user)

    def login_response(
        credentials: AuthCredentials, admin_only: bool, response
    ) -> UserResponse:
        with session_factory() as session:
            user = session.scalar(
                select(User).where(User.email == credentials.email.lower())
            )
            valid = user and verify_password(credentials.password, user.password_hash)
            if not valid or (admin_only and user.role != "admin"):
                raise HTTPException(status_code=401, detail="Invalid email or password")
            token = create_session_token(user, app_settings)
            response.set_cookie(
                app_settings.session_cookie_name,
                token,
                httponly=True,
                samesite="lax",
                secure=False,
                max_age=60 * 60 * 12,
            )
            return UserResponse.model_validate(user)

    @app.post("/api/auth/login", response_model=UserResponse)
    async def login(credentials: AuthCredentials, response: Response) -> UserResponse:
        return login_response(credentials, admin_only=False, response=response)

    @app.post("/api/admin/login", response_model=UserResponse)
    async def admin_login(
        credentials: AuthCredentials, response: Response
    ) -> UserResponse:
        return login_response(credentials, admin_only=True, response=response)

    @app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(response: Response) -> None:
        # Same endpoint for both AI-engineer and admin sessions — there's only ever one
        # session cookie, and clearing a cookie that's already absent is a harmless no-op.
        response.delete_cookie(app_settings.session_cookie_name)

    @app.get("/api/models", response_model=list[ModelResponse])
    async def list_models(
        q: str | None = Query(default=None),
        modality: str | None = Query(default=None),
        provider: str | None = Query(default=None),
    ) -> list[ModelResponse]:
        with session_factory() as session:
            statement = select(Model).order_by(Model.title)
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
    async def get_model(model_id: int) -> ModelResponse:
        with session_factory() as session:
            model = session.get(Model, model_id)
            if not model:
                raise HTTPException(status_code=404, detail="Model not found")
            return model_response(model)

    @app.get("/api/settings/demo-mode", response_model=DemoModeResponse)
    async def get_demo_mode() -> DemoModeResponse:
        # Public/unauthenticated on purpose — every AI-engineer session (including a judge's,
        # who never logs in as admin) needs to know whether to render the live tracking
        # overlay, not just the curator who flips the switch.
        with session_factory() as session:
            return DemoModeResponse.model_validate(get_or_create_demo_setting(session))

    @app.put("/api/admin/settings/demo-mode", response_model=DemoModeResponse)
    async def update_demo_mode(
        payload: DemoModeUpdate, _: User = Depends(current_admin)
    ) -> DemoModeResponse:
        with session_factory() as session:
            setting = get_or_create_demo_setting(session)
            setting.enabled = payload.enabled
            session.commit()
            session.refresh(setting)
            return DemoModeResponse.model_validate(setting)

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
    async def related_models(model_id: int, limit: int = 3) -> list[dict[str, object]]:
        """Content-based "you might also be interested in": queries the same Chroma vector
        store the recommendation pipeline uses, but keyed on *this model's own* embedding
        text (title/provider/modality/description/tags — see ModelVectorStore.document)
        rather than a user's activity summary. Grounded in real similarity, not activity —
        deliberately independent of the personalized recommendation on the Dashboard."""
        with session_factory() as session:
            model = session.get(Model, model_id)
            if not model:
                raise HTTPException(status_code=404, detail="Model not found")
            query_text = ModelVectorStore.document(model)
            # Prefer same-modality matches first — the deterministic hashed bag-of-words
            # embedding (app/vector.py) has weak semantics, so an unfiltered query can surface
            # a cross-modality "match" (e.g. an LLM as "similar to" an image model) purely on
            # shared generic words. Only fall back to an unfiltered query if same-modality
            # doesn't yield enough candidates (e.g. this modality has too few catalog entries).
            same_modality = vector_store.query_scored(
                query_text, limit=limit + 1, where={"modality": model.modality}
            )
            seen_ids = {model_id}
            results: list[dict[str, object]] = []

            def _add_candidates(scored: list[tuple[int, float]]) -> None:
                for candidate_id, distance in scored:
                    if len(results) >= limit or candidate_id in seen_ids:
                        continue
                    seen_ids.add(candidate_id)
                    candidate = session.get(Model, candidate_id)
                    if not candidate:
                        continue
                    results.append(
                        {
                            **model_response(candidate).model_dump(mode="json"),
                            "why_this": content_similarity_reason(distance, model.title),
                        }
                    )

            _add_candidates(same_modality)
            if len(results) < limit:
                _add_candidates(vector_store.query_scored(query_text, limit=limit + 1))
            return results

    @app.post(
        "/api/admin/models",
        response_model=ModelResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_model(
        payload: ModelCreate, _: User = Depends(current_admin)
    ) -> ModelResponse:
        with session_factory() as session:
            model = create_model_service(session, vector_store, payload)
            return model_response(model)

    @app.put("/api/admin/models/{model_id}", response_model=ModelResponse)
    async def update_model(
        model_id: int, payload: ModelCreate, _: User = Depends(current_admin)
    ) -> ModelResponse:
        with session_factory() as session:
            model = session.get(Model, model_id)
            if not model:
                raise HTTPException(status_code=404, detail="Model not found")
            update_model_service(session, vector_store, model, payload)
            return model_response(model)

    @app.delete("/api/admin/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_model(model_id: int, _: User = Depends(current_admin)) -> None:
        with session_factory() as session:
            model = session.get(Model, model_id)
            if not model:
                raise HTTPException(status_code=404, detail="Model not found")
            delete_model_service(session, vector_store, model)

    @app.post("/api/admin/digest/run")
    async def trigger_digest(_: User = Depends(current_admin)) -> dict[str, int]:
        """Manual override for demos only — the real delivery path is the cron job
        registered above via APScheduler (DLV-3)."""
        return run_digest(session_factory, vector_store, mesh_generator, notifier)

    async def _get_user_lock(user_id: int) -> asyncio.Lock:
        async with app.state.pipeline_locks_guard:
            lock = app.state.pipeline_locks.get(user_id)
            if lock is None:
                lock = asyncio.Lock()
                app.state.pipeline_locks[user_id] = lock
            return lock

    async def run_pipeline_in_background(user_id: int) -> None:
        """NFR-1: the pipeline's Mesh call is a real network round trip (hundreds of ms to
        seconds) — running it inline on `/api/events/batch` would blow the <150ms p95
        ingestion budget every time a trigger fires. It runs here, after the response is
        already sent, in its own session (the request's session is closed by then). The
        dashboard's polling (DLV-2) is what surfaces the result once this finishes.

        Guarded by a per-user asyncio.Lock: two near-simultaneous qualifying batches can
        each spawn this background task, each opening its own DB session; without the
        lock both could read "no recent recommendation yet" before either commits, and
        both would proceed to write a duplicate Recommendation row."""
        lock = await _get_user_lock(user_id)
        async with lock:
            with session_factory() as session:
                prepare_retrieval_recommendation(
                    session, vector_store, user_id, app.state.mesh_generator
                )

    @app.post("/api/events/batch")
    async def ingest_events(
        batch: EventBatch,
        background_tasks: BackgroundTasks,
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        with session_factory() as session:
            events = [
                Event(
                    user_id=user.id,
                    event_type=event.event_type,
                    model_id=event.model_id,
                    metadata_json=event.metadata,
                )
                for event in batch.events
            ]
            session.add_all(events)
            session.commit()
            triggered = should_trigger(session, user.id)
        if triggered:
            background_tasks.add_task(run_pipeline_in_background, user.id)
        return {
            "accepted": len(events),
            "recommendation_triggered": triggered,
        }

    @app.get("/api/recommendations/me")
    async def latest_recommendation(
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        with session_factory() as session:
            latest = session.scalar(
                select(Recommendation)
                .where(Recommendation.user_id == user.id)
                .order_by(Recommendation.created_at.desc())
            )
            current_events = recent_events(session, user.id)
            evidence = session_evidence(session, current_events)
            evidence_payload = [
                {
                    "label": item["label"],
                    "action": item["action"],
                    "created_at": as_utc(item["created_at"]),
                }
                for item in evidence
            ]

            if latest:
                models = session.scalars(
                    select(Model).where(Model.id.in_(latest.model_ids))
                ).all()
                models_by_id = {model.id: model for model in models}
                reason_by_id = {
                    entry["model_id"]: entry["reason"]
                    for entry in latest.retrieval_meta or []
                }
                return {
                    "id": latest.id,
                    "status": "ready" if latest.narrative else "retrieval_ready",
                    "narrative": latest.narrative,
                    "models": [
                        {
                            **model_response(models_by_id[model_id]).model_dump(mode="json"),
                            "why_this": reason_by_id.get(model_id),
                        }
                        for model_id in latest.model_ids
                        if model_id in models_by_id
                    ],
                    "behavior_summary": latest.behavior_summary,
                    "activity_hash": latest.activity_hash,
                    "trigger_reason": latest.trigger_reason,
                    "created_at": as_utc(latest.created_at),
                    "evidence": evidence_payload,
                }
            if not current_events:
                return {"status": "pending", "narrative": None, "models": [], "evidence": []}

            summary = activity_summary(session, current_events)
            scored = app.state.vector_store.query_scored(summary)
            if not scored:
                return {
                    "status": "pending",
                    "narrative": None,
                    "models": [],
                    "trigger_reason": "no_retrieval_candidates",
                    "evidence": evidence_payload,
                }
            candidate_ids = [model_id for model_id, _ in scored]
            models_by_id = {
                model.id: model
                for model in session.scalars(
                    select(Model).where(Model.id.in_(candidate_ids))
                ).all()
            }
            candidates = [
                {
                    **model_response(models_by_id[model_id]).model_dump(mode="json"),
                    "why_this": contextual_reason(models_by_id[model_id], distance, False, evidence),
                }
                for model_id, distance in scored
                if model_id in models_by_id
            ]
            return {
                "status": "retrieval_ready",
                "narrative": None,
                "models": candidates,
                "trigger_reason": "activity_retrieval",
                "evidence": evidence_payload,
            }

    @app.get("/api/activity/me")
    async def activity(user: User = Depends(current_user)) -> dict[str, object]:
        with session_factory() as session:
            events = session.scalars(
                select(Event)
                .where(Event.user_id == user.id)
                # created_at is second-resolution (SQLite CURRENT_TIMESTAMP), so a batch flush
                # that inserts several events in one commit can tie on it — id.desc() breaks
                # the tie by actual insertion order instead of leaving it DB-arbitrary.
                .order_by(Event.created_at.desc(), Event.id.desc())
                .limit(50)
            ).all()
            latest = session.scalar(
                select(Recommendation)
                .where(Recommendation.user_id == user.id)
                .order_by(Recommendation.created_at.desc())
            )
            return {
                "events": [
                    {
                        "type": event.event_type,
                        "model_id": event.model_id,
                        "metadata": event.metadata_json,
                        "created_at": as_utc(event.created_at),
                    }
                    for event in events
                ],
                "pipeline": {
                    "behavior_summary": latest.behavior_summary,
                    "activity_hash": latest.activity_hash,
                    "trigger_reason": latest.trigger_reason,
                    "created_at": as_utc(latest.created_at),
                }
                if latest
                else None,
            }

    return app


app = create_app()
