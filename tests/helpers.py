"""Utilitaires partagés pour parser les réponses XML S3 dans les tests."""

import base64
import hashlib
import xml.etree.ElementTree as ET

S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"
NS = {"s3": S3_NS}


def parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text)


def s3find(root: ET.Element, path: str) -> ET.Element | None:
    """Cherche un élément en utilisant le namespace S3."""
    return root.find("/".join(f"s3:{p}" for p in path.split("/")), NS)


def s3findall(root: ET.Element, path: str) -> list[ET.Element]:
    return root.findall("/".join(f"s3:{p}" for p in path.split("/")), NS)


def s3text(root: ET.Element, path: str) -> str | None:
    el = s3find(root, path)
    return el.text if el is not None else None


def parse_error(text: str) -> dict[str, str | None]:
    """Parse une réponse d'erreur S3 (sans namespace)."""
    root = ET.fromstring(text)
    return {
        "code": root.findtext("Code"),
        "message": root.findtext("Message"),
    }


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def md5_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode()


def expected_etag(data: bytes) -> str:
    """ETag S3 pour un objet simple : MD5 entre guillemets."""
    return f'"{md5_hex(data)}"'


def multipart_etag(part_etags: list[str]) -> str:
    """ETag S3 pour un objet multipart : MD5 des MD5 des parties + '-N'."""
    raw = b"".join(bytes.fromhex(e.strip('"')) for e in part_etags)
    return f'"{hashlib.md5(raw).hexdigest()}-{len(part_etags)}"'


def build_delete_xml(*keys: str) -> bytes:
    objects = "".join(f"<Object><Key>{k}</Key></Object>" for k in keys)
    return f"<Delete>{objects}</Delete>".encode()


def build_complete_multipart_xml(parts: list[tuple[int, str]]) -> bytes:
    """parts = [(part_number, etag), ...]"""
    inner = "".join(
        f"<Part><PartNumber>{n}</PartNumber><ETag>{etag}</ETag></Part>"
        for n, etag in parts
    )
    return f"<CompleteMultipartUpload>{inner}</CompleteMultipartUpload>".encode()
