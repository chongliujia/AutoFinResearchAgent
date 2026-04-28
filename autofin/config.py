from __future__ import annotations

import os
from dataclasses import dataclass, replace
from threading import Lock
from typing import Any, Dict, Optional


JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class ModelAPIConfig:
    provider: str = "openai-compatible"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.2

    @classmethod
    def from_env(cls) -> "ModelAPIConfig":
        return cls(
            provider=os.getenv("AUTOFIN_MODEL_PROVIDER", "openai-compatible"),
            model=os.getenv("AUTOFIN_MODEL_NAME", ""),
            base_url=os.getenv("AUTOFIN_MODEL_BASE_URL", ""),
            api_key=os.getenv("AUTOFIN_MODEL_API_KEY", ""),
            temperature=float(os.getenv("AUTOFIN_MODEL_TEMPERATURE", "0.2")),
        )

    def public_view(self) -> JsonDict:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_configured": bool(self.api_key),
            "api_key_preview": self._redacted_key(),
            "temperature": self.temperature,
        }

    def with_updates(self, updates: JsonDict) -> "ModelAPIConfig":
        api_key = str(updates.get("api_key", "")).strip()
        values = {
            "provider": str(updates.get("provider", self.provider)).strip() or self.provider,
            "model": str(updates.get("model", self.model)).strip(),
            "base_url": str(updates.get("base_url", self.base_url)).strip(),
            "temperature": float(updates.get("temperature", self.temperature)),
        }
        if api_key:
            values["api_key"] = api_key
        return replace(self, **values)

    def _redacted_key(self) -> str:
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "****"
        return f"{self.api_key[:4]}...{self.api_key[-4:]}"


class ModelConfigStore:
    def __init__(self, initial: Optional[ModelAPIConfig] = None) -> None:
        self._config = initial or ModelAPIConfig.from_env()
        self._lock = Lock()

    def get(self) -> ModelAPIConfig:
        with self._lock:
            return self._config

    def update(self, updates: JsonDict) -> ModelAPIConfig:
        with self._lock:
            self._config = self._config.with_updates(updates)
            return self._config
