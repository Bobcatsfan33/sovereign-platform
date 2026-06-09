"""Tests for the dependency-free Prometheus metrics registry (E5)."""

from __future__ import annotations

from sovereign.metrics import Counter, Histogram, Registry


def test_counter_renders_labels_and_value() -> None:
    c = Counter("sovereign_http_requests_total", "Total requests.")
    c.inc({"method": "GET", "status": "200"})
    c.inc({"method": "GET", "status": "200"})
    c.inc({"method": "POST", "status": "500"})
    out = c.render()
    assert "# TYPE sovereign_http_requests_total counter" in out
    assert 'sovereign_http_requests_total{method="GET",status="200"} 2' in out
    assert 'sovereign_http_requests_total{method="POST",status="500"} 1' in out


def test_histogram_buckets_are_cumulative() -> None:
    h = Histogram("dur_seconds", "Duration.", buckets=(0.1, 0.5, 1.0))
    for v in (0.05, 0.2, 0.2, 2.0):
        h.observe(v)
    out = h.render()
    # le=0.1 -> only 0.05; le=0.5 -> +two 0.2s = 3; le=1.0 -> 3; +Inf -> all 4.
    assert 'dur_seconds_bucket{le="0.1"} 1' in out
    assert 'dur_seconds_bucket{le="0.5"} 3' in out
    assert 'dur_seconds_bucket{le="1"} 3' in out
    assert 'dur_seconds_bucket{le="+Inf"} 4' in out
    assert "dur_seconds_count 4" in out
    assert "dur_seconds_sum 2.45" in out


def test_registry_renders_all() -> None:
    reg = Registry()
    reg.counter("a_total", "A.").inc()
    reg.histogram("b_seconds", "B.").observe(0.01)
    out = reg.render()
    assert "# TYPE a_total counter" in out
    assert "# TYPE b_seconds histogram" in out


def test_registry_returns_same_instance_per_name() -> None:
    reg = Registry()
    assert reg.counter("x_total", "X.") is reg.counter("x_total", "X.")
