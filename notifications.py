import ctypes
import threading


def show_error_notification(title: str, message: str) -> None:
    """Show an error message to the user via Windows message box."""

    def _show() -> None:
        try:
            MB_OK = 0x0
            MB_ICONERROR = 0x10
            MB_SYSTEMMODAL = 0x1000
            ctypes.windll.user32.MessageBoxW(0, message, title, MB_OK | MB_ICONERROR | MB_SYSTEMMODAL)
        except Exception as exc:  # pragma: no cover - OS feedback only
            print(f"Failed to show error dialog: {exc}")

    threading.Thread(target=_show, daemon=True).start()