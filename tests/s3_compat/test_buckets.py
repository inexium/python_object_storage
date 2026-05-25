"""Tests de compatibilité S3 — opérations sur les buckets."""

import uuid

import pytest
from starlette.testclient import TestClient

from tests.helpers import parse_error, parse_xml, s3find, s3findall, s3text

pytestmark = pytest.mark.s3_compat

S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


# ---------------------------------------------------------------------------
# CreateBucket — PUT /{bucket}
# ---------------------------------------------------------------------------

class TestCreateBucket:
    def test_ok(self, client: TestClient):
        name = f"test-{uuid.uuid4().hex[:8]}"
        r = client.put(f"/{name}")
        assert r.status_code == 200
        client.delete(f"/{name}")

    def test_location_header(self, client: TestClient):
        name = f"test-{uuid.uuid4().hex[:8]}"
        r = client.put(f"/{name}")
        assert r.headers.get("location") == f"/{name}"
        client.delete(f"/{name}")

    def test_duplicate_returns_409(self, client: TestClient):
        name = f"test-{uuid.uuid4().hex[:8]}"
        client.put(f"/{name}")
        r = client.put(f"/{name}")
        assert r.status_code == 409
        err = parse_error(r.text)
        assert err["code"] in ("BucketAlreadyExists", "BucketAlreadyOwnedByYou")
        client.delete(f"/{name}")

    def test_name_too_short_returns_400(self, client: TestClient):
        r = client.put("/ab")
        assert r.status_code == 400
        err = parse_error(r.text)
        assert err["code"] == "InvalidBucketName"

    def test_name_too_long_returns_400(self, client: TestClient):
        r = client.put(f"/{'a' * 64}")
        assert r.status_code == 400
        err = parse_error(r.text)
        assert err["code"] == "InvalidBucketName"

    def test_uppercase_returns_400(self, client: TestClient):
        r = client.put("/MyBucket")
        assert r.status_code == 400

    def test_underscore_returns_400(self, client: TestClient):
        r = client.put("/my_bucket")
        assert r.status_code == 400

    def test_starts_with_hyphen_returns_400(self, client: TestClient):
        r = client.put("/-bad-name")
        assert r.status_code == 400

    def test_ends_with_hyphen_returns_400(self, client: TestClient):
        r = client.put("/bad-name-")
        assert r.status_code == 400

    def test_ip_address_name_returns_400(self, client: TestClient):
        r = client.put("/192.168.1.1")
        assert r.status_code == 400

    def test_valid_hyphenated_name(self, client: TestClient):
        name = "my-valid-bucket-name"
        r = client.put(f"/{name}")
        assert r.status_code == 200
        client.delete(f"/{name}")

    def test_valid_numeric_name(self, client: TestClient):
        name = f"bucket-{uuid.uuid4().hex[:6]}-123"
        r = client.put(f"/{name}")
        assert r.status_code == 200
        client.delete(f"/{name}")


# ---------------------------------------------------------------------------
# ListBuckets — GET /
# ---------------------------------------------------------------------------

class TestListBuckets:
    def test_returns_200_xml(self, client: TestClient):
        r = client.get("/")
        assert r.status_code == 200
        assert "application/xml" in r.headers.get("content-type", "")

    def test_root_element(self, client: TestClient):
        r = client.get("/")
        root = parse_xml(r.text)
        assert root.tag.endswith("ListAllMyBucketsResult")

    def test_contains_owner_element(self, client: TestClient):
        r = client.get("/")
        root = parse_xml(r.text)
        assert s3find(root, "Owner") is not None

    def test_lists_existing_bucket(self, client: TestClient, bucket: str):
        r = client.get("/")
        root = parse_xml(r.text)
        names = [el.text for el in root.findall("s3:Buckets/s3:Bucket/s3:Name", S3_NS)]
        assert bucket in names

    def test_bucket_has_creation_date(self, client: TestClient, bucket: str):
        r = client.get("/")
        root = parse_xml(r.text)
        buckets = root.findall("s3:Buckets/s3:Bucket", S3_NS)
        ours = next((b for b in buckets if b.findtext("s3:Name", namespaces=S3_NS) == bucket), None)
        assert ours is not None
        assert ours.find("s3:CreationDate", S3_NS) is not None


# ---------------------------------------------------------------------------
# HeadBucket — HEAD /{bucket}
# ---------------------------------------------------------------------------

class TestHeadBucket:
    def test_existing_bucket_returns_200(self, client: TestClient, bucket: str):
        r = client.head(f"/{bucket}")
        assert r.status_code == 200

    def test_nonexistent_bucket_returns_404(self, client: TestClient):
        r = client.head("/bucket-that-does-not-exist-zzz")
        assert r.status_code == 404

    def test_head_has_no_body(self, client: TestClient, bucket: str):
        r = client.head(f"/{bucket}")
        assert r.content == b""


# ---------------------------------------------------------------------------
# DeleteBucket — DELETE /{bucket}
# ---------------------------------------------------------------------------

class TestDeleteBucket:
    def test_deletes_empty_bucket(self, client: TestClient):
        name = f"test-{uuid.uuid4().hex[:8]}"
        client.put(f"/{name}")
        r = client.delete(f"/{name}")
        assert r.status_code == 204

    def test_nonexistent_bucket_returns_404(self, client: TestClient):
        r = client.delete("/bucket-that-does-not-exist-zzz")
        assert r.status_code == 404
        err = parse_error(r.text)
        assert err["code"] == "NoSuchBucket"

    def test_nonempty_bucket_returns_409(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/some-object.txt", content=b"data")
        r = client.delete(f"/{bucket}")
        assert r.status_code == 409
        err = parse_error(r.text)
        assert err["code"] == "BucketNotEmpty"
        client.delete(f"/{bucket}/some-object.txt")

    def test_deleted_bucket_is_gone(self, client: TestClient):
        name = f"test-{uuid.uuid4().hex[:8]}"
        client.put(f"/{name}")
        client.delete(f"/{name}")
        r = client.head(f"/{name}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# ListObjectsV2 — GET /{bucket}?list-type=2
# ---------------------------------------------------------------------------

class TestListObjectsV2:
    def test_empty_bucket(self, client: TestClient, bucket: str):
        r = client.get(f"/{bucket}?list-type=2")
        assert r.status_code == 200
        root = parse_xml(r.text)
        assert root.tag.endswith("ListBucketResult")
        contents = root.findall("s3:Contents", S3_NS)
        assert len(contents) == 0

    def test_is_truncated_false_when_all_returned(self, client: TestClient, bucket: str):
        r = client.get(f"/{bucket}?list-type=2")
        root = parse_xml(r.text)
        assert root.findtext("s3:IsTruncated", namespaces=S3_NS) == "false"

    def test_lists_objects(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/file1.txt", content=b"hello")
        client.put(f"/{bucket}/file2.txt", content=b"world")
        r = client.get(f"/{bucket}?list-type=2")
        assert r.status_code == 200
        root = parse_xml(r.text)
        keys = [el.text for el in root.findall("s3:Contents/s3:Key", S3_NS)]
        assert "file1.txt" in keys
        assert "file2.txt" in keys

    def test_object_has_size(self, client: TestClient, bucket: str):
        data = b"hello world"
        client.put(f"/{bucket}/sized.txt", content=data)
        r = client.get(f"/{bucket}?list-type=2")
        root = parse_xml(r.text)
        contents = root.findall("s3:Contents", S3_NS)
        obj = next((c for c in contents if c.findtext("s3:Key", namespaces=S3_NS) == "sized.txt"), None)
        assert obj is not None
        assert obj.findtext("s3:Size", namespaces=S3_NS) == str(len(data))

    def test_object_has_etag(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/etag-obj.txt", content=b"data")
        r = client.get(f"/{bucket}?list-type=2")
        root = parse_xml(r.text)
        contents = root.findall("s3:Contents", S3_NS)
        obj = next((c for c in contents if c.findtext("s3:Key", namespaces=S3_NS) == "etag-obj.txt"), None)
        assert obj is not None
        etag = obj.findtext("s3:ETag", namespaces=S3_NS)
        assert etag is not None and etag.startswith('"')

    def test_object_has_last_modified(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/dated.txt", content=b"x")
        r = client.get(f"/{bucket}?list-type=2")
        root = parse_xml(r.text)
        contents = root.findall("s3:Contents", S3_NS)
        obj = next((c for c in contents if c.findtext("s3:Key", namespaces=S3_NS) == "dated.txt"), None)
        assert obj is not None
        assert obj.find("s3:LastModified", S3_NS) is not None

    def test_prefix_filter(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/img/cat.jpg", content=b"cat")
        client.put(f"/{bucket}/img/dog.jpg", content=b"dog")
        client.put(f"/{bucket}/doc/readme.txt", content=b"readme")
        r = client.get(f"/{bucket}?list-type=2&prefix=img/")
        assert r.status_code == 200
        root = parse_xml(r.text)
        keys = [el.text for el in root.findall("s3:Contents/s3:Key", S3_NS)]
        assert all(k.startswith("img/") for k in keys)
        assert "doc/readme.txt" not in keys

    def test_delimiter_groups_common_prefixes(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/a/x.txt", content=b"x")
        client.put(f"/{bucket}/a/y.txt", content=b"y")
        client.put(f"/{bucket}/b/z.txt", content=b"z")
        r = client.get(f"/{bucket}?list-type=2&delimiter=/")
        assert r.status_code == 200
        root = parse_xml(r.text)
        prefixes = [el.text for el in root.findall("s3:CommonPrefixes/s3:Prefix", S3_NS)]
        assert "a/" in prefixes
        assert "b/" in prefixes

    def test_max_keys_limits_results(self, client: TestClient, bucket: str):
        for i in range(5):
            client.put(f"/{bucket}/maxkeys-{i}", content=b"data")
        r = client.get(f"/{bucket}?list-type=2&max-keys=2&prefix=maxkeys-")
        assert r.status_code == 200
        root = parse_xml(r.text)
        assert len(root.findall("s3:Contents", S3_NS)) <= 2
        assert root.findtext("s3:IsTruncated", namespaces=S3_NS) == "true"

    def test_continuation_token_pages(self, client: TestClient, bucket: str):
        for i in range(4):
            client.put(f"/{bucket}/page-{i:02d}", content=b"data")
        r1 = client.get(f"/{bucket}?list-type=2&max-keys=2&prefix=page-")
        root1 = parse_xml(r1.text)
        token = root1.findtext("s3:NextContinuationToken", namespaces=S3_NS)
        assert token is not None
        r2 = client.get(f"/{bucket}?list-type=2&max-keys=2&prefix=page-&continuation-token={token}")
        assert r2.status_code == 200
        root2 = parse_xml(r2.text)
        assert len(root2.findall("s3:Contents", S3_NS)) >= 1

    def test_nonexistent_bucket_returns_404(self, client: TestClient):
        r = client.get("/bucket-that-does-not-exist-zzz?list-type=2")
        assert r.status_code == 404
        err = parse_error(r.text)
        assert err["code"] == "NoSuchBucket"

    def test_bucket_name_in_response(self, client: TestClient, bucket: str):
        r = client.get(f"/{bucket}?list-type=2")
        root = parse_xml(r.text)
        assert root.findtext("s3:Name", namespaces=S3_NS) == bucket

    def test_key_count_in_response(self, client: TestClient, bucket: str):
        client.put(f"/{bucket}/kc1", content=b"a")
        client.put(f"/{bucket}/kc2", content=b"b")
        r = client.get(f"/{bucket}?list-type=2&prefix=kc")
        root = parse_xml(r.text)
        key_count = root.findtext("s3:KeyCount", namespaces=S3_NS)
        assert key_count == "2"
