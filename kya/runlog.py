"""Per-run logging and config loading shared by the KYA entry points."""
from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path

_ANSI_ESCAPE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
# Rich panel top border:  ╭─── Title ───╮  (title may be empty for pure borders)
_TOP_BORDER = re.compile(r'^\s*╭─+\s*(.*?)\s*─*╮\s*$')
# Rich panel bottom border: ╰──────────╯
_BOT_BORDER = re.compile(r'^\s*╰─+╯\s*$')
# Rich panel content line: │  text  │  or  │  text  (no closing │)
_SIDE_CONTENT = re.compile(r'^\s*[│┃](.*?)[│┃]?\s*$')


def _format_rich_line(line: str) -> str:
    """Convert one Rich terminal line to plain readable text (with trailing newline)."""
    m = _TOP_BORDER.match(line)
    if m:
        title = m.group(1).strip()
        sep = '=' * 70
        return f'\n{sep}\n{title}\n{sep}\n' if title else '\n'

    if _BOT_BORDER.match(line):
        return ''

    stripped = line.strip()
    if stripped and stripped[0] in '│┃':
        m = _SIDE_CONTENT.match(line)
        if m:
            return m.group(1).rstrip() + '\n'

    return line + '\n'


class TeeLogger:
    """Tee stdout to the console and to a per-run log file.

    With ``plain=True`` the file copy is stripped of ANSI codes and Rich panel
    borders, which keeps long agent transcripts readable. ``echo=False`` writes
    to the file only (used when several runs execute in parallel).
    """

    def __init__(self, filepath, original_stdout, plain: bool = False, echo: bool = True):
        self.terminal = original_stdout
        self.echo = echo
        self.log_file = open(filepath, 'w', encoding='utf-8')
        self.plain = plain
        self._buf = ''

    def write(self, message):
        if self.echo:
            self.terminal.write(message)
        if not self.plain:
            self.log_file.write(message)
            return
        self._buf += _ANSI_ESCAPE.sub('', message).replace('\r', '')
        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            self.log_file.write(_format_rich_line(line))

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        if self._buf:
            self.log_file.write(_format_rich_line(self._buf))
            self._buf = ''
        self.log_file.close()


@contextmanager
def run_log(log_filename, plain: bool = False, echo: bool = True):
    """Redirect stdout into ``log_filename`` (and the console) for the duration of one run."""
    Path(log_filename).parent.mkdir(parents=True, exist_ok=True)
    original_stdout = sys.stdout
    logger = TeeLogger(log_filename, original_stdout, plain=plain, echo=echo)
    sys.stdout = logger
    try:
        yield
    finally:
        sys.stdout = original_stdout
        logger.close()


def load_run_list(config_path) -> list[dict]:
    """Load a run config: a JSON list with one settings object per run."""
    try:
        with open(config_path, 'r') as f:
            all_settings = json.load(f)
    except FileNotFoundError:
        sys.exit(f"Error: Config file not found at {config_path}")
    except json.JSONDecodeError:
        sys.exit(f"Error: Config file {config_path} is not valid JSON.")
    if not isinstance(all_settings, list):
        sys.exit("Error: Config file must contain a JSON *list* of settings objects.")
    return all_settings


def load_tactics_db() -> dict:
    """Load a fresh copy of the tactics database (flows mutate it while running)."""
    with open(Path(__file__).parent / "tactics_db.json", 'r') as f:
        return json.load(f)
