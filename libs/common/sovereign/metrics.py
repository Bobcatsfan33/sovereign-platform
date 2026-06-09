"""A tiny, dependency-free Prometheus metrics registry (E5).

The platform deliberately avoids a runtime metrics dependency (see
observability.py). This adds just enough — labelled counters and histograms,
rendered in Prometheus text exposition format — to expose RED metrics
(request rate, errors, duration) without pulling in `prometheus_client`.

Not a general-purpose client: single-process, no exemplars, no pushgateway.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

_NAME_RE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:"

#: Default duration buckets (seconds), matching prometheus_client's defaults.
DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)


def _sanitize(name: str) -> str:
    return "".join(c if c in _NAME_RE else "_" for c in name)


def _label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _key(labels: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((k, str(v)) for k, v in labels.items()))


def _render_labels(key: tuple[tuple[str, str], ...], extra: tuple[str, str] | None = None) -> str:
    pairs = [f'{_sanitize(k)}="{_label_value(v)}"' for k, v in key]
    if extra is not None:
        pairs.append(f'{_sanitize(extra[0])}="{_label_value(extra[1])}"')
    return "{" + ",".join(pairs) + "}" if pairs else ""


class Counter:
    def __init__(self, name: str, help_text: str) -> None:
        self.name = _sanitize(name)
        self.help = help_text
        self._values: dict[tuple[tuple[str, str], ...], float] = {}

    def inc(self, labels: Mapping[str, str] | None = None, amount: float = 1.0) -> None:
        key = _key(labels or {})
        self._values[key] = self._values.get(key, 0.0) + amount

    def render(self) -> str:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        for key, value in sorted(self._values.items()):
            out.append(f"{self.name}{_render_labels(key)} {_fmt(value)}")
        return "\n".join(out) + "\n"


class Histogram:
    def __init__(
        self, name: str, help_text: str, buckets: tuple[float, ...] = DEFAULT_BUCKETS
    ) -> None:
        self.name = _sanitize(name)
        self.help = help_text
        self.buckets = tuple(sorted(buckets))
        self._counts: dict[tuple[tuple[str, str], ...], list[int]] = {}
        self._sum: dict[tuple[tuple[str, str], ...], float] = {}
        self._total: dict[tuple[tuple[str, str], ...], int] = {}

    def observe(self, value: float, labels: Mapping[str, str] | None = None) -> None:
        key = _key(labels or {})
        counts = self._counts.setdefault(key, [0] * len(self.buckets))
        # Per-bucket tally (only the smallest matching bucket); render() turns
        # these into the cumulative `le` series Prometheus expects.
        for i, edge in enumerate(self.buckets):
            if value <= edge:
                counts[i] += 1
                break
        self._sum[key] = self._sum.get(key, 0.0) + value
        self._total[key] = self._total.get(key, 0) + 1

    def render(self) -> str:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for key in sorted(self._counts):
            counts = self._counts[key]
            cumulative = 0
            for edge, c in zip(self.buckets, counts, strict=True):
                cumulative += c
                le = _fmt(edge)
                out.append(f"{self.name}_bucket{_render_labels(key, ('le', le))} {cumulative}")
            total = self._total[key]
            out.append(f"{self.name}_bucket{_render_labels(key, ('le', '+Inf'))} {total}")
            out.append(f"{self.name}_sum{_render_labels(key)} {_fmt(self._sum[key])}")
            out.append(f"{self.name}_count{_render_labels(key)} {total}")
        return "\n".join(out) + "\n"


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(value)


class Registry:
    """A flat collection of counters and histograms, rendered together."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    def counter(self, name: str, help_text: str) -> Counter:
        with self._lock:
            return self._counters.setdefault(name, Counter(name, help_text))

    def histogram(
        self, name: str, help_text: str, buckets: tuple[float, ...] = DEFAULT_BUCKETS
    ) -> Histogram:
        with self._lock:
            return self._histograms.setdefault(name, Histogram(name, help_text, buckets))

    def render(self) -> str:
        with self._lock:
            parts = [m.render() for m in self._counters.values()]
            parts += [m.render() for m in self._histograms.values()]
        return "".join(parts)


#: Process-wide registry the request middleware writes to.
REGISTRY = Registry()
