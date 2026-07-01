import ctypes
import io
import re
import threading
import time
import traceback
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

import numpy as np
import sounddevice as sd

from notifications import show_error_notification

RECORD_SECONDS = 60  # Max recording duration in seconds
SAMPLE_RATE = 16000  # Default audio sample rate, will be adjusted if unsupported
COINIT_APARTMENTTHREADED = 0x2
COINIT_MULTITHREADED = 0x0
RPC_E_CHANGED_MODE = 0x80010106


class Recorder:
    """Handles audio recording from the selected microphone device."""

    PREFERRED_HOSTAPIS: Tuple[str, ...] = (
        "Windows WASAPI",
        "Windows DirectSound",
        "MME",
        "Windows WDM-KS",
    )
    PREFERRED_DEVICE_NAME_HINTS: Tuple[str, ...] = ("samson", "usb sound card")
    GENERIC_INPUT_ALIASES: Set[str] = {
        "microsoft sound mapper input",
        "primary sound capture driver",
    }
    GROUPING_NOISE_WORDS: Set[str] = {
        "array",
        "audio",
        "capture",
        "device",
        "digital",
        "driver",
        "endpoints",
        "front",
        "input",
        "ks",
        "microphone",
        "mme",
        "rear",
        "sound",
        "static",
        "wave",
        "wdm",
        "windows",
    }

    def __init__(self) -> None:
        self.recording: bool = False
        self.audio: List[np.ndarray] = []
        self.lock: threading.Lock = threading.Lock()
        self.device_id: Optional[int] = None
        self.raw_input_devices: List[Dict[str, Any]] = []
        self.available_input_devices: List[Dict[str, Any]] = []
        self.sample_rate: int = SAMPLE_RATE
        self.error_occurred: bool = False
        self.on_error_callback: Optional[Callable[[], None]] = None
        self.selected_device_key: Optional[str] = None
        self._initialize_device()

    def _initialize_device(self) -> None:
        """Find and select an appropriate audio input device."""
        self.refresh_devices(reinitialize_audio=False)

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()

    def _is_generic_input_alias(self, device_name: str) -> bool:
        return self._normalize_text(device_name) in self.GENERIC_INPUT_ALIASES

    def _friendly_device_label(self, device_name: str) -> str:
        match = re.match(r"^(microphone array|microphone|headset microphone|input)\s*\((.+)\)$", device_name, re.IGNORECASE)
        label = match.group(2) if match else device_name
        label = re.sub(r"^\d+\s*-\s*", "", label).strip()
        return re.sub(r"\s+", " ", label)

    def _is_probable_microphone(self, device_name: str) -> bool:
        tokens = set(self._normalize_text(device_name).split())
        if not tokens:
            return False

        if tokens & {"array", "mic", "microphone"}:
            return True

        return "headset" in tokens and not (tokens & {"display", "output", "speaker"})

    def _device_group_kind(self, device_name: str) -> str:
        return "microphone" if self._is_probable_microphone(device_name) else "input"

    def _device_group_tokens(self, device_name: str) -> Set[str]:
        friendly_name = self._friendly_device_label(device_name)
        normalized = self._normalize_text(friendly_name)
        tokens = {token for token in normalized.split() if token not in self.GROUPING_NOISE_WORDS and not token.isdigit()}
        return tokens or set(normalized.split())

    def _device_matches_group(self, device_info: Dict[str, Any], group: Dict[str, Any]) -> bool:
        if self._device_group_kind(device_info["name"]) != group["kind"]:
            return False

        normalized_label = self._normalize_text(self._friendly_device_label(device_info["name"]))
        if normalized_label in group["signatures"]:
            return True

        tokens = self._device_group_tokens(device_info["name"])
        shared_tokens = tokens & group["tokens"]
        if not shared_tokens:
            return False

        if tokens == group["tokens"]:
            return True

        if tokens <= group["tokens"] or group["tokens"] <= tokens:
            return any(len(token) >= 3 for token in shared_tokens)

        union_size = len(tokens | group["tokens"])
        return union_size > 0 and (len(shared_tokens) / union_size) >= 0.6

    def _sort_raw_input_devices(
        self,
        devices: Iterable[Dict[str, Any]],
        prioritize_device_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        default_input_id = self._get_default_input_device_id()
        return sorted(
            devices,
            key=lambda device: (
                0 if prioritize_device_id is not None and device["index"] == prioritize_device_id else 1,
                0 if device["index"] == default_input_id else 1,
                self._device_hint_rank(device["name"]),
                self._device_host_rank(device.get("hostapi_name", "Unknown")),
                self._friendly_device_label(device["name"]).lower(),
                device["index"],
            ),
        )

    def _logical_device_key(self, group: Dict[str, Any]) -> str:
        token_key = " ".join(sorted(group["tokens"]))
        if token_key:
            return f"{group['kind']}|{token_key}"
        return f"{group['kind']}|{self._normalize_text(group['best_candidate']['name'])}"

    def _deduplicate_display_names(self, logical_devices: List[Dict[str, Any]]) -> None:
        counts = Counter(device["display_name"] for device in logical_devices)
        seen: Counter[str] = Counter()
        for device in logical_devices:
            label = device["display_name"]
            if counts[label] <= 1:
                continue
            seen[label] += 1
            device["display_name"] = f"{label} ({seen[label]})"

    def _build_logical_input_devices(self) -> None:
        non_generic_devices = [device for device in self.raw_input_devices if not self._is_generic_input_alias(device["name"])]
        microphone_devices = [device for device in non_generic_devices if self._is_probable_microphone(device["name"])]

        if microphone_devices:
            device_pool = microphone_devices
        elif non_generic_devices:
            device_pool = non_generic_devices
        else:
            device_pool = list(self.raw_input_devices)

        groups: List[Dict[str, Any]] = []
        for device in self._sort_raw_input_devices(device_pool):
            normalized_label = self._normalize_text(self._friendly_device_label(device["name"]))
            tokens = self._device_group_tokens(device["name"])
            matching_group = next((group for group in groups if self._device_matches_group(device, group)), None)
            if matching_group is None:
                groups.append(
                    {
                        "best_candidate": device,
                        "candidates": [device],
                        "kind": self._device_group_kind(device["name"]),
                        "signatures": {normalized_label},
                        "tokens": set(tokens),
                    }
                )
                continue

            matching_group["candidates"].append(device)
            matching_group["signatures"].add(normalized_label)
            matching_group["tokens"].update(tokens)

        default_input_id = self._get_default_input_device_id()
        logical_devices: List[Dict[str, Any]] = []
        for group in groups:
            candidates = self._sort_raw_input_devices(group["candidates"], prioritize_device_id=self.device_id)
            best_candidate = candidates[0]
            group["best_candidate"] = best_candidate
            display_name = self._friendly_device_label(best_candidate["name"])
            logical_devices.append(
                {
                    "candidates": candidates,
                    "contains_default": any(device["index"] == default_input_id for device in candidates),
                    "display_name": display_name,
                    "hostapi_name": best_candidate.get("hostapi_name", "Unknown"),
                    "index": best_candidate["index"],
                    "logical_key": self._logical_device_key(group),
                    "name": display_name,
                }
            )

        self._deduplicate_display_names(logical_devices)
        self.available_input_devices = logical_devices

    def _initialize_com_for_audio_thread(self) -> bool:
        try:
            hr = ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            if hr in (0, 1):
                return True
            if hr == RPC_E_CHANGED_MODE:
                hr = ctypes.windll.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
                return hr in (0, 1)
            print(f"CoInitializeEx returned HRESULT {hr}")
            return False
        except Exception as exc:
            print(f"Failed to initialize COM for audio thread: {exc}")
            return False

    def _get_default_input_device_id(self) -> Optional[int]:
        try:
            default_device = sd.default.device
            if hasattr(default_device, "input"):
                input_device = int(default_device.input)
            else:
                try:
                    input_device = int(default_device[0])
                except (TypeError, KeyError, IndexError):
                    input_device = int(default_device)
            return None if input_device < 0 else input_device
        except Exception as exc:
            print(f"Could not determine default input device: {exc}")
            return None

    def _device_host_rank(self, hostapi_name: str) -> int:
        try:
            return self.PREFERRED_HOSTAPIS.index(hostapi_name)
        except ValueError:
            return len(self.PREFERRED_HOSTAPIS)

    def _device_hint_rank(self, device_name: str) -> int:
        lowered = device_name.lower()
        for index, hint in enumerate(self.PREFERRED_DEVICE_NAME_HINTS):
            if hint in lowered:
                return index
        return len(self.PREFERRED_DEVICE_NAME_HINTS)

    def _discover_input_devices(self) -> None:
        """Find all available input devices across Windows host APIs."""
        self.raw_input_devices = []
        self.available_input_devices = []

        devices = sd.query_devices()
        default_input_id = self._get_default_input_device_id()

        print("Available input devices:")
        for index, raw_device in enumerate(devices):
            if raw_device["max_input_channels"] <= 0:
                continue

            device = dict(raw_device)
            device["index"] = index
            try:
                host_api = sd.query_hostapis(device["hostapi"])
                hostapi_name = host_api["name"]
            except Exception:
                hostapi_name = "Unknown"

            device["hostapi_name"] = hostapi_name
            device["display_name"] = f"{device['name']} [{hostapi_name}]"
            self.raw_input_devices.append(device)

            default_marker = " (default)" if index == default_input_id else ""
            print(f"  ID {index}: {device['display_name']}{default_marker}")

        if not self.raw_input_devices:
            print("No input devices (microphones) found.")
            return

        self._build_logical_input_devices()
        print("Logical microphone choices:")
        for logical_device in self.available_input_devices:
            print(
                "  "
                f"{logical_device['display_name']} "
                f"-> {logical_device['hostapi_name']} (ID: {logical_device['index']})"
            )

    def _find_device_by_key(self, device_key: Optional[str]) -> Optional[Dict[str, Any]]:
        if not device_key:
            return None
        return next((device for device in self.available_input_devices if device["logical_key"] == device_key), None)

    def _find_logical_device_by_index(self, device_id: int) -> Optional[Dict[str, Any]]:
        return next(
            (
                device
                for device in self.available_input_devices
                if any(candidate["index"] == device_id for candidate in device.get("candidates", []))
            ),
            None,
        )

    def _get_ranked_input_devices(self, prioritize_current: bool = True) -> List[Dict[str, Any]]:
        current_device_key = self.selected_device_key
        ranked = sorted(
            self.available_input_devices,
            key=lambda device: (
                0 if prioritize_current and device["logical_key"] == current_device_key else 1,
                0 if device.get("contains_default") else 1,
                self._device_hint_rank(device["display_name"]),
                self._device_host_rank(device.get("hostapi_name", "Unknown")),
                device["display_name"].lower(),
                device["index"],
            ),
        )
        return ranked

    def _select_preferred_device(self) -> None:
        """Select the most appropriate input device based on current availability."""
        if not self.available_input_devices:
            self.device_id = None
            return

        preferred_device = self._find_device_by_key(self.selected_device_key)
        if preferred_device is None:
            ranked_devices = self._get_ranked_input_devices(prioritize_current=False)
            preferred_device = ranked_devices[0]

        best_candidate = preferred_device["candidates"][0]
        self.device_id = best_candidate["index"]
        self.selected_device_key = preferred_device["logical_key"]
        print(
            "Selected input device: "
            f"{preferred_device['display_name']} via {best_candidate['hostapi_name']} "
            f"(ID: {self.device_id})"
        )

    def set_device(self, device_id: int) -> None:
        """Update the current recording device and adjust sample rate."""
        device_info = self._find_logical_device_by_index(device_id)
        if device_info:
            best_candidate = device_info["candidates"][0]
            self.device_id = best_candidate["index"]
            self.selected_device_key = device_info["logical_key"]
            print(
                "Selected device: "
                f"{device_info['display_name']} via {best_candidate['hostapi_name']} "
                f"(ID: {self.device_id})"
            )
            self._set_supported_sample_rate()
        else:
            print(f"Device ID {device_id} not found in available input devices.")

    def _stream_kwargs(self, device_id: int, sample_rate: int) -> Dict[str, Any]:
        return {
            "device": device_id,
            "samplerate": sample_rate,
            "channels": 1,
            "dtype": "int16",
            "blocksize": 0,
            "latency": "high",
        }

    def _candidate_sample_rates(self, device_info: Dict[str, Any]) -> List[int]:
        candidate_rates: List[int] = []
        default_rate = device_info.get("default_samplerate")
        for rate in [default_rate, 16000, 44100, 48000, 22050, 11025, 8000]:
            try:
                numeric_rate = int(round(float(rate)))
            except (TypeError, ValueError):
                continue
            if numeric_rate > 0 and numeric_rate not in candidate_rates:
                candidate_rates.append(numeric_rate)
        if SAMPLE_RATE not in candidate_rates:
            candidate_rates.append(SAMPLE_RATE)
        return candidate_rates

    def _set_supported_sample_rate(self) -> bool:
        """Set a sample rate supported by the current device."""
        if self.device_id is None:
            print("No device selected, cannot set sample rate.")
            return False

        device_info = sd.query_devices(self.device_id)
        for rate in self._candidate_sample_rates(device_info):
            try:
                sd.check_input_settings(device=self.device_id, samplerate=rate, channels=1, dtype="int16")
                self.sample_rate = rate
                print(f"Set sample rate to {rate} Hz for device ID {self.device_id}")
                return True
            except sd.PortAudioError:
                continue

        self.sample_rate = SAMPLE_RATE
        print(f"No supported sample rate found for device ID {self.device_id}. Falling back to {SAMPLE_RATE} Hz.")
        return False

    def _can_open_input_stream(self, device_id: int, sample_rate: int) -> bool:
        try:
            with sd.InputStream(**self._stream_kwargs(device_id, sample_rate)):
                return True
        except sd.PortAudioError as exc:
            print(f"Failed to open input stream for device ID {device_id} at {sample_rate} Hz: {exc}")
            return False
        except Exception as exc:
            print(f"Unexpected error while probing device ID {device_id}: {exc}")
            return False

    def _try_prepare_working_device(self, refresh_first: bool) -> bool:
        if refresh_first:
            self.refresh_devices()
        elif not self.available_input_devices:
            self._discover_input_devices()
            if self.device_id is None:
                self._select_preferred_device()
                if self.device_id is not None:
                    self._set_supported_sample_rate()

        for logical_device in self._get_ranked_input_devices():
            self.selected_device_key = logical_device["logical_key"]
            for candidate in logical_device["candidates"]:
                self.device_id = candidate["index"]
                if not self._set_supported_sample_rate():
                    continue
                if self._can_open_input_stream(self.device_id, self.sample_rate):
                    print(
                        "Prepared working input device: "
                        f"{logical_device['display_name']} via {candidate['hostapi_name']} "
                        f"(ID: {self.device_id})"
                    )
                    return True

        return False

    def _ensure_working_device(self) -> bool:
        """Ensure the current recording device is still usable before starting a recording."""
        if self._try_prepare_working_device(refresh_first=False):
            return True

        print("No working microphone found with cached device list. Refreshing devices and retrying...")
        return self._try_prepare_working_device(refresh_first=True)

    def start(self) -> bool:
        """Start recording audio in a separate thread. Returns True if started successfully."""
        if not self._ensure_working_device():
            print("Cannot start recording: No working input device is available.")
            show_error_notification(
                "Recording Error",
                "No working microphone could be opened. The selected microphone may have been disconnected or is unavailable in the current Windows audio host API.",
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

    def refresh_devices(self, reinitialize_audio: bool = True) -> None:
        """Refresh the list of available audio devices and reselect if needed."""
        print("Refreshing audio devices...")
        if reinitialize_audio:
            try:
                sd._terminate()
                sd._initialize()
            except Exception as exc:
                print(f"Error reinitializing PortAudio: {exc}")

        previous_device_key = self.selected_device_key
        self.device_id = None
        self._discover_input_devices()
        self.selected_device_key = previous_device_key
        self._select_preferred_device()

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

        com_initialized = self._initialize_com_for_audio_thread()
        try:
            with sd.InputStream(callback=callback, **self._stream_kwargs(self.device_id, self.sample_rate)):
                start_time = time.time()
                while self.recording and (time.time() - start_time < RECORD_SECONDS):
                    time.sleep(0.1)
        except sd.PortAudioError as exc:
            error_msg = f"Audio device error: {exc}\nThe microphone may have been disconnected or become unavailable."
            print(f"Error recording audio: {exc}")
            print("Refreshing devices after recording error...")
            self.recording = False
            self.error_occurred = True
            self.refresh_devices()
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
        finally:
            if com_initialized:
                try:
                    ctypes.windll.ole32.CoUninitialize()
                except Exception as exc:
                    print(f"Failed to uninitialize COM for audio thread: {exc}")

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
