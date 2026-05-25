from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from src.config import settings

# Import models so their tables are registered in SQLModel.metadata before create_all
from src.models.bucket import Bucket  # noqa: F401
from src.models.multipart import MultipartUpload, Part  # noqa: F401
from src.models.object import Object  # noqa: F401

_engine: object = None


def get_engine():
    global _engine
    if _engine is None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{settings.db_path}", echo=False)
    return _engine


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
