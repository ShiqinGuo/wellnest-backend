"""Request-local database timings without SQL text, parameters or user identifiers."""

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter


class Phase(StrEnum):
    connect = "db_connect"
    query = "db_query"
    begin = "db_begin"
    commit = "db_commit"
    close = "db_close"


@dataclass
class RequestTiming:
    durations: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, phase: Phase, seconds: float):
        self.durations[phase] += seconds * 1000
        self.counts[phase] += 1

    def header(self):
        return ", ".join(f"{key};dur={value:.1f}" for key, value in self.durations.items())


current_timing: ContextVar[RequestTiming | None] = ContextVar("request_timing", default=None)


@contextmanager
def measure(phase: Phase):
    start = perf_counter()
    try:
        yield
    finally:
        if timing := current_timing.get():
            timing.add(phase, perf_counter() - start)
