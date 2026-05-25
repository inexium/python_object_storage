import base64
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import formatdate

from fastapi import APIRouter, Depends, Request, Response
from sqlmodel import Session, select

from src.database import get_session
from src.models.bucket import Bucket
from src.models.object import Object
from src.services.storage import StorageService
from src.services.xml_builder import XmlBuilder

router = APIRouter()
_xml = XmlBuilder()
_storage = StorageService()


def _etag(data: bytes) -> str:
    return f'"{hashlib.md5(data).hexdigest()}"'


def _http_date(dt: datetime) -> str:
    return formatdate(dt.timestamp(), usegmt=True)


def _err(code: str, message: str, *, resource: str | None = None, status: int = 400) -> Response:
    body = _xml.build_error_response(code, message, resource=resource)
    return Response(content=body, status_code=status, media_type="application/xml")


def _get_object(session: Session, bucket: str, key: str) -> Object | None:
    return session.exec(
        select(Object).where(Object.bucket == bucket, Object.key == key)
    ).first()


def _object_headers(obj: Object) -> dict[str, str]:
    headers: dict[str, str] = {
        "ETag": obj.etag,
        "Content-Length": str(obj.size),
        "Content-Type": obj.content_type,
        "Last-Modified": _http_date(obj.last_modified),
    }
    if obj.user_metadata and obj.user_metadata != "{}":
        headers.update(json.loads(obj.user_metadata))
    return headers


def _range_response(data: bytes, range_header: str, base_headers: dict[str, str]) -> Response:
    total = len(data)
    try:
        spec = range_header.removeprefix("bytes=")
        if spec.startswith("-"):
            n = int(spec[1:])
            start = max(0, total - n)
            end = total - 1
        elif spec.endswith("-"):
            start = int(spec[:-1])
            end = total - 1
        else:
            s, e = spec.split("-", 1)
            start, end = int(s), int(e)
    except (ValueError, IndexError):
        return Response(status_code=416, headers={"Content-Range": f"bytes */{total}"})

    if start >= total:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{total}"})
    end = min(end, total - 1)
    if start > end:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{total}"})

    chunk = data[start : end + 1]
    headers = dict(base_headers)
    headers["Content-Length"] = str(len(chunk))
    headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return Response(content=chunk, status_code=206, headers=headers)


def _copy_object(
    dest_bucket: str,
    dest_key: str,
    copy_source: str,
    request: Request,
    session: Session,
) -> Response:
    src = copy_source.lstrip("/")
    src_bucket, _, src_key = src.partition("/")
    if not src_bucket or not src_key:
        return _err("InvalidArgument", "Invalid copy source.")

    src_obj = _get_object(session, src_bucket, src_key)
    if not src_obj:
        return _err("NoSuchKey", "The specified key does not exist.", resource=copy_source, status=404)

    data = _storage.read(src_bucket, src_key)
    directive = request.headers.get("x-amz-metadata-directive", "COPY").upper()

    if directive == "REPLACE":
        content_type = request.headers.get("content-type", src_obj.content_type)
        user_meta = {
            k: v for k, v in request.headers.items()
            if k.lower().startswith("x-amz-meta-")
        }
    else:
        content_type = src_obj.content_type
        user_meta = json.loads(src_obj.user_metadata) if src_obj.user_metadata else {}

    etag = _etag(data)
    now = datetime.now(timezone.utc)
    _storage.write(dest_bucket, dest_key, data)

    dest_obj = _get_object(session, dest_bucket, dest_key)
    if dest_obj:
        dest_obj.size = len(data)
        dest_obj.etag = etag
        dest_obj.content_type = content_type
        dest_obj.last_modified = now
        dest_obj.user_metadata = json.dumps(user_meta)
    else:
        dest_obj = Object(
            bucket=dest_bucket,
            key=dest_key,
            size=len(data),
            etag=etag,
            content_type=content_type,
            user_metadata=json.dumps(user_meta),
        )
    session.add(dest_obj)
    session.commit()

    body = _xml.build_copy_object_response(etag=etag, last_modified=now)
    return Response(content=body, status_code=200, media_type="application/xml")


@router.put("/{bucket}/{key:path}")
async def put_object(
    bucket: str,
    key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    if not session.get(Bucket, bucket):
        return _err("NoSuchBucket", "The specified bucket does not exist.", resource=f"/{bucket}", status=404)

    copy_source = request.headers.get("x-amz-copy-source")
    if copy_source:
        return _copy_object(bucket, key, copy_source, request, session)

    body = await request.body()

    content_md5 = request.headers.get("content-md5")
    if content_md5:
        expected = base64.b64encode(hashlib.md5(body).digest()).decode()
        if content_md5 != expected:
            return _err("InvalidDigest", "The Content-MD5 you specified is not valid.")

    content_type = request.headers.get("content-type", "application/octet-stream")
    user_meta = {
        k: v for k, v in request.headers.items()
        if k.lower().startswith("x-amz-meta-")
    }
    etag = _etag(body)
    _storage.write(bucket, key, body)

    obj = _get_object(session, bucket, key)
    if obj:
        obj.size = len(body)
        obj.etag = etag
        obj.content_type = content_type
        obj.last_modified = datetime.now(timezone.utc)
        obj.user_metadata = json.dumps(user_meta)
    else:
        obj = Object(
            bucket=bucket,
            key=key,
            size=len(body),
            etag=etag,
            content_type=content_type,
            user_metadata=json.dumps(user_meta),
        )
    session.add(obj)
    session.commit()

    return Response(status_code=200, headers={"ETag": etag})


@router.get("/{bucket}/{key:path}")
def get_object(
    bucket: str,
    key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    if not session.get(Bucket, bucket):
        return _err("NoSuchBucket", "The specified bucket does not exist.", resource=f"/{bucket}", status=404)

    obj = _get_object(session, bucket, key)
    if not obj:
        return _err("NoSuchKey", "The specified key does not exist.", resource=f"/{bucket}/{key}", status=404)

    data = _storage.read(bucket, key)
    headers = _object_headers(obj)

    range_header = request.headers.get("range")
    if range_header:
        return _range_response(data, range_header, headers)

    return Response(content=data, status_code=200, headers=headers)


@router.head("/{bucket}/{key:path}")
def head_object(
    bucket: str,
    key: str,
    session: Session = Depends(get_session),
) -> Response:
    if not session.get(Bucket, bucket):
        return Response(status_code=404)

    obj = _get_object(session, bucket, key)
    if not obj:
        return Response(status_code=404)

    return Response(status_code=200, headers=_object_headers(obj))


@router.delete("/{bucket}/{key:path}")
def delete_object(
    bucket: str,
    key: str,
    session: Session = Depends(get_session),
) -> Response:
    if not session.get(Bucket, bucket):
        return _err("NoSuchBucket", "The specified bucket does not exist.", resource=f"/{bucket}", status=404)

    obj = _get_object(session, bucket, key)
    if obj:
        session.delete(obj)
        session.commit()
    _storage.delete(bucket, key)

    return Response(status_code=204)


@router.post("/{bucket}")
async def delete_objects_batch(
    bucket: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    if not session.get(Bucket, bucket):
        return _err("NoSuchBucket", "The specified bucket does not exist.", resource=f"/{bucket}", status=404)

    raw = await request.body()
    root = ET.fromstring(raw.decode())

    quiet_el = root.find("Quiet")
    quiet = quiet_el is not None and (quiet_el.text or "").lower() == "true"
    keys = [el.text for el in root.findall("Object/Key") if el.text]

    deleted: list[str] = []
    for key in keys:
        obj = _get_object(session, bucket, key)
        if obj:
            session.delete(obj)
        _storage.delete(bucket, key)
        deleted.append(key)
    session.commit()

    body = _xml.build_delete_objects_response(deleted=deleted, errors=[], quiet=quiet)
    return Response(content=body, status_code=200, media_type="application/xml")
