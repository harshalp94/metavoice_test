"""Versioned storage for the processed pipeline output.

Every write creates a new immutable version instead of overwriting the
previous output. Layout inside the destination (local directory or S3 prefix):

    {destination}/manifest.json                          <- version metadata + latest pointer
    {destination}/v1/data.parquet                        <- unpartitioned version
    {destination}/v2/{partition_column}={value}/data.parquet  <- partitioned version

The manifest is written last, so a crashed write leaves no visible version.
Designed for a single writer (the pipeline run), any number of readers.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from io import BytesIO

import boto3
import pandas as pd

logger = logging.getLogger(__name__)

MANIFEST_FILE = 'manifest.json'


class StorageBackend(ABC):
    @abstractmethod
    def read_bytes(self, key):
        pass

    @abstractmethod
    def write_bytes(self, key, data):
        pass

    @abstractmethod
    def delete(self, key):
        pass


class LocalBackend(StorageBackend):
    def __init__(self, root):
        self.root = root

    def _full_path(self, key):
        return os.path.join(self.root, *key.split('/'))

    def read_bytes(self, key):
        with open(self._full_path(key), 'rb') as f:
            return f.read()

    def write_bytes(self, key, data):
        path = self._full_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)

    def delete(self, key):
        path = self._full_path(key)
        if os.path.isfile(path):
            os.remove(path)
        # Prune directories left empty by the delete, but never the store root
        directory = os.path.dirname(path)
        root = os.path.abspath(self.root)
        while (os.path.abspath(directory) != root and os.path.isdir(directory)
               and not os.listdir(directory)):
            os.rmdir(directory)
            directory = os.path.dirname(directory)


class S3Backend(StorageBackend):
    def __init__(self, s3_client, bucket_name, prefix):
        self.s3 = s3_client
        self.bucket_name = bucket_name
        self.prefix = prefix.strip('/')

    def _full_key(self, key):
        return f"{self.prefix}/{key}" if self.prefix else key

    def read_bytes(self, key):
        response = self.s3.get_object(Bucket=self.bucket_name, Key=self._full_key(key))
        return response['Body'].read()

    def write_bytes(self, key, data):
        self.s3.put_object(Bucket=self.bucket_name, Key=self._full_key(key), Body=data)

    def delete(self, key):
        self.s3.delete_object(Bucket=self.bucket_name, Key=self._full_key(key))


class VersionStore:
    def __init__(self, destination, storage='s3', bucket_name=None, profile_name=None,
                 endpoint_url=None, s3_client=None):
        if storage == 's3':
            if bucket_name is None:
                raise ValueError("bucket_name is required when storage is 's3'.")
            if s3_client is None:
                session = boto3.Session(profile_name=profile_name)
                s3_client = session.client('s3', endpoint_url=endpoint_url)
            self.backend = S3Backend(s3_client, bucket_name, destination)
        elif storage == 'local':
            self.backend = LocalBackend(destination)
        else:
            raise ValueError(f"Invalid storage option: {storage}. Choose either 's3' or 'local'.")

    def write(self, data, partition_column=None, note=''):
        """Store data as a new version and return its version number."""
        df = pd.DataFrame(data)
        if df.empty:
            raise ValueError("Cannot write an empty version to the version store.")

        manifest = self._load_manifest()
        version = manifest['version_counter'] + 1
        files = []
        try:
            if partition_column is not None:
                for value in df[partition_column].unique():
                    partition_df = df[df[partition_column] == value]
                    key = f"v{version}/{partition_column}={value}/data.parquet"
                    self._write_parquet(key, partition_df)
                    files.append(key)
            else:
                key = f"v{version}/data.parquet"
                self._write_parquet(key, df)
                files.append(key)
        except Exception as e:
            logger.error(f"Failed to write version {version}. Error: {e}")
            raise

        manifest['versions'].append({
            'version': version,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'rows': int(len(df)),
            'partition_column': partition_column,
            'note': note,
            'files': files,
        })
        manifest['latest_version'] = version
        manifest['version_counter'] = version
        self._save_manifest(manifest)
        logger.info(f"Wrote version {version} ({len(df)} rows in {len(files)} files)")
        return version

    def read(self, version=None):
        """Return a version as a DataFrame. Defaults to the latest version."""
        manifest = self._load_manifest()
        if version is None:
            version = manifest['latest_version']
            if version is None:
                raise ValueError("The version store is empty.")
        entry = self._find_version(manifest, version)
        frames = [pd.read_parquet(BytesIO(self.backend.read_bytes(key)))
                  for key in entry['files']]
        return pd.concat(frames, ignore_index=True)

    def list_versions(self):
        """Return the metadata of every stored version, oldest first."""
        return [dict(entry) for entry in self._load_manifest()['versions']]

    def latest_version(self):
        """Return the version number reads default to, or None if the store is empty."""
        return self._load_manifest()['latest_version']

    def rollback(self, version):
        """Point the latest version back at an older version. No data is deleted."""
        manifest = self._load_manifest()
        self._find_version(manifest, version)
        manifest['latest_version'] = version
        self._save_manifest(manifest)
        logger.info(f"Rolled back latest version to {version}")

    def delete_version(self, version):
        """Delete a version's data and metadata. The latest version cannot be deleted."""
        manifest = self._load_manifest()
        entry = self._find_version(manifest, version)
        if version == manifest['latest_version']:
            raise ValueError(f"Version {version} is the latest version. "
                             f"Roll back to another version before deleting it.")
        for key in entry['files']:
            self.backend.delete(key)
        manifest['versions'] = [v for v in manifest['versions'] if v['version'] != version]
        self._save_manifest(manifest)
        logger.info(f"Deleted version {version}")

    def _load_manifest(self):
        try:
            return json.loads(self.backend.read_bytes(MANIFEST_FILE).decode('utf-8'))
        except Exception:
            logger.info("No manifest found, starting an empty version store.")
            return {'latest_version': None, 'version_counter': 0, 'versions': []}

    def _save_manifest(self, manifest):
        self.backend.write_bytes(MANIFEST_FILE, json.dumps(manifest, indent=2).encode('utf-8'))

    def _write_parquet(self, key, df):
        buffer = BytesIO()
        df.to_parquet(buffer, index=False)
        self.backend.write_bytes(key, buffer.getvalue())

    @staticmethod
    def _find_version(manifest, version):
        for entry in manifest['versions']:
            if entry['version'] == version:
                return entry
        raise ValueError(f"Version {version} does not exist in the version store.")
