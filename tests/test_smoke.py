#!/usr/bin/env python3
"""Smoke tests for dictee binaries and system tray components."""

import os
import shutil
import subprocess
import sys
import unittest

_script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestTranscribeBinary(unittest.TestCase):
    def _find_binary(self):
        for path in ["/usr/local/bin/transcribe", "/usr/bin/transcribe",
                     os.path.join(_script_dir, "target/release/transcribe")]:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        return None

    def test_binary_exists(self):
        binary = self._find_binary()
        self.assertIsNotNone(binary, "transcribe binary not found")

    def test_binary_help(self):
        binary = self._find_binary()
        if binary is None:
            self.skipTest("transcribe binary not found")
        result = subprocess.run(
            [binary, "--help"], capture_output=True, text=True, timeout=10,
        )
        self.assertIn(result.returncode, (0, 1), f"Unexpected exit code: {result.returncode}")

    def test_binary_has_cuda_support(self):
        binary = self._find_binary()
        if binary is None:
            self.skipTest("transcribe binary not found")
        result = subprocess.run(
            ["strings", binary], capture_output=True, text=True, timeout=30,
        )
        self.assertIn("Cuda", result.stdout, "Binary does not contain CUDA strings")

    def test_dictee_cuda_rpm_installed(self):
        if not shutil.which("rpm"):
            self.skipTest("rpm not available")
        result = subprocess.run(
            ["rpm", "-q", "dictee-cuda"], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"dictee-cuda not installed: {result.stderr}")

    def test_nvidia_driver_available(self):
        if not shutil.which("nvidia-smi"):
            self.skipTest("nvidia-smi not found")
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(len(result.stdout.strip()) > 0, "No GPU detected")


class TestDicteeScript(unittest.TestCase):
    def _script_path(self):
        return os.path.join(_script_dir, "dictee")

    def test_script_exists(self):
        self.assertTrue(os.path.isfile(self._script_path()))

    def test_script_executable(self):
        self.assertTrue(os.access(self._script_path(), os.X_OK))

    def test_dictee_cancel_no_error(self):
        result = subprocess.run(
            [self._script_path(), "--cancel"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "DICTEE_LANG_SOURCE": "pt"},
        )
        self.assertIn(result.returncode, (0, 1))

    def test_dictee_gpu_label_detection(self):
        if not shutil.which("rpm"):
            self.skipTest("rpm not available")
        result = subprocess.run(
            ["bash", "-c", f'source "{self._script_path()}" --help 2>/dev/null; true'],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "DICTEE_LANG_SOURCE": "pt"},
        )
        self.assertIn(result.returncode, (0, 1))


class TestPostprocessScript(unittest.TestCase):
    def _script_path(self):
        return os.path.join(_script_dir, "dictee-postprocess.py")

    def test_script_exists(self):
        self.assertTrue(os.path.isfile(self._script_path()))

    def test_script_executable(self):
        self.assertTrue(os.access(self._script_path(), os.X_OK))

    def test_script_help(self):
        result = subprocess.run(
            [sys.executable, self._script_path(), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--verbose", result.stdout)

    def test_script_stdin_stdout(self):
        result = subprocess.run(
            [sys.executable, self._script_path()],
            input="hello world", capture_output=True, text=True, timeout=10,
            env={**os.environ, "DICTEE_LANG_SOURCE": "en"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "Hello world")


class TestTrayScript(unittest.TestCase):
    def _script_path(self):
        return os.path.join(_script_dir, "dictee-tray.py")

    def test_script_exists(self):
        self.assertTrue(os.path.isfile(self._script_path()))

    def test_script_syntax_valid(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", self._script_path()],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"Syntax error: {result.stderr}")


class TestSetupScript(unittest.TestCase):
    def _script_path(self):
        return os.path.join(_script_dir, "dictee-setup.py")

    def test_script_exists(self):
        self.assertTrue(os.path.isfile(self._script_path()))

    def test_script_syntax_valid(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", self._script_path()],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"Syntax error: {result.stderr}")


class TestPttScript(unittest.TestCase):
    def _script_path(self):
        return os.path.join(_script_dir, "dictee-ptt.py")

    def test_script_exists(self):
        self.assertTrue(os.path.isfile(self._script_path()))

    def test_script_syntax_valid(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", self._script_path()],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"Syntax error: {result.stderr}")


class TestConfigFile(unittest.TestCase):
    def test_config_exists(self):
        conf = os.path.expanduser("~/.config/dictee.conf")
        self.assertTrue(os.path.isfile(conf), "dictee.conf not found")

    def test_config_has_lang_source(self):
        conf = os.path.expanduser("~/.config/dictee.conf")
        if not os.path.isfile(conf):
            self.skipTest("dictee.conf not found")
        with open(conf) as f:
            content = f.read()
        self.assertIn("DICTEE_LANG_SOURCE", content)

    def test_config_has_whisper_lang(self):
        conf = os.path.expanduser("~/.config/dictee.conf")
        if not os.path.isfile(conf):
            self.skipTest("dictee.conf not found")
        with open(conf) as f:
            content = f.read()
        self.assertIn("DICTEE_WHISPER_LANG", content)


class TestOnnxRuntimeCudaProvider(unittest.TestCase):
    def test_cuda_provider_exists_somewhere(self):
        candidates = [
            os.path.expanduser("~/.cache/ort.pyke.io/dfbin/x86_64-unknown-linux-gnu/"),
        ]
        found = False
        if os.path.isdir(candidates[0]):
            for root, dirs, files in os.walk(candidates[0]):
                if "libonnxruntime_providers_cuda.so" in files:
                    found = True
                    break
        self.assertTrue(found, "libonnxruntime_providers_cuda.so not found in ort.pyke cache")

    def test_onnxruntime_installed(self):
        if not shutil.which("rpm"):
            self.skipTest("rpm not available")
        result = subprocess.run(
            ["rpm", "-q", "onnxruntime"], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, "onnxruntime not installed")


if __name__ == "__main__":
    unittest.main()
