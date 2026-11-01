"""Base configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BaseConfig:
    base_url: str
    timeout_seconds: int = 30

    @classmethod
    def _env(cls, key: str, default: str = "") -> str:
        return os.getenv(key, default).strip()
