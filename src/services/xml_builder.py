import xml.etree.ElementTree as ET
from datetime import datetime

NS = "http://s3.amazonaws.com/doc/2006-03-01/"

# Enregistre le namespace S3 comme namespace par défaut pour éviter le préfixe ns0:
ET.register_namespace("", NS)


def _ns(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _sub(parent: ET.Element, tag: str) -> ET.Element:
    return ET.SubElement(parent, _ns(tag))


def _sub_text(parent: ET.Element, tag: str, text: str) -> None:
    _sub(parent, tag).text = text


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _to_bytes(root: ET.Element) -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        + ET.tostring(root, encoding="unicode").encode()
    )


class XmlBuilder:
    def build_error_response(
        self,
        code: str,
        message: str,
        *,
        resource: str | None = None,
    ) -> bytes:
        # Les erreurs S3 n'utilisent pas le namespace
        root = ET.Element("Error")
        ET.SubElement(root, "Code").text = code
        ET.SubElement(root, "Message").text = message
        if resource is not None:
            ET.SubElement(root, "Resource").text = resource
        return (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            + ET.tostring(root, encoding="unicode").encode()
        )

    def build_list_buckets_response(
        self,
        *,
        owner_id: str,
        owner_name: str,
        buckets: list[dict],
    ) -> bytes:
        root = ET.Element(_ns("ListAllMyBucketsResult"))
        owner = _sub(root, "Owner")
        _sub_text(owner, "ID", owner_id)
        _sub_text(owner, "DisplayName", owner_name)
        buckets_el = _sub(root, "Buckets")
        for b in buckets:
            bucket_el = _sub(buckets_el, "Bucket")
            _sub_text(bucket_el, "Name", b["name"])
            _sub_text(bucket_el, "CreationDate", _fmt_date(b["creation_date"]))
        return _to_bytes(root)

    def build_list_objects_response(
        self,
        *,
        bucket: str,
        prefix: str,
        delimiter: str,
        max_keys: int,
        objects: list[dict],
        common_prefixes: list[str],
        is_truncated: bool,
        key_count: int,
        next_continuation_token: str | None = None,
    ) -> bytes:
        root = ET.Element(_ns("ListBucketResult"))
        _sub_text(root, "Name", bucket)
        _sub_text(root, "Prefix", prefix)
        _sub_text(root, "MaxKeys", str(max_keys))
        _sub_text(root, "KeyCount", str(key_count))
        _sub_text(root, "IsTruncated", "true" if is_truncated else "false")
        if delimiter:
            _sub_text(root, "Delimiter", delimiter)
        if next_continuation_token:
            _sub_text(root, "NextContinuationToken", next_continuation_token)
        for obj in objects:
            content = _sub(root, "Contents")
            _sub_text(content, "Key", obj["key"])
            _sub_text(content, "LastModified", _fmt_date(obj["last_modified"]))
            _sub_text(content, "ETag", obj["etag"])
            _sub_text(content, "Size", str(obj["size"]))
            _sub_text(content, "StorageClass", obj.get("storage_class", "STANDARD"))
        for prefix_str in common_prefixes:
            cp = _sub(root, "CommonPrefixes")
            _sub_text(cp, "Prefix", prefix_str)
        return _to_bytes(root)

    def build_create_multipart_response(
        self, bucket: str, key: str, upload_id: str
    ) -> bytes:
        root = ET.Element(_ns("InitiateMultipartUploadResult"))
        _sub_text(root, "Bucket", bucket)
        _sub_text(root, "Key", key)
        _sub_text(root, "UploadId", upload_id)
        return _to_bytes(root)

    def build_complete_multipart_response(
        self,
        *,
        location: str,
        bucket: str,
        key: str,
        etag: str,
    ) -> bytes:
        root = ET.Element(_ns("CompleteMultipartUploadResult"))
        _sub_text(root, "Location", location)
        _sub_text(root, "Bucket", bucket)
        _sub_text(root, "Key", key)
        _sub_text(root, "ETag", etag)
        return _to_bytes(root)

    def build_copy_object_response(
        self,
        *,
        etag: str,
        last_modified: datetime,
    ) -> bytes:
        root = ET.Element(_ns("CopyObjectResult"))
        _sub_text(root, "ETag", etag)
        _sub_text(root, "LastModified", _fmt_date(last_modified))
        return _to_bytes(root)

    def build_delete_objects_response(
        self,
        *,
        deleted: list[str],
        errors: list[dict],
        quiet: bool = False,
    ) -> bytes:
        root = ET.Element(_ns("DeleteResult"))
        if not quiet:
            for key in deleted:
                d = _sub(root, "Deleted")
                _sub_text(d, "Key", key)
        for err in errors:
            e = _sub(root, "Error")
            _sub_text(e, "Key", err["key"])
            _sub_text(e, "Code", err["code"])
            _sub_text(e, "Message", err["message"])
        return _to_bytes(root)

    def build_list_parts_response(
        self,
        *,
        bucket: str,
        key: str,
        upload_id: str,
        parts: list[dict],
        is_truncated: bool,
        part_number_marker: int,
    ) -> bytes:
        root = ET.Element(_ns("ListPartsResult"))
        _sub_text(root, "Bucket", bucket)
        _sub_text(root, "Key", key)
        _sub_text(root, "UploadId", upload_id)
        _sub_text(root, "PartNumberMarker", str(part_number_marker))
        _sub_text(root, "IsTruncated", "true" if is_truncated else "false")
        for part in parts:
            p = _sub(root, "Part")
            _sub_text(p, "PartNumber", str(part["part_number"]))
            _sub_text(p, "LastModified", _fmt_date(part["last_modified"]))
            _sub_text(p, "ETag", part["etag"])
            _sub_text(p, "Size", str(part["size"]))
        return _to_bytes(root)
