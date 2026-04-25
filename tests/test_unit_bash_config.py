#!/usr/bin/env python3
"""Unit tests for the dictee bash script configuration and CUDA path logic."""

import os
import shutil
import subprocess
import tempfile
import unittest


class TestDicteeConfigLoading(unittest.TestCase):
    def _write_config(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        f.write(content)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_config_sources_vars(self):
        conf = self._write_config('DICTEE_LANG_SOURCE=pt\nDICTEE_LANG_TARGET=en\n')
        result = subprocess.run(
            ["bash", "-c", f'source "{conf}" && echo "$DICTEE_LANG_SOURCE"'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), "pt")

    def test_config_exports_whisper_lang(self):
        conf = self._write_config('DICTEE_WHISPER_LANG=pt\n')
        result = subprocess.run(
            ["bash", "-c", f'source "{conf}" && echo "$DICTEE_WHISPER_LANG"'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), "pt")

    def test_lang_source_default_from_locale(self):
        result = subprocess.run(
            ["bash", "-c", 'LANG=pt_BR.UTF-8; LANG_SOURCE="${LANG%%_*}"; echo "$LANG_SOURCE"'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), "pt")

    def test_config_missing_key_defaults(self):
        result = subprocess.run(
            ["bash", "-c",
             'DICTEE_LANG_SOURCE="${DICTEE_LANG_SOURCE:-${LANG%%_*}}"; echo "$DICTEE_LANG_SOURCE"'],
            capture_output=True, text=True,
            env={**os.environ, "LANG": "fr_FR.UTF-8"},
        )
        self.assertEqual(result.stdout.strip(), "fr")


class TestCudaPathResolution(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dictee"
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _extract_cuda_block(self):
        with open(self.script_path) as f:
            lines = f.readlines()
        start = None
        end = None
        for i, line in enumerate(lines):
            if "_ort_cuda_provider_dirs=" in line:
                start = i
            if start is not None and line.strip() == "unset _dir _ort_cuda_provider_dirs":
                end = i + 1
                break
        self.assertIsNotNone(start, "CUDA provider block not found")
        self.assertIsNotNone(end, "CUDA provider block end not found")
        return "".join(lines[start:end])

    def test_finds_cuda_so_in_dir(self):
        cuda_dir = os.path.join(self.tmpdir, "cuda")
        os.makedirs(cuda_dir)
        with open(os.path.join(cuda_dir, "libonnxruntime_providers_cuda.so"), "w") as f:
            f.write("fake")
        block = self._extract_cuda_block()
        block = block.replace(
            '"$HOME/.cache/ort.pyke.io/dfbin/x86_64-unknown-linux-gnu/"*"/"',
            f'"{cuda_dir}/"'
        ).replace(
            '"$HOME/.local/share/opencode/worktree/dictee/"*"/target/release/"',
            '"/nonexistent/path/"'
        ).replace(
            '"${XDG_DATA_HOME:-$HOME/.local/share}/dictee/cuda/"',
            '"/nonexistent/path2/"'
        )
        script = f'{block}\necho "$LD_LIBRARY_PATH"'
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True,
        )
        self.assertIn(cuda_dir, result.stdout.strip())

    def test_no_cuda_so_keeps_ld_path_empty(self):
        block = self._extract_cuda_block()
        block = block.replace(
            '"$HOME/.cache/ort.pyke.io/dfbin/x86_64-unknown-linux-gnu/"*"/"',
            f'"{self.tmpdir}/empty/"'
        ).replace(
            '"$HOME/.local/share/opencode/worktree/dictee/"*"/target/release/"',
            f'"{self.tmpdir}/empty2/"'
        )
        os.makedirs(os.path.join(self.tmpdir, "empty"), exist_ok=True)
        os.makedirs(os.path.join(self.tmpdir, "empty2"), exist_ok=True)
        script = f'{block}\necho "LD=${{LD_LIBRARY_PATH:-EMPTY}}"'
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True,
        )
        self.assertIn("LD=EMPTY", result.stdout.strip())

    def test_ld_path_no_duplicate(self):
        cuda_dir = os.path.join(self.tmpdir, "cuda")
        os.makedirs(cuda_dir)
        with open(os.path.join(cuda_dir, "libonnxruntime_providers_cuda.so"), "w") as f:
            f.write("fake")
        block = self._extract_cuda_block()
        block = block.replace(
            '"$HOME/.cache/ort.pyke.io/dfbin/x86_64-unknown-linux-gnu/"*"/"',
            f'"{cuda_dir}/"'
        ).replace(
            '"$HOME/.local/share/opencode/worktree/dictee/"*"/target/release/"',
            '"/nonexistent/"'
        ).replace(
            '"${XDG_DATA_HOME:-$HOME/.local/share}/dictee/cuda/"',
            '"/nonexistent2/"'
        )
        script = f'export LD_LIBRARY_PATH="{cuda_dir}"\n{block}\necho "$LD_LIBRARY_PATH"'
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True,
        )
        entries = result.stdout.strip().split(":")
        count = entries.count(cuda_dir)
        self.assertLessEqual(count, 1, "LD_LIBRARY_PATH has duplicate entries")


class TestDicteeScriptSyntax(unittest.TestCase):
    def test_syntax_valid(self):
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dictee"
        )
        result = subprocess.run(
            ["bash", "-n", script],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, f"Syntax error: {result.stderr}")

    def test_script_is_executable(self):
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dictee"
        )
        self.assertTrue(os.access(script, os.X_OK), "dictee script is not executable")


class TestBuildScripts(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_build_sh_supports_cuda_option(self):
        build_sh = os.path.join(self.repo_root, "build.sh")
        with open(build_sh) as f:
            content = f.read()
        self.assertIn('--cuda', content)
        self.assertIn('cargo build --release --features "$FEATURES"', content)

    def test_build_and_install_uses_cuda_build(self):
        build_and_install_sh = os.path.join(self.repo_root, "build_and_install.sh")
        with open(build_and_install_sh) as f:
            content = f.read()
        self.assertIn('"$SCRIPT_DIR/build.sh" --cuda', content)

    def test_build_scripts_syntax_valid(self):
        for script_name in ("build.sh", "build_and_install.sh"):
            script_path = os.path.join(self.repo_root, script_name)
            result = subprocess.run(
                ["bash", "-n", script_path],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"Syntax error in {script_name}: {result.stderr}",
            )


class TestDicteeStateFile(unittest.TestCase):
    def test_write_state_function(self):
        result = subprocess.run(
            ["bash", "-c",
             'STATE_FILE=$(mktemp); STATE_LOCK=$(mktemp); '
             'write_state() { (flock -n 200 || return 1; echo "$1" > "$STATE_FILE") 200>"$STATE_LOCK"; }; '
             'write_state "recording"; cat "$STATE_FILE"; '
             'rm -f "$STATE_FILE" "$STATE_LOCK"'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), "recording")


if __name__ == "__main__":
    unittest.main()
