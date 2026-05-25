import os
import uuid
import xml.etree.ElementTree as ET

import pytest
from starlette.testclient import TestClient

S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


# ---------------------------------------------------------------------------
# Infrastructure de session — un seul processus FastAPI pour toute la suite
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def storage_root(tmp_path_factory):
    return tmp_path_factory.mktemp("s3_root")


@pytest.fixture(scope="session", autouse=True)
def configure_env(storage_root):
    """Positionne les variables d'environnement avant l'import de l'app."""
    os.environ["STORAGE_PATH"] = str(storage_root / "objects")
    os.environ["DB_PATH"] = str(storage_root / "metadata.db")


@pytest.fixture(scope="session")
def app(configure_env):
    from src.main import app  # noqa: PLC0415 — import tardif intentionnel
    return app


@pytest.fixture(scope="session")
def client(app) -> TestClient:
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Fixture bucket — crée un bucket isolé par test, nettoyage garanti
# ---------------------------------------------------------------------------

@pytest.fixture
def bucket(client: TestClient) -> str:
    """Bucket unique par test. Supprime tous les objets à la fin."""
    name = f"test-{uuid.uuid4().hex[:10]}"
    r = client.put(f"/{name}")
    assert r.status_code == 200, f"CreateBucket a échoué : {r.status_code} {r.text}"
    yield name
    _force_delete_bucket(client, name)


def _force_delete_bucket(client: TestClient, name: str) -> None:
    """Vide le bucket puis le supprime, quoi qu'il arrive."""
    while True:
        r = client.get(f"/{name}?list-type=2&max-keys=1000")
        if r.status_code != 200:
            break
        root = ET.fromstring(r.text)
        keys = [el.text for el in root.findall("s3:Contents/s3:Key", S3_NS)]
        if not keys:
            break
        body = "<Delete>" + "".join(f"<Object><Key>{k}</Key></Object>" for k in keys) + "</Delete>"
        client.post(
            f"/{name}?delete",
            content=body.encode(),
            headers={"Content-Type": "application/xml"},
        )
        if root.findtext("s3:IsTruncated", namespaces=S3_NS) != "true":
            break
    client.delete(f"/{name}")
