"""One place that knows about bar sizes, so nothing else hardcodes them."""

import pandas as pd

# Our timeframe name -> (bar length, CoinDCX resolution to fetch, or None if resampled).
TIMEFRAMES = {
    "1h": (pd.Timedelta(hours=1), "60"),
    "4h": (pd.Timedelta(hours=4), None),  # CoinDCX has no 4H; built from 1h
    "1d": (pd.Timedelta(days=1), "1D"),
}

YEAR = pd.Timedelta(days=365)  # crypto trades every day


def bar_length(timeframe: str) -> pd.Timedelta:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"Unknown timeframe {timeframe!r}. Use one of {list(TIMEFRAMES)}.")
    return TIMEFRAMES[timeframe][0]


def periods_per_year(timeframe: str) -> float:
    """1d -> 365, 4h -> 2190, 1h -> 8760. Derived, never hardcoded."""
    return YEAR / bar_length(timeframe)


def api_resolution(timeframe: str) -> str | None:
    bar_length(timeframe)  # validates
    return TIMEFRAMES[timeframe][1]
