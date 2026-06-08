"""Tests for XFCC (X-Forwarded-Client-Cert) peer-identity parsing (E2)."""

from __future__ import annotations

import pytest
from sovereign.mtls import parse_xfcc_identity


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_blank_header_returns_none(raw: str | None) -> None:
    assert parse_xfcc_identity(raw) is None


def test_no_uri_field_returns_none() -> None:
    # A cert element with only Subject/DNS but no URI SAN.
    raw = 'By=spiffe://sovereign/broker;Hash=abc123;DNS=broker.svc'
    assert parse_xfcc_identity(raw) is None


def test_extracts_uri_san() -> None:
    raw = "By=spiffe://sovereign/audit;Hash=def456;URI=spiffe://sovereign/broker"
    assert parse_xfcc_identity(raw) == "spiffe://sovereign/broker"


def test_uri_match_is_case_insensitive_on_key() -> None:
    raw = "hash=abc;uri=spiffe://sovereign/broker"
    assert parse_xfcc_identity(raw) == "spiffe://sovereign/broker"


def test_quoted_value_is_unwrapped() -> None:
    # Envoy double-quotes values that contain separators.
    raw = 'Hash=abc;URI="spiffe://sovereign/broker;extra"'
    assert parse_xfcc_identity(raw) == "spiffe://sovereign/broker;extra"


def test_only_leaf_element_is_consulted() -> None:
    # First element is the downstream peer; later elements (CA/intermediate)
    # must NOT win even if they carry a URI.
    raw = (
        "URI=spiffe://sovereign/broker,"
        "URI=spiffe://sovereign/ca-should-be-ignored"
    )
    assert parse_xfcc_identity(raw) == "spiffe://sovereign/broker"


def test_quoted_comma_does_not_split_elements() -> None:
    raw = 'Subject="O=Sovereign,CN=broker";URI=spiffe://sovereign/broker'
    assert parse_xfcc_identity(raw) == "spiffe://sovereign/broker"


def test_escaped_quote_inside_value() -> None:
    raw = r'Subject="CN=\"broker\"";URI=spiffe://sovereign/broker'
    assert parse_xfcc_identity(raw) == "spiffe://sovereign/broker"


def test_empty_uri_value_returns_none() -> None:
    assert parse_xfcc_identity("Hash=abc;URI=") is None
