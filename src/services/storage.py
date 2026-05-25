from pathlib import Path

import zstandard as zstd

from src.config import settings


class StorageService:
    def __init__(self, base_path: Path | None = None) -> None:
        self._base = Path(base_path) if base_path is not None else settings.storage_path
        self._cctx = zstd.ZstdCompressor(level=settings.zstd_level)
        self._dctx = zstd.ZstdDecompressor()

    # ------------------------------------------------------------------
    # Chemins
    # ------------------------------------------------------------------

    def _object_path(self, bucket: str, key: str) -> Path:
        # Normalise la clé pour éviter les path traversal
        safe_key = Path(key.lstrip("/"))
        return self._base / bucket / safe_key

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def write(self, bucket: str, key: str, data: bytes) -> None:
        path = self._object_path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._cctx.compress(data))

    def read(self, bucket: str, key: str) -> bytes:
        path = self._object_path(bucket, key)
        if not path.is_file():
            raise FileNotFoundError(f"{bucket}/{key}")
        return self._dctx.decompress(path.read_bytes())

    def delete(self, bucket: str, key: str) -> None:
        path = self._object_path(bucket, key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def exists(self, bucket: str, key: str) -> bool:
        return self._object_path(bucket, key).is_file()

    def get_size(self, bucket: str, key: str) -> int:
        """Retourne la taille des données originales (avant compression)."""
        return len(self.read(bucket, key))

    def list(self, bucket: str, prefix: str = "") -> list[str]:
        bucket_dir = self._base / bucket
        if not bucket_dir.is_dir():
            return []
        keys = []
        for path in bucket_dir.rglob("*"):
            if not path.is_file():
                continue
            key = path.relative_to(bucket_dir).as_posix()
            if key.startswith(prefix):
                keys.append(key)
        return sorted(keys)
