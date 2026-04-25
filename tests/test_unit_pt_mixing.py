#!/usr/bin/env python3
"""Unit tests for Portuguese/English mixing detection and correction."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "dictee_postprocess", os.path.join(_script_dir, "dictee-postprocess.py")
)
pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pp)


class TestFixPortugueseTypography(unittest.TestCase):
    def test_ellipsis(self):
        self.assertEqual(pp.fix_portuguese_typography("wait..."), "wait\u2026")

    def test_four_dots(self):
        self.assertEqual(pp.fix_portuguese_typography("hello...."), "hello\u2026")

    def test_no_space_before_comma(self):
        self.assertEqual(pp.fix_portuguese_typography("hello , world"), "hello, world")

    def test_no_space_before_period(self):
        self.assertEqual(pp.fix_portuguese_typography("hello ."), "hello.")

    def test_no_space_before_exclamation(self):
        self.assertEqual(pp.fix_portuguese_typography("olá !"), "olá!")

    def test_no_space_before_question(self):
        self.assertEqual(pp.fix_portuguese_typography("oi ?"), "oi?")

    def test_no_space_before_colon(self):
        self.assertEqual(pp.fix_portuguese_typography("item : valor"), "item: valor")

    def test_no_space_before_semicolon(self):
        self.assertEqual(pp.fix_portuguese_typography("a ; b"), "a; b")

    def test_preserves_correct_spacing(self):
        self.assertEqual(pp.fix_portuguese_typography("olá mundo"), "olá mundo")

    def test_empty_string(self):
        self.assertEqual(pp.fix_portuguese_typography(""), "")

    def test_no_space_after_open_paren(self):
        result = pp.fix_portuguese_typography("(  teste)")
        self.assertNotIn("(  ", result)


class TestFixPtEnMixing(unittest.TestCase):
    def setUp(self):
        self._orig_lang = pp.LANG

    def tearDown(self):
        pp.LANG = self._orig_lang

    def test_no_mixing_pt_text(self):
        pp.LANG = "pt"
        result = pp.fix_pt_en_mixing("eu quero ir para casa")
        self.assertEqual(result, "eu quero ir para casa")

    def test_en_word_replacement(self):
        pp.LANG = "pt"
        result = pp.fix_pt_en_mixing("o the livro é muito bom")
        self.assertNotIn("the", result)
        self.assertIn("o", result)

    def test_mostly_english_rejected(self):
        pp.LANG = "pt"
        result = pp.fix_pt_en_mixing("the is are was were have has had")
        self.assertEqual(result, "")

    def test_mixed_pt_en_corrected(self):
        pp.LANG = "pt"
        result = pp.fix_pt_en_mixing("o gato is the muito bonito")
        self.assertIn("é", result)

    def test_not_pt_lang_passthrough(self):
        pp.LANG = "fr"
        text = "the quick brown fox"
        result = pp.fix_pt_en_mixing(text)
        self.assertEqual(result, text)

    def test_empty_text(self):
        pp.LANG = "pt"
        self.assertEqual(pp.fix_pt_en_mixing(""), "")

    def test_case_preservation_upper(self):
        pp.LANG = "pt"
        result = pp.fix_pt_en_mixing("o THE é muito bom")
        self.assertIn("O", result)

    def test_case_preservation_title(self):
        pp.LANG = "pt"
        result = pp.fix_pt_en_mixing("o The é muito bom")
        self.assertIn("O", result)

    def test_case_preservation_lower(self):
        pp.LANG = "pt"
        result = pp.fix_pt_en_mixing("the gato")
        self.assertIn("o", result)

    def test_mostly_pt_with_few_en_words_corrected(self):
        pp.LANG = "pt"
        text = "eu não the vejo com os olhos"
        result = pp.fix_pt_en_mixing(text)
        self.assertIn("o", result)
        self.assertNotIn("the", result)

    def test_all_pt_not_modified(self):
        pp.LANG = "pt"
        text = "eu quero comer pão com manteiga"
        result = pp.fix_pt_en_mixing(text)
        self.assertEqual(result, text)


class TestPtEnWordSets(unittest.TestCase):
    def test_pt_en_overlap_is_minimal(self):
        overlap = pp._PT_COMMON_WORDS & pp._EN_COMMON_WORDS
        self.assertLessEqual(len(overlap), 3, f"Too much overlap: {overlap}")

    def test_en_to_pt_has_common_mappings(self):
        self.assertIn("the", pp._EN_TO_PT)
        self.assertIn("is", pp._EN_TO_PT)
        self.assertIn("and", pp._EN_TO_PT)
        self.assertEqual(pp._EN_TO_PT["the"], "o")
        self.assertEqual(pp._EN_TO_PT["is"], "é")
        self.assertEqual(pp._EN_TO_PT["and"], "e")

    def test_pt_words_are_valid(self):
        for w in pp._PT_COMMON_WORDS:
            self.assertTrue(len(w) > 0, f"Empty word in PT set")
            self.assertTrue(w.isalpha() or w in ("à", "é", "ã", "õ", "á", "é", "í", "ó", "ú", "ç"),
                          f"Non-alpha PT word: {w}")

    def test_en_words_are_valid(self):
        for w in pp._EN_COMMON_WORDS:
            self.assertTrue(len(w) > 0, f"Empty word in EN set")
            self.assertTrue(w.isalpha(), f"Non-alpha EN word: {w}")

    def test_en_to_pt_values_are_strings(self):
        for en, pt in pp._EN_TO_PT.items():
            self.assertIsInstance(pt, str, f"PT value for '{en}' is not a string")
            self.assertTrue(len(pt) > 0, f"Empty PT value for '{en}'")


if __name__ == "__main__":
    unittest.main()
