use parakeet_rs::{ExecutionConfig, ExecutionProvider, ParakeetTDT, TimestampMode, Transcriber, check_cuda_available};
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::process::Command;

fn env_usize(key: &str) -> Option<usize> {
    let raw = env::var(key).ok()?;
    let value = raw.trim().parse::<usize>().ok()?;
    if value == 0 {
        return None;
    }
    Some(value)
}

fn runtime_threads(requested_gpu: bool) -> (usize, usize) {
    let default_intra = if requested_gpu { 1 } else { 4 };
    let default_inter = 1;

    let intra = env_usize("DICTEE_INTRA_THREADS").unwrap_or(default_intra);
    let inter = env_usize("DICTEE_INTER_THREADS").unwrap_or(default_inter);
    (intra, inter)
}

fn chunk_seconds() -> usize {
    // Longer chunks reduce CPU overhead from repeated setup/teardown on long files.
    env_usize("DICTEE_CHUNK_SECS").unwrap_or(120)
}

/// Returns the user-specific socket path.
/// Uses $XDG_RUNTIME_DIR/transcribe.sock (default /run/user/UID/),
/// or /tmp/transcribe-UID.sock as fallback.
fn socket_path() -> String {
    if let Ok(dir) = env::var("XDG_RUNTIME_DIR") {
        format!("{}/transcribe.sock", dir)
    } else {
        format!("/tmp/transcribe-{}.sock", unsafe { libc::getuid() })
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let socket_path = socket_path();
    let args: Vec<String> = env::args().collect();

    if args.iter().any(|a| a == "--help" || a == "-h") {
        eprintln!("transcribe-daemon - Unix socket transcription server");
        eprintln!();
        eprintln!("Usage: transcribe-daemon [model_dir]");
        eprintln!();
        eprintln!("Arguments:");
        eprintln!("  [model_dir]   TDT model directory (default: /usr/share/dictee/tdt)");
        eprintln!();
        eprintln!("Listening on {}. Use with transcribe-client.", socket_path);
        return Ok(());
    }

    let model_dir = if args.len() > 1 {
        &args[1]
    } else {
        "/usr/share/dictee/tdt"
    };

    // Remove existing socket
    if Path::new(&socket_path).exists() {
        fs::remove_file(&socket_path)?;
    }

    // Configure CUDA if available
    #[cfg(feature = "cuda")]
    let (config, requested_gpu) = {
        eprintln!("=== CUDA Configuration ===");
        let gpu_ok = check_cuda_available();
        if gpu_ok {
            eprintln!("✓ CUDA provider requested and available");
            (ExecutionConfig::new().with_execution_provider(ExecutionProvider::Cuda), true)
        } else {
            notify_gpu_fallback();
            eprintln!("✗ CUDA provider requested but NOT available - falling back to CPU");
            (ExecutionConfig::new().with_execution_provider(ExecutionProvider::Cpu), false)
        }
    };
    #[cfg(not(feature = "cuda"))]
    let (config, requested_gpu) = {
        eprintln!("=== CUDA Configuration ===");
        eprintln!("✗ CUDA feature not compiled - using CPU");
        (ExecutionConfig::new().with_execution_provider(ExecutionProvider::Cpu), false)
    };

    let provider_label = if requested_gpu { "GPU (CUDA)" } else { "CPU" };
    let (intra_threads, inter_threads) = runtime_threads(requested_gpu);
    let config = config
        .with_intra_threads(intra_threads)
        .with_inter_threads(inter_threads);
    eprintln!("Requested execution provider: {}", provider_label);
    eprintln!("ORT threads: intra={}, inter={}", intra_threads, inter_threads);

    eprintln!("\n=== Loading Model ===");
    eprintln!("Model path: {}", model_dir);
    eprintln!("Environment variables:");
    if let Ok(val) = env::var("ORT_DYLIB_PATH") {
        eprintln!("  ORT_DYLIB_PATH: {}", val);
    }
    if let Ok(val) = env::var("LD_LIBRARY_PATH") {
        eprintln!("  LD_LIBRARY_PATH: {}", val);
    }
    if let Ok(val) = env::var("CUDA_VISIBLE_DEVICES") {
        eprintln!("  CUDA_VISIBLE_DEVICES: {}", val);
    }
    if let Ok(val) = env::var("ORT_CUDA_PROVIDER_ENABLED") {
        eprintln!("  ORT_CUDA_PROVIDER_ENABLED: {}", val);
    }

    let mut parakeet = ParakeetTDT::from_pretrained(model_dir, Some(config))?;
    eprintln!("\n✓ Model loaded successfully");
    eprintln!("Listening on {}", socket_path);

    let listener = UnixListener::bind(&socket_path)?;

    // Make socket accessible (only current user)
    fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600))?;

    for stream in listener.incoming() {
        match stream {
            Ok(mut stream) => {
                let reader = BufReader::new(&stream);

                // Read the audio file path from client
                if let Some(Ok(audio_path)) = reader.lines().next() {
                    let audio_path = audio_path.trim();

                    match transcribe_file(&mut parakeet, audio_path) {
                        Ok(text) => {
                            let _ = writeln!(stream, "{}", text);
                        }
                        Err(e) => {
                            let _ = writeln!(stream, "ERROR: {}", e);
                        }
                    }
                }
            }
            Err(e) => {
                eprintln!("Connection error: {}", e);
            }
        }
    }

    Ok(())
}

fn transcribe_file(
    parakeet: &mut ParakeetTDT,
    audio_path: &str,
) -> Result<String, Box<dyn std::error::Error>> {
    eprintln!("\n=== Transcription Started ===");
    eprintln!("Audio file: {}", audio_path);

    let start_time = std::time::Instant::now();

    let mut reader = hound::WavReader::open(audio_path)?;
    let spec = reader.spec();

    let audio: Vec<f32> = match spec.sample_format {
        hound::SampleFormat::Float => reader.samples::<f32>().collect::<Result<Vec<_>, _>>()?,
        hound::SampleFormat::Int => reader
            .samples::<i16>()
            .map(|s| s.map(|s| s as f32 / 32768.0))
            .collect::<Result<Vec<_>, _>>()?,
    };

    let chunk_secs = chunk_seconds();
    let chunk_samples = chunk_secs * spec.sample_rate as usize;
    let duration_secs = audio.len() as f64 / spec.sample_rate as f64;
    eprintln!("Audio duration: {:.2}s", duration_secs);
    eprintln!("Sample rate: {} Hz, Channels: {}", spec.sample_rate, spec.channels);
    eprintln!("Audio samples: {}", audio.len());

    if audio.len() <= chunk_samples {
        eprintln!("Processing as single chunk...");
        let chunk_start = std::time::Instant::now();

        let result = parakeet.transcribe_samples(
            audio,
            spec.sample_rate,
            spec.channels,
            Some(TimestampMode::Sentences),
        )?;

        let chunk_duration = chunk_start.elapsed();
        eprintln!("Transcription time: {:.2}s", chunk_duration.as_secs_f64());
        eprintln!("Realtime factor: {:.2}x", duration_secs / chunk_duration.as_secs_f64());
        eprintln!("=== Transcription Complete ===");
        return Ok(result.text.trim().to_string());
    }

    eprintln!(
        "Long audio ({:.1}s), splitting into {}s chunks...",
        duration_secs, chunk_secs
    );

    let total_chunks = (audio.len() + chunk_samples - 1) / chunk_samples;
    let mut parts: Vec<String> = Vec::new();

    for (i, chunk) in audio.chunks(chunk_samples).enumerate() {
        let mut chunk_vec = chunk.to_vec();
        if chunk_vec.len() < chunk_samples {
            chunk_vec.resize(chunk_samples, 0.0f32);
        }

        eprintln!("  Processing chunk {}/{}...", i + 1, total_chunks);
        let chunk_start = std::time::Instant::now();

        let result = parakeet.transcribe_samples(
            chunk_vec,
            spec.sample_rate,
            spec.channels,
            Some(TimestampMode::Sentences),
        )?;

        let chunk_duration = chunk_start.elapsed();
        eprintln!("    Chunk time: {:.2}s", chunk_duration.as_secs_f64());

        let text = result.text.trim().to_string();
        if !text.is_empty() {
            parts.push(text);
        }
    }

    let total_duration = start_time.elapsed();
    eprintln!("Total transcription time: {:.2}s", total_duration.as_secs_f64());
    eprintln!("Average realtime factor: {:.2}x", duration_secs / total_duration.as_secs_f64());
    eprintln!("=== Transcription Complete ===");

    Ok(parts.join(" "))
}

use std::os::unix::fs::PermissionsExt;

fn notify_gpu_fallback() {
    eprintln!("WARNING: CUDA unavailable — running on CPU. Check: libcufft, libcurand, cuda-cudnn packages");
    let _ = Command::new("notify-send")
        .args([
            "-u", "critical",
            "-t", "15000",
            "dictee: GPU unavailable!",
            "CUDA libraries not found — transcription running on CPU.\nInstall: libcufft libcurand cuda-cudnn"
        ])
        .spawn();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_chunk_samples_calculation() {
        let chunk_samples = 120 * 16000usize;
        assert_eq!(chunk_samples, 480000);
    }

    #[test]
    fn test_chunk_count_short_audio() {
        let chunk_samples = 120 * 16000usize;
        let audio_len = chunk_samples;
        let total_chunks = (audio_len + chunk_samples - 1) / chunk_samples;
        assert_eq!(total_chunks, 1);
    }

    #[test]
    fn test_chunk_count_exact_multiple() {
        let chunk_samples = 120 * 16000usize;
        let audio_len = chunk_samples * 3;
        let total_chunks = (audio_len + chunk_samples - 1) / chunk_samples;
        assert_eq!(total_chunks, 3);
    }

    #[test]
    fn test_chunk_count_with_remainder() {
        let chunk_samples = 120 * 16000usize;
        let audio_len = chunk_samples * 2 + 1000;
        let total_chunks = (audio_len + chunk_samples - 1) / chunk_samples;
        assert_eq!(total_chunks, 3);
    }

    #[test]
    fn test_chunk_basics_iterator() {
        let chunk_samples = 100;
        let audio: Vec<f32> = (0..250).map(|i| i as f32).collect();
        let chunks: Vec<&[f32]> = audio.chunks(chunk_samples).collect();
        assert_eq!(chunks.len(), 3);
        assert_eq!(chunks[0].len(), 100);
        assert_eq!(chunks[1].len(), 100);
        assert_eq!(chunks[2].len(), 50);
    }

    #[test]
    fn test_last_chunk_padding() {
        let chunk_samples = 100;
        let audio: Vec<f32> = (0..150).map(|i| i as f32).collect();
        let mut last_chunk = audio.chunks(chunk_samples).last().unwrap().to_vec();
        assert_eq!(last_chunk.len(), 50);
        last_chunk.resize(chunk_samples, 0.0f32);
        assert_eq!(last_chunk.len(), 100);
        assert_eq!(
            last_chunk[50..].iter().cloned().collect::<Vec<f32>>(),
            vec![0.0; 50]
        );
    }

    #[test]
    fn test_socket_path_format() {
        std::env::set_var("XDG_RUNTIME_DIR", "/run/user/1000");
        let path = socket_path();
        assert_eq!(path, "/run/user/1000/transcribe.sock");
        std::env::remove_var("XDG_RUNTIME_DIR");
    }

    #[test]
    fn test_duration_calculation() {
        let sample_rate: usize = 16000;
        let audio_len: usize = 16000 * 90;
        let duration = audio_len as f64 / sample_rate as f64;
        assert!((duration - 90.0).abs() < 1e-6);
    }
}
