"""Truncation helpers for button labels and long message bodies."""


def split_plain_text_chunks(text: str, max_len: int = 3800) -> list[str]:
    """
    Split long plain-text (or light HTML) for Telegram/MAX limits.
    Prefers breaking at newlines.
    """
    t = (text or "").strip()
    if len(t) <= max_len:
        return [t] if t else [""]
    out: list[str] = []
    i = 0
    n = len(t)
    while i < n:
        end = min(i + max_len, n)
        if end < n:
            br = t.rfind("\n", i, end)
            if br > i + max_len // 3:
                end = br + 1
        chunk = t[i:end].strip()
        if chunk:
            out.append(chunk)
        i = end
    return out if out else [""]


def truncate_smart(text: str, max_len: int, suffix: str = "…") -> str:
    """
    Shorten text to max_len, preferring a word boundary; adds suffix if trimmed.
    """
    if not text:
        return ""
    t = text.strip()
    if len(t) <= max_len:
        return t
    reserve = len(suffix)
    n = max_len - reserve
    if n < 6:
        return (t[: max_len - reserve] + suffix) if max_len > reserve else t[:max_len]
    cut = t[:n]
    last_sp = cut.rfind(" ")
    if last_sp > n * 0.5:
        cut = cut[:last_sp].rstrip()
    return cut + suffix


def event_button_label(title: str, prefix: str = "📅 ", max_total: int = 58) -> str:
    """
    Label for inline buttons (Telegram/MAX ~64 chars). Prefix + truncated title.
    """
    budget = max_total - len(prefix)
    if budget < 12:
        budget = 12
    return prefix + truncate_smart((title or "").strip(), budget)
