"""미국 NHTSA 리콜(공개 API, 키 불필요). 브랜드·연식별 모델 목록 → 모델별 리콜 → 최근 접수분만."""

import re
import time
from datetime import datetime, timedelta, timezone

from .. import http
from ..models import Signal

API = "https://api.nhtsa.gov"
_KST = timezone(timedelta(hours=9))


def parse_report_date(value):
    """NHTSA 날짜(dd/mm/yyyy 또는 mm/dd/yyyy, ISO)를 읽는다. 애매하면 dd/mm으로 본다."""
    if not value:
        return None
    value = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if not m:
        return None
    a, b, y = int(m[1]), int(m[2]), int(m[3])
    if b > 12:          # mm/dd
        month, day = a, b
    else:               # dd/mm (a>12인 경우 포함, 애매하면 이쪽)
        day, month = a, b
    try:
        return datetime(y, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def models(make, year):
    data = http.get_json(f"{API}/products/vehicle/models", {"modelYear": year, "make": make, "issueType": "r"})
    return list(dict.fromkeys(r.get("model") for r in data.get("results", []) if r.get("model")))


def recalls_for(make, model, year):
    data = http.get_json(f"{API}/recalls/recallsByVehicle", {"make": make, "model": model, "modelYear": year})
    return data.get("results", [])


def collect_recalls(rows, since):
    """여러 모델의 리콜 결과를 캠페인 번호로 합친다."""
    camps = {}
    for r in rows:
        num = r.get("NHTSACampaignNumber")
        if not num:
            continue
        date = parse_report_date(r.get("ReportReceivedDate"))
        if date and date < since:
            continue
        c = camps.setdefault(num, {"row": r, "date": date, "vehicles": set()})
        c["vehicles"].add(f"{r.get('ModelYear', '')} {r.get('Make', '')} {r.get('Model', '')}".strip())
    out = []
    for num, c in camps.items():
        r = c["row"]
        vehicles = sorted(c["vehicles"])
        out.append(Signal(
            channel="nhtsa",
            title=f"[NHTSA 리콜 {num}] {r.get('Manufacturer', '')} · {r.get('Component', '')}",
            url=f"https://www.nhtsa.gov/recalls?nhtsaId={num}",
            published=c["date"], source="NHTSA",
            text=" / ".join(x for x in [
                "대상: " + ", ".join(vehicles[:12]) + (" 외" if len(vehicles) > 12 else ""),
                f"요약: {r.get('Summary', '')}", f"위험: {r.get('Consequence', '')}", f"조치: {r.get('Remedy', '')}",
                f"원 접수일 표기: {r.get('ReportReceivedDate', '')}"] if x),
            meta={"uid": f"nhtsa:{num}", "campaign": num, "vehicles": vehicles,
                  "manufacturer": r.get("Manufacturer", ""), "component": r.get("Component", "")},
        ))
    return out


def search(makes, years, since, sleep=0.15, log=None):
    rows = []
    for make in makes:
        for year in years:
            try:
                names = models(make, year)
            except Exception as e:  # noqa: BLE001 - 한 브랜드·연식 실패가 전체를 막지 않게
                if log:
                    log(f"[NHTSA] {make} {year} 모델 목록 실패: {e}")
                continue
            for name in names:
                try:
                    rows += recalls_for(make, name, year)
                except Exception as e:  # noqa: BLE001
                    if log:
                        log(f"[NHTSA] {make} {name} {year} 실패: {e}")
                time.sleep(sleep)
    return collect_recalls(rows, since)
