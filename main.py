import logging
import os
import tempfile
import time
from read_data.file_reader import S3FileReader
from transformation.flac_transformer import FlacTranscriber
from storage_util import partition_storage

logging.basicConfig(filename='application.log', level=logging.INFO)
logger = logging.getLogger(__name__)

# Setting up a separate logger for timings
time_logger = logging.getLogger('time_logger')
time_handler = logging.FileHandler('timings.log')
time_logger.addHandler(time_handler)
time_logger.setLevel(logging.INFO)


class MainProcessor:
    BUCKET_NAME = 'data-engineer-test'
    ENDPOINT_URL = 'https://bdadc4417ecd7714dd7d42a104a276c2.r2.cloudflarestorage.com/'

    def __init__(self):
        self.file_manager = S3FileReader('r2', self.ENDPOINT_URL)
        self.processor = FlacTranscriber('base')
        self.data_structures = []

    def process(self):
        file_generator = self.file_manager.list_files(self.BUCKET_NAME)
        total_start_time = time.time()
        processing_times = []
        for file_key in file_generator:
            start_time = time.time()
            logger.info(f"Processing file: {file_key}")
            with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as temp_file:
                temp_file_path = temp_file.name
            self.file_manager.download_file(self.BUCKET_NAME, file_key, temp_file.name)
            processed_data = self.processor.process_audio(temp_file_path, file_key)
            self.data_structures.append(processed_data)
            os.remove(temp_file_path)

            end_time = time.time()
            elapsed_time = end_time - start_time
            processing_times.append(elapsed_time)
            time_logger.info(f"Time taken for {file_key}: {elapsed_time:.2f} seconds")

        total_end_time = time.time()
        total_elapsed_time = total_end_time - total_start_time

        avg_time_per_file = sum(processing_times) / len(processing_times) if processing_times else 0

        time_logger.info(f"Total time taken: {total_elapsed_time:.2f} seconds")
        time_logger.info(f"Average time taken per file: {avg_time_per_file:.2f} seconds")

        partition_storage.save_to_parquet(self.data_structures, destination='output',
                                          storage='s3', bucket_name=self.BUCKET_NAME, profile_name='r2',
                                          endpoint_url=self.ENDPOINT_URL)


if __name__ == "__main__":
    processor = MainProcessor()
    processor.process()
