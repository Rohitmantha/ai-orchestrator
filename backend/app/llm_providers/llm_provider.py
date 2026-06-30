from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
import asyncio
import json
import logging

logger = logging.getLogger(__name__)

class LLMProviderError(Exception):
    pass

class LLMProvider(ABC):
    @abstractmethod
    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any], schema_name: str
    ) -> dict[str, Any]:
        raise NotImplementedError

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o", timeout_seconds: float = 30.0):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model

    async def generate_structured(self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any], schema_name: str) -> dict[str, Any]:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                response_format={"type": "json_schema", "json_schema": {"name": schema_name, "schema": json_schema, "strict": True}},
            )
        except Exception as exc: 
            raise LLMProviderError(f"OpenAI call failed: {exc}") from exc

        content = response.choices[0].message.content
        if not content:
            raise LLMProviderError("OpenAI returned an empty response body")

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(f"OpenAI response was not valid JSON: {exc}") from exc

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", timeout_seconds: float = 30.0):
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._timeout_ms = timeout_seconds * 1000

    async def generate_structured(self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any], schema_name: str) -> dict[str, Any]:
        from google.genai import errors as genai_errors
        from google.genai import types

        max_retries = 3
        backoff_time = 15
        
        for attempt in range(max_retries):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        response_json_schema=json_schema,
                        http_options=types.HttpOptions(timeout=int(self._timeout_ms)),
                    ),
                )
                if not response.text:
                    raise LLMProviderError("Gemini returned an empty response body")
                return json.loads(response.text)

            except genai_errors.APIError as exc:
                if exc.code == 429 and attempt < max_retries - 1:
                    logger.warning(f"Rate limit hit (429). Retrying in {backoff_time}s...")
                    await asyncio.sleep(backoff_time)
                    backoff_time *= 2
                    continue
                raise LLMProviderError(f"Gemini call failed: {exc}") from exc
            except Exception as exc:
                raise LLMProviderError(f"Gemini call failed unexpectedly: {exc}") from exc
        
        raise LLMProviderError("Exhausted all retry attempts due to rate limiting.")