import logging


def setup_logger() -> None:
    """Log operational metadata to stderr, without updates or exception payloads."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )
    logging.getLogger("aiogram.event").setLevel(logging.CRITICAL)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.CRITICAL)
