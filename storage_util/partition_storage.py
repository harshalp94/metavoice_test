import os
import pandas as pd
import logging
import boto3
from io import BytesIO

logger = logging.getLogger(__name__)


def save_to_parquet(data, destination, partition_column='folder_name', storage='s3',
                    bucket_name=None, profile_name=None, endpoint_url=None):
    try:
        df = pd.DataFrame(data)

        if not destination.endswith('/'):
            destination += '/'

        # For each unique value in the partition column, save a partition
        for value in df[partition_column].unique():
            partition_df = df[df[partition_column] == value]

            path = f"{destination}{partition_column}={value}/data.parquet"

            if storage == 's3':
                try:
                    session = boto3.Session(profile_name=profile_name)
                    s3_resource = session.client('s3', endpoint_url=endpoint_url)
                    parquet_buffer = BytesIO()
                    partition_df.to_parquet(parquet_buffer, index=False)
                    s3_resource.put_object(Bucket=bucket_name, Key=path, Body=parquet_buffer.getvalue())
                except Exception as e:
                    logger.error(f"Failed to save data to S3 at {path}. Error: {e}")
                    raise

            elif storage == 'local':
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    partition_df.to_parquet(path, index=False)
                except Exception as e:
                    logger.error(f"Failed to save data locally at {path}. Error: {e}")
                    raise

            else:
                raise ValueError(f"Invalid storage option: {storage}. Choose either 's3' or 'local'.")

    except Exception as e:
        logger.error(f"Failed to save data to parquet. Error: {e}")
        raise
