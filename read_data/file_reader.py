import os
import boto3


class S3FileReader:
    def __init__(self, bucket_name):
        self.bucket_name = bucket_name

    def list_files_in_bucket(self, prefix, extension=".flac"):
        s3 = boto3.client('s3')
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            for content in page.get('Contents', []):
                if content['Key'].endswith(extension):
                    yield content['Key']

    def download_file(self, file_key, download_path):
        s3 = boto3.client('s3')
        s3.download_file(self.bucket_name, file_key, download_path)
