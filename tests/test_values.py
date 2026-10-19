"""Printed text -> typed database values."""
from datetime import date, datetime, timezone
from decimal import Decimal

from db.values import day_end, day_start, printed_date, printed_money, printed_time


def test_print_time_is_shop_time_stored_as_utc():
    assert printed_time("2026-09-17T13:20:00") == datetime(2026, 9, 17, 18, 20, tzinfo=timezone.utc)  # CDT
    assert printed_time("2026-12-17T13:20:00") == datetime(2026, 12, 17, 19, 20, tzinfo=timezone.utc)  # CST
    assert printed_time("") is None


def test_dates():
    assert printed_date("8/21/2026") == date(2026, 8, 21)
    assert printed_date("04/07/2026") == date(2026, 4, 7)
    assert printed_date("Days") is None and printed_date("") is None and printed_date("2/30/2026") is None


def test_money():
    assert printed_money("500.00") == Decimal("500.00")
    assert printed_money("$2,000.00 - Not Waived") == Decimal("2000.00")
    assert printed_money("None") is None and printed_money("") is None


def test_shop_day_bounds():
    assert day_start("2026-10-01") == datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)
    assert day_end("2026-09-30") == datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)
