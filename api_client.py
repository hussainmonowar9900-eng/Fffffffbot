"""External reseller API client — handles communication with the upstream API."""

import logging
import urllib.request
import urllib.error
import json
from typing import Optional
from config import Config

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Raised when the external API returns an error or is unreachable."""


class APIClient:
    """Thin wrapper around the external reseller API.

    Uses urllib (stdlib) to avoid adding a dependency.
    """

    def __init__(self, config: Config):
        self.api_url = config.api_url.rstrip("/")
        self.api_key = config.api_key
        self.master_key = config.master_key
        self.timeout = config.api_timeout

    @property
    def is_configured(self) -> bool:
        """True if API URL and key are set."""
        return bool(self.api_url and self.api_key)

    def _make_request(self, endpoint: str, data: dict, method: str = "POST") -> dict:
        """Make an HTTP request to the external API. Raises APIError on failure."""
        if not self.is_configured:
            raise APIError("External API is not configured.")

        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        payload = json.dumps(data).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.master_key:
            headers["X-Master-Key"] = self.master_key

        req = urllib.request.Request(url, data=payload, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                pass
            logger.error("API HTTP %d: %s", e.code, body[:200])
            raise APIError(f"API returned HTTP {e.code}")
        except urllib.error.URLError as e:
            logger.error("API connection error: %s", e.reason)
            raise APIError("Could not connect to the external API.")
        except json.JSONDecodeError:
            logger.error("API returned invalid JSON")
            raise APIError("External API returned an invalid response.")
        except Exception as e:
            logger.error("API unexpected error: %s", e)
            raise APIError("Unexpected error contacting the external API.")

    def place_order(self, pid_value: str, plan_name: str = "", quantity: int = 1) -> dict:
        """Place an order with the external API.

        Returns a dict with at least:
            - key: the activation key or order reference
            - order_id: the upstream order ID

        Raises APIError on failure.
        """
        data = {
            "pid": pid_value,
            "plan": plan_name,
            "quantity": quantity,
        }
        result = self._make_request("order", data)

        if not result or "key" not in result:
            raise APIError("API did not return a valid key.")

        return result

    def check_balance(self) -> Optional[dict]:
        """Check the reseller API account balance. Returns None if unavailable."""
        if not self.is_configured:
            return None
        try:
            return self._make_request("balance", {}, method="GET")
        except APIError:
            return None
