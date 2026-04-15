use crate::error::{Error, Result};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

/// Vocabulary parser for vocab.txt format used by TDT models
#[derive(Debug, Clone)]
pub struct Vocabulary {
    pub id_to_token: Vec<String>,
    pub _blank_id: usize,
}

impl Vocabulary {
    /// Load vocabulary from vocab.txt file
    pub fn from_file<P: AsRef<Path>>(path: P) -> Result<Self> {
        let file = File::open(path.as_ref())
            .map_err(|e| Error::Config(format!("Failed to open vocab file: {}", e)))?;

        let reader = BufReader::new(file);
        let mut id_to_token = Vec::new();
        let mut blank_id = 0;

        for line in reader.lines() {
            let line =
                line.map_err(|e| Error::Config(format!("Failed to read vocab file: {}", e)))?;

            let parts: Vec<&str> = line.splitn(2, ' ').collect();
            if parts.len() == 2 {
                let token = parts[0].to_string();
                let id: usize = parts[1]
                    .parse()
                    .map_err(|e| Error::Config(format!("Invalid token ID in vocab: {}", e)))?;

                if id >= id_to_token.len() {
                    id_to_token.resize(id + 1, String::new());
                }
                id_to_token[id] = token.clone();

                // Track blank token
                if token == "<blk>" || token == "<blank>" {
                    blank_id = id;
                }
            }
        }

        // Default to last token if no blank found
        if blank_id == 0 && !id_to_token.is_empty() {
            blank_id = id_to_token.len() - 1;
        }

        Ok(Self {
            id_to_token,
            _blank_id: blank_id,
        })
    }

    /// Get token by ID
    pub fn id_to_text(&self, id: usize) -> Option<&str> {
        self.id_to_token.get(id).map(|s| s.as_str())
    }

    /// Get vocabulary size (number of tokens)
    pub fn size(&self) -> usize {
        self.id_to_token.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write_vocab_file(entries: &[(&str, usize)]) -> String {
        use std::sync::atomic::{AtomicU64, Ordering};
        static COUNTER: AtomicU64 = AtomicU64::new(0);
        let id = COUNTER.fetch_add(1, Ordering::Relaxed);
        let path = format!("/tmp/test_vocab_{}.txt", id);
        let mut f = std::fs::File::create(&path).unwrap();
        for (token, idx) in entries {
            writeln!(f, "{} {}", token, idx).unwrap();
        }
        path
    }

    #[test]
    fn test_vocab_from_file_basic() {
        let path = write_vocab_file(&[("<blk>", 0), ("hello", 1), ("▁world", 2)]);
        let vocab = Vocabulary::from_file(&path).unwrap();
        assert_eq!(vocab.size(), 3);
        assert_eq!(vocab.id_to_text(0), Some("<blk>"));
        assert_eq!(vocab.id_to_text(1), Some("hello"));
        assert_eq!(vocab.id_to_text(2), Some("▁world"));
        std::fs::remove_file(&path).ok();
    }

    #[test]
    fn test_vocab_blank_detection_blk() {
        let path = write_vocab_file(&[("<blk>", 0), ("a", 1)]);
        let vocab = Vocabulary::from_file(&path).unwrap();
        assert_eq!(vocab._blank_id, 1);
        std::fs::remove_file(&path).ok();
    }

    #[test]
    fn test_vocab_blank_detection_blank() {
        let path = write_vocab_file(&[("<blank>", 0), ("a", 1)]);
        let vocab = Vocabulary::from_file(&path).unwrap();
        assert_eq!(vocab._blank_id, 1);
        std::fs::remove_file(&path).ok();
    }

    #[test]
    fn test_vocab_no_blank_defaults_to_last() {
        let path = write_vocab_file(&[("a", 0), ("b", 1), ("c", 2)]);
        let vocab = Vocabulary::from_file(&path).unwrap();
        assert_eq!(vocab._blank_id, 2);
        std::fs::remove_file(&path).ok();
    }

    #[test]
    fn test_vocab_sparse_ids() {
        let path = format!("/tmp/test_vocab_sparse_{}.txt", std::process::id());
        let mut f = std::fs::File::create(&path).unwrap();
        writeln!(f, "a 0").unwrap();
        writeln!(f, "z 25").unwrap();
        let vocab = Vocabulary::from_file(&path).unwrap();
        assert_eq!(vocab.size(), 26);
        assert_eq!(vocab.id_to_text(0), Some("a"));
        assert_eq!(vocab.id_to_text(25), Some("z"));
        assert_eq!(vocab.id_to_text(5), Some(""));
        std::fs::remove_file(&path).ok();
    }

    #[test]
    fn test_vocab_nonexistent_file() {
        let result = Vocabulary::from_file("/nonexistent/vocab.txt");
        assert!(result.is_err());
    }

    #[test]
    fn test_vocab_empty_file() {
        let path = format!("/tmp/test_vocab_empty_{}.txt", std::process::id());
        std::fs::write(&path, "").unwrap();
        let vocab = Vocabulary::from_file(&path).unwrap();
        assert_eq!(vocab.size(), 0);
        std::fs::remove_file(&path).ok();
    }

    #[test]
    fn test_vocab_skip_invalid_lines() {
        let path = format!("/tmp/test_vocab_mixed_{}.txt", std::process::id());
        let mut f = std::fs::File::create(&path).unwrap();
        writeln!(f, "a 0").unwrap();
        writeln!(f, "b 1").unwrap();
        writeln!(f, "").unwrap();
        writeln!(f, "nospace").unwrap();
        let vocab = Vocabulary::from_file(&path).unwrap();
        assert_eq!(vocab.size(), 2);
        std::fs::remove_file(&path).ok();
    }
}
