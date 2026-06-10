from urllib.parse import urlsplit


def normalize_whitelist_entry(value: str) -> str:
    raw_value = value.strip()
    if not raw_value:
        raise ValueError("Whitelist entry must not be empty.")

    parsed = urlsplit(raw_value if "://" in raw_value else f"http://{raw_value}")
    if not parsed.hostname:
        raise ValueError(f"Invalid whitelist entry: {value}")
    return parsed.hostname.lower()
