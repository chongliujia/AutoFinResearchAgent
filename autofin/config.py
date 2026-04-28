from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
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

    @classmethod
    def from_files(
        cls,
        config_path: str | Path = ".autofin/config.json",
        secrets_path: str | Path = ".autofin/secrets.json",
    ) -> "ModelAPIConfig":
        base = cls.from_env()
        config_data = cls._read_json(config_path)
        secrets_data = cls._read_json(secrets_path)
        merged = {
            "provider": config_data.get("provider", base.provider),
            "model": config_data.get("model", base.model),
            "base_url": config_data.get("base_url", base.base_url),
            "temperature": config_data.get("temperature", base.temperature),
            "api_key": secrets_data.get("api_key", base.api_key),
        }
        return cls(
            provider=str(merged["provider"]),
            model=str(merged["model"]),
            base_url=str(merged["base_url"]),
            api_key=str(merged["api_key"]),
            temperature=float(merged["temperature"]),
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

    def config_file_view(self) -> JsonDict:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
        }

    def secrets_file_view(self) -> JsonDict:
        return {"api_key": self.api_key} if self.api_key else {}

    def _redacted_key(self) -> str:
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "****"
        return f"{self.api_key[:4]}...{self.api_key[-4:]}"

    @staticmethod
    def _read_json(path: str | Path) -> JsonDict:
        file_path = Path(path)
        if not file_path.exists():
            return {}
        with file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)


class ModelConfigStore:
    def __init__(
        self,
        initial: Optional[ModelAPIConfig] = None,
        config_path: str | Path = ".autofin/config.json",
        secrets_path: str | Path = ".autofin/secrets.json",
        persist: bool = True,
    ) -> None:
        self.config_path = Path(config_path)
        self.secrets_path = Path(secrets_path)
        self.persist = persist
        self._config = initial or ModelAPIConfig.from_files(self.config_path, self.secrets_path)
        self._lock = Lock()

    def get(self) -> ModelAPIConfig:
        with self._lock:
            return self._config

    def update(self, updates: JsonDict) -> ModelAPIConfig:
        with self._lock:
            self._config = self._config.with_updates(updates)
            if self.persist:
                self._write()
            return self._config

    def _write(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(self.config_path, self._config.config_file_view())
        if self._config.api_key:
            self._write_json(self.secrets_path, self._config.secrets_file_view())

    def _write_json(self, path: Path, payload: JsonDict) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
