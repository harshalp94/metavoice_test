import tempfile
from io import BytesIO

import pytest

from storage_util.version_store import VersionStore

SAMPLE_DATA = [
    {'folder_name': 'p225', 'file_name': 'p225/a.flac', 'transcription': 'hello', 'token': [[1.0, 2.0]]},
    {'folder_name': 'p225', 'file_name': 'p225/b.flac', 'transcription': 'world', 'token': [[3.0, 4.0]]},
    {'folder_name': 'p226', 'file_name': 'p226/c.flac', 'transcription': 'again', 'token': [[5.0, 6.0]]},
]

UPDATED_DATA = [
    {'folder_name': 'p225', 'file_name': 'p225/a.flac', 'transcription': 'hello fixed', 'token': [[1.0, 2.0]]},
]


class FakeS3Client:
    """In-memory stand-in for the boto3 S3 client, for tests without credentials."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.read()

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(f"NoSuchKey: {Key}")
        return {'Body': BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


@pytest.fixture
def local_store():
    with tempfile.TemporaryDirectory() as temp_dir:
        yield VersionStore(destination=temp_dir, storage='local')


def test_write_and_read_latest(local_store):
    version = local_store.write(SAMPLE_DATA)
    assert version == 1
    df = local_store.read()
    assert len(df) == 3
    assert sorted(df['file_name']) == ['p225/a.flac', 'p225/b.flac', 'p226/c.flac']


def test_versions_are_immutable_and_addressable(local_store):
    local_store.write(SAMPLE_DATA)
    local_store.write(UPDATED_DATA)

    assert local_store.latest_version() == 2
    assert len(local_store.read()) == 1
    assert len(local_store.read(1)) == 3
    assert local_store.read(2)['transcription'][0] == 'hello fixed'


def test_partitioned_write(local_store):
    local_store.write(SAMPLE_DATA, partition_column='folder_name')

    versions = local_store.list_versions()
    assert versions[0]['files'] == [
        'v1/folder_name=p225/data.parquet',
        'v1/folder_name=p226/data.parquet',
    ]
    assert len(local_store.read()) == 3


def test_list_versions_metadata(local_store):
    local_store.write(SAMPLE_DATA, note='first run')
    local_store.write(UPDATED_DATA, note='fixed transcription')

    versions = local_store.list_versions()
    assert [v['version'] for v in versions] == [1, 2]
    assert [v['rows'] for v in versions] == [3, 1]
    assert versions[1]['note'] == 'fixed transcription'
    assert all(v['created_at'] for v in versions)


def test_rollback(local_store):
    local_store.write(SAMPLE_DATA)
    local_store.write(UPDATED_DATA)

    local_store.rollback(1)
    assert local_store.latest_version() == 1
    assert len(local_store.read()) == 3
    # Rolled-past version is still there, just no longer the default
    assert len(local_store.read(2)) == 1


def test_delete_version(local_store):
    local_store.write(SAMPLE_DATA)
    local_store.write(UPDATED_DATA)

    local_store.delete_version(1)
    assert [v['version'] for v in local_store.list_versions()] == [2]
    with pytest.raises(ValueError):
        local_store.read(1)


def test_cannot_delete_latest_version(local_store):
    local_store.write(SAMPLE_DATA)
    with pytest.raises(ValueError):
        local_store.delete_version(1)


def test_version_numbers_are_never_reused(local_store):
    local_store.write(SAMPLE_DATA)
    local_store.write(UPDATED_DATA)
    local_store.rollback(1)
    local_store.delete_version(2)

    assert local_store.write(SAMPLE_DATA) == 3


def test_empty_store(local_store):
    assert local_store.latest_version() is None
    assert local_store.list_versions() == []
    with pytest.raises(ValueError):
        local_store.read()


def test_write_empty_data_raises(local_store):
    with pytest.raises(ValueError):
        local_store.write([])


def test_invalid_storage_option():
    with pytest.raises(ValueError):
        VersionStore(destination='output', storage='ftp')


def test_s3_store_roundtrip():
    fake_s3 = FakeS3Client()
    store = VersionStore(destination='output', storage='s3',
                         bucket_name='test-bucket', s3_client=fake_s3)

    store.write(SAMPLE_DATA, partition_column='folder_name', note='pipeline run')
    store.write(UPDATED_DATA)

    assert ('test-bucket', 'output/manifest.json') in fake_s3.objects
    assert ('test-bucket', 'output/v1/folder_name=p225/data.parquet') in fake_s3.objects
    assert len(store.read(1)) == 3
    assert len(store.read()) == 1

    store.rollback(1)
    assert len(store.read()) == 3

    store.delete_version(2)
    assert ('test-bucket', 'output/v2/data.parquet') not in fake_s3.objects
