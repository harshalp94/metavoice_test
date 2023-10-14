from abc import ABC, abstractmethod


class FileManager(ABC):
    @abstractmethod
    def list_files(self, bucket_name, prefix=''):
        pass

    @abstractmethod
    def download_file(self, bucket_name, file_key, destination_path):
        pass