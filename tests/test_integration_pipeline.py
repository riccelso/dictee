#!/usr/bin/env python3
"""Integration tests for dictee-postprocess pipeline (stdin → stdout)."""

import os
import subprocess
import sys
import unittest

_script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_pp_script = os.path.join(_script_dir, "dictee-postprocess.py")


class TestPostprocessPipelineFR(unittest.TestCase):
    def _run(self, text, env_extra=None):
        env = {**os.environ, "DICTEE_LANG_SOURCE": "fr"}
        env.update(env_extra or {})
        result = subprocess.run(
            [sys.executable, _pp_script],
            input=text, capture_output=True, text=True,
            env=env, timeout=30,
        )
        return result.stdout

    def test_french_typography_applied(self):
        output = self._run("bonjour: ça va?")
        self.assertIn("\u00a0:", output)

    def test_french_elisions_applied(self):
        output = self._run("je ai vu le homme")
        self.assertIn("'ai", output)
        self.assertIn("l'homme", output)

    def test_empty_input_passthrough(self):
        output = self._run("  \n")
        self.assertEqual(output.strip(), "")

    def test_capitalization(self):
        output = self._run("bonjour. ça va")
        self.assertIn("Bonjour", output)

    def test_wrong_language_cyrillic_rejected(self):
        output = self._run("привет мир это тест")
        self.assertEqual(output.strip(), "")


class TestPostprocessPipelinePT(unittest.TestCase):
    def _run(self, text, env_extra=None):
        env = {**os.environ, "DICTEE_LANG_SOURCE": "pt"}
        env.update(env_extra or {})
        result = subprocess.run(
            [sys.executable, _pp_script],
            input=text, capture_output=True, text=True,
            env=env, timeout=30,
        )
        return result.stdout

    def test_pt_typography_applied(self):
        output = self._run("olá ... tudo bem ?")
        self.assertIn("\u2026", output)

    def test_pt_en_mixing_correction(self):
        output = self._run("o gato is muito bonito")
        self.assertIn("é", output)

    def test_pt_mostly_english_rejected(self):
        output = self._run("the is are was were have has had")
        self.assertEqual(output.strip(), "")

    def test_pt_pure_portuguese_kept(self):
        output = self._run("eu quero ir para casa hoje")
        self.assertIn("casa", output)

    def test_pt_no_space_before_punctuation(self):
        output = self._run("olá , mundo")
        self.assertNotIn(" ,", output)

    def test_pt_capitalization(self):
        output = self._run("olá. tudo bem")
        self.assertIn("Olá", output)
        self.assertIn("Tudo", output)

    def test_pt_lang_mixing_disabled(self):
        output = self._run(
            "the quick brown fox",
            {"DICTEE_PP_LANG_MIXING": "false"},
        )
        self.assertNotEqual(output.strip(), "")


class TestPostprocessPipelineEN(unittest.TestCase):
    def _run(self, text, env_extra=None):
        env = {**os.environ, "DICTEE_LANG_SOURCE": "en"}
        env.update(env_extra or {})
        result = subprocess.run(
            [sys.executable, _pp_script],
            input=text, capture_output=True, text=True,
            env=env, timeout=30,
        )
        return result.stdout

    def test_passthrough(self):
        output = self._run("hello world")
        self.assertEqual(output.strip(), "Hello world")

    def test_wrong_language_cyrillic_rejected(self):
        output = self._run("привет мир")
        self.assertEqual(output.strip(), "")

    def test_no_pt_en_mixing_for_en(self):
        output = self._run("the cat is very beautiful")
        self.assertIn("cat", output)


class TestPostprocessPipelineStageControl(unittest.TestCase):
    def _run(self, text, env_extra):
        env = {**os.environ, "DICTEE_LANG_SOURCE": "fr"}
        env.update(env_extra)
        result = subprocess.run(
            [sys.executable, _pp_script],
            input=text, capture_output=True, text=True,
            env=env, timeout=30,
        )
        return result.stdout

    def test_disable_capitalization(self):
        output = self._run("hello world", {"DICTEE_PP_CAPITALIZATION": "false"})
        self.assertNotIn("Hello", output)

    def test_disable_typography(self):
        output = self._run("bonjour: test", {"DICTEE_PP_TYPOGRAPHY": "false"})
        self.assertNotIn("\u00a0:", output)

    def test_disable_numbers(self):
        output = self._run("j'ai trois chats", {"DICTEE_PP_NUMBERS": "false"})
        self.assertIn("trois", output or "trois")


class TestPostprocessVerbose(unittest.TestCase):
    def test_verbose_stderr(self):
        env = {**os.environ, "DICTEE_LANG_SOURCE": "en", "DICTEE_PP_VERBOSE": "true"}
        result = subprocess.run(
            [sys.executable, _pp_script],
            input="hello world", capture_output=True, text=True,
            env=env, timeout=30,
        )
        self.assertIn("[dictee-postprocess]", result.stderr)


if __name__ == "__main__":
    unittest.main()
