__all__ = ["wrap_argument"]


def wrap_argument(text: str) -> str:
    """
    Wrap command argument in quotes and escape when this contains special characters.
    """
    if not any(x in text for x in [" ", '"', "'", "\\"]):
        return text
    else:
        return '"%s"' % (text.replace("\\", r"\\").replace('"', r"\""),)
