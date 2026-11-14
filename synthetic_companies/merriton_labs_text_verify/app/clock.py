from datetime import datetime, timedelta, timezone


class FixedClock:
    """Injected demo time; never consult wall time in product decisions."""

    def __init__(self, value: datetime | None = None):
        self.value = value or datetime(2026, 11, 14, 12, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)
