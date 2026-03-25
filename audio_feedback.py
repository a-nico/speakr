import os
import threading
from typing import Dict

import simpleaudio as sa

from config import Config

# Cache for preloaded WaveObjects
SOUND_WAVES: Dict[str, sa.WaveObject] = {}


def load_sounds(config: Config) -> None:
    """Preload sound files into memory for feedback sounds."""
    for kind, filename in config.sound_files.items():
        path = config.get_path(filename)
        if not os.path.exists(path):
            print(f"Sound file not found at startup: {path}")
            continue
        try:
            SOUND_WAVES[kind] = sa.WaveObject.from_wave_file(path)
            print(f"Preloaded sound '{kind}': {path}")
        except Exception as exc:  # pragma: no cover - feedback only
            print(f"Error preloading sound '{kind}' from {path}: {exc}")


def play_click(kind: str = "start") -> None:
    wave_obj = SOUND_WAVES.get(kind) or SOUND_WAVES.get("start")
    if not wave_obj:
        print(f"No preloaded sound available for '{kind}'.")
        return

    def _play() -> None:
        try:
            wave_obj.play()
        except Exception as exc:  # pragma: no cover - feedback only
            print(f"Error playing preloaded sound '{kind}': {exc}")

    threading.Thread(target=_play, daemon=True).start()
