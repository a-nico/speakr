import io
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import sounddevice as sd

from audio_feedback import show_error_notification

RECORD_SECONDS = 60  # Max recording duration in seconds
SAMPLE_RATE = 16000  # Default audio sample rate, will be adjusted if unsupported


class Recorder:
    """Handles audio recording from the selected microphone device."""

    def __init__(self) -> None:
        self.recording: bool = False
        self.audio: List[np.ndarray] = []
        self.lock: threading.Lock = threading.Lock()
        self.device_id: Optional[int] = None
        self.wasapi_devices: List[Dict[str, Any]] = []
        self.sample_rate: int = SAMPLE_RATE
        self.error_occurred: bool = False
        self.on_error_callback: Optional[Callable[[], None]] = None
        self._initialize_device()

    def _initialize_device(self) -> None:
        """Find and select an appropriate audio input device."""
        self._find_wasapi_devices()
        if self.wasapi_devices:
            self._select_preferred_device()
        else:
            print("No devices found using Windows WASAPI API. Falling back to default device.")
            self._fallback_to_default_device()

        if self.device_id is not None:
            self._set_supported_sample_rate()

    def _find_wasapi_devices(self) -> None:
        """Find all available WASAPI input devices."""
        devices = sd.query_devices()
        input_devices = [d for d in devices if d["max_input_channels"] > 0]

        if not input_devices:
            print("No input devices (microphones) found.")
            return

        print("Available input devices (microphones) using recommended Windows WASAPI API:")
        for idx, dev in enumerate(input_devices):
            try:
                host_api = sd.query_hostapis(dev["hostapi"])
                if host_api["name"] == "Windows WASAPI":
                    self.wasapi_devices.append(dev)
                    print(f"  {idx}: {dev['name']}")
            except sd.PortAudioError:
                continue

    def _select_preferred_device(self) -> None:
        """Select the best available WASAPI device."""
        samson_device = next((d for d in self.wasapi_devices if "samson" in d["name"].lower()), None)
        if samson_device:
            self.device_id = samson_device["index"]
            print(f"Using Samson input device: {samson_device['name']} (ID: {self.device_id})")
            return

        usb_sound_card = next((d for d in self.wasapi_devices if "usb sound card" in d["name"].lower()), None)
        if usb_sound_card:
            self.device_id = usb_sound_card["index"]
            print(f"Using USB Sound Card input device: {usb_sound_card['name']} (ID: {self.device_id})")
            return

        self.device_id = self.wasapi_devices[0]["index"]
        print(f"Using first WASAPI device: {self.wasapi_devices[0]['name']} (ID: {self.device_id})")

    def _fallback_to_default_device(self) -> None:
        """Fall back to the system's default input device."""
        try:
            device_index = sd.default.device[0]
            if device_index != -1:
                self.device_id = device_index
                device_info = sd.query_devices(device_index)
                print(f"Using default input device: {device_info['name']} (ID: {self.device_id})")
            else:
                print("No default input device found.")
        except Exception as exc:
            print(f"Could not determine default device: {exc}")

    def set_device(self, device_id: int) -> None:
        """Update the current recording device and adjust sample rate."""
        device_info = next((d for d in self.wasapi_devices if d["index"] == device_id), None)
        if device_info:
            self.device_id = device_id
            print(f"Selected device: {device_info['name']} (ID: {device_id})")
            self._set_supported_sample_rate()
        else:
            print(f"Device ID {device_id} not found in WASAPI devices.")

    def _set_supported_sample_rate(self) -> None:
        """Set a sample rate supported by the current device."""
        if self.device_id is None:
            print("No device selected, cannot set sample rate.")
            return

        device_info = sd.query_devices(self.device_id)
        common_rates = [44100, 48000, 16000, 8000]
        for rate in common_rates:
            try:
                sd.check_input_settings(device=self.device_id, samplerate=rate, channels=1, dtype="int16")
                self.sample_rate = rate
                print(f"Set sample rate to {rate} Hz for device ID {self.device_id}")
                return
            except sd.PortAudioError:
                continue

        default_rate = device_info.get("default_samplerate", SAMPLE_RATE)
        try:
            sd.check_input_settings(device=self.device_id, samplerate=int(default_rate), channels=1, dtype="int16")
            self.sample_rate = int(default_rate)
            print(f"Set sample rate to default {default_rate} Hz for device ID {self.device_id}")
        except (sd.PortAudioError, ValueError):
            self.sample_rate = SAMPLE_RATE
            print(f"No supported sample rate found. Falling back to default {SAMPLE_RATE} Hz, may not work.")

    def start(self) -> bool:
        """Start recording audio in a separate thread. Returns True if started successfully."""
        if self.device_id is None:
            print("Cannot start recording: No input device is selected.")
            show_error_notification(
                "Recording Error", "No microphone selected. Please select a microphone from the tray menu."
            )
            return False

        self.recording = True
        self.audio = []
        self.error_occurred = False
        threading.Thread(target=self._record, daemon=True).start()
        return True

    def stop(self) -> None:
        """Stop the current recording."""
        self.recording = False

    def cancel(self) -> None:
        """Stop recording and discard any captured audio."""
        self.stop()
        with self.lock:
            self.audio = []
        self.error_occurred = False

    def refresh_devices(self) -> None:
        """Refresh the list of available audio devices and reselect if needed."""
        print("Refreshing audio devices...")
        sd._terminate()
        sd._initialize()

        previous_device_id = self.device_id
        self.wasapi_devices = []
        self.device_id = None

        self._find_wasapi_devices()
        if self.wasapi_devices:
            if previous_device_id is not None:
                device_still_exists = any(d["index"] == previous_device_id for d in self.wasapi_devices)
                if device_still_exists:
                    self.device_id = previous_device_id
                    print(f"Restored previous device ID: {previous_device_id}")
                else:
                    print(f"Previous device (ID: {previous_device_id}) no longer available.")
                    self._select_preferred_device()
            else:
                self._select_preferred_device()
        else:
            print("No devices found after refresh. Falling back to default device.")
            self._fallback_to_default_device()

        if self.device_id is not None:
            self._set_supported_sample_rate()

    def _record(self) -> None:
        """Internal method to handle the recording loop."""

        def callback(indata, frames, time_info, status):
            if status:
                print(f"Recording status: {status}")
            if self.recording:
                with self.lock:
                    self.audio.append(np.array(indata, dtype="int16"))

        try:
            with sd.InputStream(
                samplerate=self.sample_rate, channels=1, dtype="int16", callback=callback, device=self.device_id
            ):
                start_time = time.time()
                while self.recording and (time.time() - start_time < RECORD_SECONDS):
                    time.sleep(0.1)
        except sd.PortAudioError as exc:
            error_msg = f"Audio device error: {exc}\nThe microphone may have been disconnected."
            print(f"Error recording audio: {exc}")
            print("This may indicate that the microphone was disconnected.")
            self.recording = False
            self.error_occurred = True
            show_error_notification("Microphone Error", error_msg)
            if self.on_error_callback:
                self.on_error_callback()
        except Exception as exc:
            error_msg = f"Recording failed: {exc}"
            print(f"Unexpected error during recording: {exc}")
            print(traceback.format_exc())
            self.recording = False
            self.error_occurred = True
            show_error_notification("Recording Error", error_msg)
            if self.on_error_callback:
                self.on_error_callback()

    def get_wav_bytes(self) -> Optional[io.BytesIO]:
        """Return the recorded audio as WAV bytes in a BytesIO buffer."""
        import soundfile as sf

        try:
            with self.lock:
                if not self.audio:
                    return None
                audio_np = np.concatenate(self.audio, axis=0)
            buf = io.BytesIO()
            sf.write(buf, audio_np, self.sample_rate, format="WAV", subtype="PCM_16")
            buf.seek(0)
            return buf
        except Exception as exc:
            print(f"Error creating WAV bytes: {exc}")
            show_error_notification("Audio Processing Error", f"Failed to process recorded audio: {exc}")
            return None
