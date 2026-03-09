import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure basic console logging for local development."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

