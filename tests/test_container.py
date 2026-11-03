import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import launcher
from browser_log import BrowserLog


class ContainerTests(unittest.TestCase):
    def test_invalid_options_hide_credentials(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"ATRUST_OPTS": '--password="test-secret'}), \
                patch("sys.stderr", output), patch("launcher.os.execv") as execute:
            self.assertEqual(launcher.main(), 2)
        self.assertNotIn("test-secret", output.getvalue())
        execute.assert_not_called()

    def test_launcher_executes_argument_list(self):
        with patch.dict(os.environ, {"ATRUST_OPTS": '--username="test user" --password="test password"'}), \
                patch("launcher.os.execv") as execute:
            launcher.main()
        executable, command = execute.call_args.args
        self.assertEqual(executable, sys.executable)
        self.assertIn("--username=test user", command)
        self.assertIn("--password=test password", command)

    def test_output_capture_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            log = BrowserLog(io.BytesIO(b"test line\n" * 30000), Path(directory) / "chrome.log",
                             max_bytes=16384, backup_count=2)
            log.close()
            self.assertFalse(log.thread.is_alive())
            files = list(Path(directory).glob("chrome.log*"))
            self.assertLessEqual(len(files), 3)
            self.assertLessEqual(sum(path.stat().st_size for path in files), 3 * 16384)

    @unittest.skipUnless(shutil.which("bash"), "Bash is required")
    def test_shell_retries_runtime_failure_after_delay(self):
        result, delays = self.run_shell("retry")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(delays, "30\n")

    @unittest.skipUnless(shutil.which("bash"), "Bash is required")
    def test_shell_stops_on_configuration_error(self):
        result, delays = self.run_shell("invalid")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(delays, "")

    def run_shell(self, mode):
        script = Path(__file__).resolve().parents[1] / "docker/bin/start-with-autologin-actual.sh"
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            scripts = {
                "xset": "#!/bin/sh\nexit 0\n",
                "sleep": '#!/bin/sh\nprintf "%s\\n" "$1" >> "$SLEEP_LOG"\n',
                "python3": '#!/bin/sh\n[ "$TEST_MODE" = invalid ] && exit 2\n'
                           '[ -f "$STATE_FILE" ] && exit 0\ntouch "$STATE_FILE"\nexit 1\n',
            }
            for name, content in scripts.items():
                path = directory / name
                path.write_text(content)
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ["PATH"],
                       TEST_MODE=mode, STATE_FILE=str(directory / "state"), SLEEP_LOG=str(directory / "sleep.log"))
            result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=5)
            log = directory / "sleep.log"
            return result, log.read_text() if log.exists() else ""


if __name__ == "__main__":
    unittest.main()
