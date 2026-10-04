"""Makine bazlı üretim planı. Streamlit'e bağımlı değildir.

Model
-----
* Her makinenin günlük çalışma saati vardır; pasif makineler plana girmez.
* Operasyon sırası korunur: bir operasyon, kendinden önceki operasyonlar bitmeden başlamaz. İstisna: arka arkaya
  gelen ve aynı makine türünde olan operasyonlar (ör. 1. ve 2. operasyon ikisi de tornalama) bir "aşama"
  oluşturur; aynı anda, farklı makinelerde (iki tornada) çalışabilir. Sonraki aşama (ör. 3. operasyon dik işleme),
  önceki aşamanın tüm operasyonları bitince başlar.
* Operasyon süresi = sök-tak (iş emri başına bir kez) + kalan adet × birim süre × (1 + buffer).
* Operasyon, kendi makine türündeki (boşsa herhangi bir) aktif makineler arasından en erken biteceği makineye atanır.
* İş emirleri termin sırasıyla (aynı terminde sipariş sırasıyla) planlanır; makineler önceki işlerden kalan
  doluluğu taşır.
* Zaman, "iş günü sırası × 1440 + o günün dakikası" olarak tutulur; hafta sonu (çalışma günü ayarına göre)
  atlanır. Gün içinde makine, günlük saatini aşan işi ertesi iş gününe böler.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

EPS = 1e-9
DAY = 1440.0
ANY = ""  # makine türü boş = herhangi bir makine


def is_workday(d: date, week_days: int) -> bool:
    return d.weekday() < week_days


class Calendar:
    """İş günü sırası <-> tarih."""

    def __init__(self, start: date, week_days: int):
        self.week_days = week_days
        d = start
        while not is_workday(d, week_days):
            d += timedelta(days=1)
        self.days = [d]

    def index_of(self, d: date) -> int:
        """`d` gününden önce ya da o gün olan ilk iş günü sırası (geçmiş günler 0)."""
        n = 0
        while self.date_of(n) < d:
            n += 1
        return n

    def date_of(self, n: int) -> date:
        while len(self.days) <= n:
            d = self.days[-1] + timedelta(days=1)
            while not is_workday(d, self.week_days):
                d += timedelta(days=1)
            self.days.append(d)
        return self.days[n]


@dataclass
class Machine:
    id: int
    name: str
    type: str
    daily_hours: float
    changeover: float = 120.0  # parça ayarlama süresi (dk): operasyon başına, op. kendi sök-tak süresini vermediyse
    free: float = 0.0  # makinenin boşaldığı an (mutlak)
    load: dict = field(default_factory=dict)  # iş günü sırası -> dolu dakika

    @property
    def cap(self) -> float:
        return max(0.0, float(self.daily_hours)) * 60


def _norm(t: float, cap: float) -> float:
    """Gün kapasitesinin tam sonundaki an, ertesi iş gününün başıdır."""
    n = int(t // DAY + EPS)
    m = t - n * DAY
    if m >= cap - EPS:
        return (n + 1) * DAY
    return t


def place(m: Machine, ready: float, duration: float):
    """`duration` dakikalık işi makineye `ready` anından sonra yerleştirir.
    Dönüş: (başlangıç, bitiş, [(gün, gün_içi_başlangıç_dk, gün_içi_bitiş_dk)])."""
    t = _norm(max(m.free, ready), m.cap)
    if duration <= EPS or m.cap <= EPS:
        return t, t, []
    start, left, segs = t, duration, []
    n = int(t // DAY + EPS)
    mi = t - n * DAY
    while left > EPS:
        take = min(m.cap - mi, left)
        segs.append((n, mi, mi + take))
        mi += take
        left -= take
        if left > EPS:
            n, mi = n + 1, 0.0
    return start, n * DAY + mi, segs


@dataclass
class OpSpec:
    name: str
    minutes: float          # adet başına süre (dk)
    setup: float = 0.0      # sök-tak (dk), iş emri başına bir kez
    machine_type: str = ANY
    key: object = None      # operasyon kimliği (elle yerleştirmeler için)


@dataclass
class OrderSpec:
    key: object
    label: str
    product: str
    qty: float              # kalan adet
    due: str | None         # ISO tarih
    ops: list[OpSpec]


def stages(ops: list["OpSpec"]) -> list[list["OpSpec"]]:
    """Ardışık, aynı makine türündeki operasyonlar tek aşamadır (eş zamanlı yapılabilir)."""
    out: list[list[OpSpec]] = []
    for o in ops:
        if out and o.machine_type != ANY and out[-1][0].machine_type == o.machine_type:
            out[-1].append(o)
        else:
            out.append([o])
    return out


def setup_for(o: OpSpec, qty: float, m: "Machine | None" = None) -> float:
    """Sök-tak / parça ayarlama süresi: operasyonda girilmişse o, yoksa makinenin varsayılanı."""
    if qty <= 0:
        return 0.0
    return o.setup if o.setup > 0 else (m.changeover if m is not None else 0.0)


def op_duration(o: OpSpec, qty: float, buffer_pct: float, m: "Machine | None" = None) -> float:
    return setup_for(o, qty, m) + qty * o.minutes * (1 + buffer_pct / 100)


def schedule(orders: list[OrderSpec], machines: list[dict], start: date, week_days: int,
             buffer_pct: float = 0.0, day0_offset: float = 0.0, overrides: dict | None = None) -> dict:
    """Siparişleri makinelere yerleştirir.

    machines: {id, name, type, daily_hours, active}. day0_offset: ilk iş gününde makinelerin dolu sayıldığı dakika
    (bugünü "şu andan" başlatmak için). Dönüş:
      orders: [{key,label,product,qty,due,state,start,end,hours,items:[...],parts:[...]}]
      machines: [{id,name,type,daily_hours,busy:{tarih: dk}}]
      end: tüm planın bitiş tarihi
    """
    overrides = overrides or {}  # (sipariş_key, op_key) -> (makine_id | None, en erken gün: date | None)
    cal = Calendar(start, week_days)
    ms = [Machine(int(m["id"]), m["name"], m.get("type") or "", float(m["daily_hours"]),
                  float(m["changeover_minutes"]) if m.get("changeover_minutes") is not None else 120.0,
                  free=float(day0_offset))
          for m in machines if m.get("active", 1) and float(m["daily_hours"]) > 0]
    result = []
    for o in sorted(orders, key=lambda o: (o.due or "9999", str(o.key))):
        entry = {"key": o.key, "label": o.label, "product": o.product, "qty": o.qty, "due": o.due,
                 "items": [], "parts": [], "start": None, "end": None, "hours": 0.0, "state": "Zamanında"}
        if not o.ops or sum(x.setup + o.qty * x.minutes for x in o.ops) <= EPS:
            entry["state"] = "Operasyon yok"
            result.append(entry)
            continue
        first, last, blocked = None, 0.0, None
        ready = 0.0
        for si, st in enumerate(stages(o.ops), 1):
            stage_end = ready
            for op in st:
                ov = overrides.get((o.key, op.key)) if op.key is not None else None
                forced = next((m for m in ms if ov and ov[0] is not None and m.id == ov[0]), None)
                cands = [forced] if forced else [m for m in ms if op.machine_type == ANY or m.type == op.machine_type]
                if not cands:
                    blocked = op
                    break
                ready_op = ready
                if ov and ov[1]:
                    ready_op = max(ready, cal.index_of(ov[1]) * DAY)
                best = None
                for m in cands:
                    d = op_duration(op, o.qty, buffer_pct, m)
                    s_, e_, sg_ = place(m, ready_op, d)
                    if best is None or (e_, s_) < (best[2], best[1]):
                        best = (m, s_, e_, sg_, d)
                m, s_, e_, sg, dur = best
                m.free = e_
                for n, a0, a1 in sg:
                    m.load[n] = m.load.get(n, 0.0) + (a1 - a0)
                setup = setup_for(op, o.qty, m)
                entry["items"].append({"op": op.name, "op_key": op.key, "order_key": o.key, "stage": si,
                                       "forced": bool(ov and (forced or ov[1])), "req_day": ov[1] if ov else None,
                                       "req_machine": ov[0] if ov else None, "machine": m.name, "machine_id": m.id,
                                       "type": op.machine_type, "start": s_, "end": e_, "minutes": dur,
                                       "setup": setup, "run": dur - setup, "segments": sg})
                first = s_ if first is None else min(first, s_)
                last = max(last, e_)
                stage_end = max(stage_end, e_)
            if blocked:
                break
            ready = stage_end
        if blocked:
            entry["state"] = "Makine yok"
            entry["blocked_op"] = blocked.name
            entry["blocked_type"] = blocked.machine_type
            result.append(entry)
            continue
        entry["hours"] = sum(it["minutes"] for it in entry["items"]) / 60
        entry["start_t"], entry["end_t"] = first, last
        entry["start"] = cal.date_of(int(first // DAY + EPS))
        entry["end"] = cal.date_of(int(last // DAY + EPS))
        if o.due and entry["end"].isoformat() > o.due:
            entry["state"] = "Gecikir"
        for it in entry["items"]:
            it["start_date"], it["end_date"] = cal.date_of(int(it["start"] // DAY + EPS)), cal.date_of(int(it["end"] // DAY + EPS))
            it["segments"] = [(cal.date_of(n), a0, a1) for n, a0, a1 in it["segments"]]
        entry["parts"] = [{"part": it["op"], "op": it["op"], "machine": it["machine"], "end": it["end"],
                           "end_date": it["end_date"], "stage": it["stage"]} for it in entry["items"]]
        result.append(entry)
    ends = [e["end"] for e in result if e["end"]]
    return {
        "orders": result,
        "machines": [{"id": m.id, "name": m.name, "type": m.type, "daily_hours": m.daily_hours,
                      "busy": {cal.date_of(n): v for n, v in sorted(m.load.items())}} for m in ms],
        "end": max(ends) if ends else None,
        "calendar": cal,
    }


def clock(t: float, shift_start_min: int = 8 * 60) -> str:
    """Mutlak ana göre saat:dakika (vardiya 08:00'de başlar)."""
    m = t - int(t // DAY + EPS) * DAY
    mm = int(round(m)) + shift_start_min
    return f"{mm // 60 % 24:02d}:{mm % 60:02d}"


def hm(minutes_in_day: float, shift_start_min: int = 8 * 60) -> str:
    """Gün içi dakika -> saat:dakika."""
    mm = int(round(minutes_in_day)) + shift_start_min
    return f"{mm // 60 % 24:02d}:{mm % 60:02d}"
