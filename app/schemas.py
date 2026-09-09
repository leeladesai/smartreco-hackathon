from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class AuthCredentials(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8)


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    telegram_chat_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AdminUserResponse(UserResponse):
    created_at: datetime


class ModelCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    story: str | None = Field(default=None)
    provider: str = Field(min_length=1, max_length=120)
    modality: str = Field(min_length=1, max_length=40)
    price: str = Field(min_length=1, max_length=120)
    latency_ms: int | None = Field(default=None, ge=0)
    context_window: str | None = Field(default=None, max_length=120)
    use_case_tags: list[str] = Field(default_factory=list)
    source_url: HttpUrl | None = None

    model_config = ConfigDict(protected_namespaces=())


class ModelResponse(ModelCreate):
    id: int
    vector_synced: bool
    ingestion_adapter: str
    review_status: str
    last_synced_at: datetime | None = None
    sync_stale: bool
    ingestion_meta: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BulkImportRowResult(BaseModel):
    row: int
    title: str | None = None
    status: str
    errors: list[str] = Field(default_factory=list)


class BulkImportResponse(BaseModel):
    inserted: int
    skipped_duplicate: int
    invalid: int
    rows: list[BulkImportRowResult]


class FeedConfigRequest(BaseModel):
    feed_url: HttpUrl
    auth_token: str | None = Field(default=None, max_length=500)


class FeedSyncResponse(BaseModel):
    inserted: int
    skipped_duplicate: int
    invalid: int
    rows: list[BulkImportRowResult]


class ScrapePreviewRequest(BaseModel):
    url: HttpUrl
    selectors: dict[str, str] = Field(default_factory=dict)


class ScrapePreviewResponse(BaseModel):
    markup_type: str
    rows: list[dict]


class ScrapeConfirmRequest(BaseModel):
    url: HttpUrl
    markup_type: str
    rows: list[dict] = Field(min_length=1, max_length=100)


class ScrapeConfirmRowResult(BaseModel):
    row: int
    title: str | None = None
    status: str
    errors: list[str] = Field(default_factory=list)
    model_id: int | None = None


class ScrapeConfirmResponse(BaseModel):
    rows: list[ScrapeConfirmRowResult]


class IngestionAdapterStatus(BaseModel):
    count: int
    last_synced_at: datetime | None = None
    sync_stale: bool
    pending_review: int


class IngestionStatusResponse(BaseModel):
    feed: IngestionAdapterStatus
    scrape: IngestionAdapterStatus


class TrackEventInput(BaseModel):
    event_type: str = Field(
        pattern="^(page_view|model_view|search|click|model_compare|dwell|catalog_filter"
        "|model_copy|model_watchlist|recommendation_feedback)$"
    )
    model_id: int | None = None
    metadata: dict = Field(default_factory=dict)

    model_config = ConfigDict(protected_namespaces=())


class TrackEventBatch(BaseModel):
    # The tenant key travels in the body, not a header — navigator.sendBeacon (used
    # for the on-unload flush, app/static/js/tracker.js) can't set custom headers, so
    # a header-only scheme would silently lose every beacon-flushed batch.
    tenant_key: str = Field(min_length=1)
    visitor_id: str = Field(min_length=1, max_length=64)
    events: list[TrackEventInput] = Field(min_length=1, max_length=100)
