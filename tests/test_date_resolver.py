"""
Unit tests for message-timestamp relative date resolver.
Verifies calculations are strictly anchored to message date, never computer clock.
"""

from datetime import datetime, timedelta
from owi.ai.date_resolver import resolve_relative_date

def test_tomorrow_resolution():
    # Anchor: 14 September 2026 (Monday)
    anchor = datetime(2026, 9, 14, 10, 0, 0)
    
    res_ar = resolve_relative_date("هبعتلك الملف بكرة الصبح", anchor)
    assert res_ar == datetime(2026, 9, 15, 10, 0, 0)

    res_en = resolve_relative_date("I will send the draft tomorrow", anchor)
    assert res_en == datetime(2026, 9, 15, 10, 0, 0)

def test_day_after_tomorrow():
    anchor = datetime(2026, 9, 14, 10, 0, 0)
    res = resolve_relative_date("هنتقابل بعد بكرة إن شاء الله", anchor)
    assert res == datetime(2026, 9, 16, 10, 0, 0)

def test_in_n_days():
    anchor = datetime(2026, 9, 14, 10, 0, 0)
    res_ar = resolve_relative_date("أكدوا لي الملاحظات خلال 3 أيام", anchor)
    assert res_ar == datetime(2026, 9, 17, 10, 0, 0)

    res_en = resolve_relative_date("need this in 5 days", anchor)
    assert res_en == datetime(2026, 9, 19, 10, 0, 0)

def test_weekday_relative_resolution():
    # Monday 14 September 2026
    anchor = datetime(2026, 9, 14, 10, 0, 0)
    
    # Thursday is 17 September 2026
    res_thursday_en = resolve_relative_date("We will sign by Thursday", anchor)
    assert res_thursday_en == datetime(2026, 9, 17, 10, 0, 0)

    res_thursday_ar = resolve_relative_date("المعاينة يوم الخميس القادم", anchor)
    assert res_thursday_ar == datetime(2026, 9, 17, 10, 0, 0)
