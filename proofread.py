import time
from typing import Any, Optional, Tuple

import keyboard as kb
import pyperclip
import requests

from config import Config
from notifications import show_error_notification


KEY_STATE_SETTLE_DELAY_SECONDS = 0.05
CLIPBOARD_COPY_TIMEOUT_SECONDS = 0.75
CLIPBOARD_POLL_INTERVAL_SECONDS = 0.05
SELECTION_CAPTURE_FAILED = "copy_failed"
SELECTION_NOT_FOUND = "no_selection"


def _extract_text_from_response(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = payload.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for chunk in content:
                if not isinstance(chunk, dict):
                    continue
                text = chunk.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        if parts:
            return "\n".join(parts)

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()

    return ""


def _get_selected_text() -> Tuple[Optional[str], Optional[str]]:
    try:
        original_clipboard = pyperclip.paste()
        sentinel = f"__speakr_selection_probe__{time.perf_counter_ns()}__"
        pyperclip.copy(sentinel)
        time.sleep(KEY_STATE_SETTLE_DELAY_SECONDS)
        kb.press_and_release("ctrl+c")
        selected = sentinel
        deadline = time.time() + CLIPBOARD_COPY_TIMEOUT_SECONDS

        while time.time() < deadline:
            time.sleep(CLIPBOARD_POLL_INTERVAL_SECONDS)
            selected = pyperclip.paste()
            if selected != sentinel:
                break

        if selected == sentinel:
            pyperclip.copy(original_clipboard)
            return None, SELECTION_CAPTURE_FAILED

        if not selected or not selected.strip():
            pyperclip.copy(original_clipboard)
            return None, SELECTION_NOT_FOUND

        return selected.strip(), None
    except Exception as exc:
        print(f"Failed to capture selected text: {exc}")
        return None, SELECTION_CAPTURE_FAILED


def proofread_selected_text(config: Config) -> bool:
    selected_text, selection_error = _get_selected_text()
    if not selected_text:
        message = "No selected text found. Please highlight text first."
        if selection_error == SELECTION_CAPTURE_FAILED:
            message = (
                "Could not copy the current selection. Release the hotkey and make sure the target app supports Ctrl+C."
            )
        show_error_notification("Proofread Error", message)
        return False

    if not config.azure_proofread_endpoint or not config.azure_proofread_api_key:
        show_error_notification(
            "Proofread Error",
            "Azure proofread is not configured. Please set azure.proofread.endpoint and azure.proofread.api_key.",
        )
        return False

    selected_prompt = config.azure_proofread_system_prompt
    if not selected_prompt:
        show_error_notification(
            "Proofread Error",
            "Azure proofread is missing system_prompt_options. Please add at least one prompt in config.yaml.",
        )
        return False

    headers = {
        "Content-Type": "application/json",
        "api-key": config.azure_proofread_api_key,
    }
    payload = {
        "model": config.azure_proofread_model,
        "max_output_tokens": config.azure_proofread_max_completion_tokens,
        "input": f"{selected_prompt}\n\nText to proofread:\n{selected_text}",
    }

    try:
        response = requests.post(config.azure_proofread_endpoint, headers=headers, json=payload, timeout=45)
        response.raise_for_status()
        corrected_text = _extract_text_from_response(response.json())
        if not corrected_text:
            show_error_notification("Proofread Error", "No text was returned by the model.")
            return False

        pyperclip.copy(corrected_text)
        kb.press_and_release("ctrl+v")
        return True
    except requests.exceptions.HTTPError as exc:
        details = ""
        if exc.response is not None:
            try:
                details = exc.response.text.strip()
            except Exception:
                details = ""
        print(f"Proofread request failed: {exc}")
        if details:
            print(f"Azure error details: {details}")
        show_error_notification(
            "Proofread Error",
            f"Azure request failed: {exc}" + (f"\n\nDetails: {details[:500]}" if details else ""),
        )
        return False
    except requests.exceptions.RequestException as exc:
        print(f"Proofread request failed: {exc}")
        show_error_notification("Proofread Error", f"Azure request failed: {exc}")
        return False
    except Exception as exc:
        print(f"Proofread failed: {exc}")
        show_error_notification("Proofread Error", f"Failed to proofread text: {exc}")
        return False
