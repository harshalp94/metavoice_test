# Metavoice Test

<!-- TOC -->
* [Metavoice Test](#metavoice-test)
  * [Reading of files.](#reading-of-files-)
    * [S3 File reader](#s3-file-reader)
  * [Processing](#processing)
    * [flac_transformer](#flactransformer)
      * [1. Transcription](#1-transcription)
      * [2. Tokenization](#2-tokenization)
  * [Storage](#storage)
    * [Version store](#version-store)
  * [Performance](#performance)
  * [Extensibility](#extensibility)
<!-- TOC -->


## Reading of files. 
To read the files from the provided S3 bucket, you must create an AWS profile and set the secret and access keys. The endpoint URL and profile are directly used in the main file.

You can configure this using the aws-cli with the following command:
````
aws configure --profile r2
````
This command will prompt you to enter the following four parameters: 

````
 1. Access Key
 2. Secret Key
 3. Region
 4. File format
````
Configure these parameters based on your credentials and region.

### S3 File reader
For reading the files from the S3 bucket, I have created an interface file_manager, which can be extended according to the implementation. 


For this task, I am listing the files from the S3 bucket, putting them in a list, and then using a generator, I take a single name, download that file to a temporary location using the python library tempfile, which keeps the file in the temp location till my processing is complete. Once the processing is complete, the temp file is deleted.

This helps me keep a single file in memory while processing. The processing can be further enhanced using a streaming service like Apache Kafka/RabbitMQ or any other message queue to distribute the reading file. 
We can distribute the reading and processing parts among several nodes using a message queue service.


```mermaid
graph LR
a[List of S3 Files]-->b[Select File];
b[Select File]-->c[(Temp Storage)];
c[(Temp Storage)] --> d[Processor];
d[Processor] --> e[Delete Temp File];
```
## Processing
For processing, I have created a transformation package in which there are two files, flac_transformer and test_tokens
### flac_transformer
The flac_transformer takes the given input file (.flac file in our case) and processes it. The processing is done in two parts.
#### 1. Transcription
The Transcription part is done using the Openai's Whisper library. The Whisper library gives us different models: tiny, base, medium, and large. For this task, I have used base model to transcribe the audio file. The base model did the transcription part correctly, and the large model took a long time to process small files; hence, the base model.
#### 2. Tokenization
The tokenization is done using the librosa library. I wasn't sure what tokenization wasn't in this case, so I went by the following links and paper I found on the internet regarding discrete audio representation(tokenization)
````
https://arxiv.org/pdf/2309.10922.pdf
https://www.analyticsvidhya.com/blog/2021/06/mfcc-technique-for-speech-recognition/
https://openreview.net/pdf?id=v8Mi8KU6056
````
The code used for tokenization and conversion to torch tensor is 
````
    mfccs = librosa.feature.mfcc(y=audio_np_array, sr=sr, n_mfcc=n_mfcc)
    mfcc_tensor = torch.tensor(mfccs, dtype=torch.float32)
````
The token is then converted into a list (list of lists). the conversion is necessary because we can't store tensors in a parquet file. This conversion facilitates storing the file containing the folder_name, file_name, transcription, and token in parquet format.

Once these two steps are completed, the file is stored in the provided S3 bucket.
## Storage
For storage, I use Pyarrow, fastparquet, and Pandas to store the file in the specified S3 bucket. I also wrote a partition_storage.py to partition the data based on the folder_name and store it in the S3 bucket.

Once all files are processed, the file is written, and a list of dictionaries has been created. The dictionary structure is:
````
 1. folder_name: This contains the folder name (p225)
 2. file_name: Relative path of the file in the S3 bucket
 3. Transcription: Transcribed text of the file
 4. Token: Tokenized representation of the audio file
````
The output file is named data.parquet and is stored in each folder. Folder creation is currently hardcoded in the main file, with the path format: s3://{bucket_name}/output/{partition_name}/data.parquet.
### Version store
Writing directly to output/ overwrites the previous run. storage_util/version_store.py adds a VersionStore that turns every write into a new immutable version instead, with a manifest tracking metadata and a latest pointer:
````
{destination}/manifest.json                              -> version metadata + latest pointer
{destination}/v1/data.parquet                            -> unpartitioned version
{destination}/v2/{partition_column}={value}/data.parquet -> partitioned version
````
It supports the same two storage options as partition_storage ('s3' and 'local') and uses the same AWS profile/endpoint configuration. Usage:
````python
from storage_util.version_store import VersionStore

store = VersionStore(destination='output', storage='s3', bucket_name=BUCKET_NAME,
                     profile_name='r2', endpoint_url=ENDPOINT_URL)

version = store.write(data_structures, partition_column='folder_name', note='full pipeline run')
df = store.read()        # latest version
df_v1 = store.read(1)    # a specific version
store.list_versions()    # metadata of every version (rows, created_at, note, files)
store.rollback(1)        # point latest back to v1, keeping the newer data
store.delete_version(2)  # remove a non-latest version's data and metadata
````
The manifest is written after the data files, so an interrupted write never leaves a visible half-written version, and version numbers are never reused after a delete. Unit tests live in test_version_store.py and run against a temporary local directory and an in-memory S3 fake, so they need no credentials.
## Performance
The application generates two logs, 
1. application.log - Application logs
2. timing.log - stores time required to process each file, average time per file and total time

The time to transcribe and tokenize the 11756 files was 7864.04 seconds, with the average file processing time being 0.67 seconds.
The time taken depends on the machine as well. With CUDA installed, the average time taken is 0.67 seconds; without CUDA installed, the time taken is around 60 seconds. 


## Extensibility
````
 1. The reading files can be extended by adding implementation of Apache Kafka, which can make the process of reading files distributed.
 2. Use of containerization to spawn multiple pods and process multiple folders sequentially instead of processing files.
 3. Using Dask/Spark to process the file in distributed manner to make the processing faster. 
 4. Using Dask partition to partition the parquet file, instead of manually creating partitions in the S3 bucket.
````
