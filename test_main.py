import tempfile

import whisper
import boto3
from transformation import test_token

# print(os.path.isfile("audio.mp3"))
# model = whisper.load_model("base")
# aud_str = 'audio.mp3'
# audio = whisper.load_audio(aud_str)
# audio = whisper.pad_or_trim(audio)
# result = model.transcribe(aud_str)
# print(result["text"])
# # make log-Mel spectrogram and move to the same device as the model
# mel = whisper.log_mel_spectrogram(audio).to(model.device)
#
# # detect the spoken language
# _, probs = model.detect_language(mel)
# print(f"Detected language: {max(probs, key=probs.get)}")
session = boto3.Session(profile_name='r2')
s3 = session.client('s3', endpoint_url='https://bdadc4417ecd7714dd7d42a104a276c2.r2.cloudflarestorage.com/')


def list_files_in_bucket(bucket_name, prefix=''):
    paginator = s3.get_paginator('list_objects_v2')
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


def download_file_s3(bucket_name, file_key, destination_path):
    s3.download_file(bucket_name, file_key, destination_path)


bucket_name = 'data-engineer-test'
file_generator = list_files_in_bucket(bucket_name)
first_file = next(file_generator, None)
if first_file:
    print(f"First file is: {first_file}")
else:
    print("No files found.")
# with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as temp_file:
#     temp_file_path = temp_file.name
#
# download_file_s3(bucket_name, first_file, temp_file_path)

print(first_file.split('/'))

# audio_data = whisper.load_audio(temp_file_path)
# model = whisper.load_model('large')
# result = model.transcribe(audio_data)
#
# print(test_token.tokenise(audio_data))
# print(result['text'])
