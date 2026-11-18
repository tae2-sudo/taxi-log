#!/usr/bin/env python3
"""events.json 요약 출력 — 워크플로 로그·요약용."""
import json
import sys
from datetime import datetime, timedelta, timezone

path = sys.argv[1] if len(sys.argv) > 1 else "events.json"
d = json.load(open(path, encoding="utf-8"))
KST = timezone(timedelta(hours=9))
today = datetime.now(KST).date().isoformat()
events = d.get("events", [])
today_events = [e for e in events if e["start_date"] <= today <= e["end_date"]]

print("갱신 %s | 행사 %d건 | 오늘(%s) %d건" % (d.get("generated_at"), len(events), today, len(today_events)))
for s in d.get("sources", []):
    print("출처 %s %s" % (s.get("name"), "OK" if s.get("ok") else "실패"))
for e in today_events:
    print("  %s~%s | %s | %s | %s" % (e.get("start_time"), e.get("end_est"), e.get("venue"), e.get("title"), e.get("category")))
for e in events:
    if e["start_date"] > today:
        print("  [다음] %s %s~%s | %s | %s" % (e["start_date"], e.get("start_time"), e.get("end_est"), e.get("venue"), e.get("title")))
