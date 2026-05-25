"""Tests unitaires — src.services.xml_builder."""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.unit

S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def _parse(xml_bytes: bytes) -> ET.Element:
    return ET.fromstring(xml_bytes)


def _text(root: ET.Element, path: str) -> str | None:
    el = root.find("/".join(f"s3:{p}" for p in path.split("/")), S3_NS)
    if el is None:
        el = root.find(path)
    return el.text if el is not None else None


@pytest.fixture
def builder():
    from src.services.xml_builder import XmlBuilder
    return XmlBuilder()


# ---------------------------------------------------------------------------
# build_error_response
# ---------------------------------------------------------------------------

class TestBuildErrorResponse:
    def test_root_tag_is_error(self, builder):
        xml = builder.build_error_response("NoSuchBucket", "Bucket does not exist")
        root = _parse(xml)
        assert root.tag == "Error"

    def test_contains_code(self, builder):
        xml = builder.build_error_response("NoSuchKey", "Key not found")
        root = _parse(xml)
        assert root.findtext("Code") == "NoSuchKey"

    def test_contains_message(self, builder):
        xml = builder.build_error_response("BucketNotEmpty", "Bucket has objects")
        root = _parse(xml)
        assert root.findtext("Message") == "Bucket has objects"

    def test_optional_resource(self, builder):
        xml = builder.build_error_response("NoSuchBucket", "msg", resource="/my-bucket")
        root = _parse(xml)
        assert root.findtext("Resource") == "/my-bucket"

    def test_returns_bytes(self, builder):
        result = builder.build_error_response("Err", "msg")
        assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# build_list_buckets_response
# ---------------------------------------------------------------------------

class TestBuildListBucketsResponse:
    def test_root_element(self, builder):
        xml = builder.build_list_buckets_response(owner_id="id", owner_name="name", buckets=[])
        root = _parse(xml)
        assert root.tag.endswith("ListAllMyBucketsResult")

    def test_has_namespace(self, builder):
        xml = builder.build_list_buckets_response(owner_id="id", owner_name="name", buckets=[])
        assert b"s3.amazonaws.com" in xml

    def test_empty_buckets(self, builder):
        xml = builder.build_list_buckets_response(owner_id="id", owner_name="name", buckets=[])
        root = _parse(xml)
        assert root.findall("s3:Buckets/s3:Bucket", S3_NS) == []

    def test_bucket_name_and_date(self, builder):
        now = datetime.now(timezone.utc)
        buckets = [{"name": "my-bucket", "creation_date": now}]
        xml = builder.build_list_buckets_response(owner_id="id", owner_name="name", buckets=buckets)
        root = _parse(xml)
        bucket_els = root.findall("s3:Buckets/s3:Bucket", S3_NS)
        assert len(bucket_els) == 1
        assert bucket_els[0].findtext("s3:Name", namespaces=S3_NS) == "my-bucket"
        assert bucket_els[0].find("s3:CreationDate", S3_NS) is not None

    def test_multiple_buckets(self, builder):
        now = datetime.now(timezone.utc)
        buckets = [{"name": f"bucket-{i}", "creation_date": now} for i in range(3)]
        xml = builder.build_list_buckets_response(owner_id="id", owner_name="name", buckets=buckets)
        root = _parse(xml)
        assert len(root.findall("s3:Buckets/s3:Bucket", S3_NS)) == 3

    def test_owner_elements(self, builder):
        xml = builder.build_list_buckets_response(owner_id="uid", owner_name="Alice", buckets=[])
        root = _parse(xml)
        assert root.findtext("s3:Owner/s3:ID", namespaces=S3_NS) == "uid"
        assert root.findtext("s3:Owner/s3:DisplayName", namespaces=S3_NS) == "Alice"


# ---------------------------------------------------------------------------
# build_list_objects_response
# ---------------------------------------------------------------------------

class TestBuildListObjectsResponse:
    def _make_obj(self, key: str, size: int = 10) -> dict:
        return {
            "key": key,
            "size": size,
            "etag": '"abc123"',
            "last_modified": datetime.now(timezone.utc),
            "storage_class": "STANDARD",
        }

    def test_root_element(self, builder):
        xml = builder.build_list_objects_response(
            bucket="b", prefix="", delimiter="", max_keys=1000,
            objects=[], common_prefixes=[], is_truncated=False,
            key_count=0,
        )
        root = _parse(xml)
        assert root.tag.endswith("ListBucketResult")

    def test_bucket_name(self, builder):
        xml = builder.build_list_objects_response(
            bucket="my-bucket", prefix="", delimiter="", max_keys=1000,
            objects=[], common_prefixes=[], is_truncated=False, key_count=0,
        )
        root = _parse(xml)
        assert root.findtext("s3:Name", namespaces=S3_NS) == "my-bucket"

    def test_is_truncated_false(self, builder):
        xml = builder.build_list_objects_response(
            bucket="b", prefix="", delimiter="", max_keys=1000,
            objects=[], common_prefixes=[], is_truncated=False, key_count=0,
        )
        root = _parse(xml)
        assert root.findtext("s3:IsTruncated", namespaces=S3_NS) == "false"

    def test_is_truncated_true_with_token(self, builder):
        xml = builder.build_list_objects_response(
            bucket="b", prefix="", delimiter="", max_keys=1,
            objects=[self._make_obj("a.txt")],
            common_prefixes=[], is_truncated=True, key_count=1,
            next_continuation_token="tok123",
        )
        root = _parse(xml)
        assert root.findtext("s3:IsTruncated", namespaces=S3_NS) == "true"
        assert root.findtext("s3:NextContinuationToken", namespaces=S3_NS) == "tok123"

    def test_object_fields(self, builder):
        obj = self._make_obj("file.txt", size=42)
        xml = builder.build_list_objects_response(
            bucket="b", prefix="", delimiter="", max_keys=1000,
            objects=[obj], common_prefixes=[], is_truncated=False, key_count=1,
        )
        root = _parse(xml)
        content = root.find("s3:Contents", S3_NS)
        assert content is not None
        assert content.findtext("s3:Key", namespaces=S3_NS) == "file.txt"
        assert content.findtext("s3:Size", namespaces=S3_NS) == "42"
        assert content.findtext("s3:ETag", namespaces=S3_NS) == '"abc123"'

    def test_common_prefixes(self, builder):
        xml = builder.build_list_objects_response(
            bucket="b", prefix="", delimiter="/", max_keys=1000,
            objects=[], common_prefixes=["img/", "doc/"],
            is_truncated=False, key_count=0,
        )
        root = _parse(xml)
        prefixes = [el.text for el in root.findall("s3:CommonPrefixes/s3:Prefix", S3_NS)]
        assert "img/" in prefixes
        assert "doc/" in prefixes

    def test_key_count(self, builder):
        objs = [self._make_obj(f"k{i}.txt") for i in range(3)]
        xml = builder.build_list_objects_response(
            bucket="b", prefix="", delimiter="", max_keys=1000,
            objects=objs, common_prefixes=[], is_truncated=False, key_count=3,
        )
        root = _parse(xml)
        assert root.findtext("s3:KeyCount", namespaces=S3_NS) == "3"


# ---------------------------------------------------------------------------
# build_create_multipart_response
# ---------------------------------------------------------------------------

class TestBuildCreateMultipartResponse:
    def test_root_element(self, builder):
        xml = builder.build_create_multipart_response("bucket", "key.bin", "uid-123")
        root = _parse(xml)
        assert root.tag.endswith("InitiateMultipartUploadResult")

    def test_contains_upload_id(self, builder):
        xml = builder.build_create_multipart_response("b", "k", "my-upload-id")
        root = _parse(xml)
        uid = root.findtext("s3:UploadId", namespaces=S3_NS) or root.findtext("UploadId")
        assert uid == "my-upload-id"

    def test_contains_bucket_and_key(self, builder):
        xml = builder.build_create_multipart_response("my-bucket", "my/key.bin", "uid")
        root = _parse(xml)
        bucket = root.findtext("s3:Bucket", namespaces=S3_NS) or root.findtext("Bucket")
        key = root.findtext("s3:Key", namespaces=S3_NS) or root.findtext("Key")
        assert bucket == "my-bucket"
        assert key == "my/key.bin"


# ---------------------------------------------------------------------------
# build_complete_multipart_response
# ---------------------------------------------------------------------------

class TestBuildCompleteMultipartResponse:
    def test_root_element(self, builder):
        xml = builder.build_complete_multipart_response(
            location="http://test/bucket/key",
            bucket="bucket", key="key", etag='"abc-2"',
        )
        root = _parse(xml)
        assert root.tag.endswith("CompleteMultipartUploadResult")

    def test_contains_etag(self, builder):
        xml = builder.build_complete_multipart_response(
            location="http://test/b/k", bucket="b", key="k", etag='"abc-2"',
        )
        root = _parse(xml)
        etag = root.findtext("s3:ETag", namespaces=S3_NS) or root.findtext("ETag")
        assert etag == '"abc-2"'

    def test_contains_location(self, builder):
        loc = "http://localhost/my-bucket/my-key"
        xml = builder.build_complete_multipart_response(
            location=loc, bucket="my-bucket", key="my-key", etag='"e"',
        )
        root = _parse(xml)
        result_loc = root.findtext("s3:Location", namespaces=S3_NS) or root.findtext("Location")
        assert result_loc == loc


# ---------------------------------------------------------------------------
# build_copy_object_response
# ---------------------------------------------------------------------------

class TestBuildCopyObjectResponse:
    def test_root_element(self, builder):
        xml = builder.build_copy_object_response(
            etag='"abc"', last_modified=datetime.now(timezone.utc),
        )
        root = _parse(xml)
        assert root.tag.endswith("CopyObjectResult")

    def test_contains_etag(self, builder):
        xml = builder.build_copy_object_response(
            etag='"myetag"', last_modified=datetime.now(timezone.utc),
        )
        root = _parse(xml)
        etag = root.findtext("s3:ETag", namespaces=S3_NS) or root.findtext("ETag")
        assert etag == '"myetag"'

    def test_contains_last_modified(self, builder):
        now = datetime.now(timezone.utc)
        xml = builder.build_copy_object_response(etag='"e"', last_modified=now)
        root = _parse(xml)
        lm = root.findtext("s3:LastModified", namespaces=S3_NS) or root.findtext("LastModified")
        assert lm is not None


# ---------------------------------------------------------------------------
# build_delete_objects_response
# ---------------------------------------------------------------------------

class TestBuildDeleteObjectsResponse:
    def test_root_element(self, builder):
        xml = builder.build_delete_objects_response(deleted=[], errors=[])
        root = _parse(xml)
        assert root.tag.endswith("DeleteResult")

    def test_deleted_keys_listed(self, builder):
        xml = builder.build_delete_objects_response(
            deleted=["a.txt", "b.txt"], errors=[],
        )
        root = _parse(xml)
        deleted = root.findall("s3:Deleted", S3_NS)
        keys = [d.findtext("s3:Key", namespaces=S3_NS) or d.findtext("Key") for d in deleted]
        assert "a.txt" in keys
        assert "b.txt" in keys

    def test_errors_listed(self, builder):
        xml = builder.build_delete_objects_response(
            deleted=[],
            errors=[{"key": "bad.txt", "code": "AccessDenied", "message": "Forbidden"}],
        )
        root = _parse(xml)
        errors = root.findall("s3:Error", S3_NS)
        assert len(errors) == 1
        key = errors[0].findtext("s3:Key", namespaces=S3_NS) or errors[0].findtext("Key")
        assert key == "bad.txt"

    def test_quiet_mode_empty_result(self, builder):
        xml = builder.build_delete_objects_response(deleted=[], errors=[], quiet=True)
        root = _parse(xml)
        assert root.findall("s3:Deleted", S3_NS) == []


# ---------------------------------------------------------------------------
# build_list_parts_response
# ---------------------------------------------------------------------------

class TestBuildListPartsResponse:
    def _make_part(self, n: int) -> dict:
        return {
            "part_number": n,
            "etag": f'"etag{n}"',
            "size": 5 * 1024 * 1024,
            "last_modified": datetime.now(timezone.utc),
        }

    def test_root_element(self, builder):
        xml = builder.build_list_parts_response(
            bucket="b", key="k", upload_id="uid", parts=[],
            is_truncated=False, part_number_marker=0,
        )
        root = _parse(xml)
        assert root.tag.endswith("ListPartsResult")

    def test_parts_listed(self, builder):
        parts = [self._make_part(1), self._make_part(2)]
        xml = builder.build_list_parts_response(
            bucket="b", key="k", upload_id="uid", parts=parts,
            is_truncated=False, part_number_marker=0,
        )
        root = _parse(xml)
        part_els = root.findall("s3:Part", S3_NS)
        assert len(part_els) == 2
        nums = [int(p.findtext("s3:PartNumber", namespaces=S3_NS)) for p in part_els]
        assert 1 in nums and 2 in nums

    def test_part_has_etag_and_size(self, builder):
        parts = [self._make_part(1)]
        xml = builder.build_list_parts_response(
            bucket="b", key="k", upload_id="uid", parts=parts,
            is_truncated=False, part_number_marker=0,
        )
        root = _parse(xml)
        part = root.find("s3:Part", S3_NS)
        assert part.findtext("s3:ETag", namespaces=S3_NS) == '"etag1"'
        assert part.findtext("s3:Size", namespaces=S3_NS) == str(5 * 1024 * 1024)
