"""String manipulation functions"""


def format_string(template: str, **kwargs) -> str:
    """Format the given template string with provided keyword arguments
    only if the placeholders are present in the string.

    Args:
        template (str): The template string containing placeholders.
        kwargs: Keyword arguments with replacement values.

    Returns:
        str: The formatted string.
    """
    for key, value in kwargs.items():
        placeholder = f"{{{key}}}"

        if placeholder in template:
            template = template.replace(placeholder, str(value))

    return template


def add_ordinal_suffix(number: int) -> str:
    """
    Add the appropriate ordinal suffix to an integer.

    Args:
        number (int): The integer to add the suffix to.

    Returns:
        str: The integer with its ordinal suffix.
    """
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")

    return f"{number}{suffix}"
