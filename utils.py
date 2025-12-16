import traceback
from typing import Any, Callable

from audio_feedback import show_error_notification


def safe_execute(func: Callable, error_context: str, *args, **kwargs) -> Any:
    """Execute a function safely, catching and logging any exceptions."""
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        error_msg = f"{error_context}: {exc}"
        print(f"ERROR: {error_msg}")
        print(traceback.format_exc())
        show_error_notification("Speech-to-Text Error", error_msg)
        return None
