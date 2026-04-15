use crate::config::PreprocessorConfig;
use crate::error::{Error, Result};
use hound::{WavReader, WavSpec};
use ndarray::Array2;
use std::f32::consts::PI;
use std::path::Path;

#[cfg(test)]
mod tests {
    use super::*;
    use hound::{WavSpec, WavWriter};
    use std::io::Cursor;

    #[allow(dead_code)]
    fn write_wav(samples: &[f32], sample_rate: u32, channels: u16) -> Vec<u8> {
        let spec = WavSpec {
            channels,
            sample_rate,
            bits_per_sample: 32,
            sample_format: hound::SampleFormat::Float,
        };
        let mut buf = Cursor::new(Vec::new());
        {
            let mut writer = WavWriter::new(&mut buf, spec).unwrap();
            for &s in samples {
                writer.write_sample(s).unwrap();
            }
            writer.finalize().unwrap();
        }
        buf.into_inner()
    }

    #[test]
    fn test_load_audio_float_wav() {
        let samples: Vec<f32> = vec![0.0, 0.5, -0.5, 1.0];
        let path = "test_load_float.wav";

        let spec = WavSpec {
            channels: 1,
            sample_rate: 16000,
            bits_per_sample: 32,
            sample_format: hound::SampleFormat::Float,
        };
        {
            let mut writer = WavWriter::create(path, spec).unwrap();
            for &s in &samples {
                writer.write_sample(s).unwrap();
            }
            writer.finalize().unwrap();
        }

        let (loaded, wav_spec) = load_audio(path).unwrap();
        assert_eq!(loaded.len(), 4);
        assert!((loaded[0] - 0.0).abs() < 1e-6);
        assert!((loaded[1] - 0.5).abs() < 1e-6);
        assert!((loaded[2] - (-0.5)).abs() < 1e-6);
        assert!((loaded[3] - 1.0).abs() < 1e-6);
        assert_eq!(wav_spec.sample_rate, 16000);
        assert_eq!(wav_spec.channels, 1);

        std::fs::remove_file(path).ok();
    }

    #[test]
    fn test_load_audio_int_wav() {
        let samples: Vec<i16> = vec![0, 16384, -16384, 32767];
        let path = "test_load_int.wav";
        let spec = WavSpec {
            channels: 1,
            sample_rate: 16000,
            bits_per_sample: 16,
            sample_format: hound::SampleFormat::Int,
        };
        {
            let mut writer = WavWriter::create(path, spec).unwrap();
            for &s in &samples {
                writer.write_sample(s).unwrap();
            }
            writer.finalize().unwrap();
        }

        let (loaded, wav_spec) = load_audio(path).unwrap();
        assert_eq!(loaded.len(), 4);
        assert!((loaded[0] - 0.0).abs() < 1e-4);
        assert!((loaded[1] - 0.5).abs() < 0.01);
        assert!((loaded[2] - (-0.5)).abs() < 0.01);
        assert_eq!(wav_spec.sample_rate, 16000);

        std::fs::remove_file(path).ok();
    }

    #[test]
    fn test_load_audio_nonexistent() {
        let result = load_audio("/nonexistent/path.wav");
        assert!(result.is_err());
    }

    #[test]
    fn test_apply_preemphasis_identity() {
        let audio = vec![1.0f32, 2.0, 3.0, 4.0];
        let result = apply_preemphasis(&audio, 0.0);
        assert_eq!(result, audio);
    }

    #[test]
    fn test_apply_preemphasis_standard() {
        let audio = vec![1.0f32, 2.0, 3.0, 4.0];
        let result = apply_preemphasis(&audio, 0.97);
        assert!((result[0] - 1.0).abs() < 1e-6);
        assert!((result[1] - (2.0 - 0.97 * 1.0)).abs() < 1e-6);
        assert!((result[2] - (3.0 - 0.97 * 2.0)).abs() < 1e-6);
        assert!((result[3] - (4.0 - 0.97 * 3.0)).abs() < 1e-6);
    }

    #[test]
    fn test_apply_preemphasis_single_sample() {
        let audio = vec![0.5f32];
        let result = apply_preemphasis(&audio, 0.97);
        assert_eq!(result.len(), 1);
        assert!((result[0] - 0.5).abs() < 1e-6);
    }

    #[test]
    fn test_hann_window() {
        let w = hann_window(4);
        assert_eq!(w.len(), 4);
        assert!((w[0]).abs() < 1e-6);
        assert!(w[1] > 0.0);
        assert!(w[2] > 0.0);
        assert!((w[3]).abs() < 1e-6);
    }

    #[test]
    fn test_stft_output_shape() {
        let audio = vec![0.0f32; 16000];
        let n_fft = 512;
        let hop_length = 160;
        let win_length = 400;
        let spec = stft(&audio, n_fft, hop_length, win_length);

        let freq_bins = n_fft / 2 + 1;
        assert_eq!(spec.shape()[0], freq_bins);
        assert!(spec.shape()[1] > 0);
    }

    #[test]
    fn test_stft_silence_is_near_zero() {
        let audio = vec![0.0f32; 16000];
        let spec = stft(&audio, 512, 160, 400);
        for val in spec.iter() {
            assert!(val.abs() < 1e-10);
        }
    }

    #[test]
    fn test_stft_sine_has_energy() {
        let sample_rate = 16000.0f32;
        let freq = 440.0f32;
        let audio: Vec<f32> = (0..16000)
            .map(|i| (2.0 * PI * freq * i as f32 / sample_rate).sin() * 0.5)
            .collect();
        let spec = stft(&audio, 512, 160, 400);
        let total_energy: f32 = spec.iter().sum();
        assert!(total_energy > 1.0);
    }

    #[test]
    fn test_create_mel_filterbank_shape() {
        let fb = create_mel_filterbank(512, 80, 16000);
        assert_eq!(fb.shape(), &[80, 257]);
    }

    #[test]
    fn test_create_mel_filterbank_nonnegative() {
        let fb = create_mel_filterbank(512, 80, 16000);
        for val in fb.iter() {
            assert!(*val >= 0.0);
        }
    }

    #[test]
    fn test_create_mel_filterbank_tdt_128() {
        let fb = create_mel_filterbank(512, 128, 16000);
        assert_eq!(fb.shape(), &[128, 257]);
        let sum: f32 = fb.iter().sum();
        assert!(sum > 0.0);
    }

    #[test]
    fn test_hz_to_mel_slaney_zero() {
        assert!((hz_to_mel_slaney(0.0)).abs() < 1e-10);
    }

    #[test]
    fn test_hz_to_mel_slaney_low() {
        let mel = hz_to_mel_slaney(100.0);
        assert!((mel - 100.0 / (200.0 / 3.0)).abs() < 1e-10);
    }

    #[test]
    fn test_hz_to_mel_slaney_high() {
        let mel = hz_to_mel_slaney(8000.0);
        assert!(mel > 0.0);
    }

    #[test]
    fn test_mel_to_hz_roundtrip() {
        for hz in [0.0, 100.0, 500.0, 1000.0, 4000.0, 8000.0] {
            let mel = hz_to_mel_slaney(hz);
            let hz_back = mel_to_hz_slaney(mel);
            assert!(
                (hz - hz_back).abs() < 1e-6,
                "roundtrip failed for {} Hz",
                hz
            );
        }
    }

    #[test]
    fn test_extract_features_wrong_sample_rate() {
        let audio = vec![0.0f32; 1600];
        let config = PreprocessorConfig::default();
        let result = extract_features_raw(audio, 8000, 1, &config);
        assert!(result.is_err());
        match result.unwrap_err() {
            Error::Audio(msg) => assert!(msg.contains("8000")),
            _ => panic!("Expected Audio error"),
        }
    }

    #[test]
    fn test_extract_features_stereo_downmix() {
        let audio: Vec<f32> = vec![1.0, 3.0, 2.0, 4.0];
        let config = PreprocessorConfig::default();
        let result = extract_features_raw(audio, 16000, 2, &config);
        assert!(result.is_ok());
        let features = result.unwrap();
        assert!(features.shape()[0] > 0);
        assert_eq!(features.shape()[1], config.feature_size);
    }

    #[test]
    fn test_extract_features_mono_shape() {
        let audio = vec![0.5f32; 16000];
        let config = PreprocessorConfig::default();
        let result = extract_features_raw(audio, 16000, 1, &config);
        assert!(result.is_ok());
        let features = result.unwrap();
        assert!(features.shape()[0] > 0);
        assert_eq!(features.shape()[1], config.feature_size);
    }
}

pub fn load_audio<P: AsRef<Path>>(path: P) -> Result<(Vec<f32>, WavSpec)> {
    let mut reader = WavReader::open(path)?;
    let spec = reader.spec();

    let samples: Vec<f32> = match spec.sample_format {
        hound::SampleFormat::Float => reader
            .samples::<f32>()
            .collect::<std::result::Result<Vec<_>, _>>()
            .map_err(|e| Error::Audio(format!("Failed to read float samples: {e}")))?,
        hound::SampleFormat::Int => reader
            .samples::<i16>()
            .map(|s| s.map(|s| s as f32 / 32768.0))
            .collect::<std::result::Result<Vec<_>, _>>()
            .map_err(|e| Error::Audio(format!("Failed to read int samples: {e}")))?,
    };

    Ok((samples, spec))
}

pub fn apply_preemphasis(audio: &[f32], coef: f32) -> Vec<f32> {
    let mut result = Vec::with_capacity(audio.len());
    result.push(audio[0]);

    for i in 1..audio.len() {
        result.push(audio[i] - coef * audio[i - 1]);
    }

    result
}

fn hann_window(window_length: usize) -> Vec<f32> {
    (0..window_length)
        .map(|i| 0.5 - 0.5 * ((2.0 * PI * i as f32) / (window_length as f32 - 1.0)).cos())
        .collect()
}

// We use proper FFT here instead of naive DFT because the model was trained
// on correctly computed spectrograms. Naive DFT produces wrong frequency bins
// and the model outputs all blank tokens. RustFFT gives us O(n log n) performance
// and numerically correct results that match what the model expects.
pub fn stft(audio: &[f32], n_fft: usize, hop_length: usize, win_length: usize) -> Array2<f32> {
    use rustfft::{num_complex::Complex, FftPlanner};

    let pad_amount = n_fft / 2;
    let mut padded = vec![0.0f32; pad_amount];
    padded.extend_from_slice(audio);
    padded.resize(padded.len() + pad_amount, 0.0);

    let window = hann_window(win_length);
    let num_frames = (padded.len() - n_fft) / hop_length + 1;
    let freq_bins = n_fft / 2 + 1;
    let mut spectrogram = Array2::<f32>::zeros((freq_bins, num_frames));

    let mut planner = FftPlanner::<f32>::new();
    let fft = planner.plan_fft_forward(n_fft);

    for frame_idx in 0..num_frames {
        let start = frame_idx * hop_length;

        let mut frame: Vec<Complex<f32>> = vec![Complex::new(0.0, 0.0); n_fft];
        for i in 0..win_length.min(padded.len() - start) {
            frame[i] = Complex::new(padded[start + i] * window[i], 0.0);
        }

        fft.process(&mut frame);

        for k in 0..freq_bins {
            let magnitude = frame[k].norm();
            spectrogram[[k, frame_idx]] = magnitude * magnitude;
        }
    }

    spectrogram
}

// Slaney mel scale (again librosa)
const F_SP: f64 = 200.0 / 3.0;
const MIN_LOG_HZ: f64 = 1000.0;
const MIN_LOG_MEL: f64 = MIN_LOG_HZ / F_SP;
const LOG_STEP: f64 = 0.06875177742094912;

fn hz_to_mel_slaney(hz: f64) -> f64 {
    if hz < MIN_LOG_HZ {
        hz / F_SP
    } else {
        MIN_LOG_MEL + (hz / MIN_LOG_HZ).ln() / LOG_STEP
    }
}

fn mel_to_hz_slaney(mel: f64) -> f64 {
    if mel < MIN_LOG_MEL {
        mel * F_SP
    } else {
        MIN_LOG_HZ * ((mel - MIN_LOG_MEL) * LOG_STEP).exp()
    }
}

pub fn create_mel_filterbank(n_fft: usize, n_mels: usize, sample_rate: usize) -> Array2<f32> {
    let freq_bins = n_fft / 2 + 1;
    let mut filterbank = Array2::<f32>::zeros((n_mels, freq_bins));

    let fmax = sample_rate as f64 / 2.0;
    let mel_min = hz_to_mel_slaney(0.0);
    let mel_max = hz_to_mel_slaney(fmax);

    // Mel cent freq
    let mel_points: Vec<f64> = (0..=n_mels + 1)
        .map(|i| mel_to_hz_slaney(mel_min + (mel_max - mel_min) * i as f64 / (n_mels + 1) as f64))
        .collect();

    // FFT bin freq
    let fft_freqs: Vec<f64> = (0..freq_bins)
        .map(|i| i as f64 * sample_rate as f64 / n_fft as f64)
        .collect();

    // librosa's ramp
    let fdiff: Vec<f64> = mel_points.windows(2).map(|w| w[1] - w[0]).collect();

    for i in 0..n_mels {
        for (k, &freq) in fft_freqs.iter().enumerate() {
            let lower = (freq - mel_points[i]) / fdiff[i];
            let upper = (mel_points[i + 2] - freq) / fdiff[i + 1];
            filterbank[[i, k]] = 0.0f64.max(lower.min(upper)) as f32;
        }
    }

    // Slaney norm
    for i in 0..n_mels {
        let enorm = 2.0 / (mel_points[i + 2] - mel_points[i]);
        for k in 0..freq_bins {
            filterbank[[i, k]] *= enorm as f32;
        }
    }

    filterbank
}

/// Extract mel spectrogram features from raw audio samples.
///
/// # Arguments
///
/// * `audio` - Audio samples as f32 values
/// * `sample_rate` - Sample rate in Hz
/// * `channels` - Number of audio channels
/// * `config` - Preprocessor configuration
///
/// # Returns
///
/// 2D array of mel spectrogram features (time_steps x feature_size)
pub fn extract_features_raw(
    mut audio: Vec<f32>,
    sample_rate: u32,
    channels: u16,
    config: &PreprocessorConfig,
) -> Result<Array2<f32>> {
    if sample_rate != config.sampling_rate as u32 {
        return Err(Error::Audio(format!(
            "Audio sample rate {} doesn't match expected {}. Please resample your audio first.",
            sample_rate, config.sampling_rate
        )));
    }

    if channels > 1 {
        let mono: Vec<f32> = audio
            .chunks(channels as usize)
            .map(|chunk| chunk.iter().sum::<f32>() / channels as f32)
            .collect();
        audio = mono;
    }

    audio = apply_preemphasis(&audio, config.preemphasis);

    let spectrogram = stft(&audio, config.n_fft, config.hop_length, config.win_length);

    let mel_filterbank =
        create_mel_filterbank(config.n_fft, config.feature_size, config.sampling_rate);
    let mel_spectrogram = mel_filterbank.dot(&spectrogram);
    // Log with additive guard (NeMo: log_zero_guard_type="add", value=2^-24)
    let log_zero_guard: f32 = 2.0f32.powi(-24);
    let mel_spectrogram = mel_spectrogram.mapv(|x| (x + log_zero_guard).ln());

    let mut mel_spectrogram = mel_spectrogram.t().to_owned();

    // Normalize per_feature: mean=0, std=1 with Bessel's correction (N-1)
    let num_frames = mel_spectrogram.shape()[0];
    let num_features = mel_spectrogram.shape()[1];

    for feat_idx in 0..num_features {
        let mut column = mel_spectrogram.column_mut(feat_idx);
        let mean: f32 = column.iter().sum::<f32>() / num_frames as f32;
        let variance: f32 =
            column.iter().map(|&x| (x - mean).powi(2)).sum::<f32>() / (num_frames as f32 - 1.0);
        let std = variance.sqrt() + 1e-5;

        for val in column.iter_mut() {
            *val = (*val - mean) / std;
        }
    }

    Ok(mel_spectrogram)
}
