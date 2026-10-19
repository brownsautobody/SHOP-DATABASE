"""Printed estimate text -> typed database values (print times, dates, money), and the shop's time zone.
The text itself stays in each document's stored parse; these are the typed copies the database sorts and sums."""
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

# Louisiana, MO. Estimates print local time; the database keeps UTC.
SHOP_TZ = ZoneInfo(os.environ.get("SHOP_TIMEZONE", "America/Chicago"))


def printed_time(text):
    """'2026-09-17T13:20:00' (shop local, as the parser gives it) -> aware UTC datetime; blank -> None."""
    if not text:
        return None
    return datetime.fromisoformat(text).replace(tzinfo=SHOP_TZ).astimezone(timezone.utc)


def printed_date(text):
    """'8/21/2026' or '04/07/2026' -> date; anything else (blank, 'Days') -> None."""
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", text or "")
    if not m:
        return None
    try:
        return date(int(m[3]), int(m[1]), int(m[2]))
    except ValueError:
        return None


def printed_money(text):
    """'500.00', '$2,000.00 - Not Waived' -> Decimal; no amount printed ('', 'None') -> None."""
    m = re.search(r"-?\$?\s*(\d[\d,]*\.\d\d)", text or "")
    return Decimal(m[1].replace(",", "")) if m else None


def local(dt):
    """A stored (UTC) time in the shop's time zone."""
    return dt.astimezone(SHOP_TZ) if dt else None


def day_start(day):
    """The UTC moment the shop's day starts ('2026-09-17' or a date)."""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return datetime.combine(d, time(), SHOP_TZ).astimezone(timezone.utc)


def day_end(day):
    """The UTC moment after the shop's day ends (exclusive bound)."""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return day_start(d + timedelta(days=1))
