import io
import wave
from typing import Tuple

import requests
import simpleaudio as sa

from audio_feedback import show_error_notification
from config import Config

ECHO_MODE = False


def set_echo_mode(enabled: bool) -> None:
    global ECHO_MODE
    ECHO_MODE = enabled
    print(f"Echo mode {'enabled' if ECHO_MODE else 'disabled'}.")


def toggle_echo_mode() -> None:
    set_echo_mode(not ECHO_MODE)


def is_echo_mode() -> bool:
    return ECHO_MODE


def transcribe_audio(wav_bytes: io.BytesIO, config: Config) -> str:
    """Send audio data to Azure Speech-to-Text service and return transcribed text.
       When echo mode is enabled, play back the audio instead of sending it."""
    try:
        if ECHO_MODE:
            print("ECHO MODE: Playing back recorded audio instead of sending to API.")
            wav_bytes.seek(0)
            try:
                with wave.open(wav_bytes, "rb") as wf:
                    wave_obj = sa.WaveObject(
                        wf.readframes(wf.getnframes()), wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
                    )
                play_obj = wave_obj.play()
                play_obj.wait_done()
            except Exception as exc:  # pragma: no cover - playback only
                print(f"Error during playback: {exc}")
            return "[Echo mode: Audio played back locally]"

        if not config.azure_stt_api_key or not config.azure_stt_endpoint:
            print("Azure STT not configured.")
            show_error_notification(
                "STT Error", "Azure STT not configured. Please set AZURE_STT_ENDPOINT and AZURE_STT_API_KEY."
            )
            return ""

        headers = {"api-key": config.azure_stt_api_key}
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        response = requests.post(config.azure_stt_endpoint, headers=headers, files=files)
        response.raise_for_status()
        return response.json().get("text", "")
    except Exception as exc:
        print(f"Transcription/playback failed: {exc}")
        return ""


def copy_and_paste(text: str) -> bool:
    """Copy the given text to clipboard and simulate Ctrl+V to paste it. Returns True on success."""
    import keyboard as kb
    import pyperclip

    try:
        pyperclip.copy(text)
        kb.press_and_release("ctrl+v")
        return True
    except Exception as exc:
        print(f"Error copying/pasting text: {exc}")
        show_error_notification(
            "Paste Error", f"Failed to paste text: {exc}\n\nThe text has been copied to your clipboard."
        )
        return False
