import re

GA_ID_RE = re.compile(r"G-[A-Z0-9]{4,20}")


def valid_ga_id(value):
    return bool(GA_ID_RE.fullmatch(value or ""))