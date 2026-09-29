"""Üretim planı hesapları: operasyon süresi + buffer, günlük/haftalık kapasite ve
sıralı iş takvimi. Streamlit'e bağımlı değildir."""
from __future__ import annotations

import math
from datetime import date, timedelta

EPS = 1e-9


def is_workday(d: date, week_days: int) -> bool:
    """week_days=5: Pzt-Cum, 6: Pzt-Cmt, 7: her gün."""
    return d.weekday() < week_days


def next_workday(d: date, week_days: int) -> date:
    while not is_workday(d, week_days):
        d += timedelta(days=1)
    return d


def buffered(minutes: float, buffer_pct: float) -> float:
    return float(minutes or 0) * (1 + float(buffer_pct or 0) / 100)


def per_day(cap_min: float, unit_min: float) -> int:
    """Bir iş gününde tamamlanabilecek adet (tam sayı)."""
    return int(cap_min // unit_min + EPS) if unit_min > 0 else 0


def per_week(cap_min: float, week_days: int, unit_min: float) -> int:
    """Bir haftada tamamlanabilecek adet (yarım kalan iş ertesi güne devreder)."""
    return int(cap_min * week_days // unit_min + EPS) if unit_min > 0 else 0


def allocate(total_min: float, day: date, used: float, cap_min: float, week_days: int):
    """total_min dakikalık işi `day` gününden (o gün `used` dk dolu) başlayarak günlük kapasiteye dağıtır.
    Dönüş: (başlangıç, bitiş, [(gün, dk), ...], sonraki_gün, sonraki_gün_dolu_dk)."""
    day = next_workday(day, week_days)
    if total_min <= EPS or cap_min <= 0:
        return day, day, [], day, used
    left, chunks, start, end = total_min, [], None, day
    while left > EPS:
        day = next_workday(day, week_days)
        avail = cap_min - used
        if avail <= EPS:
            day, used = day + timedelta(days=1), 0.0
            continue
        take = min(avail, left)
        chunks.append((day, take))
        start = start or day
        end = day
        used += take
        left -= take
    return start, end, chunks, day, used


def units_done_by_day(chunks: list[tuple[date, float]], unit_min: float) -> list[int]:
    """Her günün sonunda toplam tamamlanmış adet."""
    out, cum = [], 0.0
    for _, m in chunks:
        cum += m
        out.append(int(cum / unit_min + EPS) if unit_min > 0 else 0)
    return out


def remaining_units(qty: float, progress: float) -> int:
    return int(math.ceil(float(qty or 0) * (100 - float(progress or 0)) / 100 - EPS))
