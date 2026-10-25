"""The console story must reach a piped log at once: the approval code line is read aloud during a live call, so a
block-buffered `python demo/build.py | tee log` that shows it only at exit loses the call (rehearsal 22:17)."""
from __future__ import annotations

import io

from demo.common import Narrator


class _Tracked(io.StringIO):
    """A stream that records what had been flushed, like a pipe that only delivers on flush."""

    def __init__(self):
        super().__init__()
        self.delivered = ""

    def flush(self):
        super().flush()
        self.delivered = self.getvalue()


def test_every_narrator_line_is_flushed_when_written():
    stream = _Tracked()
    n = Narrator(True, stream)
    n.note("approval code for the call (read it, then say approve): maple river")
    assert "maple river" in stream.delivered
    n.line("LIVE", "a tagged fact")
    assert "a tagged fact" in stream.delivered
    n.header(1, "title", "code")
    assert "BEAT 1: title" in stream.delivered


def test_a_silent_narrator_writes_and_flushes_nothing():
    stream = _Tracked()
    Narrator(False, stream).note("secret")
    assert stream.getvalue() == "" and stream.delivered == ""
