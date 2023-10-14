import time
import torch
import numpy as np
import librosa


def tokenise(audio_np_array: np.ndarray, sr: int = 22050, n_mfcc: int = 13) -> torch.Tensor:
    """
    Function to tokenise an audio file represented as a NumPy array using MFCCs.

    Args:
    - audio_np_array (np.ndarray): The audio file as a NumPy array.
    - sr (int): Sample rate of the audio. Default is 22050Hz which is librosa's default.
    - n_mfcc (int): Number of MFCCs to compute. Default is 13.

    Returns:
    - torch.Tensor: A tensor containing the MFCCs of the audio.
    """

    # Check if the input is a NumPy array
    if not isinstance(audio_np_array, np.ndarray):
        raise ValueError("Input should be a NumPy array")

    mfccs = librosa.feature.mfcc(y=audio_np_array, sr=sr, n_mfcc=n_mfcc)

    mfcc_tensor = torch.tensor(mfccs, dtype=torch.float32)

    return mfcc_tensor
