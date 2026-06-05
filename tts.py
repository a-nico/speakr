import re
import threading
import time
from xml.sax.saxutils import escape
from typing import List, Optional

import pyperclip
import keyboard as kb

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:  # pragma: no cover - dependency/runtime environment
    speechsdk = None

from audio_feedback import play_click
from config import Config
from notifications import show_error_notification


class TextToSpeechService:
    """Handles text-to-speech conversion using Azure Speech SDK."""

    def __init__(self, config: Config):
        self.config = config
        self.current_voice: str = config.tts_voice_default
        self.speed = config.tts_speed_default

        self._is_playing: bool = False
        self._play_lock = threading.Lock()
        self._current_synthesizer = None
        self._stop_event = threading.Event()
        self._streaming_active: bool = False

    @property
    def available_voices(self) -> List[str]:
        return Config.TTS_VOICES

    def set_voice(self, voice: str) -> None:
        if voice and voice.strip():
            self.current_voice = voice
            print(f"TTS voice set to: {voice}")
        else:
            print("Invalid TTS voice name.")

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

    def _create_speech_config(self):
        if speechsdk is None:
            show_error_notification(
                "TTS Error",
                "Azure Speech SDK is not installed. Run 'pip install -r requirements.txt' to install it.",
            )
            return None

        if not self.config.azure_tts_api_key or (not self.config.azure_tts_region and not self.config.azure_tts_endpoint):
            print("Azure TTS not configured.")
            show_error_notification(
                "TTS Error",
                "Azure TTS not configured. Please set azure.tts.api_key and either azure.tts.region or azure.tts.endpoint in config.yaml.",
            )
            return None

        try:
            if self.config.azure_tts_endpoint:
                speech_config = speechsdk.SpeechConfig(
                    subscription=self.config.azure_tts_api_key,
                    endpoint=self.config.azure_tts_endpoint,
                )
            else:
                speech_config = speechsdk.SpeechConfig(
                    subscription=self.config.azure_tts_api_key,
                    region=self.config.azure_tts_region,
                )
            speech_config.speech_synthesis_voice_name = self.current_voice
            return speech_config
        except Exception as exc:
            print(f"Failed to initialize Azure Speech config: {exc}")
            play_click("cancel")
            show_error_notification("TTS Error", f"Failed to initialize Azure Speech: {exc}")
            return None

    def _voice_locale(self) -> str:
        parts = self.current_voice.split("-")
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
        return "en-US"

    def _build_ssml(self, text: str) -> str:
        rate_delta = int(round((self.speed - 1.0) * 100))
        rate = f"{rate_delta:+d}%" if rate_delta else "0%"
        locale = self._voice_locale()
        escaped_text = escape(text)
        return (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{locale}'>"
            f"<voice name='{self.current_voice}'>"
            f"<prosody rate='{rate}'>{escaped_text}</prosody>"
            f"</voice>"
            f"</speak>"
        )

    def _speak_chunk_blocking(self, text: str) -> bool:
        speech_config = self._create_speech_config()
        if speech_config is None:
            return False

        try:
            audio_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
            with self._play_lock:
                self._current_synthesizer = synthesizer
                self._is_playing = True

            print(f"Speaking chunk with voice '{self.current_voice}' at speed {self.speed}...")
            result = synthesizer.speak_ssml_async(self._build_ssml(text)).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                return True

            if result.reason == speechsdk.ResultReason.Canceled:
                details = result.cancellation_details
                print(f"Speech synthesis canceled: {details.reason}")
                if details.reason == speechsdk.CancellationReason.Error:
                    error_details = details.error_details or "Unknown Azure Speech error"
                    print(f"Speech synthesis error details: {error_details}")
                    play_click("cancel")
                    show_error_notification("TTS Error", f"Failed to synthesize speech: {error_details}")
                return False

            print(f"Speech synthesis returned unexpected reason: {result.reason}")
            return False
        except Exception as exc:
            print(f"Speech synthesis failed: {exc}")
            play_click("cancel")
            show_error_notification("TTS Error", f"Failed to synthesize speech: {exc}")
            return False
        finally:
            with self._play_lock:
                self._current_synthesizer = None
                self._is_playing = False

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
            if self._current_synthesizer is not None and self._is_playing:
                try:
                    self._current_synthesizer.stop_speaking_async().get()
                    print("TTS playback stopped.")
                except Exception as exc:
                    print(f"Error stopping TTS playback: {exc}")
                finally:
                    self._current_synthesizer = None
                    self._is_playing = False
            else:
                print("No TTS audio is currently playing.")
        self._streaming_active = False

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
            for idx, chunk in enumerate(chunks):
                if self._stop_event.is_set():
                    break
                if not self._speak_chunk_blocking(chunk):
                    print(f"Skipping failed TTS chunk at index {idx}.")
                    if not self._stop_event.is_set():
                        break
        finally:
            self._streaming_active = False
            with self._play_lock:
                self._is_playing = False
                self._current_synthesizer = None

    def speak_text_streaming(self, text: str, max_chunk_len: int = 400) -> None:
        chunks = self.chunk_text(text, max_chunk_len)
        if not chunks:
            print("No text to speak.")
            return

        self.stop_playback()
        self._stop_event.clear()
        threading.Thread(target=self._stream_chunks, args=(chunks,), daemon=True).start()
