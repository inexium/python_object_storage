"""Tests unitaires — src.services.storage.StorageService."""

import os

import pytest

from tests.helpers import md5_hex

pytestmark = pytest.mark.unit


@pytest.fixture
def storage(tmp_path):
    from src.services.storage import StorageService
    return StorageService(base_path=tmp_path)


class TestWrite:
    def test_write_creates_file(self, storage, tmp_path):
        storage.write("bucket", "key.txt", b"hello")
        # Au moins un fichier doit exister sous tmp_path
        files = list(tmp_path.rglob("*"))
        assert any(f.is_file() for f in files)

    def test_write_then_read_roundtrip(self, storage):
        data = b"roundtrip content"
        storage.write("bucket", "rt.txt", data)
        assert storage.read("bucket", "rt.txt") == data

    def test_write_empty_bytes(self, storage):
        storage.write("bucket", "empty.txt", b"")
        assert storage.read("bucket", "empty.txt") == b""

    def test_write_overwrites_existing(self, storage):
        storage.write("bucket", "over.txt", b"v1")
        storage.write("bucket", "over.txt", b"v2")
        assert storage.read("bucket", "over.txt") == b"v2"

    def test_write_large_data_roundtrip(self, storage):
        data = os.urandom(10 * 1024 * 1024)  # 10 MB aléatoire
        storage.write("bucket", "large.bin", data)
        assert storage.read("bucket", "large.bin") == data

    def test_write_nested_key(self, storage):
        data = b"nested"
        storage.write("bucket", "a/b/c/deep.txt", data)
        assert storage.read("bucket", "a/b/c/deep.txt") == data

    def test_compression_is_transparent(self, storage, tmp_path):
        data = b"compress me " * 1000  # données compressibles
        storage.write("bucket", "compressed.txt", data)
        assert storage.read("bucket", "compressed.txt") == data


class TestRead:
    def test_read_nonexistent_key_raises(self, storage):
        with pytest.raises(FileNotFoundError):
            storage.read("bucket", "no-such-key.txt")

    def test_read_binary_data(self, storage):
        data = bytes(range(256))
        storage.write("bucket", "binary.bin", data)
        assert storage.read("bucket", "binary.bin") == data


class TestDelete:
    def test_delete_removes_object(self, storage):
        storage.write("bucket", "to-del.txt", b"bye")
        storage.delete("bucket", "to-del.txt")
        with pytest.raises(FileNotFoundError):
            storage.read("bucket", "to-del.txt")

    def test_delete_nonexistent_is_silent(self, storage):
        # Pas d'exception pour une clé qui n'existe pas
        storage.delete("bucket", "does-not-exist.txt")

    def test_delete_specific_key_leaves_others(self, storage):
        storage.write("bucket", "keep.txt", b"keep")
        storage.write("bucket", "delete.txt", b"delete")
        storage.delete("bucket", "delete.txt")
        assert storage.read("bucket", "keep.txt") == b"keep"


class TestExists:
    def test_returns_true_for_existing(self, storage):
        storage.write("bucket", "exists.txt", b"yes")
        assert storage.exists("bucket", "exists.txt") is True

    def test_returns_false_for_missing(self, storage):
        assert storage.exists("bucket", "missing.txt") is False

    def test_returns_false_after_delete(self, storage):
        storage.write("bucket", "ex-del.txt", b"gone")
        storage.delete("bucket", "ex-del.txt")
        assert storage.exists("bucket", "ex-del.txt") is False


class TestGetSize:
    def test_size_matches_original_not_compressed(self, storage):
        data = b"size check " * 100
        storage.write("bucket", "sized.txt", data)
        assert storage.get_size("bucket", "sized.txt") == len(data)

    def test_size_of_empty_object(self, storage):
        storage.write("bucket", "zero.txt", b"")
        assert storage.get_size("bucket", "zero.txt") == 0

    def test_size_nonexistent_raises(self, storage):
        with pytest.raises(FileNotFoundError):
            storage.get_size("bucket", "no-key.txt")


class TestList:
    def test_list_empty_bucket(self, storage):
        result = storage.list("empty-bucket")
        assert result == []

    def test_list_returns_written_keys(self, storage):
        storage.write("lb", "a.txt", b"a")
        storage.write("lb", "b.txt", b"b")
        keys = storage.list("lb")
        assert "a.txt" in keys
        assert "b.txt" in keys

    def test_list_with_prefix(self, storage):
        storage.write("pfx", "img/cat.jpg", b"cat")
        storage.write("pfx", "img/dog.jpg", b"dog")
        storage.write("pfx", "doc/readme.txt", b"readme")
        keys = storage.list("pfx", prefix="img/")
        assert all(k.startswith("img/") for k in keys)
        assert "doc/readme.txt" not in keys

    def test_list_reflects_deletes(self, storage):
        storage.write("del-list", "stay.txt", b"keep")
        storage.write("del-list", "gone.txt", b"bye")
        storage.delete("del-list", "gone.txt")
        keys = storage.list("del-list")
        assert "stay.txt" in keys
        assert "gone.txt" not in keys
