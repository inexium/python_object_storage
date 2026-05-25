# python-object-storage

An AWS S3-compatible object storage server written in Python. Drop-in replacement for S3 in local and self-hosted environments — works with any S3 client (AWS CLI, boto3, s3cmd, …).

## Quick start

```bash
docker run -d \
  --name object-storage \
  -p 9000:9000 \
  -v s3-storage:/storage \
  ghcr.io/inexium/python_object_storage:main
```

The server is now available at `http://localhost:9000`.

## Volume layout

All persistent data lives under a single `/storage` volume:

```
/storage
├── data/     # compressed object blobs (zstd)
└── meta/     # SQLite metadata database
```

Mount a named volume (`-v s3-storage:/storage`) or a host directory (`-v /srv/s3:/storage`).

## Docker Compose

```yaml
services:
  storage:
    image: ghcr.io/inexium/python_object_storage:main
    ports:
      - "9000:9000"
    volumes:
      - s3-storage:/storage
    environment:
      ZSTD_LEVEL: 3      # compression level 1-22
      LOG_LEVEL: info

volumes:
  s3-storage:
```

```bash
docker compose up -d
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_PATH` | `/storage/data` | Object blobs directory |
| `DB_PATH` | `/storage/meta/metadata.db` | SQLite database path |
| `HOST` | `0.0.0.0` | Listen address |
| `PORT` | `9000` | Listen port |
| `LOG_LEVEL` | `info` | Uvicorn log level |
| `ZSTD_LEVEL` | `3` | Zstd compression level (1–22) |

## Usage

Configure any S3 client to point at `http://localhost:9000`. Credentials can be anything non-empty.

### AWS CLI

```bash
aws configure set aws_access_key_id     test
aws configure set aws_secret_access_key test

alias s3local="aws s3 --endpoint-url http://localhost:9000"

s3local mb s3://my-bucket
s3local cp file.txt s3://my-bucket/file.txt
s3local ls s3://my-bucket
s3local cp s3://my-bucket/file.txt ./downloaded.txt
s3local rm s3://my-bucket/file.txt
```

### boto3

```python
import boto3

s3 = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",
    aws_access_key_id="test",
    aws_secret_access_key="test",
    region_name="us-east-1",
)

s3.create_bucket(Bucket="my-bucket")
s3.put_object(Bucket="my-bucket", Key="hello.txt", Body=b"Hello, world!")
obj = s3.get_object(Bucket="my-bucket", Key="hello.txt")
print(obj["Body"].read())  # b'Hello, world!'
```

## Supported S3 operations

| Operation | Method + Path |
|-----------|--------------|
| ListBuckets | `GET /` |
| CreateBucket | `PUT /{bucket}` |
| HeadBucket | `HEAD /{bucket}` |
| DeleteBucket | `DELETE /{bucket}` |
| ListObjectsV2 | `GET /{bucket}` |
| PutObject | `PUT /{bucket}/{key}` |
| GetObject | `GET /{bucket}/{key}` |
| HeadObject | `HEAD /{bucket}/{key}` |
| DeleteObject | `DELETE /{bucket}/{key}` |
| DeleteObjects | `POST /{bucket}?delete` |
| CopyObject | `PUT /{bucket}/{key}` + `x-amz-copy-source` |
| CreateMultipartUpload | `POST /{bucket}/{key}?uploads` |
| UploadPart | `PUT /{bucket}/{key}?partNumber&uploadId` |
| CompleteMultipartUpload | `POST /{bucket}/{key}?uploadId` |
| AbortMultipartUpload | `DELETE /{bucket}/{key}?uploadId` |
| ListParts | `GET /{bucket}/{key}?uploadId` |

## Building from source

```bash
git clone https://github.com/inexium/python_object_storage
cd python_object_storage

docker build -t python-object-storage .

docker run -d -p 9000:9000 -v s3-storage:/storage python-object-storage
```
