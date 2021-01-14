import os
import pickle
import random
import librosa
import numpy as np
import soundfile
from tqdm import tqdm

import dataset.spectogram_features.spectogram_configs as cfg
from utils.plot_utils import plot_debug_image

MEL_FILTER_BANK_MATRIX = librosa.filters.mel(
    sr=cfg.working_sample_rate,
    n_fft=cfg.NFFT,
    n_mels=cfg.mel_bins,
    fmin=cfg.mel_min_freq,
    fmax=cfg.mel_max_freq).T


def read_multichannel_audio(audio_path, target_fs=None):
    """
    Read the audio samples in files and resample them to fit the desired sample ratre
    """
    (multichannel_audio, sample_rate) = soundfile.read(audio_path)
    if len(multichannel_audio.shape) == 1:
        multichannel_audio = multichannel_audio.reshape(-1, 1)
    if multichannel_audio.shape[1] < cfg.audio_channels:
        print(multichannel_audio.shape[1])
        multichannel_audio = np.repeat(multichannel_audio.mean(1).reshape(-1, 1), cfg.audio_channels, axis=1)
    elif cfg.audio_channels == 1:
        multichannel_audio = multichannel_audio.mean(1).reshape(-1, 1)
    elif multichannel_audio.shape[1] > cfg.audio_channels:
        multichannel_audio = multichannel_audio[:, :cfg.audio_channels]

    if target_fs is not None and sample_rate != target_fs:

        channels_num = multichannel_audio.shape[1]

        multichannel_audio = np.array(
            [librosa.resample(multichannel_audio[:, i], orig_sr=sample_rate, target_sr=target_fs) for i in range(channels_num)]
        ).T

    return multichannel_audio


def multichannel_stft(multichannel_signal):
    (samples, channels_num) = multichannel_signal.shape
    features = []
    for c in range(channels_num):
        complex_spectogram = librosa.core.stft(
                            y=multichannel_signal[:, c],
                            n_fft=cfg.NFFT,
                            win_length=cfg.frame_size,
                            hop_length=cfg.hop_size,
                            window=np.hanning(cfg.frame_size),
                            center=True,
                            dtype=np.complex64,
                            pad_mode='reflect').T
        '''(N, n_fft // 2 + 1)'''
        features.append(complex_spectogram)
    return np.array(features)


def multichannel_complex_to_log_mel(multichannel_complex_spectogram):
    multichannel_power_spectogram = np.abs(multichannel_complex_spectogram) ** 2
    multichannel_mel_spectogram = np.dot(multichannel_power_spectogram, MEL_FILTER_BANK_MATRIX)
    multichannel_logmel_spectogram = librosa.core.power_to_db(multichannel_mel_spectogram,
                                                              ref=1.0, amin=1e-10, top_db=None).astype(np.float32)

    return multichannel_logmel_spectogram


def calculate_scalar_of_tensor(x):
    if x.ndim == 2:
        axis = 0
    elif x.ndim == 3:
        axis = (0, 1)

    mean = np.mean(x, axis=axis)
    std = np.std(x, axis=axis)

    return mean, std


def preprocess_data(audio_path_and_labels, output_dir, output_mean_std_file, preprocess_mode='logMel'):
    os.makedirs(output_dir, exist_ok=True)

    all_features = []

    for (audio_path, start_times, end_times, audio_name) in tqdm(audio_path_and_labels):
        multichannel_waveform = read_multichannel_audio(audio_path=audio_path, target_fs=cfg.working_sample_rate)
        feature = multichannel_stft(multichannel_waveform)
        if preprocess_mode == 'logMel':
            feature = multichannel_complex_to_log_mel(feature)
        all_features.append(feature)

        output_path = os.path.join(output_dir, audio_name + f"_{preprocess_mode}_features_and_labels.pkl")
        with open(output_path, 'wb') as f:
            pickle.dump({'features': feature, 'start_times': start_times, 'end_times': end_times},
                        f)

    all_features = np.concatenate(all_features, axis=1)
    mean, std = calculate_scalar_of_tensor(all_features)
    with open(output_mean_std_file, 'wb') as f:
        pickle.dump({'mean': mean, 'std': std}, f)

    # Visualize single data sample
    (audio_path, start_times, end_times, audio_name) = random.choice(audio_path_and_labels)
    analyze_data_sample(audio_path, start_times, end_times, audio_name,
                        os.path.join(os.path.dirname(output_mean_std_file), "data_sample.png"))


def analyze_data_sample(audio_path, start_times, end_times, audio_name, plot_path):
    """
    A debug function that plots a single sample and analyzes how the spectogram configuration affect the feature final size
    """
    from dataset.spectogram_features.spectograms_dataset import create_event_matrix
    org_multichannel_audio, org_sample_rate = soundfile.read(audio_path)

    multichannel_audio = read_multichannel_audio(audio_path=audio_path, target_fs=cfg.working_sample_rate)
    feature = multichannel_stft(multichannel_audio)
    feature = multichannel_complex_to_log_mel(feature)
    first_channel_feature = feature[0]
    event_matrix = create_event_matrix(first_channel_feature.shape[0], start_times, end_times)
    file_name = f"{os.path.basename(os.path.dirname(audio_path))}_{os.path.splitext(os.path.basename(audio_path))[0]}"
    plot_debug_image(first_channel_feature, target=event_matrix, plot_path=plot_path, file_name=file_name)

    signal_time = multichannel_audio.shape[0]/cfg.working_sample_rate
    FPS = cfg.working_sample_rate / cfg.hop_size
    print(f"Data sample analysis: {audio_name}")
    print(f"\tOriginal audio: {org_multichannel_audio.shape} sample_rate={org_sample_rate}")
    print(f"\tsingle channel audio: {multichannel_audio.shape}, sample_rate={cfg.working_sample_rate}")
    print(f"\tSignal time is (num_samples/sample_rate)={signal_time:.1f}s")
    print(f"\tSIFT FPS is (sample_rate/hop_size)={FPS}")
    print(f"\tTotal number of frames is (FPS*signal_time)={FPS*signal_time:.1f}")
    print(f"\tEach frame covers {cfg.frame_size} samples or {cfg.frame_size / cfg.working_sample_rate:.3f} seconds "
          f"padded into {cfg.NFFT} samples and allow ({cfg.NFFT}//2+1)={cfg.NFFT // 2 + 1} frequency bins")
    print(f"\tFeatures shape: {feature.shape}")

