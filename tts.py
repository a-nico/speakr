import io
import os
import re
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
        self._stop_event = threading.Event()
        self._streaming_active: bool = False

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

    @staticmethod
    def chunk_text(text: str, max_len: int = 400) -> List[str]:
        if not text:
            return []

        normalized = text.replace("\r\n", "\n")
        paragraphs = [p.strip() for p in normalized.split("\n") if p.strip()]

        sentences: List[str] = []
        for paragraph in paragraphs:
            parts = re.split(r"(?<=[.!?])\s+", paragraph)
            for part in parts:
                cleaned = part.strip()
                if cleaned:
                    sentences.append(cleaned)

        if not sentences:
            sentences = paragraphs

        chunks: List[str] = []
        current = ""

        for sentence in sentences:
            if len(sentence) > max_len:
                if current:
                    chunks.append(current.strip())
                    current = ""
                for i in range(0, len(sentence), max_len):
                    sliced = sentence[i : i + max_len].strip()
                    if sliced:
                        chunks.append(sliced)
                continue

            if len(current) + len(sentence) + (1 if current else 0) <= max_len:
                current = f"{current} {sentence}".strip()
            else:
                if current:
                    chunks.append(current.strip())
                current = sentence

        if current:
            chunks.append(current.strip())

        return chunks

    def stop_playback(self) -> None:
        self._stop_event.set()
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
        self._streaming_active = False

    def _play_audio_blocking(self, audio_data: bytes) -> None:
        with self._play_lock:
            self._is_playing = True

        try:
            if self._stop_event.is_set():
                return

            audio_io = io.BytesIO(audio_data)
            try:
                import wave

                with wave.open(audio_io, "rb") as wf:
                    wave_obj = sa.WaveObject(
                        wf.readframes(wf.getnframes()), wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
                    )
            except Exception:
                import soundfile as sf

                audio_io.seek(0)
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

    def play_audio(self, audio_data: bytes) -> None:
        with self._play_lock:
            if self._is_playing:
                print("Audio is already playing, skipping...")
                return
            self._stop_event.clear()

        threading.Thread(target=self._play_audio_blocking, args=(audio_data,), daemon=True).start()

    def speak_clipboard(self, copy_selection: bool = True) -> None:
        text = self.get_clipboard_text(copy_selection=copy_selection)
        if not text:
            print("No text in clipboard to speak.")
            show_error_notification("TTS Error", "No text found in clipboard. Please select or copy some text first.")
            return

        print(f"Speaking clipboard text: {text[:50]}..." if len(text) > 50 else f"Speaking: {text}")
        self.speak_text_streaming(text)

    def _stream_chunks(self, chunks: List[str]) -> None:
        if not chunks:
            print("No text chunks to stream.")
            return

        self._streaming_active = True
        try:
            max_workers = min(2, len(chunks))
            executor = ThreadPoolExecutor(max_workers=max_workers)
            try:
                pending = {executor.submit(self.synthesize_speech, chunk): idx for idx, chunk in enumerate(chunks)}
                buffer = {}
                next_index = 0

                while pending and not self._stop_event.is_set():
                    done, _ = wait(list(pending.keys()), return_when=FIRST_COMPLETED)
                    for future in done:
                        idx = pending.pop(future)
                        try:
                            audio = future.result()
                        except Exception as exc:  # pragma: no cover - defensive
                            print(f"TTS chunk {idx} failed: {exc}")
                            audio = None
                        buffer[idx] = audio

                        while next_index in buffer and not self._stop_event.is_set():
                            audio_data = buffer.pop(next_index)
                            if audio_data:
                                self._play_audio_blocking(audio_data)
                            else:
                                print(f"Skipping empty audio chunk at index {next_index}.")
                            next_index += 1

                if not self._stop_event.is_set():
                    while next_index in buffer:
                        audio_data = buffer.pop(next_index)
                        if audio_data:
                            self._play_audio_blocking(audio_data)
                        else:
                            print(f"Skipping empty audio chunk at index {next_index}.")
                        next_index += 1
                else:
                    for future in pending:
                        future.cancel()
            finally:
                executor.shutdown(wait=not self._stop_event.is_set(), cancel_futures=True)
        finally:
            self._streaming_active = False
            with self._play_lock:
                self._is_playing = False
                self._current_play_obj = None

    def speak_text_streaming(self, text: str, max_chunk_len: int = 400) -> None:
        chunks = self.chunk_text(text, max_chunk_len)
        if not chunks:
            print("No text to speak.")
            return

        self.stop_playback()
        self._stop_event.clear()
        threading.Thread(target=self._stream_chunks, args=(chunks,), daemon=True).start()
