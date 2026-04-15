use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PreprocessorConfig {
    pub feature_extractor_type: String,
    pub feature_size: usize,
    pub hop_length: usize,
    pub n_fft: usize,
    pub padding_side: String,
    pub padding_value: f32,
    pub preemphasis: f32,
    pub processor_class: String,
    pub return_attention_mask: bool,
    pub sampling_rate: usize,
    pub win_length: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelConfig {
    pub architectures: Vec<String>,
    pub vocab_size: usize,
    pub pad_token_id: usize,
}

impl Default for PreprocessorConfig {
    fn default() -> Self {
        Self {
            feature_extractor_type: "ParakeetFeatureExtractor".to_string(),
            feature_size: 80,
            hop_length: 160,
            n_fft: 512,
            padding_side: "right".to_string(),
            padding_value: 0.0,
            preemphasis: 0.97,
            processor_class: "ParakeetProcessor".to_string(),
            return_attention_mask: true,
            sampling_rate: 16000,
            win_length: 400,
        }
    }
}

impl Default for ModelConfig {
    fn default() -> Self {
        Self {
            architectures: vec!["ParakeetForCTC".to_string()],
            vocab_size: 1025,
            pad_token_id: 1024,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_preprocessor_config_defaults() {
        let config = PreprocessorConfig::default();
        assert_eq!(config.feature_size, 80);
        assert_eq!(config.hop_length, 160);
        assert_eq!(config.n_fft, 512);
        assert_eq!(config.sampling_rate, 16000);
        assert_eq!(config.win_length, 400);
        assert!((config.preemphasis - 0.97).abs() < 1e-6);
        assert!((config.padding_value).abs() < 1e-6);
        assert_eq!(config.padding_side, "right");
        assert!(config.return_attention_mask);
    }

    #[test]
    fn test_model_config_defaults() {
        let config = ModelConfig::default();
        assert_eq!(config.vocab_size, 1025);
        assert_eq!(config.pad_token_id, 1024);
        assert_eq!(config.architectures, vec!["ParakeetForCTC"]);
    }

    #[test]
    fn test_preprocessor_config_serde_roundtrip() {
        let config = PreprocessorConfig::default();
        let json = serde_json::to_string(&config).unwrap();
        let parsed: PreprocessorConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.feature_size, config.feature_size);
        assert_eq!(parsed.hop_length, config.hop_length);
        assert_eq!(parsed.n_fft, config.n_fft);
        assert_eq!(parsed.sampling_rate, config.sampling_rate);
        assert_eq!(parsed.win_length, config.win_length);
        assert!((parsed.preemphasis - config.preemphasis).abs() < 1e-6);
    }

    #[test]
    fn test_model_config_serde_roundtrip() {
        let config = ModelConfig::default();
        let json = serde_json::to_string(&config).unwrap();
        let parsed: ModelConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.vocab_size, config.vocab_size);
        assert_eq!(parsed.pad_token_id, config.pad_token_id);
        assert_eq!(parsed.architectures, config.architectures);
    }

    #[test]
    fn test_preprocessor_config_from_json() {
        let json = r#"{
            "feature_extractor_type": "CustomExtractor",
            "feature_size": 128,
            "hop_length": 160,
            "n_fft": 512,
            "padding_side": "left",
            "padding_value": 1.0,
            "preemphasis": 0.95,
            "processor_class": "CustomProcessor",
            "return_attention_mask": false,
            "sampling_rate": 16000,
            "win_length": 400
        }"#;
        let config: PreprocessorConfig = serde_json::from_str(json).unwrap();
        assert_eq!(config.feature_size, 128);
        assert_eq!(config.padding_side, "left");
        assert!((config.preemphasis - 0.95).abs() < 1e-6);
        assert!(!config.return_attention_mask);
    }
}
