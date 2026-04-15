use std::fmt;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug)]
pub enum Error {
    Io(std::io::Error),
    Ort(ort::Error),
    Audio(String),
    Model(String),
    Tokenizer(String),
    Config(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Io(e) => write!(f, "IO error: {e}"),
            Error::Ort(e) => write!(f, "ONNX Runtime error: {e}"),
            Error::Audio(msg) => write!(f, "Audio processing error: {msg}"),
            Error::Model(msg) => write!(f, "Model error: {msg}"),
            Error::Tokenizer(msg) => write!(f, "Tokenizer error: {msg}"),
            Error::Config(msg) => write!(f, "Config error: {msg}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e)
    }
}

impl From<ort::Error> for Error {
    fn from(e: ort::Error) -> Self {
        Error::Ort(e)
    }
}

impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        Error::Config(e.to_string())
    }
}

impl From<hound::Error> for Error {
    fn from(e: hound::Error) -> Self {
        Error::Audio(e.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_display_io_error() {
        let err = Error::Io(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "file not found",
        ));
        let msg = format!("{}", err);
        assert!(msg.contains("IO error"));
        assert!(msg.contains("file not found"));
    }

    #[test]
    fn test_display_audio_error() {
        let err = Error::Audio("bad sample".to_string());
        let msg = format!("{}", err);
        assert!(msg.contains("Audio processing error"));
        assert!(msg.contains("bad sample"));
    }

    #[test]
    fn test_display_model_error() {
        let err = Error::Model("no weights".to_string());
        let msg = format!("{}", err);
        assert!(msg.contains("Model error"));
    }

    #[test]
    fn test_display_tokenizer_error() {
        let err = Error::Tokenizer("bad token".to_string());
        let msg = format!("{}", err);
        assert!(msg.contains("Tokenizer error"));
    }

    #[test]
    fn test_display_config_error() {
        let err = Error::Config("missing field".to_string());
        let msg = format!("{}", err);
        assert!(msg.contains("Config error"));
    }

    #[test]
    fn test_from_io_error() {
        let io_err = std::io::Error::new(std::io::ErrorKind::PermissionDenied, "denied");
        let err: Error = io_err.into();
        match err {
            Error::Io(_) => {}
            _ => panic!("Expected Io variant"),
        }
    }

    #[test]
    fn test_debug_format() {
        let err = Error::Audio("test".to_string());
        let debug = format!("{:?}", err);
        assert!(debug.contains("Audio"));
    }

    #[test]
    fn test_error_is_send_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<Error>();
    }
}
