from typing import Callable, List

import pystray
from PIL import Image

from config import Config
from stt import is_echo_mode, toggle_echo_mode
from tts import TextToSpeechService


def create_icon(config: Config) -> Image.Image:
    """Load tray icon from speaking.ico; fallback to default."""
    size = (64, 64)
    try:
        img = Image.open(config.icon_path)
        if img.size != size:
            img = img.resize(size, Image.Resampling.LANCZOS)
        return img
    except Exception as exc:  # pragma: no cover - UI only
        print(f"Icon load error: {exc} — using default.")
        return Image.new("RGB", size, (240, 255, 0))


def create_mic_menu(recorder, icon) -> List[pystray.MenuItem]:
    mic_items: List[pystray.MenuItem] = []
    for dev in recorder.wasapi_devices:
        device_index: int = dev["index"]

        def make_handler(d_id: int) -> Callable[[], None]:
            def handler() -> None:
                recorder.set_device(d_id)
                icon.update_menu()

            return handler

        def make_checker(d_id: int) -> Callable[[pystray.MenuItem], bool]:
            return lambda item, device=d_id: recorder.device_id == device

        item = pystray.MenuItem(dev["name"], make_handler(device_index), checked=make_checker(device_index), radio=True)
        mic_items.append(item)
    return mic_items


def create_voice_menu(tts_service: TextToSpeechService, icon) -> List[pystray.MenuItem]:
    voice_items: List[pystray.MenuItem] = []
    for voice in tts_service.available_voices:

        def make_handler(v: str) -> Callable[[], None]:
            def handler() -> None:
                tts_service.set_voice(v)
                icon.update_menu()

            return handler

        def make_checker(v: str) -> Callable[[pystray.MenuItem], bool]:
            return lambda item, voice_name=v: tts_service.current_voice == voice_name

        item = pystray.MenuItem(voice.capitalize(), make_handler(voice), checked=make_checker(voice), radio=True)
        voice_items.append(item)
    return voice_items


def create_speed_menu(tts_service: TextToSpeechService, icon) -> List[pystray.MenuItem]:
    speed_items: List[pystray.MenuItem] = []
    preset_speeds = [1.0, 1.15, 1.30, 1.45, 1.6]

    for speed in preset_speeds:
        label = f"{speed:.2f}x".rstrip("0").rstrip(".") + "x"

        def make_handler(s: float) -> Callable[[], None]:
            def handler() -> None:
                tts_service.speed = s
                print(f"TTS speed set to {s}")
                icon.update_menu()

            return handler

        def make_checker(s: float) -> Callable[[pystray.MenuItem], bool]:
            return lambda item, value=s: abs(tts_service.speed - value) < 1e-6

        item = pystray.MenuItem(label, make_handler(speed), checked=make_checker(speed), radio=True)
        speed_items.append(item)

    return speed_items


def create_tray_menu(
    recorder,
    icon: pystray.Icon,
    on_refresh_mics: Callable[[pystray.Icon], None],
    on_exit: Callable[[pystray.Icon], None],
    tts_service: TextToSpeechService,
) -> pystray.Menu:
    return pystray.Menu(
        pystray.MenuItem("Microphones", pystray.Menu(lambda: create_mic_menu(recorder, icon))),
        pystray.MenuItem("TTS Voice", pystray.Menu(lambda: create_voice_menu(tts_service, icon))),
        pystray.MenuItem("TTS Speed", pystray.Menu(lambda: create_speed_menu(tts_service, icon))),
        pystray.MenuItem("Refresh mics", on_refresh_mics),
        pystray.MenuItem("Echo mode", lambda icon, item: toggle_echo_mode(), checked=lambda item: is_echo_mode()),
        pystray.MenuItem("Exit", on_exit),
    )
