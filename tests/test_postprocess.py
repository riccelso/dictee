#!/usr/bin/env python3
"""Tests for dictee-postprocess.py"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "dictee_postprocess", os.path.join(_script_dir, "dictee-postprocess.py")
)
pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pp)


class TestParseRules(unittest.TestCase):
    def _write_rules(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        f.write(content)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_basic_rule(self):
        path = self._write_rules("[*] /foo/bar/ \n")
        rules = pp._parse_rules(path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0][1], "bar")

    def test_empty_replacement(self):
        path = self._write_rules("[*] /foo// \n")
        rules = pp._parse_rules(path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0][1], "")

    def test_skip_comments(self):
        path = self._write_rules("# comment\n[*] /a/b/ \n")
        rules = pp._parse_rules(path)
        self.assertEqual(len(rules), 1)

    def test_skip_empty_lines(self):
        path = self._write_rules("\n\n[*] /a/b/ \n\n")
        rules = pp._parse_rules(path)
        self.assertEqual(len(rules), 1)

    def test_nonexistent_file(self):
        rules = pp._parse_rules("/nonexistent/file.conf")
        self.assertEqual(rules, [])

    def test_language_filter_match(self):
        old_lang = os.environ.get("DICTEE_LANG_SOURCE")
        os.environ["DICTEE_LANG_SOURCE"] = "fr"
        pp.LANG = "fr"
        path = self._write_rules("[fr] /bonjour/salut/ \n[en] /hello/hi/ \n")
        rules = pp._parse_rules(path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0][1], "salut")
        if old_lang is not None:
            os.environ["DICTEE_LANG_SOURCE"] = old_lang
        else:
            os.environ.pop("DICTEE_LANG_SOURCE", None)
        pp.LANG = os.environ.get("DICTEE_LANG_SOURCE", "").lower()[:2]

    def test_wildcard_matches_all(self):
        old_lang = os.environ.get("DICTEE_LANG_SOURCE")
        os.environ["DICTEE_LANG_SOURCE"] = "de"
        pp.LANG = "de"
        path = self._write_rules("[*] /foo/bar/ \n")
        rules = pp._parse_rules(path)
        self.assertEqual(len(rules), 1)
        if old_lang is not None:
            os.environ["DICTEE_LANG_SOURCE"] = old_lang
        else:
            os.environ.pop("DICTEE_LANG_SOURCE", None)
        pp.LANG = os.environ.get("DICTEE_LANG_SOURCE", "").lower()[:2]

    def test_case_insensitive_flag(self):
        path = self._write_rules("[*] /hello/hi/i \n")
        rules = pp._parse_rules(path)
        self.assertEqual(len(rules), 1)
        result = rules[0][0].sub(rules[0][1], "HELLO world")
        self.assertEqual(result, "hi world")


class TestApplyRules(unittest.TestCase):
    def test_single_rule(self):
        import re

        rules = [(re.compile(r"foo"), "bar")]
        self.assertEqual(pp.apply_rules("foo baz", rules), "bar baz")

    def test_multiple_rules_sequential(self):
        import re

        rules = [(re.compile(r"foo"), "bar"), (re.compile(r"bar"), "qux")]
        self.assertEqual(pp.apply_rules("foo", rules), "qux")

    def test_no_match(self):
        import re

        rules = [(re.compile(r"xyz"), "abc")]
        self.assertEqual(pp.apply_rules("hello world", rules), "hello world")


class TestFixElisions(unittest.TestCase):
    def test_je_elision(self):
        self.assertEqual(pp.fix_elisions("je ai"), "j'ai")
        self.assertEqual(pp.fix_elisions("je suis"), "je suis")

    def test_le_elision(self):
        self.assertEqual(pp.fix_elisions("le homme"), "l'homme")

    def test_la_elision(self):
        self.assertEqual(pp.fix_elisions("la arbre"), "l'arbre")

    def test_de_elision(self):
        self.assertEqual(pp.fix_elisions("de un"), "d'un")

    def test_que_elision(self):
        self.assertEqual(pp.fix_elisions("que il"), "qu'il")

    def test_ce_elision(self):
        self.assertEqual(pp.fix_elisions("ce est"), "c'est")

    def test_aspirated_h_no_elision(self):
        result = pp.fix_elisions("le hibou")
        self.assertIn("hibou", result)
        self.assertNotIn("l'hibou", result)

    def test_si_il_elision(self):
        self.assertEqual(pp.fix_elisions("si il"), "s'il")

    def test_si_ils_elision(self):
        self.assertEqual(pp.fix_elisions("si ils"), "s'ils")

    def test_no_elision_before_consonant(self):
        self.assertEqual(pp.fix_elisions("je mange"), "je mange")

    def test_se_elision(self):
        self.assertEqual(pp.fix_elisions("se appelle"), "s'appelle")

    def test_me_elision(self):
        self.assertEqual(pp.fix_elisions("me appelle"), "m'appelle")


class TestFixFrenchTypography(unittest.TestCase):
    def test_ellipsis(self):
        self.assertEqual(pp.fix_french_typography("wait..."), "wait\u2026")

    def test_thin_space_before_semicolon(self):
        result = pp.fix_french_typography("bonjour; salut")
        self.assertIn("\u202f;", result)

    def test_thin_space_before_exclamation(self):
        result = pp.fix_french_typography("bonjour!")
        self.assertIn("\u202f!", result)

    def test_thin_space_before_question(self):
        result = pp.fix_french_typography("comment ?")
        self.assertIn("\u202f?", result)

    def test_nbsp_before_colon(self):
        result = pp.fix_french_typography("voici: test")
        self.assertIn("\u00a0:", result)

    def test_guillemets(self):
        result = pp.fix_french_typography('"bonjour"')
        self.assertIn("\u00ab", result)
        self.assertIn("\u00bb", result)

    def test_english_quotes_to_french(self):
        result = pp.fix_french_typography('"hello"')
        self.assertIn("\u00ab", result)
        self.assertIn("\u00bb", result)


class TestParseDictionary(unittest.TestCase):
    def _write_dict(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        f.write(content)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_basic_entry(self):
        path = self._write_dict("[*] foo=bar\n")
        entries = pp._parse_dictionary(path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][0], "foo")
        self.assertEqual(entries[0][2], "bar")

    def test_skip_comments(self):
        path = self._write_dict("# comment\n[*] foo=bar\n")
        entries = pp._parse_dictionary(path)
        self.assertEqual(len(entries), 1)

    def test_nonexistent_file(self):
        entries = pp._parse_dictionary("/nonexistent/dict.conf")
        self.assertEqual(entries, [])


class TestApplyDictionary(unittest.TestCase):
    def test_exact_replacement(self):
        import re

        entries = [
            (
                "foo",
                re.compile(r"\bfoo\b", re.IGNORECASE),
                "bar",
            )
        ]
        self.assertEqual(
            pp.apply_dictionary("foo baz", entries, fuzzy=False), "bar baz"
        )

    def test_case_preservation_upper(self):
        import re

        entries = [
            (
                "foo",
                re.compile(r"\bfoo\b", re.IGNORECASE),
                "bar",
            )
        ]
        self.assertEqual(
            pp.apply_dictionary("FOO baz", entries, fuzzy=False), "BAR baz"
        )

    def test_case_preservation_title(self):
        import re

        entries = [
            (
                "foo",
                re.compile(r"\bfoo\b", re.IGNORECASE),
                "bar",
            )
        ]
        self.assertEqual(
            pp.apply_dictionary("Foo baz", entries, fuzzy=False), "Bar baz"
        )

    def test_no_match(self):
        import re

        entries = [
            (
                "xyz",
                re.compile(r"\bxyz\b", re.IGNORECASE),
                "abc",
            )
        ]
        self.assertEqual(
            pp.apply_dictionary("hello world", entries, fuzzy=False), "hello world"
        )


class TestFixCapitalization(unittest.TestCase):
    def test_capitalize_start(self):
        self.assertEqual(pp.fix_capitalization("hello world"), "Hello world")

    def test_capitalize_after_period(self):
        self.assertEqual(pp.fix_capitalization("hello. world"), "Hello. World")

    def test_capitalize_after_exclamation(self):
        self.assertEqual(pp.fix_capitalization("hi! bye"), "Hi! Bye")

    def test_capitalize_after_question(self):
        self.assertEqual(pp.fix_capitalization("hi? bye"), "Hi? Bye")

    def test_already_capitalized(self):
        self.assertEqual(pp.fix_capitalization("Hello world"), "Hello world")

    def test_empty_string(self):
        self.assertEqual(pp.fix_capitalization(""), "")

    def test_capitalize_after_ellipsis(self):
        result = pp.fix_capitalization("wait\u2026 and then")
        self.assertIn("And", result)


class TestEnvHelpers(unittest.TestCase):
    def test_env_bool_true(self):
        os.environ["TEST_BOOL"] = "true"
        self.assertTrue(pp._env_bool("TEST_BOOL"))
        del os.environ["TEST_BOOL"]

    def test_env_bool_false(self):
        os.environ["TEST_BOOL"] = "false"
        self.assertFalse(pp._env_bool("TEST_BOOL"))
        del os.environ["TEST_BOOL"]

    def test_env_bool_default(self):
        self.assertTrue(pp._env_bool("TEST_NONEXISTENT_BOOL", "true"))
        self.assertFalse(pp._env_bool("TEST_NONEXISTENT_BOOL", "false"))

    def test_env_int(self):
        os.environ["TEST_INT"] = "42"
        self.assertEqual(pp._env_int("TEST_INT", 0), 42)
        del os.environ["TEST_INT"]

    def test_env_int_default(self):
        self.assertEqual(pp._env_int("TEST_NONEXISTENT_INT", 10), 10)

    def test_env_int_invalid(self):
        os.environ["TEST_INT"] = "not_a_number"
        self.assertEqual(pp._env_int("TEST_INT", 10), 10)
        del os.environ["TEST_INT"]


class TestPreviewText(unittest.TestCase):
    def test_short_text(self):
        self.assertEqual(pp._preview_text("hello"), "hello")

    def test_long_text_truncated(self):
        long_text = "a" * 200
        result = pp._preview_text(long_text)
        self.assertTrue(result.endswith("..."))
        self.assertEqual(len(result), 120)

    def test_newlines_escaped(self):
        self.assertEqual(pp._preview_text("hello\nworld"), "hello\\nworld")


if __name__ == "__main__":
    unittest.main()
