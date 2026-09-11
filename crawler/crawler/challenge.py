"""Detects bot-challenge/block pages (Cloudflare, hCaptcha, reCAPTCHA, DataDome,
PerimeterX, GeeTest, ...) so the spider can avoid storing them as real content
and avoid retrying them forever."""

# substrings are matched case-insensitively against the response body
_CHALLENGE_MARKERS = [
    "checking your browser",
    "just a moment",
    "cf-browser-verification",
    "cf_chl_opt",
    "cf-turnstile",
    "attention required! | cloudflare",
    "verify you are human",
    "verify you are a human",
    "please verify you are a human",
    "g-recaptcha",
    "hcaptcha.com",
    "captcha-delivery.com",  # DataDome
    "px-captcha",  # PerimeterX
    "geetest",
]

_BLOCKED_STATUSES = {403, 429, 503}


def detect_challenge(status, text):
    """Returns a short reason string if this response looks like a bot
    challenge/block page rather than real content, else None."""
    lowered = (text or "").lower()
    for marker in _CHALLENGE_MARKERS:
        if marker in lowered:
            return f"marker:{marker}"
    if status in _BLOCKED_STATUSES:
        return f"status:{status}"
    return None
