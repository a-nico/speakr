import os
import sys
from typing import Any, Dict, Optional

import yaml


__version__ = "1.3.0"


class Config:
    """Manages application configuration, paths, and credentials."""

    TTS_VOICES = [
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "nova",
        "onyx",
        "sage",
        "shimmer",
    ]

    def __init__(self) -> None:
        self.base_path = self._get_base_path()
        self.yaml_config = self._load_yaml_config()

        # Speech-to-Text (STT) configuration
        self.azure_stt_endpoint = self._read_str("azure", "stt", "endpoint")
        self.azure_stt_api_key = self._read_str("azure", "stt", "api_key")

        # Text-to-Speech (TTS) configuration
        self.azure_tts_endpoint = self._read_str("azure", "tts", "endpoint")
        self.azure_tts_api_key = self._read_str("azure", "tts", "api_key")

        tts_voice_default = (self._read_str("azure", "tts", "voice_default", default="alloy") or "alloy").lower()
        if tts_voice_default in self.TTS_VOICES:
            self.tts_voice_default = tts_voice_default
        else:
            print(f"Invalid config.yaml value azure.tts.voice_default='{tts_voice_default}'; falling back to 'alloy'.")
            self.tts_voice_default = "alloy"

        self.tts_speed_default = self._read_float("azure", "tts", "speed_default", default=1.0, minimum=0.25, maximum=4.0)

        # Proofread (LLM) configuration
        self.azure_proofread_endpoint = self._read_str("azure", "proofread", "endpoint")
        self.azure_proofread_api_key = self._read_str("azure", "proofread", "api_key")
        self.azure_proofread_model = self._read_str("azure", "proofread", "model", default="gpt-5.2-chat")
        self.azure_proofread_api_version = self._read_str("azure", "proofread", "api_version", default="2025-04-01-preview")
        self.azure_proofread_system_prompt = self._read_str(
            "azure",
            "proofread",
            "system_prompt",
            default=(
                "You are a careful proofreading assistant. Correct grammar, spelling, punctuation, "
                "and clarity while preserving tone. Return only corrected text."
            ),
        )
        self.azure_proofread_max_completion_tokens = self._read_int(
            "azure", "proofread", "max_completion_tokens", default=2048, minimum=1
        )

        self.sound_files = {
            "start": "start.wav",
            "stop": "stop.wav",
            "cancel": "cancel.wav",
            "send": "send.wav",
        }

        self.icon_path = self.get_path("speaking.ico")
        self._print_config_status()

    def _get_base_path(self) -> str:
        """Determine the base path for the application, handling PyInstaller."""
        if getattr(sys, "frozen", False):
            return sys._MEIPASS  # type: ignore[attr-defined]
        return os.path.dirname(os.path.abspath(__file__))

    def _load_yaml_config(self) -> Dict[str, Any]:
        """Load config.yaml located next to the executable or script."""
        config_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(
            os.path.abspath(__file__)
        )
        config_path = os.path.join(config_dir, "config.yaml")
        print(f"Looking for config file at: {config_path}")
        if not os.path.exists(config_path):
            print(f"config.yaml not found at: {config_path}")
            return {}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                print("config.yaml loaded successfully")
                return data
            print("config.yaml is invalid (root must be a mapping).")
            return {}
        except Exception as exc:
            print(f"Failed to read config.yaml: {exc}")
            return {}

    def _read_str(self, *path: str, default: Optional[str] = None) -> Optional[str]:
        value = self._read_value(*path)
        if value is None:
            return default
        if isinstance(value, str):
            text = value.strip()
            return text or default
        return str(value)

    def _read_float(
        self,
        *path: str,
        default: float,
        minimum: Optional[float] = None,
        maximum: Optional[float] = None,
    ) -> float:
        value = self._read_value(*path)
        if value is None:
            return default
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            print(f"Invalid config.yaml value for {'.'.join(path)}; falling back to {default}.")
            return default

        if minimum is not None:
            numeric = max(minimum, numeric)
        if maximum is not None:
            numeric = min(maximum, numeric)
        return numeric

    def _read_int(
        self,
        *path: str,
        default: int,
        minimum: Optional[int] = None,
        maximum: Optional[int] = None,
    ) -> int:
        value = self._read_value(*path)
        if value is None:
            return default
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            print(f"Invalid config.yaml value for {'.'.join(path)}; falling back to {default}.")
            return default

        if minimum is not None:
            numeric = max(minimum, numeric)
        if maximum is not None:
            numeric = min(maximum, numeric)
        return numeric

    def _read_value(self, *path: str) -> Any:
        current: Any = self.yaml_config
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def get_path(self, filename: str) -> str:
        """Get the absolute path for a given asset file."""
        return os.path.join(self.base_path, filename)

    def _print_config_status(self) -> None:
        """Print the status of the Azure configuration."""
        if not self.azure_stt_endpoint or not self.azure_stt_api_key:
            print("Azure STT configuration incomplete. Check config.yaml at azure.stt.endpoint / azure.stt.api_key.")
        else:
            print("Azure STT configuration loaded successfully")

        if not self.azure_tts_endpoint or not self.azure_tts_api_key:
            print("Azure TTS configuration incomplete. Check config.yaml at azure.tts.endpoint / azure.tts.api_key.")
        else:
            print("Azure TTS configuration loaded successfully")

        if not self.azure_proofread_endpoint or not self.azure_proofread_api_key:
            print(
                "Azure proofread configuration incomplete. "
                "Check config.yaml at azure.proofread.endpoint / azure.proofread.api_key."
            )
        else:
            print("Azure proofread configuration loaded successfully")
