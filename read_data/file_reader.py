import logging
import os
import boto3
from read_data.file_manager import FileManager

logger = logging.getLogger(__name__)


class S3FileReader(FileManager):
    def __init__(self, session_profile, endpoint_url):
        self.session = boto3.Session(profile_name=session_profile)
        self.s3 = self.session.client('s3', endpoint_url=endpoint_url)

    def list_files(self, bucket_name, prefix=''):
        paginator = self.s3.get_paginator('list_objects_v2')
        folders_to_process = [prefix]

        while folders_to_process:
            current_prefix = folders_to_process.pop(0)

            for page in paginator.paginate(Bucket=bucket_name, Prefix=current_prefix):
                for content in page.get('Contents', []):
                    file_key = content['Key']
                    if file_key.endswith('/'):
                        folders_to_process.append(file_key)
                    elif file_key.endswith('.flac'):
                        yield file_key

    def download_file(self, bucket_name, file_key, destination_path):
        try:
            self.s3.download_file(bucket_name, file_key, destination_path)
        except Exception as e:
            logger.error(f"Error downloading {file_key} from {bucket_name}: {str(e)}")
            raise
