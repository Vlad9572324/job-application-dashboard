"""Classify transport failures so a pre-POST network outage is recoverable, not a hard pause.

Only connectivity categories known to app.manager._network_reason are returned. Anything else
(HTTP statuses, parsing, auth) yields None and keeps the existing protective behaviour.
"""
import asyncio
import socket
import ssl

import aiohttp
import requests

# Order matters: the most specific category first.
_RULES = (
    ("proxy_error", lambda e: isinstance(e, (aiohttp.ClientProxyConnectionError, requests.exceptions.ProxyError))
        or any(c.__name__ in ("ProxyError", "ProxyConnectionError", "ProxyTimeoutError") for c in type(e).__mro__)),
    ("tls_error", lambda e: isinstance(e, (ssl.SSLError, aiohttp.ClientSSLError, requests.exceptions.SSLError))),
    ("connect_timeout", lambda e: isinstance(e, requests.exceptions.ConnectTimeout)),
    ("read_timeout", lambda e: isinstance(e, (requests.exceptions.ReadTimeout, aiohttp.ServerTimeoutError))),
    ("timeout", lambda e: isinstance(e, (asyncio.TimeoutError, TimeoutError, requests.exceptions.Timeout))),
    ("connection_error", lambda e: isinstance(e, (aiohttp.ClientConnectionError, aiohttp.ClientOSError,
        socket.gaierror, ConnectionError, requests.exceptions.ConnectionError))),
    ("network_error", lambda e: isinstance(e, (aiohttp.ClientError, requests.exceptions.RequestException))),
)


def classify_network_exception(exc):
    """Return a network category for `exc` or anything in its cause/context chain, else None."""
    seen, current = set(), exc
    for _ in range(8):
        if not isinstance(current, BaseException) or id(current) in seen:
            break
        seen.add(id(current))
        for category, matches in _RULES:
            if matches(current):
                return category
        current = current.__cause__ or current.__context__
    return None


def pre_dispatch_network_info(exc, error_code):
    """Result info for a network failure that happened BEFORE any write was sent."""
    category = classify_network_exception(exc)
    if category is None:
        return None
    return {"error_code": error_code, "error_type": "oauth_bridge_network",
            "reason": category, "phase": "oauth_bridge", "dispatched": False}
