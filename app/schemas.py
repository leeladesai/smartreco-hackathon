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
