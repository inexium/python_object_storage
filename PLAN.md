# Plan d'implémentation

Ordre de réalisation optimisé pour avoir des tests verts le plus tôt possible.
Chaque étape débloque des tests existants sans maintenir du code mort en attente.

```
config → storage (tests unitaires verts) → xml_builder (tests unitaires verts)
       → database/models → main + buckets (premiers tests S3 verts)
       → objects → multipart (suite complète verte)
```

---

## Étapes

### 1. `src/config.py` ✅
Lecture des variables d'environnement (`STORAGE_PATH`, `DB_PATH`, `PORT`, etc.).
Tout le reste en dépend.

### 2. `src/services/storage.py` — `StorageService` ✅
Premier composant vérifiable par les tests unitaires (`tests/unit/test_storage.py`)
sans FastAPI ni base de données.
- Écriture/lecture de fichiers
- Compression zstd transparente
- `delete`, `exists`, `get_size`, `list`

### 3. `src/services/xml_builder.py` — `XmlBuilder`
`tests/unit/test_xml_builder.py` tourne sans app.
Construire la sérialisation XML en premier évite de mélanger logique de
sérialisation et logique HTTP.

### 4. `src/database.py` + `src/models/`
SQLModel models (`Bucket`, `Object`, `MultipartUpload`, `Part`) et
initialisation SQLite. Nécessaire avant les routers.

### 5. `src/main.py` + `src/routers/buckets.py`
Les routes bucket sont les plus simples (pas de corps de requête complexe,
pas de streaming). C'est là que les tests S3 compat commencent à passer.

### 6. `src/routers/objects.py`
Dépend de `StorageService` et `XmlBuilder` — déjà bien fondé.
Points délicats : range requests et calcul d'ETag.

### 7. `src/routers/multipart.py`
Le plus complexe : état en base, assemblage des parties, calcul d'ETag
multipart (`"md5-N"`). À faire en dernier quand le reste est stable.
