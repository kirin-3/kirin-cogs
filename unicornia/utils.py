def validate_url(url: str) -> bool:
    """Validate if a string is a valid HTTP/HTTPS URL"""
    return url.startswith(("http://", "https://")) and len(url) < 2000

def validate_club_name(name: str) -> bool:
    """Validate club name (alphanumeric and some symbols, max 20 chars)"""
    if not name or len(name) > 20:
        return False
    # Allow alphanumeric, spaces, and common safe symbols
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_!@#$*")
    return all(c in allowed_chars for c in name)

def validate_text_input(text: str, max_length: int = 200, allow_empty: bool = True) -> bool:
    """Validate generic text input length."""
    if text is None:
        return allow_empty
    return len(text) <= max_length
