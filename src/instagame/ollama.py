"""Minimal Ollama HTTP client.

Deliberately built on the standard library so running local models adds no
dependency. Only the two endpoints the game needs are covered.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .logging_config import get_logger

logger = get_logger("ollama")

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT = 120.0


class OllamaError(RuntimeError):
    """Raised when Ollama cannot be reached or returns an error."""


@dataclass(frozen=True)
class Completion:
    """One model response.

    Attributes
    ----------
    text : str
        Raw response body from the model.
    latency : float
        Wall clock seconds for the call.
    eval_count : int
        Tokens generated, or 0 when the server did not report it.
    """

    text: str
    latency: float
    eval_count: int


def normalise_host(host: str | None) -> str:
    """Return a usable base URL for the Ollama server.

    Accepts the bare ``host:port`` form that ``OLLAMA_HOST`` often carries.

    Parameters
    ----------
    host : str or None
        Configured host, or None to read the environment then fall back to
        the default localhost address.

    Returns
    -------
    str
        Base URL with a scheme and no trailing slash.
    """
    value = host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
    if "://" not in value:
        value = f"http://{value}"
    return value.rstrip("/")


class OllamaClient:
    """Thin wrapper over the Ollama generate API.

    Parameters
    ----------
    host : str or None, optional
        Server base URL, by default read from ``OLLAMA_HOST``.
    timeout : float, optional
        Per-request timeout in seconds, by default 120.
    """

    def __init__(self, host: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.host = normalise_host(host)
        self.timeout = timeout
        self._think_unsupported: set[str] = set()

    def _post(self, path: str, payload: dict) -> dict:
        """POST a JSON body and return the decoded response.

        Parameters
        ----------
        path : str
            Endpoint path, such as ``/api/generate``.
        payload : dict
            Request body.

        Returns
        -------
        dict
            Decoded JSON response.

        Raises
        ------
        OllamaError
            On transport failure or a non-2xx response.
        """
        request = urllib.request.Request(
            f"{self.host}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise OllamaError(f"{exc.code} from {path}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OllamaError(f"cannot reach ollama at {self.host}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise OllamaError(f"malformed response from {path}: {exc}") from exc

    def available_models(self) -> list[str]:
        """List model tags the server has locally.

        Returns
        -------
        list of str
            Model tags, sorted.

        Raises
        ------
        OllamaError
            If the server cannot be reached.
        """
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise OllamaError(f"cannot list models at {self.host}: {exc}") from exc
        return sorted(entry["name"] for entry in payload.get("models", []))

    def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        schema: dict | None = None,
        temperature: float = 0.7,
        num_predict: int = 128,
        think: bool | None = False,
    ) -> Completion:
        """Run one completion.

        Parameters
        ----------
        model : str
            Model tag.
        prompt : str
            User prompt.
        system : str or None, optional
            System prompt. Keeping this stable across calls lets Ollama reuse
            its cached prefix.
        schema : dict or None, optional
            JSON schema constraining the output.
        temperature : float, optional
            Sampling temperature, by default 0.7.
        num_predict : int, optional
            Output token ceiling, by default 128.
        think : bool or None, optional
            Whether to allow reasoning tokens on hybrid models. Passing False
            keeps latency down. Models that reject the field are detected once
            and the field is dropped for them afterwards.

        Returns
        -------
        Completion
            The model response with timing.

        Raises
        ------
        OllamaError
            On transport failure or a non-2xx response.
        """
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if system is not None:
            payload["system"] = system
        if schema is not None:
            payload["format"] = schema
        send_think = think is not None and model not in self._think_unsupported
        if send_think:
            payload["think"] = think

        started = time.monotonic()
        try:
            data = self._post("/api/generate", payload)
        except OllamaError as exc:
            if send_think and "think" in str(exc).lower():
                logger.info("model %s rejects the think field; retrying without it", model)
                self._think_unsupported.add(model)
                payload.pop("think")
                data = self._post("/api/generate", payload)
            else:
                raise
        return Completion(
            text=data.get("response", ""),
            latency=time.monotonic() - started,
            eval_count=int(data.get("eval_count") or 0),
        )
