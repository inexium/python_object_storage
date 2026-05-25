from datetime import datetime, timezone
from sqlmodel import Field, SQLModel


class Bucket(SQLModel, table=True):
    name: str = Field(primary_key=True)
    creation_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
