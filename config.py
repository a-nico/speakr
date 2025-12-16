import os
import sys
from dotenv import load_dotenv


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
        self._load_dotenv()

        # Speech-to-Text (STT) configuration
        self.azure_stt_endpoint = os.getenv("AZURE_STT_ENDPOINT")
        self.azure_stt_api_key = os.getenv("AZURE_STT_API_KEY")

        # Text-to-Speech (TTS) configuration
        self.azure_tts_endpoint = os.getenv("AZURE_TTS_ENDPOINT")
        self.azure_tts_api_key = os.getenv("AZURE_TTS_API_KEY")

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

    def _load_dotenv(self) -> None:
        """Load environment variables from a .env file located next to the executable or script."""
        env_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(
            os.path.abspath(__file__)
        )
        env_path = os.path.join(env_dir, ".env")
        print(f"Looking for .env file at: {env_path}")
        if os.path.exists(env_path):
            load_dotenv(env_path)
            print(".env file loaded successfully")
        else:
            print(f".env file not found at: {env_path}")

    def get_path(self, filename: str) -> str:
        """Get the absolute path for a given asset file."""
        return os.path.join(self.base_path, filename)

    def _print_config_status(self) -> None:
        """Print the status of the Azure configuration."""
        if not self.azure_stt_endpoint or not self.azure_stt_api_key:
            print("Azure STT configuration incomplete. Check AZURE_STT_ENDPOINT / AZURE_STT_API_KEY.")
        else:
            print("Azure STT configuration loaded successfully")

        if not self.azure_tts_endpoint or not self.azure_tts_api_key:
            print("Azure TTS configuration incomplete. Check AZURE_TTS_ENDPOINT / AZURE_TTS_API_KEY.")
        else:
            print("Azure TTS configuration loaded successfully")
