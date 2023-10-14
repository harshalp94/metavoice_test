import logging
import whisper
from transformation import test_token

logger = logging.getLogger(__name__)


class FlacTranscriber:
    def __init__(self, model_type):
        self.model = whisper.load_model(model_type)

    def process_audio(self, file_path, s3_path):
        try:
            folder_name = s3_path.split('/')[1]
            audio_data = whisper.load_audio(file_path)
            result = self.model.transcribe(audio_data)
            tokens = test_token.tokenise(audio_data)
            tokens_list = tokens.numpy().tolist()
            return {
                "folder_name": folder_name,
                "file_name": s3_path,
                "transcription": result['text'],
                "tokens": tokens_list
            }
        except Exception as e:
            logger.error(f"Error processing audio {file_path}: {str(e)}")
            raise
