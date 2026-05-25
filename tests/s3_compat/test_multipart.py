"""Tests de compatibilité S3 — multipart uploads."""

import pytest
from starlette.testclient import TestClient

from tests.helpers import (
    build_complete_multipart_xml,
    expected_etag,
    multipart_etag,
    parse_error,
    parse_xml,
)

pytestmark = pytest.mark.s3_compat

S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

# Taille minimale d'une partie S3 : 5 MiB (sauf la dernière)
MIN_PART_SIZE = 5 * 1024 * 1024


def _create_upload(client: TestClient, bucket: str, key: str) -> str:
    """Crée un multipart upload et retourne l'uploadId."""
    r = client.post(f"/{bucket}/{key}?uploads")
    assert r.status_code == 200
    root = parse_xml(r.text)
    upload_id = root.findtext("s3:UploadId", namespaces=S3_NS) or root.findtext("UploadId")
    assert upload_id, "UploadId manquant dans la réponse"
    return upload_id


def _upload_part(client: TestClient, bucket: str, key: str, upload_id: str, part_number: int, data: bytes) -> str:
    """Upload une partie et retourne son ETag."""
    r = client.put(
        f"/{bucket}/{key}?partNumber={part_number}&uploadId={upload_id}",
        content=data,
    )
    assert r.status_code == 200
    etag = r.headers.get("etag")
    assert etag, "ETag manquant dans la réponse de UploadPart"
    return etag


# ---------------------------------------------------------------------------
# CreateMultipartUpload — POST /{bucket}/{key}?uploads
# ---------------------------------------------------------------------------

class TestCreateMultipartUpload:
    def test_returns_200(self, client: TestClient, bucket: str):
        r = client.post(f"/{bucket}/upload.bin?uploads")
        assert r.status_code == 200
        upload_id = _create_upload(client, bucket, "cleanup-create.bin")
        # Abort pour nettoyer
        client.delete(f"/{bucket}/cleanup-create.bin?uploadId={upload_id}")

    def test_returns_xml_with_upload_id(self, client: TestClient, bucket: str):
        r = client.post(f"/{bucket}/create-test.bin?uploads")
        assert r.status_code == 200
        root = parse_xml(r.text)
        assert root.tag.endswith("InitiateMultipartUploadResult")
        upload_id = root.findtext("s3:UploadId", namespaces=S3_NS) or root.findtext("UploadId")
        assert upload_id and len(upload_id) > 0
        client.delete(f"/{bucket}/create-test.bin?uploadId={upload_id}")

    def test_response_contains_bucket_and_key(self, client: TestClient, bucket: str):
        r = client.post(f"/{bucket}/bk-key-test.bin?uploads")
        root = parse_xml(r.text)
        bucket_el = root.findtext("s3:Bucket", namespaces=S3_NS) or root.findtext("Bucket")
        key_el = root.findtext("s3:Key", namespaces=S3_NS) or root.findtext("Key")
        assert bucket_el == bucket
        assert key_el == "bk-key-test.bin"
        upload_id = root.findtext("s3:UploadId", namespaces=S3_NS) or root.findtext("UploadId")
        client.delete(f"/{bucket}/bk-key-test.bin?uploadId={upload_id}")

    def test_nonexistent_bucket_returns_404(self, client: TestClient):
        r = client.post("/bucket-that-does-not-exist-zzz/key.bin?uploads")
        assert r.status_code == 404
        err = parse_error(r.text)
        assert err["code"] == "NoSuchBucket"

    def test_with_content_type(self, client: TestClient, bucket: str):
        r = client.post(
            f"/{bucket}/typed.bin?uploads",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert r.status_code == 200
        upload_id = (parse_xml(r.text).findtext("s3:UploadId", namespaces=S3_NS)
                     or parse_xml(r.text).findtext("UploadId"))
        client.delete(f"/{bucket}/typed.bin?uploadId={upload_id}")


# ---------------------------------------------------------------------------
# UploadPart — PUT /{bucket}/{key}?partNumber=N&uploadId=X
# ---------------------------------------------------------------------------

class TestUploadPart:
    def test_returns_200_with_etag(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "part-test.bin")
        data = b"x" * MIN_PART_SIZE
        r = client.put(
            f"/{bucket}/part-test.bin?partNumber=1&uploadId={upload_id}",
            content=data,
        )
        assert r.status_code == 200
        assert r.headers.get("etag") == expected_etag(data)
        client.delete(f"/{bucket}/part-test.bin?uploadId={upload_id}")

    def test_invalid_upload_id_returns_404(self, client: TestClient, bucket: str):
        r = client.put(
            f"/{bucket}/any.bin?partNumber=1&uploadId=invalid-upload-id",
            content=b"data",
        )
        assert r.status_code == 404
        err = parse_error(r.text)
        assert err["code"] == "NoSuchUpload"

    def test_part_number_out_of_range_returns_400(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "partnum.bin")
        r = client.put(
            f"/{bucket}/partnum.bin?partNumber=10001&uploadId={upload_id}",
            content=b"data",
        )
        assert r.status_code == 400
        client.delete(f"/{bucket}/partnum.bin?uploadId={upload_id}")

    def test_part_number_zero_returns_400(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "partnum0.bin")
        r = client.put(
            f"/{bucket}/partnum0.bin?partNumber=0&uploadId={upload_id}",
            content=b"data",
        )
        assert r.status_code == 400
        client.delete(f"/{bucket}/partnum0.bin?uploadId={upload_id}")


# ---------------------------------------------------------------------------
# CompleteMultipartUpload — POST /{bucket}/{key}?uploadId=X
# ---------------------------------------------------------------------------

class TestCompleteMultipartUpload:
    def test_completes_single_part_upload(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "complete1.bin")
        data = b"final content"
        etag = _upload_part(client, bucket, "complete1.bin", upload_id, 1, data)
        body = build_complete_multipart_xml([(1, etag)])
        r = client.post(
            f"/{bucket}/complete1.bin?uploadId={upload_id}",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        assert r.status_code == 200

    def test_result_xml(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "result-xml.bin")
        etag = _upload_part(client, bucket, "result-xml.bin", upload_id, 1, b"part data")
        body = build_complete_multipart_xml([(1, etag)])
        r = client.post(
            f"/{bucket}/result-xml.bin?uploadId={upload_id}",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        root = parse_xml(r.text)
        assert root.tag.endswith("CompleteMultipartUploadResult")
        result_etag = root.findtext("s3:ETag", namespaces=S3_NS) or root.findtext("ETag")
        assert result_etag and "-1" in result_etag  # format ETag multipart : "md5-N"

    def test_completed_object_is_readable(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "readable.bin")
        data = b"readable content after complete"
        etag = _upload_part(client, bucket, "readable.bin", upload_id, 1, data)
        body = build_complete_multipart_xml([(1, etag)])
        client.post(
            f"/{bucket}/readable.bin?uploadId={upload_id}",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        r = client.get(f"/{bucket}/readable.bin")
        assert r.status_code == 200
        assert r.content == data

    def test_multipart_assembles_parts_in_order(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "ordered.bin")
        part1_data = b"A" * MIN_PART_SIZE
        part2_data = b"B" * MIN_PART_SIZE
        part3_data = b"C" * 1024  # Dernière partie peut être < MIN_PART_SIZE
        e1 = _upload_part(client, bucket, "ordered.bin", upload_id, 1, part1_data)
        e2 = _upload_part(client, bucket, "ordered.bin", upload_id, 2, part2_data)
        e3 = _upload_part(client, bucket, "ordered.bin", upload_id, 3, part3_data)
        body = build_complete_multipart_xml([(1, e1), (2, e2), (3, e3)])
        r = client.post(
            f"/{bucket}/ordered.bin?uploadId={upload_id}",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        assert r.status_code == 200
        get = client.get(f"/{bucket}/ordered.bin")
        assert get.content == part1_data + part2_data + part3_data

    def test_etag_has_multipart_format(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "etag-mp.bin")
        part_data = b"y" * MIN_PART_SIZE
        e1 = _upload_part(client, bucket, "etag-mp.bin", upload_id, 1, part_data)
        part_data2 = b"z" * 1024
        e2 = _upload_part(client, bucket, "etag-mp.bin", upload_id, 2, part_data2)
        body = build_complete_multipart_xml([(1, e1), (2, e2)])
        r = client.post(
            f"/{bucket}/etag-mp.bin?uploadId={upload_id}",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        root = parse_xml(r.text)
        result_etag = root.findtext("s3:ETag", namespaces=S3_NS) or root.findtext("ETag")
        assert result_etag is not None
        assert result_etag.endswith('-2"') or result_etag.endswith("-2")

    def test_invalid_upload_id_returns_404(self, client: TestClient, bucket: str):
        body = build_complete_multipart_xml([(1, '"abc123"')])
        r = client.post(
            f"/{bucket}/no-upload.bin?uploadId=invalid-id",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        assert r.status_code == 404
        err = parse_error(r.text)
        assert err["code"] == "NoSuchUpload"

    def test_wrong_etag_returns_400(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "wrong-etag.bin")
        _upload_part(client, bucket, "wrong-etag.bin", upload_id, 1, b"real data")
        body = build_complete_multipart_xml([(1, '"wrongetag"')])
        r = client.post(
            f"/{bucket}/wrong-etag.bin?uploadId={upload_id}",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        assert r.status_code == 400
        client.delete(f"/{bucket}/wrong-etag.bin?uploadId={upload_id}")


# ---------------------------------------------------------------------------
# AbortMultipartUpload — DELETE /{bucket}/{key}?uploadId=X
# ---------------------------------------------------------------------------

class TestAbortMultipartUpload:
    def test_aborts_upload(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "abort.bin")
        r = client.delete(f"/{bucket}/abort.bin?uploadId={upload_id}")
        assert r.status_code == 204

    def test_aborted_upload_not_accessible(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "aborted.bin")
        _upload_part(client, bucket, "aborted.bin", upload_id, 1, b"data")
        client.delete(f"/{bucket}/aborted.bin?uploadId={upload_id}")
        # Tentative de compléter après abort
        body = build_complete_multipart_xml([(1, '"any"')])
        r = client.post(
            f"/{bucket}/aborted.bin?uploadId={upload_id}",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        assert r.status_code == 404

    def test_invalid_upload_id_returns_404(self, client: TestClient, bucket: str):
        r = client.delete(f"/{bucket}/any.bin?uploadId=invalid-upload-id")
        assert r.status_code == 404
        err = parse_error(r.text)
        assert err["code"] == "NoSuchUpload"


# ---------------------------------------------------------------------------
# ListParts — GET /{bucket}/{key}?uploadId=X
# ---------------------------------------------------------------------------

class TestListParts:
    def test_returns_empty_list_before_upload(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "listparts.bin")
        r = client.get(f"/{bucket}/listparts.bin?uploadId={upload_id}")
        assert r.status_code == 200
        root = parse_xml(r.text)
        assert root.tag.endswith("ListPartsResult")
        parts = root.findall("s3:Part", S3_NS)
        assert len(parts) == 0
        client.delete(f"/{bucket}/listparts.bin?uploadId={upload_id}")

    def test_lists_uploaded_parts(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "listparts2.bin")
        data = b"p" * MIN_PART_SIZE
        _upload_part(client, bucket, "listparts2.bin", upload_id, 1, data)
        _upload_part(client, bucket, "listparts2.bin", upload_id, 2, b"last")
        r = client.get(f"/{bucket}/listparts2.bin?uploadId={upload_id}")
        assert r.status_code == 200
        root = parse_xml(r.text)
        parts = root.findall("s3:Part", S3_NS)
        assert len(parts) == 2
        part_numbers = [int(p.findtext("s3:PartNumber", namespaces=S3_NS)) for p in parts]
        assert 1 in part_numbers
        assert 2 in part_numbers
        client.delete(f"/{bucket}/listparts2.bin?uploadId={upload_id}")

    def test_part_has_etag_and_size(self, client: TestClient, bucket: str):
        upload_id = _create_upload(client, bucket, "part-meta.bin")
        data = b"q" * MIN_PART_SIZE
        _upload_part(client, bucket, "part-meta.bin", upload_id, 1, data)
        r = client.get(f"/{bucket}/part-meta.bin?uploadId={upload_id}")
        root = parse_xml(r.text)
        part = root.find("s3:Part", S3_NS)
        assert part is not None
        assert part.findtext("s3:ETag", namespaces=S3_NS) is not None
        assert part.findtext("s3:Size", namespaces=S3_NS) == str(len(data))
        client.delete(f"/{bucket}/part-meta.bin?uploadId={upload_id}")

    def test_invalid_upload_id_returns_404(self, client: TestClient, bucket: str):
        r = client.get(f"/{bucket}/any.bin?uploadId=invalid-id")
        assert r.status_code == 404
        err = parse_error(r.text)
        assert err["code"] == "NoSuchUpload"


# ---------------------------------------------------------------------------
# Flux complet — intégration de bout en bout
# ---------------------------------------------------------------------------

class TestMultipartFullFlow:
    def test_full_three_part_upload(self, client: TestClient, bucket: str):
        key = "full-flow.bin"
        upload_id = _create_upload(client, bucket, key)
        p1 = b"A" * MIN_PART_SIZE
        p2 = b"B" * MIN_PART_SIZE
        p3 = b"C" * 512  # dernière partie petite
        e1 = _upload_part(client, bucket, key, upload_id, 1, p1)
        e2 = _upload_part(client, bucket, key, upload_id, 2, p2)
        e3 = _upload_part(client, bucket, key, upload_id, 3, p3)
        body = build_complete_multipart_xml([(1, e1), (2, e2), (3, e3)])
        r = client.post(
            f"/{bucket}/{key}?uploadId={upload_id}",
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        assert r.status_code == 200
        # Vérification du contenu final
        get = client.get(f"/{bucket}/{key}")
        assert get.status_code == 200
        assert get.content == p1 + p2 + p3
        # Vérification que l'objet est listable
        list_r = client.get(f"/{bucket}?list-type=2")
        root = parse_xml(list_r.text)
        keys = [el.text for el in root.findall("s3:Contents/s3:Key", S3_NS)]
        assert key in keys
