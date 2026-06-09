# Service Level Objectives (E5)

These SLOs apply to each chassis service (`broker`, `control-plane`,
`audit-service`, `metering-service`). They are measured from the RED metrics
the services emit (`sovereign_http_requests_total`,
`sovereign_http_request_duration_seconds`) and the liveness gauge
(`sovereign_service_up`), and enforced by the alerting rules in
[`deploy/k8s/prometheus-rules.yaml`](../deploy/k8s/prometheus-rules.yaml).

## Objectives

| SLO | Target | SLI | Window |
|-----|--------|-----|--------|
| **Availability** | 99.9% | `1 - (5xx rate / total rate)` | 30-day rolling |
| **Latency** | p99 < 500 ms | `histogram_quantile(0.99, …duration_bucket)` | 30-day rolling |
| **Liveness** | up | `sovereign_service_up == 1` | — |

99.9% availability is an error budget of ~43 minutes of full failure per
30 days, or ~0.1% of requests.

## Recording rules (SLIs)

- `sovereign:request_error_rate5m` — 5m 5xx fraction per service.
- `sovereign:request_availability5m` — `1 - error_rate`.
- `sovereign:request_latency_p99_5m` — 5m p99 latency per service.

## Alerts

| Alert | Fires when | Severity |
|-------|-----------|----------|
| `SovereignServiceDown` | `sovereign_service_up == 0` for 5m | critical |
| `SovereignErrorBudgetBurn` | 5m error rate > 0.1% for 10m | warning |
| `SovereignErrorBudgetFastBurn` | 5m error rate > 5% for 2m | critical |
| `SovereignHighLatencyP99` | p99 > 500 ms for 10m | warning |

The two error-budget alerts approximate a multi-window burn-rate policy: the
slow-burn warning catches sustained budget exhaustion, the fast-burn critical
catches an acute outage. Tune thresholds per service as real traffic
baselines emerge.

## On-call

Wire `severity: critical` alerts to the pager and `warning` to the team
channel via Alertmanager routing. The `continuous_monitor` script
(`scripts/continuous_monitor.py`) provides a complementary pull-based check
(audit freshness, drift, sentinels) for environments without Prometheus.
