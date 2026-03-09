"""Progress bar utility for FSM registration steps."""

FILLED = "🔘"
CURRENT = "🏍"
EMPTY = "⚪"


def make_progress_bar(current_step: int, total_steps: int) -> str:
    """
    Generate a progress bar string for FSM steps.

    Args:
        current_step: 1-based current step number
        total_steps: total number of steps

    Returns:
        String like 'Шаг 3 из 8  🔘🔘🔸⚪⚪⚪⚪⚪'
    """
    bar_parts = []
    for i in range(1, total_steps + 1):
        if i < current_step:
            bar_parts.append(FILLED)
        elif i == current_step:
            bar_parts.append(CURRENT)
        else:
            bar_parts.append(EMPTY)

    return f"Шаг {current_step} из {total_steps}  {''.join(bar_parts)}"


def progress_prefix(current_step: int, total_steps: int) -> str:
    """Return progress bar line followed by a newline, ready to prepend to a message."""
    return make_progress_bar(current_step, total_steps) + "\n\n"
