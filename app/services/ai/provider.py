from __future__ import annotations

import json
from typing import TypeVar

from flask import current_app
from openai import OpenAI
from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class AIProviderError(RuntimeError):
    pass


class OpenAIProvider:
    """Multi-provider structured output adapter with OpenAI and OpenRouter support.
    
    Supports automatic fallback across models and providers when tokens run out or
    rate/quota limits are reached.
    """

    def __init__(self) -> None:
        primary_key = current_app.config.get("OPENAI_API_KEY", "").strip()
        backup_key = current_app.config.get("OPENAI_BACKUP_API_KEY", "").strip()
        openrouter_key = current_app.config.get("OPENROUTER_API_KEY", "").strip()

        if not primary_key and not backup_key and not openrouter_key:
            raise AIProviderError("Neither OPENAI_API_KEY nor OPENROUTER_API_KEY is configured.")

        timeout = current_app.config.get("OPENAI_TIMEOUT_SECONDS", 45.0)
        self.max_output_tokens = current_app.config.get("OPENAI_MAX_OUTPUT_TOKENS", 3000)

        self.candidates: list[dict] = []

        # 1. Register direct OpenAI candidates if keys are configured
        openai_models: list[str] = []
        for model in [
            current_app.config.get("OPENAI_MODEL", "gpt-5-mini").strip(),
            current_app.config.get("OPENAI_FALLBACK_MODEL", "gpt-4o-mini").strip(),
        ]:
            if model and model not in openai_models:
                openai_models.append(model)

        openai_keys: list[tuple[str, str]] = []
        if primary_key:
            openai_keys.append(("OpenAI primary", primary_key))
        if backup_key and backup_key != primary_key:
            openai_keys.append(("OpenAI backup", backup_key))

        for key_label, key in openai_keys:
            client = OpenAI(
                api_key=key,
                timeout=timeout,
                max_retries=1,
            )
            for model in openai_models:
                self.candidates.append(
                    {
                        "label": f"{key_label} ({model})",
                        "client": client,
                        "model": model,
                        "mode": "responses",
                    }
                )

        # 2. Register OpenRouter candidates if OPENROUTER_API_KEY is configured
        if openrouter_key:
            openrouter_models: list[str] = []
            for model in [
                current_app.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip(),
                current_app.config.get("OPENROUTER_FALLBACK_MODEL", "google/gemini-2.0-flash-001").strip(),
            ]:
                if model and model not in openrouter_models:
                    openrouter_models.append(model)

            openrouter_base_url = current_app.config.get(
                "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ).strip()

            openrouter_client = OpenAI(
                base_url=openrouter_base_url,
                api_key=openrouter_key,
                timeout=timeout,
                max_retries=1,
                default_headers={
                    "HTTP-Referer": "https://github.com/parksmart-ai",
                    "X-Title": "ParkSmart AI",
                },
            )

            for model in openrouter_models:
                self.candidates.append(
                    {
                        "label": f"OpenRouter ({model})",
                        "client": openrouter_client,
                        "model": model,
                        "mode": "chat",
                    }
                )

    def _invoke_candidate(
        self, candidate: dict, instructions: str, payload: dict, schema: type[SchemaT]
    ) -> SchemaT | None:
        client: OpenAI = candidate["client"]
        model: str = candidate["model"]
        mode: str = candidate["mode"]

        user_content = (
            "Analyze only this supplied JSON:\n"
            + json.dumps(payload, separators=(",", ":"), default=str)
        )

        if mode == "responses":
            response = client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": user_content},
                ],
                text_format=schema,
                max_output_tokens=self.max_output_tokens,
                store=False,
            )
            return getattr(response, "output_parsed", None)

        # Chat completions mode (used for OpenRouter and OpenAI-compatible endpoints)
        try:
            chat_response = client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": user_content},
                ],
                response_format=schema,
                max_tokens=self.max_output_tokens,
            )
            if chat_response.choices and chat_response.choices[0].message.parsed:
                return chat_response.choices[0].message.parsed
        except Exception:
            # Fallback for models on OpenRouter that don't support strict response_format
            fallback_response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"{instructions}\nRespond with valid JSON conforming to: "
                            f"{json.dumps(schema.model_json_schema())}"
                        ),
                    },
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                max_tokens=self.max_output_tokens,
            )
            content = fallback_response.choices[0].message.content or ""
            return schema.model_validate_json(content)

        return None

    def generate(self, *, instructions: str, payload: dict, schema: type[SchemaT]) -> SchemaT:
        errors: list[str] = []

        for candidate in self.candidates:
            label = candidate["label"]
            try:
                parsed = self._invoke_candidate(candidate, instructions, payload, schema)
                if parsed is not None:
                    return parsed
                errors.append(f"{label}: returned no validated output.")
            except Exception as exc:
                error_summary = f"{type(exc).__name__}: {str(exc)[:150]}"
                errors.append(f"{label} failed ({error_summary})")
                current_app.logger.warning(
                    "AI generation failed on %s. Attempting fallback if available. Error: %s",
                    label,
                    exc,
                )

        raise AIProviderError(
            f"All AI candidates failed: {'; '.join(errors)}"
        )

