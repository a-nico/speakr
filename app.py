import threading
from typing import Callable

import pystray

from audio_feedback import load_sounds, play_click, show_error_notification
from config import Config
from hotkeys import create_hotkey_listener
from recorder import Recorder
from stt import copy_and_paste, transcribe_audio
from tray import create_icon, create_tray_menu
from tts import TextToSpeechService


def main() -> None:
    config = Config()
    load_sounds(config)

    recorder = Recorder()
    tts_service = TextToSpeechService(config)

    def transcribe_and_paste(wav_bytes) -> None:
        try:
            text = transcribe_audio(wav_bytes, config)
            if text:
                print("Transcribed:", text)
                copy_and_paste(text)
            else:
                print("Transcription returned no text.")
        except Exception as exc:
            print(f"Error during transcription or pasting: {exc}")
            show_error_notification("Transcription Error", f"Failed to transcribe audio: {exc}")

    listener = create_hotkey_listener(recorder, tts_service, transcribe_and_paste, play_click)
    listener.start()

    def on_exit(icon: pystray.Icon) -> None:
        listener.stop()
        icon.stop()

    def on_refresh_mics(icon: pystray.Icon) -> None:
        recorder.refresh_devices()
        icon.menu = create_tray_menu(recorder, icon, on_refresh_mics, on_exit, tts_service)
        icon.update_menu()
        print("Microphone menu refreshed.")

    icon = pystray.Icon("Speakr", create_icon(config), "Speakr")
    icon.menu = create_tray_menu(recorder, icon, on_refresh_mics, on_exit, tts_service)
    icon.run()


if __name__ == "__main__":
    main()
