"""Prometheus 指标：TTFT / token / degraded / recall / cost"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response


gateway_requests_total = Counter(
    "gateway_requests_total", "Total requests",
    ["model", "stream", "status"])

gateway_ttft_seconds = Histogram(
    "gateway_ttft_seconds", "Time to first token",
    ["model"], buckets=(0.1, 0.3, 0.5, 1, 2, 5, 10, 30, 60))

gateway_duration_seconds = Histogram(
    "gateway_duration_seconds", "End-to-end duration",
    ["model", "stream"], buckets=(0.5, 1, 3, 5, 10, 30, 60, 120, 300))

gateway_tokens_total = Counter(
    "gateway_tokens_total", "Total tokens",
    ["model", "type"])

memory_recall_total = Counter(
    "memory_recall_total", "Recall calls",
    ["backend", "status"])

memory_recall_hits = Histogram(
    "memory_recall_hits", "Number of hits per recall",
    ["backend"], buckets=(0, 1, 2, 3, 5, 10))

memory_write_total = Counter(
    "memory_write_total", "Write calls",
    ["backend", "status"])

context_degraded_total = Counter(
    "context_degraded_total", "Context degradation events",
    ["reason"])

gateway_cost_yuan = Counter(
    "gateway_cost_yuan", "Estimated cost in CNY",
    ["model"])

gateway_rate_limited_total = Counter(
    "gateway_rate_limited_total", "Rate limited requests",
    ["user_id"])

memory_user_count = Gauge(
    "memory_user_count", "Distinct users in memory")

memory_total_count = Gauge(
    "memory_total_count", "Total memories stored")


def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
