import hashlib
import shutil
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlmodel import Session, select

from src.config import settings
from src.database import get_session
from src.models.bucket import Bucket
from src.models.multipart import MultipartUpload, Part
from src.models.object import Object
from src.services.storage import StorageService
from src.services.xml_builder import XmlBuilder

router = APIRouter()
_xml = XmlBuilder()
_storage = StorageService()


def _etag(data: bytes) -> str:
    return f'"{hashlib.md5(data).hexdigest()}"'


def _err(code: str, message: str, *, resource: str | None = None, status: int = 400) -> Response:
    body = _xml.build_error_response(code, message, resource=resource)
    return Response(content=body, status_code=status, media_type="application/xml")


def _part_path(upload_id: str, part_number: int):
    return settings.storage_path / ".multipart" / upload_id / str(part_number)


def _cleanup_parts(upload_id: str) -> None:
    part_dir = settings.storage_path / ".multipart" / upload_id
    if part_dir.exists():
        shutil.rmtree(str(part_dir))


def handle_create_multipart(bucket: str, key: str, content_type: str, session: Session) -> Response:
    if not session.get(Bucket, bucket):
        return _err("NoSuchBucket", "The specified bucket does not exist.", resource=f"/{bucket}", status=404)
    upload_id = str(uuid.uuid4())
    session.add(MultipartUpload(upload_id=upload_id, bucket=bucket, key=key, content_type=content_type))
    session.commit()
    body = _xml.build_create_multipart_response(bucket, key, upload_id)
    return Response(content=body, status_code=200, media_type="application/xml")


def handle_upload_part(
    bucket: str, key: str, upload_id: str, part_number: int, body: bytes, session: Session
) -> Response:
    if part_number < 1 or part_number > 10000:
        return _err("InvalidArgument", "Part number must be an integer between 1 and 10000, inclusive.")

    upload = session.get(MultipartUpload, upload_id)
    if not upload or upload.bucket != bucket or upload.key != key:
        return _err("NoSuchUpload", "The specified upload does not exist.", status=404)

    etag = _etag(body)
    p = _part_path(upload_id, part_number)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)

    existing = session.exec(
        select(Part).where(Part.upload_id == upload_id, Part.part_number == part_number)
    ).first()
    if existing:
        existing.etag = etag
        existing.size = len(body)
        existing.last_modified = datetime.now(timezone.utc)
        session.add(existing)
    else:
        session.add(Part(upload_id=upload_id, part_number=part_number, etag=etag, size=len(body)))
    session.commit()

    return Response(status_code=200, headers={"ETag": etag})


def handle_complete_multipart(
    bucket: str, key: str, upload_id: str, xml_body: bytes, session: Session
) -> Response:
    upload = session.get(MultipartUpload, upload_id)
    if not upload or upload.bucket != bucket or upload.key != key:
        return _err("NoSuchUpload", "The specified upload does not exist.", status=404)

    root = ET.fromstring(xml_body.decode())
    requested = [
        (int(el.findtext("PartNumber")), el.findtext("ETag"))
        for el in root.findall("Part")
    ]
    requested.sort(key=lambda x: x[0])

    for pn, expected_etag in requested:
        stored = session.exec(
            select(Part).where(Part.upload_id == upload_id, Part.part_number == pn)
        ).first()
        if not stored or stored.etag != expected_etag:
            return _err("InvalidPart", "One or more of the specified parts could not be found.")

    assembled = b"".join(_part_path(upload_id, pn).read_bytes() for pn, _ in requested)
    part_etags = [etag for _, etag in requested]

    md5_bytes = b"".join(bytes.fromhex(e.strip('"')) for e in part_etags)
    mp_etag = f'"{hashlib.md5(md5_bytes).hexdigest()}-{len(part_etags)}"'

    _storage.write(bucket, key, assembled)

    now = datetime.now(timezone.utc)
    obj = session.exec(select(Object).where(Object.bucket == bucket, Object.key == key)).first()
    if obj:
        obj.size = len(assembled)
        obj.etag = mp_etag
        obj.content_type = upload.content_type
        obj.last_modified = now
        obj.user_metadata = "{}"
    else:
        obj = Object(
            bucket=bucket, key=key, size=len(assembled),
            etag=mp_etag, content_type=upload.content_type, user_metadata="{}",
        )
    session.add(obj)

    for part in session.exec(select(Part).where(Part.upload_id == upload_id)).all():
        session.delete(part)
    session.delete(upload)
    session.commit()
    _cleanup_parts(upload_id)

    body_xml = _xml.build_complete_multipart_response(
        location=f"/{bucket}/{key}", bucket=bucket, key=key, etag=mp_etag
    )
    return Response(content=body_xml, status_code=200, media_type="application/xml")


def handle_abort_multipart(bucket: str, key: str, upload_id: str, session: Session) -> Response:
    upload = session.get(MultipartUpload, upload_id)
    if not upload or upload.bucket != bucket or upload.key != key:
        return _err("NoSuchUpload", "The specified upload does not exist.", status=404)

    for part in session.exec(select(Part).where(Part.upload_id == upload_id)).all():
        session.delete(part)
    session.delete(upload)
    session.commit()
    _cleanup_parts(upload_id)

    return Response(status_code=204)


def handle_list_parts(bucket: str, key: str, upload_id: str, session: Session) -> Response:
    upload = session.get(MultipartUpload, upload_id)
    if not upload or upload.bucket != bucket or upload.key != key:
        return _err("NoSuchUpload", "The specified upload does not exist.", status=404)

    parts = session.exec(
        select(Part).where(Part.upload_id == upload_id).order_by(Part.part_number)
    ).all()

    body = _xml.build_list_parts_response(
        bucket=bucket,
        key=key,
        upload_id=upload_id,
        parts=[
            {"part_number": p.part_number, "last_modified": p.last_modified, "etag": p.etag, "size": p.size}
            for p in parts
        ],
        is_truncated=False,
        part_number_marker=0,
    )
    return Response(content=body, status_code=200, media_type="application/xml")


@router.post("/{bucket}/{key:path}")
async def post_object(
    bucket: str,
    key: str,
    request: Request,
    upload_id: str | None = Query(default=None, alias="uploadId"),
    session: Session = Depends(get_session),
) -> Response:
    if "uploads" in request.query_params:
        content_type = request.headers.get("content-type", "application/octet-stream")
        return handle_create_multipart(bucket, key, content_type, session)

    if upload_id:
        xml_body = await request.body()
        return handle_complete_multipart(bucket, key, upload_id, xml_body, session)

    return _err("BadRequest", "Missing required query parameter.")
