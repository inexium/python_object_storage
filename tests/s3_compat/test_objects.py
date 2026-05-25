"""Tests de compatibilité S3 — opérations sur les objets."""

import hashlib

import pytest
from starlette.testclient import TestClient

from tests.helpers import (
    build_delete_xml,
    expected_etag,
    md5_b64,
    md5_hex,
    parse_error,
    parse_xml,
)

pytestmark = pytest.mark.s3_compat

S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


# ---------------------------------------------------------------------------
# PutObject — PUT /{bucket}/{key}
# ---------------------------------------------------------------------------

class TestPutObject:
    def test_returns_200(self, client: TestClient, bucket: str):
        r = client.put(f"/{bucket}/hello.txt", content=b"hello")
        assert r.status_code == 200

    def test_returns_etag_header(self, client: TestClient, bucket: str):
        data = b"hello world"
        r = client.put(f"/{bucket}/etag.txt", content=data)
        assert r.status_code == 200
        etag = r.headers.get("etag")
        assert etag == expected_etag(data)

    def test_content_type_stored(self, client: TestClient, bucket: str):
        r = client.put(
            f"/{bucket}/image.png",
            content=b"\x89PNG",
            headers={"Content-Type": "image/png"},
        )
        assert r.status_code == 200
        head = client.head(f"/{bucket}/image.png")
        assert head.headers.get("content-type") == "image/png"

    def test_user_metadata_stored(self, client: TestClient, bucket: str):
        r = client.put(
            f"/{bucket}/meta.txt",
            content=b"data",
            headers={"x-amz-meta-author": "alice", "x-amz-meta-project": "test"},
        )
        assert r.status_code == 200
        head = client.head(f"/{bucket}/meta.txt")
        assert head.headers.get("x-amz-meta-author") == "alice"
        assert head.headers.get("x-amz-meta-project") == "test"

    def test_overwrite_existing_object(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/overwrite.txt", content=b"v1")
        r = client.put(f"/{bucket}/overwrite.txt", content=b"v2")
        assert r.status_code == 200
        get = client.get(f"/{bucket}/overwrite.txt")
        assert get.content == b"v2"

    def test_empty_object(self, client: TestClient, bucket: str):
        r = client.put(f"/{bucket}/empty.txt", content=b"")
        assert r.status_code == 200
        get = client.get(f"/{bucket}/empty.txt")
        assert get.content == b""

    def test_nested_key_path(self, client: TestClient, bucket: str):
        r = client.put(f"/{bucket}/a/b/c/deep.txt", content=b"deep")
        assert r.status_code == 200
        get = client.get(f"/{bucket}/a/b/c/deep.txt")
        assert get.content == b"deep"

    def test_key_with_spaces_encoded(self, client: TestClient, bucket: str):
        r = client.put(f"/{bucket}/my%20file.txt", content=b"space")
        assert r.status_code == 200

    def test_large_object(self, client: TestClient, bucket: str):
        data = b"x" * (10 * 1024 * 1024)  # 10 MB
        r = client.put(f"/{bucket}/large.bin", content=data)
        assert r.status_code == 200
        get = client.get(f"/{bucket}/large.bin")
        assert get.content == data

    def test_content_md5_valid(self, client: TestClient, bucket: str):
        data = b"check integrity"
        r = client.put(
            f"/{bucket}/md5check.txt",
            content=data,
            headers={"Content-MD5": md5_b64(data)},
        )
        assert r.status_code == 200

    def test_content_md5_invalid_returns_400(self, client: TestClient, bucket: str):
        r = client.put(
            f"/{bucket}/md5bad.txt",
            content=b"some data",
            headers={"Content-MD5": "AAAAAAAAAAAAAAAAAAAAAA=="},
        )
        assert r.status_code == 400
        err = parse_error(r.text)
        assert err["code"] == "InvalidDigest"

    def test_nonexistent_bucket_returns_404(self, client: TestClient):
        r = client.put("/bucket-that-does-not-exist-zzz/key.txt", content=b"data")
        assert r.status_code == 404
        err = parse_error(r.text)
        assert err["code"] == "NoSuchBucket"


# ---------------------------------------------------------------------------
# GetObject — GET /{bucket}/{key}
# ---------------------------------------------------------------------------

class TestGetObject:
    def test_returns_content(self, client: TestClient, bucket: str):
        data = b"hello world"
        client.put(f"/{bucket}/get.txt", content=data)
        r = client.get(f"/{bucket}/get.txt")
        assert r.status_code == 200
        assert r.content == data

    def test_returns_etag_header(self, client: TestClient, bucket: str):
        data = b"etag check"
        client.put(f"/{bucket}/etag-get.txt", content=data)
        r = client.get(f"/{bucket}/etag-get.txt")
        assert r.headers.get("etag") == expected_etag(data)

    def test_returns_content_length(self, client: TestClient, bucket: str):
        data = b"measure me"
        client.put(f"/{bucket}/length.txt", content=data)
        r = client.get(f"/{bucket}/length.txt")
        assert int(r.headers.get("content-length", 0)) == len(data)

    def test_returns_content_type(self, client: TestClient, bucket: str):
        client.put(
            f"/{bucket}/typed.json",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
        r = client.get(f"/{bucket}/typed.json")
        assert "application/json" in r.headers.get("content-type", "")

    def test_returns_last_modified(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/dated-get.txt", content=b"x")
        r = client.get(f"/{bucket}/dated-get.txt")
        assert r.headers.get("last-modified") is not None

    def test_nonexistent_key_returns_404(self, client: TestClient, bucket: str):
        r = client.get(f"/{bucket}/does-not-exist.txt")
        assert r.status_code == 404
        err = parse_error(r.text)
        assert err["code"] == "NoSuchKey"

    def test_nonexistent_bucket_returns_404(self, client: TestClient):
        r = client.get("/bucket-that-does-not-exist-zzz/key.txt")
        assert r.status_code == 404

    def test_range_request_partial(self, client: TestClient, bucket: str):
        data = b"0123456789"
        client.put(f"/{bucket}/range.txt", content=data)
        r = client.get(f"/{bucket}/range.txt", headers={"Range": "bytes=2-5"})
        assert r.status_code == 206
        assert r.content == data[2:6]
        assert "content-range" in r.headers

    def test_range_request_from_offset(self, client: TestClient, bucket: str):
        data = b"abcdefghij"
        client.put(f"/{bucket}/range2.txt", content=data)
        r = client.get(f"/{bucket}/range2.txt", headers={"Range": "bytes=5-"})
        assert r.status_code == 206
        assert r.content == data[5:]

    def test_range_suffix(self, client: TestClient, bucket: str):
        data = b"abcdefghij"
        client.put(f"/{bucket}/range3.txt", content=data)
        r = client.get(f"/{bucket}/range3.txt", headers={"Range": "bytes=-3"})
        assert r.status_code == 206
        assert r.content == data[-3:]

    def test_range_beyond_size_returns_416(self, client: TestClient, bucket: str):
        data = b"short"
        client.put(f"/{bucket}/range-bad.txt", content=data)
        r = client.get(f"/{bucket}/range-bad.txt", headers={"Range": "bytes=100-200"})
        assert r.status_code == 416

    def test_user_metadata_returned(self, client: TestClient, bucket: str):
        client.put(
            f"/{bucket}/meta-get.txt",
            content=b"data",
            headers={"x-amz-meta-tag": "value"},
        )
        r = client.get(f"/{bucket}/meta-get.txt")
        assert r.headers.get("x-amz-meta-tag") == "value"


# ---------------------------------------------------------------------------
# HeadObject — HEAD /{bucket}/{key}
# ---------------------------------------------------------------------------

class TestHeadObject:
    def test_existing_object_returns_200(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/head.txt", content=b"head test")
        r = client.head(f"/{bucket}/head.txt")
        assert r.status_code == 200

    def test_has_no_body(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/headbody.txt", content=b"test")
        r = client.head(f"/{bucket}/headbody.txt")
        assert r.content == b""

    def test_headers_match_get(self, client: TestClient, bucket: str):
        data = b"compare headers"
        client.put(f"/{bucket}/compare.txt", content=data)
        head = client.head(f"/{bucket}/compare.txt")
        get = client.get(f"/{bucket}/compare.txt")
        assert head.headers.get("etag") == get.headers.get("etag")
        assert head.headers.get("content-length") == get.headers.get("content-length")
        assert head.headers.get("content-type") == get.headers.get("content-type")

    def test_nonexistent_key_returns_404(self, client: TestClient, bucket: str):
        r = client.head(f"/{bucket}/no-such-key.txt")
        assert r.status_code == 404

    def test_nonexistent_bucket_returns_404(self, client: TestClient):
        r = client.head("/bucket-that-does-not-exist-zzz/key.txt")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DeleteObject — DELETE /{bucket}/{key}
# ---------------------------------------------------------------------------

class TestDeleteObject:
    def test_deletes_existing_object(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/to-delete.txt", content=b"bye")
        r = client.delete(f"/{bucket}/to-delete.txt")
        assert r.status_code == 204

    def test_deleted_object_is_gone(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/gone.txt", content=b"soon gone")
        client.delete(f"/{bucket}/gone.txt")
        r = client.get(f"/{bucket}/gone.txt")
        assert r.status_code == 404

    def test_nonexistent_key_still_returns_204(self, client: TestClient, bucket: str):
        # S3 idempotent delete — 204 même si l'objet n'existe pas
        r = client.delete(f"/{bucket}/never-existed.txt")
        assert r.status_code == 204

    def test_nonexistent_bucket_returns_404(self, client: TestClient):
        r = client.delete("/bucket-that-does-not-exist-zzz/key.txt")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DeleteObjects (batch) — POST /{bucket}?delete
# ---------------------------------------------------------------------------

class TestDeleteObjects:
    def test_deletes_multiple_objects(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/del-a.txt", content=b"a")
        client.put(f"/{bucket}/del-b.txt", content=b"b")
        body = build_delete_xml("del-a.txt", "del-b.txt")
        r = client.post(
            f"/{bucket}?delete",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        assert r.status_code == 200
        root = parse_xml(r.text)
        assert root.tag.endswith("DeleteResult")
        deleted_keys = [el.text for el in root.findall("s3:Deleted/s3:Key", S3_NS)]
        assert "del-a.txt" in deleted_keys
        assert "del-b.txt" in deleted_keys

    def test_deleted_objects_are_gone(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/batch-a.txt", content=b"a")
        client.put(f"/{bucket}/batch-b.txt", content=b"b")
        body = build_delete_xml("batch-a.txt", "batch-b.txt")
        client.post(f"/{bucket}?delete", content=body, headers={"Content-Type": "application/xml"})
        assert client.get(f"/{bucket}/batch-a.txt").status_code == 404
        assert client.get(f"/{bucket}/batch-b.txt").status_code == 404

    def test_nonexistent_keys_reported_as_deleted(self, client: TestClient, bucket: str):
        # S3 considère les clés inexistantes comme supprimées (succès silencieux)
        body = build_delete_xml("does-not-exist-1.txt", "does-not-exist-2.txt")
        r = client.post(
            f"/{bucket}?delete",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        assert r.status_code == 200

    def test_quiet_mode_suppresses_deleted_list(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/quiet-obj.txt", content=b"q")
        body = b"<Delete><Quiet>true</Quiet><Object><Key>quiet-obj.txt</Key></Object></Delete>"
        r = client.post(
            f"/{bucket}?delete",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        assert r.status_code == 200
        root = parse_xml(r.text)
        # En mode Quiet, les succès ne sont pas listés
        assert len(root.findall("s3:Deleted", S3_NS)) == 0


# ---------------------------------------------------------------------------
# CopyObject — PUT /{bucket}/{key} avec x-amz-copy-source
# ---------------------------------------------------------------------------

class TestCopyObject:
    def test_copies_object(self, client: TestClient, bucket: str):
        data = b"source content"
        client.put(f"/{bucket}/source.txt", content=data)
        r = client.put(
            f"/{bucket}/dest.txt",
            headers={"x-amz-copy-source": f"/{bucket}/source.txt"},
        )
        assert r.status_code == 200

    def test_copy_result_xml(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/copy-src.txt", content=b"copy me")
        r = client.put(
            f"/{bucket}/copy-dst.txt",
            headers={"x-amz-copy-source": f"/{bucket}/copy-src.txt"},
        )
        root = parse_xml(r.text)
        assert root.tag.endswith("CopyObjectResult")
        assert root.find("s3:ETag", S3_NS) is not None or root.findtext("ETag") is not None

    def test_copied_content_matches(self, client: TestClient, bucket: str):
        data = b"copy check"
        client.put(f"/{bucket}/cp-src.txt", content=data)
        client.put(
            f"/{bucket}/cp-dst.txt",
            headers={"x-amz-copy-source": f"/{bucket}/cp-src.txt"},
        )
        r = client.get(f"/{bucket}/cp-dst.txt")
        assert r.content == data

    def test_source_not_found_returns_404(self, client: TestClient, bucket: str):
        r = client.put(
            f"/{bucket}/dst.txt",
            headers={"x-amz-copy-source": f"/{bucket}/no-such-source.txt"},
        )
        assert r.status_code == 404

    def test_cross_bucket_copy(self, client: TestClient, bucket: str):
        import uuid
        other = f"test-{uuid.uuid4().hex[:8]}"
        client.put(f"/{other}")
        client.put(f"/{other}/item.txt", content=b"cross bucket")
        r = client.put(
            f"/{bucket}/from-other.txt",
            headers={"x-amz-copy-source": f"/{other}/item.txt"},
        )
        assert r.status_code == 200
        assert client.get(f"/{bucket}/from-other.txt").content == b"cross bucket"
        client.delete(f"/{other}/item.txt")
        client.delete(f"/{other}")

    def test_copy_with_metadata_replace(self, client: TestClient, bucket: str):
        client.put(
            f"/{bucket}/meta-src.txt",
            content=b"data",
            headers={"x-amz-meta-original": "yes"},
        )
        r = client.put(
            f"/{bucket}/meta-dst.txt",
            headers={
                "x-amz-copy-source": f"/{bucket}/meta-src.txt",
                "x-amz-metadata-directive": "REPLACE",
                "x-amz-meta-new": "metadata",
            },
        )
        assert r.status_code == 200
        head = client.head(f"/{bucket}/meta-dst.txt")
        assert head.headers.get("x-amz-meta-new") == "metadata"
