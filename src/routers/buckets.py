import re

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session, select

from src.database import get_session
from src.models.bucket import Bucket
from src.models.object import Object
from src.services.xml_builder import XmlBuilder

router = APIRouter()
_xml = XmlBuilder()

_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _is_valid_bucket_name(name: str) -> bool:
    if len(name) < 3 or len(name) > 63:
        return False
    if _IP_RE.match(name):
        return False
    return bool(_BUCKET_RE.match(name))


def _err(code: str, message: str, *, resource: str | None = None, status: int = 400) -> Response:
    body = _xml.build_error_response(code, message, resource=resource)
    return Response(content=body, status_code=status, media_type="application/xml")


@router.get("/")
def list_buckets(session: Session = Depends(get_session)) -> Response:
    buckets = session.exec(select(Bucket)).all()
    body = _xml.build_list_buckets_response(
        owner_id="owner",
        owner_name="owner",
        buckets=[{"name": b.name, "creation_date": b.creation_date} for b in buckets],
    )
    return Response(content=body, media_type="application/xml")


@router.put("/{bucket}")
def create_bucket(bucket: str, session: Session = Depends(get_session)) -> Response:
    if not _is_valid_bucket_name(bucket):
        return _err("InvalidBucketName", "The specified bucket is not valid.", resource=f"/{bucket}")
    if session.get(Bucket, bucket):
        return _err(
            "BucketAlreadyOwnedByYou",
            "Your previous request to create the named bucket succeeded and you already own it.",
            resource=f"/{bucket}",
            status=409,
        )
    session.add(Bucket(name=bucket))
    session.commit()
    return Response(status_code=200, headers={"Location": f"/{bucket}"})


@router.head("/{bucket}")
def head_bucket(bucket: str, session: Session = Depends(get_session)) -> Response:
    if not session.get(Bucket, bucket):
        return Response(status_code=404)
    return Response(status_code=200)


@router.delete("/{bucket}")
def delete_bucket(bucket: str, session: Session = Depends(get_session)) -> Response:
    b = session.get(Bucket, bucket)
    if not b:
        return _err("NoSuchBucket", "The specified bucket does not exist.", resource=f"/{bucket}", status=404)
    has_objects = session.exec(select(Object).where(Object.bucket == bucket).limit(1)).first()
    if has_objects:
        return _err("BucketNotEmpty", "The bucket you tried to delete is not empty.", resource=f"/{bucket}", status=409)
    session.delete(b)
    session.commit()
    return Response(status_code=204)


@router.get("/{bucket}")
def list_objects(
    bucket: str,
    prefix: str = Query(default="", alias="prefix"),
    delimiter: str = Query(default="", alias="delimiter"),
    max_keys: int = Query(default=1000, alias="max-keys"),
    continuation_token: str | None = Query(default=None, alias="continuation-token"),
    session: Session = Depends(get_session),
) -> Response:
    if not session.get(Bucket, bucket):
        return _err("NoSuchBucket", "The specified bucket does not exist.", resource=f"/{bucket}", status=404)

    stmt = select(Object).where(Object.bucket == bucket)
    if prefix:
        stmt = stmt.where(Object.key.like(f"{prefix}%"))
    if continuation_token:
        stmt = stmt.where(Object.key > continuation_token)
    stmt = stmt.order_by(Object.key)

    all_objs = session.exec(stmt).all()

    result_objs: list[Object] = []
    common_prefixes: set[str] = set()

    for obj in all_objs:
        if delimiter:
            after = obj.key[len(prefix):]
            pos = after.find(delimiter)
            if pos >= 0:
                common_prefixes.add(prefix + after[: pos + len(delimiter)])
                continue
        result_objs.append(obj)

    is_truncated = len(result_objs) > max_keys
    if is_truncated:
        result_objs = result_objs[:max_keys]

    next_token = result_objs[-1].key if is_truncated else None
    key_count = len(result_objs) + len(common_prefixes)

    body = _xml.build_list_objects_response(
        bucket=bucket,
        prefix=prefix,
        delimiter=delimiter,
        max_keys=max_keys,
        objects=[
            {
                "key": obj.key,
                "last_modified": obj.last_modified,
                "etag": obj.etag,
                "size": obj.size,
            }
            for obj in result_objs
        ],
        common_prefixes=sorted(common_prefixes),
        is_truncated=is_truncated,
        key_count=key_count,
        next_continuation_token=next_token,
    )
    return Response(content=body, media_type="application/xml")
