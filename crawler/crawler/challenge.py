"""Detects bot-challenge/block pages (Cloudflare, hCaptcha, reCAPTCHA, DataDome,
PerimeterX, GeeTest, ...) so the spider can avoid storing them as real content
and avoid retrying them forever."""

# substrings that only ever appear on an actual interstitial/block page -
# matched case-insensitively against the response body, unconditionally
_STRONG_CHALLENGE_MARKERS = [
    "checking your browser",
    "just a moment",
    "cf-browser-verification",
    "cf_chl_opt",
    "cf-turnstile",
    "attention required! | cloudflare",
    "verify you are human",
    "verify you are a human",
    "please verify you are a human",
    "captcha-delivery.com",  # DataDome
    "px-captcha",  # PerimeterX
    "geetest",
]

# substrings that also show up as ordinary page furniture - a reCAPTCHA
# widget on a comment/newsletter/contact form, or an hCaptcha script tag for
# one - on otherwise-normal content pages across a huge share of the web.
# e.g. indianexpress.com/hindustantimes.com pages were observed at 200 with
# 900KB-1.1MB of real article HTML, flagged purely because ".g-recaptcha"
# appears as a CSS class for a footer widget. Only trust these markers on a
# response thin enough to plausibly *be* the challenge itself - a genuine
# reCAPTCHA/hCaptcha checkpoint page is a near-empty shell, not a full page
# with an embedded widget.
_WEAK_CHALLENGE_MARKERS = [
    "g-recaptcha",
    "hcaptcha.com",
]
_WEAK_MARKER_MAX_BODY_LEN = 10_000

_BLOCKED_STATUSES = {403, 429, 503}


def detect_challenge(status, text):
    """Returns a short reason string if this response looks like a bot
    challenge/block page rather than real content, else None."""
    lowered = (text or "").lower()
    for marker in _STRONG_CHALLENGE_MARKERS:
        if marker in lowered:
            return f"marker:{marker}"
    if len(lowered) < _WEAK_MARKER_MAX_BODY_LEN:
        for marker in _WEAK_CHALLENGE_MARKERS:
            if marker in lowered:
                return f"marker:{marker}"
    if status in _BLOCKED_STATUSES:
        return f"status:{status}"
    return None
