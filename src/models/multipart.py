from datetime import datetime, timezone
from sqlmodel import Field, SQLModel


class MultipartUpload(SQLModel, table=True):
    __tablename__ = "multipart_upload"

    upload_id: str = Field(primary_key=True)
    bucket: str = Field(index=True)
    key: str
    content_type: str = Field(default="application/octet-stream")
    initiated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Part(SQLModel, table=True):
    __tablename__ = "part"

    id: int | None = Field(default=None, primary_key=True)
    upload_id: str = Field(index=True)
    part_number: int
    etag: str
    size: int
    last_modified: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
