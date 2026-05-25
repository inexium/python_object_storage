# CLAUDE.md — python_object_storage

Stockage objet compatible AWS S3, écrit en Python 3.13. L'API implémente les routes S3 de base (buckets, objets, multipart uploads) et est conçue pour tourner en conteneur Docker.

## Stack technique

| Composant | Rôle |
|-----------|------|
| **FastAPI** | Serveur HTTP, routing S3, serialisation XML |
| **SQLModel** | ORM — modèles de métadonnées (buckets, objets, parts) |
| **SQLite** | Base de données embarquée pour les métadonnées |
| **ctypes** | Bindings C bas niveau si nécessaire (checksums, crypto) |
| **zstandard** | Compression des objets stockés sur disque |
| **Docker** | Conteneurisation et déploiement |
| **pytest** | Tests unitaires et de compatibilité S3 |
| **uv** | Gestionnaire de paquets et d'environnements virtuels |

## Commandes essentielles

```bash
# Installer les dépendances
uv sync

# Lancer le serveur en développement
uv run fastapi dev src/main.py

# Lancer le serveur en production
uv run fastapi run src/main.py

# Lancer tous les tests
uv run pytest

# Lancer les tests avec couverture
uv run pytest --cov=src --cov-report=term-missing

# Lancer uniquement les tests de compatibilité S3
uv run pytest tests/s3_compat/

# Lancer uniquement les tests unitaires
uv run pytest tests/unit/

# Build Docker
docker build -t python-object-storage .

# Lancer avec Docker Compose
docker compose up -d
```

## Structure du projet

```
python_object_storage/
├── src/
│   ├── main.py               # Point d'entrée FastAPI, montage des routers
│   ├── config.py             # Settings (chemin stockage, port, etc.)
│   ├── database.py           # Initialisation SQLite + session SQLModel
│   ├── models/
│   │   ├── bucket.py         # Modèle SQLModel Bucket
│   │   ├── object.py         # Modèle SQLModel Object
│   │   └── multipart.py      # Modèles UploadPart, MultipartUpload
│   ├── routers/
│   │   ├── buckets.py        # Routes S3 bucket (PUT, GET, DELETE, HEAD)
│   │   ├── objects.py        # Routes S3 object (PUT, GET, DELETE, HEAD, COPY)
│   │   └── multipart.py      # Routes multipart upload
│   ├── services/
│   │   ├── storage.py        # Lecture/écriture fichiers + compression zstd
│   │   └── xml_builder.py    # Construction des réponses XML compatibles S3
│   └── middleware/
│       └── auth.py           # Validation signature AWS SigV4 (optionnel)
├── tests/
│   ├── conftest.py           # Fixtures pytest (app, client, tmp storage)
│   ├── unit/                 # Tests unitaires par module
│   └── s3_compat/            # Tests de compatibilité AWS S3
│       ├── test_buckets.py
│       ├── test_objects.py
│       └── test_multipart.py
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── CLAUDE.md
```

## Routes S3 implémentées

### Buckets
| Méthode | Route | Action S3 |
|---------|-------|-----------|
| `PUT` | `/{bucket}` | CreateBucket |
| `GET` | `/` | ListBuckets |
| `GET` | `/{bucket}` | ListObjectsV2 |
| `HEAD` | `/{bucket}` | HeadBucket |
| `DELETE` | `/{bucket}` | DeleteBucket |

### Objets
| Méthode | Route | Action S3 |
|---------|-------|-----------|
| `PUT` | `/{bucket}/{key+}` | PutObject |
| `GET` | `/{bucket}/{key+}` | GetObject |
| `HEAD` | `/{bucket}/{key+}` | HeadObject |
| `DELETE` | `/{bucket}/{key+}` | DeleteObject |
| `DELETE` | `/{bucket}?delete` | DeleteObjects (batch) |
| `COPY` | `/{bucket}/{key+}` (header `x-amz-copy-source`) | CopyObject |

### Multipart Upload
| Méthode | Route | Action S3 |
|---------|-------|-----------|
| `POST` | `/{bucket}/{key+}?uploads` | CreateMultipartUpload |
| `PUT` | `/{bucket}/{key+}?partNumber&uploadId` | UploadPart |
| `POST` | `/{bucket}/{key+}?uploadId` | CompleteMultipartUpload |
| `DELETE` | `/{bucket}/{key+}?uploadId` | AbortMultipartUpload |
| `GET` | `/{bucket}?uploadId` | ListParts |

## Conventions de code

- **Réponses XML** : S3 attend du XML, pas du JSON — utiliser `xml_builder.py` et retourner `Response(content=xml, media_type="application/xml")`.
- **Codes HTTP S3** : respecter les codes exacts (ex. `409 BucketAlreadyExists`, `404 NoSuchBucket`, `404 NoSuchKey`).
- **ETag** : calculer le MD5 du contenu brut (avant compression) et l'exposer dans les headers et les réponses XML.
- **Compression** : les objets sont compressés avec zstd à l'écriture et décompressés à la lecture ; transparent pour le client.
- **Nommage** : snake_case pour les fonctions et variables, PascalCase pour les classes SQLModel.
- **Sessions DB** : utiliser le pattern `Depends(get_session)` de FastAPI pour toutes les routes accédant à SQLite.
- **Pas de commentaires évidents** : commenter uniquement les invariants non-triviaux (format de stockage zstd, calcul ETag multipart, etc.).

## Tests de compatibilité S3

Les tests utilisent `boto3` configuré sur `localhost` pour valider la compatibilité réelle avec le SDK AWS :

```python
# tests/conftest.py
import boto3
import pytest

@pytest.fixture
def s3_client(base_url):
    return boto3.client(
        "s3",
        endpoint_url=base_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
```

Chaque test de compatibilité doit passer avec `boto3` **et** avec des requêtes HTTP brutes pour garantir la conformité du protocole.

## Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `STORAGE_PATH` | `./data` | Répertoire racine des objets stockés |
| `DB_PATH` | `./data/metadata.db` | Chemin de la base SQLite |
| `HOST` | `0.0.0.0` | Adresse d'écoute |
| `PORT` | `9000` | Port d'écoute |
| `LOG_LEVEL` | `info` | Niveau de log uvicorn |
| `ZSTD_LEVEL` | `3` | Niveau de compression (1-22) |

## Docker

```yaml
# docker-compose.yml — usage typique
services:
  storage:
    build: .
    ports:
      - "9000:9000"
    volumes:
      - ./data:/data
    environment:
      STORAGE_PATH: /data/objects
      DB_PATH: /data/metadata.db
```

## Dépendances clés (pyproject.toml)

```toml
[project]
requires-python = ">=3.13"

[project.dependencies]
fastapi = ">=0.115"
sqlmodel = ">=0.0.21"
uvicorn = { extras = ["standard"], version = ">=0.32" }
zstandard = ">=0.23"
python-multipart = ">=0.0.12"

[tool.uv]
dev-dependencies = [
    "pytest>=8",
    "pytest-cov>=6",
    "httpx>=0.27",        # client de test ASGI
    "boto3>=1.35",        # tests de compatibilité S3
    "anyio[trio]>=4",
]
```

## Pièges connus

- **ListObjectsV2 vs ListObjects** : S3 a deux versions ; implémenter V2 en priorité (paramètre `list-type=2`), V1 en fallback.
- **ETag multipart** : le format est `"<md5_des_md5_parts>-<nombre_parts>"`, différent d'un objet simple.
- **Content-MD5** : certains clients S3 envoient ce header pour valider l'upload ; le vérifier si présent.
- **Trailing slash dans les clés** : les "dossiers" S3 sont des objets avec une clé se terminant par `/`.
- **URL path encoding** : les clés d'objets peuvent contenir des caractères spéciaux encodés en URL ; toujours décoder avant usage.
