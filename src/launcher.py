"""Start the container login process with shell-style argument quoting."""

import os
import shlex
import sys
from pathlib import Path


def build_command(options):
    return [
        sys.executable, str(Path(__file__).with_name("main.py")),
        "--interactive=True", "--wait_atrust=True", "--driver_type=chrome",
        f"--data_dir={Path.home() / '.atrust-data'}",
        "--driver_path=/usr/bin/chromedriver", "--browser_path=/usr/bin/chromium",
        "--container_mode=True", *shlex.split(options),
    ]


def main():
    try:
        command = build_command(os.environ.get("ATRUST_OPTS", ""))
    except ValueError:
        print("ATRUST_OPTS contains unmatched quotes. Check the argument quoting.", file=sys.stderr)
        return 2
    os.execv(sys.executable, command)


if __name__ == "__main__":
    sys.exit(main())
