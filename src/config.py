import os
from pathlib import Path


class Settings:
    storage_path: Path
    db_path: Path
    host: str
    port: int
    log_level: str
    zstd_level: int

    def __init__(self) -> None:
        self.storage_path = Path(os.environ.get("STORAGE_PATH", "./data/objects"))
        self.db_path = Path(os.environ.get("DB_PATH", "./data/metadata.db"))
        self.host = os.environ.get("HOST", "0.0.0.0")
        self.port = int(os.environ.get("PORT", "9000"))
        self.log_level = os.environ.get("LOG_LEVEL", "info")
        self.zstd_level = int(os.environ.get("ZSTD_LEVEL", "3"))


settings = Settings()
