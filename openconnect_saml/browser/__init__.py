try:
    from .browser import Browser, Terminated
except ImportError:
    # PyQt6 not installed — GUI browser unavailable (headless-only mode)
    Browser = None  # type: ignore[assignment, misc]

    class Terminated(Exception):  # type: ignore[no-redef]
        pass


__all__ = ["Browser", "Terminated"]
