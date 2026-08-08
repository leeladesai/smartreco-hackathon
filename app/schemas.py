from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class AuthCredentials(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8)


class UserResponse(BaseModel):
    id: int
    email: str
    role: str

    model_config = ConfigDict(from_attributes=True)


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
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EventInput(BaseModel):
    event_type: str = Field(
        pattern="^(page_view|model_view|search|click|model_compare|dwell|catalog_filter|model_copy|model_watchlist)$"
    )
    model_id: int | None = None
    metadata: dict = Field(default_factory=dict)

    model_config = ConfigDict(protected_namespaces=())


class EventBatch(BaseModel):
    events: list[EventInput] = Field(min_length=1, max_length=100)


class DemoModeResponse(BaseModel):
    enabled: bool

    model_config = ConfigDict(from_attributes=True)


class DemoModeUpdate(BaseModel):
    enabled: bool
