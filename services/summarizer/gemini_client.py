"""Google Gemini integration: turns a list of news items into structured digest topics."""

import asyncio
import json
import logging
import random
from collections.abc import Sequence

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from db.models import NewsItem
from services.summarizer.prompts import SYSTEM_INSTRUCTION, build_user_prompt

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class SummarizationError(RuntimeError):
    """Raised when Gemini could not produce a usable result after all attempts."""


class Topic(BaseModel):
    category: str
    headline: str
    summary: str
    source_id: int


class DigestResponse(BaseModel):
    topics: list[Topic]


class GeminiSummarizer:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash",
        timeout_seconds: int = 90,
        max_attempts: int = 3,
        client: genai.Client | None = None,
        backoff_base_seconds: float = 2.0,
        fallback_model: str | None = None,
    ) -> None:
        self._client = client or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=timeout_seconds * 1000)
        )
        # Attempts rotate through these models, so an overloaded primary does not sink the whole request.
        self._models = [model] + ([fallback_model] if fallback_model and fallback_model != model else [])
        self._timeout = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds

    async def generate_topics(
        self, items: Sequence[NewsItem], categories: Sequence[str], window_hours: int
    ) -> list[Topic]:
        """Cluster and summarize `items`. Retries transient failures up to `max_attempts` times."""
        if not items:
            return []

        prompt = build_user_prompt(items, categories, window_hours)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=DigestResponse,
            temperature=0.3,
            max_output_tokens=8192,
        )

        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            model = self._models[(attempt - 1) % len(self._models)]
            try:
                # Outer timeout guards against hangs the HTTP-level timeout does not catch.
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(model=model, contents=prompt, config=config),
                    timeout=self._timeout + 5,
                )
                return self._parse(response.text)
            except genai_errors.APIError as exc:
                last_error = exc
                if exc.code not in RETRYABLE_STATUS_CODES:
                    raise SummarizationError(f"Gemini API error {exc.code}: {exc.message}") from exc
                logger.warning("Gemini attempt %d/%d (%s) failed: %s %s", attempt, self._max_attempts, model, exc.code, exc.message)
            except (asyncio.TimeoutError, TimeoutError) as exc:
                last_error = exc
                logger.warning("Gemini attempt %d/%d (%s) timed out", attempt, self._max_attempts, model)
            except (ValueError, ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.warning("Gemini attempt %d/%d returned invalid output: %s", attempt, self._max_attempts, exc)
            except Exception as exc:  # noqa: BLE001 - network-level errors from the SDK's HTTP layer
                last_error = exc
                logger.warning("Gemini attempt %d/%d failed: %r", attempt, self._max_attempts, exc)

            if attempt < self._max_attempts:
                await asyncio.sleep(self._backoff_base * 2 ** (attempt - 1) + random.uniform(0, 0.5))

        raise SummarizationError(f"Gemini failed after {self._max_attempts} attempts: {last_error!r}")

    @staticmethod
    def _parse(text: str | None) -> list[Topic]:
        if not text:
            raise ValueError("Empty response from Gemini")
        return DigestResponse.model_validate_json(text).topics
