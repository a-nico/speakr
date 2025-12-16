import threading
import time
import traceback
from typing import Callable, List, Set

from pynput import keyboard

from utils import safe_execute

CTRL_KEYS = {keyboard.Key.ctrl_l}
WIN_KEYS = {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r}
ALT_KEYS = {keyboard.Key.alt_l}
B_KEY = keyboard.KeyCode.from_char("b")
MIN_RECORD_DURATION = 1.0


def create_hotkey_listener(
    recorder,
    tts_service,
    transcribe_callback: Callable[[object], None],
    play_click: Callable[[str], None],
) -> keyboard.Listener:
    state_lock = threading.Lock()
    pressed_keys: Set[keyboard.Key] = set()
    key_press_order: List[keyboard.Key] = []
    hotkey_combo = {keyboard.Key.alt, B_KEY}
    tts_hotkey_combo = {keyboard.Key.ctrl, keyboard.Key.cmd}
    combo_activated = False
    tts_combo_activated = False
    record_start_time = 0.0

    def reset_state() -> None:
        nonlocal combo_activated, tts_combo_activated
        with state_lock:
            combo_activated = False
            tts_combo_activated = False
            pressed_keys.clear()
            key_press_order.clear()
        if recorder.recording:
            recorder.cancel()
        print("State reset complete - ready for next recording.")

    recorder.on_error_callback = reset_state

    def on_press(key: keyboard.Key) -> None:
        nonlocal combo_activated, tts_combo_activated, record_start_time
        try:
            if key == keyboard.Key.esc:
                if tts_service and getattr(tts_service, "_is_playing", False):
                    tts_service.stop_playback()
                    return

            if key in WIN_KEYS:
                with state_lock:
                    rec_active = recorder.recording or combo_activated
                if rec_active:
                    safe_execute(play_click, "Playing cancel sound", "cancel")
                    print("Recording canceled (Win key).")
                    recorder.cancel()
                    with state_lock:
                        combo_activated = False
                        pressed_keys.clear()
                        key_press_order.clear()
                    return

            normalized_key = key
            if key in CTRL_KEYS:
                normalized_key = keyboard.Key.ctrl
            elif key in WIN_KEYS:
                normalized_key = keyboard.Key.cmd
            elif key in ALT_KEYS:
                normalized_key = keyboard.Key.alt
            elif hasattr(key, "char") and key.char == "b":
                normalized_key = B_KEY

            with state_lock:
                if normalized_key in (keyboard.Key.ctrl, keyboard.Key.cmd, keyboard.Key.alt, B_KEY):
                    if normalized_key not in pressed_keys:
                        pressed_keys.add(normalized_key)
                        key_press_order.append(normalized_key)

                def is_second_key(first_key, second_key) -> bool:
                    if len(key_press_order) < 2:
                        return False
                    try:
                        first_pos = key_press_order.index(first_key)
                        second_pos = key_press_order.index(second_key)
                        return second_pos > first_pos
                    except ValueError:
                        return False

                if (
                    tts_hotkey_combo.issubset(pressed_keys)
                    and not tts_combo_activated
                    and not combo_activated
                    and is_second_key(keyboard.Key.ctrl, keyboard.Key.cmd)
                ):
                    if keyboard.Key.alt not in pressed_keys:
                        tts_combo_activated = True
                        print("TTS hotkey activated - will speak clipboard text on release...")
                        return

                if (
                    hotkey_combo.issubset(pressed_keys)
                    and not recorder.recording
                    and not combo_activated
                    and not tts_combo_activated
                    and is_second_key(keyboard.Key.alt, B_KEY)
                ):
                    combo_activated = True
                    safe_execute(play_click, "Playing start sound", "start")
                    print("Recording started... (release to transcribe)")
                    record_start_time = time.time()
                    if not recorder.start():
                        combo_activated = False
                        pressed_keys.clear()
                        key_press_order.clear()
        except Exception as exc:
            print(f"Error in on_press handler: {exc}")
            print(traceback.format_exc())
            reset_state()

    def on_release(key: keyboard.Key) -> None:
        nonlocal combo_activated, tts_combo_activated
        try:
            normalized_key = key
            if key in CTRL_KEYS:
                normalized_key = keyboard.Key.ctrl
            elif key in WIN_KEYS:
                normalized_key = keyboard.Key.cmd
            elif key in ALT_KEYS:
                normalized_key = keyboard.Key.alt
            elif hasattr(key, "char") and key.char == "b":
                normalized_key = B_KEY

            with state_lock:
                was_tts_combo_active = tts_combo_activated
                was_combo_active = combo_activated
                is_combo_key = normalized_key in hotkey_combo
                is_tts_combo_key = normalized_key in tts_hotkey_combo

            if is_tts_combo_key and was_tts_combo_active:
                safe_execute(play_click, "Playing send sound", "send")
                print("TTS hotkey released - speaking clipboard text...")

                def do_tts() -> None:
                    try:
                        tts_service.speak_clipboard()
                    except Exception as exc:  # pragma: no cover - runtime only
                        print(f"TTS error: {exc}")
                        print(traceback.format_exc())

                threading.Thread(target=do_tts, daemon=True).start()

                with state_lock:
                    pressed_keys.clear()
                    key_press_order.clear()
                    tts_combo_activated = False
                return

            if is_combo_key and was_combo_active:
                recorder.stop()
                duration: float = time.time() - record_start_time

                if recorder.error_occurred:
                    print("Recording had an error, skipping transcription.")
                    with state_lock:
                        pressed_keys.clear()
                        key_press_order.clear()
                        combo_activated = False
                    return

                if duration < MIN_RECORD_DURATION:
                    safe_execute(play_click, "Playing cancel sound", "cancel")
                    print(f"Recording too short ({duration:.2f}s). Canceled.")
                else:
                    safe_execute(play_click, "Playing stop sound", "stop")
                    print("Recording stopped.")
                    wav_bytes = recorder.get_wav_bytes()
                    if wav_bytes:
                        print("Transcribing...")
                        try:
                            transcribe_callback(wav_bytes)
                        except Exception as exc:
                            print(f"Error during transcription or pasting: {exc}")
                            print(traceback.format_exc())

                with state_lock:
                    pressed_keys.clear()
                    key_press_order.clear()
                    combo_activated = False

            elif normalized_key in (keyboard.Key.ctrl, keyboard.Key.cmd, keyboard.Key.alt, B_KEY):
                with state_lock:
                    pressed_keys.discard(normalized_key)
                    while normalized_key in key_press_order:
                        key_press_order.remove(normalized_key)

        except Exception as exc:
            print(f"Error in on_release handler: {exc}")
            print(traceback.format_exc())
            reset_state()

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    return listener
