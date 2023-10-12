import whisper
import os

print(os.path.isfile("audio.mp3"))
model = whisper.load_model("base")
aud_str = 'audio.mp3'
audio = whisper.load_audio(aud_str)
audio = whisper.pad_or_trim(audio)
result = model.transcribe(aud_str)
print(result["text"])
# make log-Mel spectrogram and move to the same device as the model
mel = whisper.log_mel_spectrogram(audio).to(model.device)

# detect the spoken language
_, probs = model.detect_language(mel)
print(f"Detected language: {max(probs, key=probs.get)}")
