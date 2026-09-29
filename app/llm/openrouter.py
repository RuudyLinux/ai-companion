"""
OpenRouter (OpenAI-compatible) client with timeouts, retries and model fallback.

Retries only happen *before* the first token arrives: once text has been streamed to the
user, retrying would duplicate or contradict it, so a mid-stream failure surfaces as an
LLMError and the caller keeps the partial text.
"""

import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache

import openai
from openai import OpenAI

from core.config import settings

log = logging.getLogger("app.llm")


class LLMError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class StreamResult:
    """Filled in while stream_reply() iterates; read after the iterator is exhausted."""

    model: str | None = None
    finish_reason: str | None = None


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    if not settings.openrouter_api_key:
        raise LLMError("LLM_NOT_CONFIGURED", "OPENROUTER_API_KEY is not set.")
    return OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,  # retries are handled below so fallback models get a turn
    )


def _normalise(exc: Exception) -> LLMError:
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, openai.APITimeoutError):
        return LLMError("LLM_TIMEOUT", "The language model took too long to respond.", retryable=True)
    if isinstance(exc, openai.APIConnectionError):
        return LLMError("LLM_UNAVAILABLE", "Couldn't reach the language model provider.", retryable=True)
    if isinstance(exc, openai.RateLimitError):
        return LLMError("LLM_RATE_LIMITED", "The language model is rate limited. Try again shortly.", retryable=True)
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return LLMError("LLM_AUTH_FAILED", "The language model provider rejected our credentials.")
    if isinstance(exc, openai.BadRequestError):
        return LLMError("LLM_BAD_REQUEST", "The language model rejected the request.")
    if isinstance(exc, openai.NotFoundError):
        return LLMError("LLM_MODEL_NOT_FOUND", "The configured language model doesn't exist.")
    if isinstance(exc, openai.APIStatusError):
        return LLMError("LLM_PROVIDER_ERROR", "The language model provider returned an error.", retryable=exc.status_code >= 500)
    return LLMError("LLM_ERROR", "The language model request failed.")


def _models() -> list[str]:
    return [settings.openrouter_model, *[m for m in settings.openrouter_fallback_models if m != settings.openrouter_model]]


def _with_retries(open_call: Callable[[str], object]):
    """Tries each model, retrying retryable failures with exponential backoff + jitter.
    Returns (model, opened_response)."""
    last_error: LLMError | None = None
    for model in _models():
        for attempt in range(settings.llm_max_retries + 1):
            try:
                return model, open_call(model)
            except Exception as exc:
                last_error = _normalise(exc)
                log.warning(
                    "llm call failed",
                    extra={"model": model, "error_code": last_error.code, "attempt": attempt + 1},
                )
                if not last_error.retryable:
                    break  # e.g. bad model name: move on to the fallback model immediately
                if attempt < settings.llm_max_retries:
                    time.sleep(min(8.0, 0.5 * 2**attempt) + random.uniform(0, 0.25))
    raise last_error or LLMError("LLM_ERROR", "The language model request failed.")


def stream_reply(
    messages: list[dict],
    result: StreamResult | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[str]:
    """Yields text chunks. `messages` must already include the system message."""
    result = result if result is not None else StreamResult()

    def open_stream(model: str):
        stream = _client().chat.completions.create(
            model=model,
            stream=True,
            max_tokens=settings.llm_max_output_tokens,
            messages=messages,
        )
        # pull the first chunk inside the retry window: most provider failures show up here
        iterator = iter(stream)
        first = next(iterator, None)
        return stream, iterator, first

    model, (stream, iterator, first) = _with_retries(open_stream)
    result.model = model

    def chunks():
        if first is not None:
            yield first
        yield from iterator

    try:
        for chunk in chunks():
            if should_stop is not None and should_stop():
                break
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                result.finish_reason = choice.finish_reason
            delta = choice.delta.content if choice.delta else None
            if delta:
                yield delta
    except Exception as exc:
        raise _normalise(exc) from exc
    finally:
        stream.close()  # releases the HTTP connection, also on cancel/disconnect


def complete(messages: list[dict], max_tokens: int = 600, temperature: float = 0.2) -> tuple[str, str]:
    """Non-streaming completion for background work (summaries, memory extraction).
    Returns (text, model)."""

    def open_call(model: str):
        return _client().chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens, temperature=temperature
        )

    model, response = _with_retries(open_call)
    text = (response.choices[0].message.content or "").strip() if response.choices else ""
    return text, model
