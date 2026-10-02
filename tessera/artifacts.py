from __future__ import annotations

import hashlib
import json
from pathlib import Path


def canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class LocalArtifactStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_json(self, key: str, payload: dict) -> dict:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = canonical_json(payload)
        path.write_bytes(body)
        return {"key": key, "sha256": hashlib.sha256(body).hexdigest(), "size": len(body), "backend": "filesystem"}

    def get_json(self, key: str) -> dict:
        return json.loads(self._path(key).read_bytes())

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if self.root not in candidate.parents:
            raise ValueError("Artifact key escapes configured storage root")
        return candidate

    def ping(self) -> bool:
        return self.root.is_dir()


class S3ArtifactStore:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str,
                 region: str = "us-east-1") -> None:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("S3 artifacts require the 's3' TESSERA dependency") from exc
        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint or None, region_name=region,
                                   aws_access_key_id=access_key or None,
                                   aws_secret_access_key=secret_key or None)

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except Exception:
                self.client.head_bucket(Bucket=self.bucket)

    def put_json(self, key: str, payload: dict) -> dict:
        body = canonical_json(payload)
        digest = hashlib.sha256(body).hexdigest()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/json",
                               Metadata={"sha256": digest}, ServerSideEncryption="AES256")
        return {"key": key, "sha256": digest, "size": len(body), "backend": "s3", "bucket": self.bucket}

    def get_json(self, key: str) -> dict:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"].read()
        expected = response.get("Metadata", {}).get("sha256")
        if expected and hashlib.sha256(body).hexdigest() != expected:
            raise ValueError("Artifact integrity check failed")
        return json.loads(body)

    def ping(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


def create_artifact_store(settings):
    if settings.object_storage_bucket:
        store = S3ArtifactStore(settings.object_storage_endpoint, settings.object_storage_bucket,
                                settings.object_storage_access_key, settings.object_storage_secret_key,
                                settings.object_storage_region)
        store.ensure_bucket()
        return store
    return LocalArtifactStore(settings.artifact_path)
