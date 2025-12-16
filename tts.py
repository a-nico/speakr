import io
import os
import threading
import time
import traceback
from typing import List, Optional

import numpy as np
import pyperclip
import requests
import simpleaudio as sa
from pynput import keyboard
import keyboard as kb

from audio_feedback import play_click, show_error_notification
from config import Config


class TextToSpeechService:
    """Handles text-to-speech conversion using Azure OpenAI TTS API."""

    def __init__(self, config: Config):
        self.config = config
        env_voice = (os.getenv("AZURE_TTS_VOICE_DEFAULT", "alloy") or "").lower()
        if env_voice in Config.TTS_VOICES:
            self.current_voice: str = env_voice
        else:
            print(f"Invalid AZURE_TTS_VOICE_DEFAULT '{env_voice}'; falling back to 'alloy'")
            self.current_voice = "alloy"

        try:
            env_speed = os.getenv("AZURE_TTS_SPEED_DEFAULT")
            if env_speed is not None:
                value = float(env_speed)
                self.speed = max(0.25, min(4.0, value))
            else:
                self.speed = 1.0
        except ValueError:
            print("Invalid AZURE_TTS_SPEED_DEFAULT value; falling back to 1.0")
            self.speed = 1.0

        self._is_playing: bool = False
        self._play_lock = threading.Lock()
        self._current_play_obj: Optional[sa.PlayObject] = None

    @property
    def available_voices(self) -> List[str]:
        return Config.TTS_VOICES

    def set_voice(self, voice: str) -> None:
        if voice in self.available_voices:
            self.current_voice = voice
            print(f"TTS voice set to: {voice}")
        else:
            print(f"Invalid voice '{voice}'. Available voices: {self.available_voices}")

    def get_clipboard_text(self, copy_selection: bool = False) -> Optional[str]:
        try:
            if copy_selection:
                original_clipboard = pyperclip.paste()
                kb.press_and_release("ctrl+c")
                time.sleep(0.15)
                text = pyperclip.paste()
                if text == original_clipboard:
                    print("No text was selected, using existing clipboard content.")
            else:
                text = pyperclip.paste()

            if text and text.strip():
                return text.strip()
            return None
        except Exception as exc:
            print(f"Error reading clipboard: {exc}")
            return None

    def synthesize_speech(self, text: str) -> Optional[bytes]:
        if not self.config.azure_tts_api_key or not self.config.azure_tts_endpoint:
            print("Azure TTS not configured.")
            show_error_notification("TTS Error", "Azure TTS not configured. Please set AZURE_TTS_ENDPOINT and AZURE_TTS_API_KEY.")
            return None

        try:
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.config.azure_tts_api_key}"}
            payload = {"model": "tts-hd", "input": text, "voice": self.current_voice, "speed": self.speed}
            print(f"Sending TTS request with voice '{self.current_voice}' at speed {self.speed}...")
            response = requests.post(self.config.azure_tts_endpoint, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            print(f"TTS response received: {len(response.content)} bytes")
            return response.content
        except requests.exceptions.Timeout:
            print("TTS request timed out after 30 seconds.")
            play_click("cancel")
            show_error_notification("TTS Error", "Request timed out after 30 seconds. Please try again.")
            return None
        except requests.exceptions.RequestException as exc:
            print(f"TTS request failed: {exc}")
            play_click("cancel")
            show_error_notification("TTS Error", f"Failed to synthesize speech: {exc}")
            return None

    def stop_playback(self) -> None:
        with self._play_lock:
            if self._current_play_obj is not None and self._is_playing:
                try:
                    self._current_play_obj.stop()
                    print("TTS playback stopped.")
                except Exception as exc:
                    print(f"Error stopping TTS playback: {exc}")
                finally:
                    self._current_play_obj = None
                    self._is_playing = False
            else:
                print("No TTS audio is currently playing.")

    def play_audio(self, audio_data: bytes) -> None:
        with self._play_lock:
            if self._is_playing:
                print("Audio is already playing, skipping...")
                return
            self._is_playing = True

        def _play() -> None:
            try:
                try:
                    audio_io = io.BytesIO(audio_data)
                    import wave

                    with wave.open(audio_io, "rb") as wf:
                        wave_obj = sa.WaveObject(
                            wf.readframes(wf.getnframes()), wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
                        )
                    play_obj = wave_obj.play()
                    with self._play_lock:
                        self._current_play_obj = play_obj
                    play_obj.wait_done()
                except Exception:
                    import soundfile as sf

                    audio_io = io.BytesIO(audio_data)
                    data, samplerate = sf.read(audio_io)
                    if data.dtype != np.int16:
                        if data.max() <= 1.0 and data.min() >= -1.0:
                            data = (data * 32767).astype(np.int16)
                        else:
                            data = data.astype(np.int16)

                    num_channels = 1 if len(data.shape) == 1 else data.shape[1]
                    wave_obj = sa.WaveObject(data.tobytes(), num_channels, 2, samplerate)
                    play_obj = wave_obj.play()
                    with self._play_lock:
                        self._current_play_obj = play_obj
                    play_obj.wait_done()
            except Exception as exc:
                print(f"Error playing TTS audio: {exc}")
                print(traceback.format_exc())
                show_error_notification("TTS Playback Error", f"Failed to play audio: {exc}")
            finally:
                with self._play_lock:
                    self._is_playing = False
                    self._current_play_obj = None

        threading.Thread(target=_play, daemon=True).start()

    def speak_clipboard(self, copy_selection: bool = True) -> None:
        text = self.get_clipboard_text(copy_selection=copy_selection)
        if not text:
            print("No text in clipboard to speak.")
            show_error_notification("TTS Error", "No text found in clipboard. Please select or copy some text first.")
            return

        print(f"Speaking clipboard text: {text[:50]}..." if len(text) > 50 else f"Speaking: {text}")
        audio_data = self.synthesize_speech(text)
        if audio_data:
            self.play_audio(audio_data)
