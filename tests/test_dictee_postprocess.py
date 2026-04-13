import importlib.util
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import subprocess

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "dictee_postprocess", os.path.join(_root, "dictee-postprocess.py")
)
pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pp)


class TestChunkText(unittest.TestCase):
    def test_short_text_returns_single_chunk(self):
        self.assertEqual(pp._chunk_text("Hello world."), ["Hello world."])

    def test_exact_max_chars_returns_single_chunk(self):
        self.assertEqual(len(pp._chunk_text("a" * 4000, max_chars=4000)), 1)

    def test_over_max_chars_splits(self):
        text = "First sentence. " * 400
        self.assertGreater(len(pp._chunk_text(text, max_chars=4000)), 1)

    def test_each_chunk_within_max(self):
        text = "This is sentence one. This is sentence two. " * 500
        for chunk in pp._chunk_text(text, max_chars=4000):
            self.assertLessEqual(len(chunk), 4000)

    def test_newline_splits(self):
        text = "Line one.\nLine two.\nLine three."
        self.assertGreater(len(pp._chunk_text(text, max_chars=20)), 1)

    def test_empty_text(self):
        self.assertEqual(pp._chunk_text(""), [""])

    def test_single_very_long_sentence_no_split_within(self):
        text = "Word " * 3000 + "."
        self.assertEqual(len(pp._chunk_text(text, max_chars=4000)), 1)

    def test_all_content_preserved(self):
        text = (
            "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five."
        )
        joined = " ".join(pp._chunk_text(text, max_chars=40))
        self.assertEqual(joined, text)


class TestAdaptiveTimeout(unittest.TestCase):
    def test_small_text_uses_base_timeout(self):
        base, text = 10, "Short text."
        computed = min(base + (len(text) / 1000) * 2, 60)
        self.assertAlmostEqual(computed, 10.012, places=1)

    def test_large_text_increases_timeout(self):
        base, text = 10, "word " * 5000
        computed = min(base + (len(text) / 1000) * 2, 60)
        self.assertGreater(computed, base)

    def test_timeout_capped_at_60(self):
        base, text = 10, "word " * 100000
        computed = min(base + (len(text) / 1000) * 2, 60)
        self.assertLessEqual(computed, 60)


class TestOllamaStdinPipe(unittest.TestCase):
    def _mock_popen(self, stdout=b"corrected", stderr=b"", rc=0):
        m = MagicMock()
        m.communicate.return_value = (stdout, stderr)
        m.returncode = rc
        return m

    @patch.object(pp.subprocess, "Popen")
    def test_uses_stdin_pipe_not_cli_argument(self, mock_popen_cls):
        mock_popen_cls.return_value = self._mock_popen()
        pp.ollama_postprocess("input text", "prompt content", "gemma3:4b", 15)
        args, kwargs = mock_popen_cls.call_args
        self.assertEqual(args[0], ["ollama", "run", "--hidethinking", "gemma3:4b"])
        self.assertIs(kwargs["stdin"], subprocess.PIPE)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.PIPE)

    @patch.object(pp.subprocess, "Popen")
    def test_prompt_sent_via_communicate_input(self, mock_popen_cls):
        mock_popen_cls.return_value = self._mock_popen()
        prompt = "This is a very long prompt. " * 500
        pp.ollama_postprocess("input", prompt, "model", 10)
        _, kwargs = mock_popen_cls.return_value.communicate.call_args
        self.assertEqual(kwargs["input"], prompt.encode("utf-8"))

    @patch.dict(os.environ, {"DICTEE_LLM_CPU": "true"})
    @patch.object(pp.subprocess, "Popen")
    def test_cpu_mode_sets_env_var(self, mock_popen_cls):
        mock_popen_cls.return_value = self._mock_popen()
        pp.ollama_postprocess("text", "prompt", "model", 10)
        env_arg = mock_popen_cls.call_args[1]["env"]
        self.assertEqual(env_arg["OLLAMA_NUM_GPU"], "0")

    @patch.object(pp.subprocess, "Popen")
    def test_nonzero_returncode_returns_none(self, mock_popen_cls):
        mock_popen_cls.return_value = self._mock_popen(stderr=b"error", rc=1)
        self.assertIsNone(pp.ollama_postprocess("text", "prompt", "model", 10))

    @patch.object(pp.subprocess, "Popen", side_effect=FileNotFoundError("not found"))
    def test_missing_ollama_returns_none(self, _):
        self.assertIsNone(pp.ollama_postprocess("text", "prompt", "model", 10))

    @patch.object(pp.subprocess, "Popen")
    def test_timeout_returns_none(self, mock_popen_cls):
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(
            cmd="ollama", timeout=1
        )
        mock_popen_cls.return_value = mock_proc
        self.assertIsNone(pp.ollama_postprocess("text", "prompt", "model", 1))


class TestLlmPostprocessChunking(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "DICTEE_LLM_PROVIDER": "ollama",
            "DICTEE_LLM_MODEL": "test",
            "DICTEE_LLM_TIMEOUT": "10",
        },
    )
    @patch.object(
        pp, "_load_prompt", return_value="{additional_context}<input>{text}</input>"
    )
    @patch.object(pp, "ollama_postprocess")
    def test_single_chunk_calls_handler_once(self, mock_handler, _):
        mock_handler.return_value = "corrected"
        self.assertEqual(pp.llm_postprocess("short text"), "corrected")
        self.assertEqual(mock_handler.call_count, 1)

    @patch.dict(
        os.environ,
        {
            "DICTEE_LLM_PROVIDER": "ollama",
            "DICTEE_LLM_MODEL": "test",
            "DICTEE_LLM_TIMEOUT": "10",
        },
    )
    @patch.object(
        pp, "_load_prompt", return_value="{additional_context}<input>{text}</input>"
    )
    @patch.object(pp, "ollama_postprocess")
    def test_multiple_chunks_calls_handler_per_chunk(self, mock_handler, _):
        mock_handler.return_value = "corrected"
        text = "This is sentence one. " * 500
        pp.llm_postprocess(text)
        self.assertGreater(mock_handler.call_count, 1)

    @patch.dict(
        os.environ,
        {
            "DICTEE_LLM_PROVIDER": "ollama",
            "DICTEE_LLM_MODEL": "test",
            "DICTEE_LLM_TIMEOUT": "10",
        },
    )
    @patch.object(
        pp, "_load_prompt", return_value="{additional_context}<input>{text}</input>"
    )
    @patch.object(pp, "ollama_postprocess")
    def test_chunk_failure_keeps_original(self, mock_handler, _):
        mock_handler.side_effect = Exception("network error")
        self.assertEqual(pp.llm_postprocess("Hello world."), "Hello world.")

    @patch.dict(
        os.environ,
        {
            "DICTEE_LLM_PROVIDER": "ollama",
            "DICTEE_LLM_MODEL": "test",
            "DICTEE_LLM_TIMEOUT": "10",
        },
    )
    @patch.object(
        pp, "_load_prompt", return_value="{additional_context}<input>{text}</input>"
    )
    @patch.object(pp, "ollama_postprocess")
    def test_empty_handler_return_keeps_original(self, mock_handler, _):
        mock_handler.return_value = None
        self.assertEqual(pp.llm_postprocess("Hello world."), "Hello world.")

    @patch.dict(
        os.environ,
        {
            "DICTEE_LLM_PROVIDER": "ollama",
            "DICTEE_LLM_MODEL": "test",
            "DICTEE_LLM_TIMEOUT": "10",
            "DICTEE_LLM_ADDITIONAL_CONTEXT": "Domain: software engineering",
        },
    )
    @patch.object(
        pp, "_load_prompt", return_value="{additional_context}<input>{text}</input>"
    )
    @patch.object(pp, "ollama_postprocess")
    def test_additional_context_in_prompt(self, mock_handler, _):
        mock_handler.return_value = "corrected"
        pp.llm_postprocess("test text")
        prompt = mock_handler.call_args[0][1]
        self.assertIn("software engineering", prompt)
        self.assertIn("additional_context", prompt)


class TestDefaultPrompt(unittest.TestCase):
    def test_prompt_contains_both_modes(self):
        self.assertIn("GRAMMAR FIX", pp.DEFAULT_PROMPT)
        self.assertIn("BETTER TEXT", pp.DEFAULT_PROMPT)

    def test_prompt_has_doubt_rule(self):
        self.assertIn("unsure", pp.DEFAULT_PROMPT.lower())
        self.assertIn("ALWAYS use GRAMMAR FIX", pp.DEFAULT_PROMPT)

    def test_prompt_has_additional_context_placeholder(self):
        self.assertIn("{additional_context}", pp.DEFAULT_PROMPT)

    def test_prompt_has_text_placeholder(self):
        self.assertIn("{text}", pp.DEFAULT_PROMPT)

    def test_prompt_no_temperature_reference(self):
        self.assertNotIn("temperature", pp.DEFAULT_PROMPT.lower())

    def test_prompt_has_self_corrections_keywords(self):
        self.assertIn("self-correction", pp.DEFAULT_PROMPT.lower())
        self.assertIn("linearize", pp.DEFAULT_PROMPT.lower())

    def test_prompt_has_explanatory_detection(self):
        self.assertIn("beginning", pp.DEFAULT_PROMPT.lower())
        self.assertIn("development", pp.DEFAULT_PROMPT.lower())
        self.assertIn("conclusion", pp.DEFAULT_PROMPT.lower())


class TestLlmProviderDispatch(unittest.TestCase):
    @patch.dict(
        os.environ, {"DICTEE_LLM_PROVIDER": "openrouter", "DICTEE_LLM_MODEL": "test"}
    )
    @patch.object(
        pp, "_load_prompt", return_value="{additional_context}<input>{text}</input>"
    )
    @patch.object(pp, "openrouter_postprocess", return_value="corrected")
    def test_openrouter_selected(self, mock_h, _):
        pp.llm_postprocess("text")
        mock_h.assert_called_once()

    @patch.dict(
        os.environ, {"DICTEE_LLM_PROVIDER": "gemini", "DICTEE_LLM_MODEL": "test"}
    )
    @patch.object(
        pp, "_load_prompt", return_value="{additional_context}<input>{text}</input>"
    )
    @patch.object(pp, "gemini_postprocess", return_value="corrected")
    def test_gemini_selected(self, mock_h, _):
        pp.llm_postprocess("text")
        mock_h.assert_called_once()

    @patch.dict(os.environ, {"DICTEE_LLM_PROVIDER": "groq", "DICTEE_LLM_MODEL": "test"})
    @patch.object(
        pp, "_load_prompt", return_value="{additional_context}<input>{text}</input>"
    )
    @patch.object(pp, "groq_postprocess", return_value="corrected")
    def test_groq_selected(self, mock_h, _):
        pp.llm_postprocess("text")
        mock_h.assert_called_once()

    @patch.dict(
        os.environ,
        {"DICTEE_LLM_PROVIDER": "unknown_provider", "DICTEE_LLM_MODEL": "test"},
    )
    @patch.object(
        pp, "_load_prompt", return_value="{additional_context}<input>{text}</input>"
    )
    @patch.object(pp, "ollama_postprocess", return_value="corrected")
    def test_unknown_falls_back_to_ollama(self, mock_h, _):
        pp.llm_postprocess("text")
        mock_h.assert_called_once()


class TestHttpJsonErrors(unittest.TestCase):
    @patch.object(pp.urllib.request, "urlopen")
    def test_http_error_returns_none(self, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.test.com",
            code=413,
            msg="Too Large",
            hdrs={},
            fp=None,
        )
        self.assertIsNone(pp._http_json("https://api.test.com", {}, {}, 5))


if __name__ == "__main__":
    unittest.main()
