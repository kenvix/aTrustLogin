import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from browser_log import BrowserLog


class GeneratedOutput(io.RawIOBase):
    """Generate process output incrementally with a final identifiable record."""
    def __init__(self, size):
        super().__init__()
        self.remaining = size
        self.tail = b"latest-browser-output"

    def read(self, size=-1):
        if self.remaining:
            count = self.remaining if size < 0 else min(size, self.remaining)
            self.remaining -= count
            return b"x" * count
        tail, self.tail = self.tail, b""
        return tail


class BrowserLogTests(unittest.TestCase):
    def test_default_rotation_keeps_five_files_and_latest_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "chrome.log")
            stream = GeneratedOutput(120 * 1024 * 1024)
            log = BrowserLog(stream, path)
            log.thread.join(timeout=30)
            log.close()
            self.assertFalse(log.thread.is_alive())
            self.assertTrue(stream.closed)
            self.assertEqual(log.handler.maxBytes, 20 * 1024 * 1024)
            self.assertEqual(log.handler.backupCount, 4)
            files = list(Path(directory).glob("chrome.log*"))
            self.assertEqual({file.name for file in files},
                             {"chrome.log", "chrome.log.1", "chrome.log.2", "chrome.log.3", "chrome.log.4"})
            self.assertTrue(all(file.stat().st_size <= 20 * 1024 * 1024 for file in files))
            self.assertIn(b"latest-browser-output", path.read_bytes())

    def test_custom_rotation_limits(self):
        for count in (2, 7):
            with self.subTest(files=count), tempfile.TemporaryDirectory() as directory:
                path = Path(directory, "chrome.log")
                stream = GeneratedOutput(16384 * (count + 2))
                log = BrowserLog(stream, path, max_bytes=16384, backup_count=count - 1)
                log.close()
                self.assertFalse(log.thread.is_alive())
                files = list(Path(directory).glob("chrome.log*"))
                self.assertEqual(len(files), count)
                self.assertTrue(all(file.stat().st_size <= 16384 for file in files))
                self.assertIn(b"latest-browser-output", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
