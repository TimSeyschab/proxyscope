import logging


def configure_logging(level: int = logging.INFO, handler: logging.Handler | None = None) -> None:
    """Configure console logging, or route records to an optional application handler."""
    kwargs: dict[str, object] = {
        "level": level,
        "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
        "force": True,
    }
    if handler is not None:
        kwargs["handlers"] = [handler]
    logging.basicConfig(**kwargs)
