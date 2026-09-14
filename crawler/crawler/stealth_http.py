"""Stealth HTTP fetching for the plain (non-Playwright) request path.

Anti-bot/CAPTCHA systems (Cloudflare, DataDome, PerimeterX, ...) commonly flag
a request before they even look at its headers: Python's default TLS stack
(urllib3/Twisted) produces a JA3/JA4 fingerprint that matches no real browser,
so the request is rejected on the handshake alone. curl_cffi ships builds of
curl linked against a patched BoringSSL/QUIC stack that reproduce a real
Chrome build's handshake byte-for-byte (the ``impersonate`` parameter below),
which is what actually avoids the CAPTCHA - a spoofed User-Agent string alone
does nothing about the TLS layer.

Header consistency and session continuity matter too: a request claiming to
be Chrome 124 but sending a mismatched or incomplete header set is its own
tell, and a request with no cookie history looks colder than one with a
built-up session. curl_cffi's impersonation already emits Chrome's real
header cluster (sec-ch-ua*, sec-fetch-*, Accept, ...) matched to the
impersonated version, so this module only overrides the couple of values
(platform, and whatever the real request carries - Referer, Cookie, POST
body/Content-Type) that need to reflect this crawl rather than curl_cffi's
own default macOS placeholder identity. A curl_cffi Session is kept per
domain so cookies accumulate across requests to the same host the way a real
browsing session's would, instead of every request looking like a fresh,
cookie-less visitor.
"""

import threading
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests
from scrapy.http import Request, Response
from scrapy.responsetypes import responsetypes

# Kept in step with the Chrome version impersonated below and with
# settings.USER_AGENT's Windows Chrome/124 identity, so the TLS fingerprint,
# User-Agent, and sec-ch-ua* headers all agree on the same browser/OS - an
# inconsistency between them is itself a signal anti-bot systems check for.
IMPERSONATE = "chrome124"
PLATFORM_HEADERS = {
    "sec-ch-ua-platform": '"Windows"',
}

# Headers curl_cffi's impersonation should keep full control of - Scrapy's
# DefaultHeadersMiddleware/UserAgentMiddleware fill these with generic values
# (a plain "en" Accept-Language, an Accept with no browser-specific MIME
# clause, ...) that are less internally consistent than what curl_cffi
# already sends for the impersonated Chrome build, and a mismatched
# User-Agent/Accept-Encoding pair is exactly the kind of inconsistency
# anti-bot systems check for. Every other request header - Referer, Cookie,
# Content-Type, and crucially any auth header (ApiTokenAuthMiddleware's
# Authorization or a custom header_name from auth.json) - must still reach
# the real request, so those are forwarded as-is rather than allowlisted.
UNFORWARDED_HEADERS = {"user-agent", "accept-encoding", "accept", "accept-language"}

_sessions = {}
_sessions_lock = threading.Lock()


def _session_for_domain(domain):
    with _sessions_lock:
        session = _sessions.get(domain)
        if session is None:
            session = curl_requests.Session()
            _sessions[domain] = session
        return session


def _forwarded_headers(request: Request) -> dict:
    headers = {}
    for key, values in request.headers.items():
        name = key.decode("utf-8", errors="ignore")
        if name.lower() not in UNFORWARDED_HEADERS and values:
            headers[name] = b",".join(values).decode("utf-8", errors="ignore")
    return headers


def stealth_fetch(request: Request) -> Response:
    """Runs one Scrapy Request through curl_cffi's Chrome impersonation and
    returns the equivalent Scrapy Response. Synchronous/blocking - callers
    run this in a thread (see StealthDownloadHandler)."""
    domain = urlparse(request.url).netloc
    session = _session_for_domain(domain)

    headers = {**PLATFORM_HEADERS, **_forwarded_headers(request)}
    timeout = request.meta.get("download_timeout") or 30

    curl_response = session.request(
        request.method,
        request.url,
        headers=headers,
        data=request.body or None,
        impersonate=IMPERSONATE,
        allow_redirects=True,
        timeout=timeout,
    )

    response_headers = {
        name.encode("utf-8"): value.encode("utf-8")
        for name, value in curl_response.headers.items()
    }
    respcls = responsetypes.from_args(
        headers=response_headers, url=curl_response.url, body=curl_response.content
    )
    return respcls(
        url=curl_response.url,
        status=curl_response.status_code,
        headers=response_headers,
        body=curl_response.content,
        request=request,
    )
