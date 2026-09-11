"""Per-domain authentication config for crawling login/subscription-gated
sites, loaded from a local JSON file (default: auth.json, gitignored - never
commit it). Only ever references environment variable NAMES for credentials/
tokens, never the secret values themselves - actual secrets come from the
process environment (e.g. a local, gitignored .env loaded before `scrapy
crawl`, or your shell/CI secret store) at run time.

Four methods, one per domain:
  - storage_state:   reuse an already-authenticated session (cookies +
                      localStorage) exported from a real browser/prior login.
                      No login flow is run at all - just loaded.
  - form_login:       plain HTML <form method=post> login. Two-hop GET+POST.
  - playwright_login:  JS-rendered login (SPA/React) - driven via a real
                      browser (Playwright): fill fields, click submit, wait
                      for a post-login element.
  - api_token:        token/API-key auth - a header is injected on every
                      request to the domain (see ApiTokenAuthMiddleware),
                      no login flow needed.

This only handles crawling sites you already have legitimate access to
(your own subscription, an internal tool, an authorized client engagement).
It does not attempt to solve CAPTCHAs, 2FA, or otherwise get past an access
control you don't have valid credentials for."""

import json
import os


class AuthError(Exception):
    pass


VALID_METHODS = ("storage_state", "form_login", "playwright_login", "api_token")


class AuthProfile:
    def __init__(self, domain, config):
        self.domain = domain
        self.method = config.get("method")
        if self.method not in VALID_METHODS:
            raise AuthError(f"auth config for {domain}: 'method' must be one of {VALID_METHODS}, got {self.method!r}")
        self._config = config

    def _env(self, key):
        env_name = self._config.get(key)
        if not env_name:
            raise AuthError(f"auth config for {self.domain}: missing {key!r} (the name of an environment variable)")
        value = os.environ.get(env_name)
        if not value:
            raise AuthError(
                f"auth config for {self.domain}: environment variable {env_name!r} "
                f"(referenced by {key!r}) is not set"
            )
        return value

    # storage_state
    @property
    def storage_state_path(self):
        return self._config.get("storage_state")

    # form_login / playwright_login
    @property
    def login_url(self):
        return self._config.get("login_url")

    @property
    def username(self):
        return self._env("username_env")

    @property
    def password(self):
        return self._env("password_env")

    @property
    def username_field(self):
        return self._config.get("username_field", "username")

    @property
    def password_field(self):
        return self._config.get("password_field", "password")

    @property
    def username_selector(self):
        return self._config.get("username_selector")

    @property
    def password_selector(self):
        return self._config.get("password_selector")

    @property
    def submit_selector(self):
        return self._config.get("submit_selector")

    @property
    def success_selector(self):
        return self._config.get("success_selector")

    @property
    def save_storage_state(self):
        return self._config.get("save_storage_state")

    # api_token
    @property
    def header_name(self):
        return self._config.get("header_name", "Authorization")

    @property
    def token_format(self):
        return self._config.get("token_format", "{token}")

    @property
    def token(self):
        return self._env("token_env")

    def token_header_value(self):
        return self.token_format.format(token=self.token)

    def validate(self):
        """Fail fast at spider startup - before any requests go out - rather
        than mid-crawl on the first request that needed this profile."""
        if self.method == "storage_state":
            if not self.storage_state_path:
                raise AuthError(f"auth config for {self.domain}: storage_state requires a 'storage_state' path")
            if not os.path.exists(self.storage_state_path):
                raise AuthError(f"auth config for {self.domain}: storage_state file not found: {self.storage_state_path}")
        elif self.method == "form_login":
            if not self.login_url:
                raise AuthError(f"auth config for {self.domain}: form_login requires 'login_url'")
            self.username
            self.password
        elif self.method == "playwright_login":
            if not self.login_url:
                raise AuthError(f"auth config for {self.domain}: playwright_login requires 'login_url'")
            for key in ("username_selector", "password_selector", "submit_selector", "success_selector"):
                if not self._config.get(key):
                    raise AuthError(f"auth config for {self.domain}: playwright_login requires {key!r}")
            self.username
            self.password
        elif self.method == "api_token":
            self.token


def load_auth_config(path):
    """Returns {domain: AuthProfile}. Returns {} if the file doesn't exist -
    auth is entirely optional, a crawl with no auth config behaves exactly as
    a plain unauthenticated crawl always has."""
    if not path or not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    profiles = {}
    for domain, config in raw.items():
        if domain.startswith("_"):
            continue  # e.g. a top-level "_comment" key - not a real domain
        profile = AuthProfile(domain, config)
        profile.validate()
        profiles[domain] = profile
    return profiles
