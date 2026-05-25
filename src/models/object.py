from datetime import datetime, timezone
from sqlmodel import Field, SQLModel


class Object(SQLModel, table=True):
    __tablename__ = "object"

    id: int | None = Field(default=None, primary_key=True)
    bucket: str = Field(index=True)
    key: str = Field(index=True)
    size: int
    etag: str
    content_type: str = Field(default="application/octet-stream")
    last_modified: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_metadata: str = Field(default="{}")  # JSON-serialized x-amz-meta-* headers
