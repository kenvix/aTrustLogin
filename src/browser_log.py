"""Bounded capture of browser process output."""

import logging
import threading
from logging.handlers import RotatingFileHandler


class BrowserLog:
    def __init__(self, stream, path, max_bytes=5 * 1024 * 1024, backup_count=2):
        self.stream = stream
        self.handler = RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.thread = threading.Thread(target=self._copy, name="browser-log", daemon=True)
        self.thread.start()

    def _copy(self):
        try:
            while True:
                chunk = self.stream.read(4096)
                if not chunk:
                    break
                record = logging.LogRecord(
                    "browser", logging.INFO, "", 0,
                    chunk.decode("utf-8", errors="replace"), (), None,
                )
                self.handler.emit(record)
        finally:
            self.stream.close()
            self.handler.close()

    def close(self):
        self.thread.join(timeout=5)
