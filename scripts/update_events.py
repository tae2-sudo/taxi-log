#!/usr/bin/env python3
"""서울 주요 공연장·경기장의 오늘/내일 행사 일정을 모아 events.json 을 만든다.

- 유료 API 키 없이 동작한다. 표준 라이브러리만 사용.
- 출처 1: Spotts(spotts.kr) 공연장별 일정 페이지 — 콘서트·뮤지컬·클래식 등
- 출처 2: 네이버 스포츠 일정 API — KBO·K리그·KBL·V리그 (서울 구장만)
- 출처가 하나 실패해도 나머지로 파일을 채운다. 전부 실패하면 기존 events.json 을
  건드리지 않고 종료 코드 1로 끝나 워크플로가 실패를 표시한다(직전 데이터 보존).

사용: python3 scripts/update_events.py [--days 3] [--out events.json] [--check]
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

KST = timezone(timedelta(hours=9))
UA = "taxi-log-events/1.0 (+https://github.com/tae2-sudo/taxi-log; personal driver dashboard)"

# 공연장 페이지 → 스팟 id (spots.html 의 SPOTS id)
VENUES = [
    # slug, 표시 이름, 스팟 id
    ("kspo-dome", "KSPO DOME", "olympicpark"),
    ("olympic-hall", "올림픽공원 올림픽홀", "olympicpark"),
    ("gocheok-sky-dome", "고척스카이돔", "gaebong"),
    ("jamsil-students-gymnasium", "잠실학생체육관", "jamsil"),
    ("jangchung-arena", "장충체육관", "ddp"),
    ("coex-artium", "코엑스아티움", "samseong"),
    ("sejong-center", "세종문화회관", "gwanghwamun"),
    ("seoul-arts-center", "예술의전당", "gyodae"),
    ("blue-square", "블루스퀘어", "itaewon"),
    ("yes24-live-hall", "예스24라이브홀", "kondae"),
    ("mapo-art-center", "마포아트센터", "gongdeok"),
    ("sungam-art-hall", "성암아트홀", "seongsu"),
]

# 네이버 스포츠 경기장 이름 → 스팟 id
STADIUMS = [
    ("잠실학생", "jamsil"),
    ("잠실실내", "jamsil"),
    ("잠실", "jamsil"),
    ("고척", "gaebong"),
    ("목동", "mokdong"),
    ("장충", "ddp"),
    ("상암", "worldcup"),
    ("올림픽공원", "olympicpark"),
]

# 종목별 기본 시작·소요 시간(분) — 공연 시간이 안 적혀 있을 때 추정에 쓴다
CATEGORY_DEFAULT = {
    "콘서트": (19 * 60 + 30, 150),
    "클래식": (19 * 60 + 30, 120),
    "뮤지컬": (19 * 60 + 30, 165),
    "연극": (19 * 60 + 30, 120),
    "무용": (19 * 60 + 30, 120),
    "국악": (19 * 60 + 30, 110),
    "전시": (10 * 60, 480),
    "축제": (12 * 60, 540),
    "페스티벌": (12 * 60, 540),
    "공연": (19 * 60 + 30, 140),
    "스포츠": (18 * 60 + 30, 150),
}
SPORT_MINUTES = {"kbo": 195, "kleague": 120, "kbl": 130, "vleague": 130}

NAVER_SERIES = [
    ("kbaseball", "kbo"),
    ("football", "kleague"),
    ("basketball", "kbl"),
    ("volleyball", "vleague"),
]


def log(msg):
    print(msg, flush=True)


def fetch(url, retries=2, timeout=25):
    last = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
            })
            with urlopen(req, timeout=timeout) as r:
                raw = r.read()
                charset = r.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, "replace")
        except (HTTPError, URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < retries:
                time.sleep(2 + attempt * 3)
    raise last


def text_of(html_fragment):
    s = re.sub(r"<[^>]+>", "", html_fragment)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- Spotts
def parse_spotts_page(html, venue_name, spot_id, slug):
    """공연장 페이지의 <article> 목록에서 행사 정보를 뽑는다."""
    out = []
    for block in re.split(r"<article[^>]*>", html)[1:]:
        block = block.split("</article>")[0]
        m = re.search(r'<h3[^>]*>\s*<a[^>]*href="(/f/[^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        href, title = m.group(1), text_of(m.group(2))
        fields = {}
        for dt, dd in re.findall(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", block, re.S):
            fields[text_of(dt)] = text_of(dd)
        period = fields.get("행사 기간", "")
        dates = re.findall(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.", period)
        if not dates:
            continue
        start = "%s-%02d-%02d" % (dates[0][0], int(dates[0][1]), int(dates[0][2]))
        end = "%s-%02d-%02d" % (dates[-1][0], int(dates[-1][1]), int(dates[-1][2]))
        cat_m = re.search(r'<p class="s2ne5ob[^"]*"[^>]*>(.*?)</p>', block, re.S)
        category = text_of(cat_m.group(1)) if cat_m else "공연"
        desc_m = re.search(r'<p class="s2ne5on[^"]*"[^>]*>(.*?)</p>', block, re.S)
        desc = text_of(desc_m.group(1)) if desc_m else ""
        place = fields.get("행사 장소") or venue_name
        place = place.split(",")[0].strip()
        out.append({
            "id": "spotts:" + href.split("/f/")[-1],
            "source": "Spotts",
            "venue_key": slug,
            "venue": place,
            "spot": spot_id,
            "title": title,
            "category": category,
            "start_date": start,
            "end_date": end,
            "hint": desc,
            "url": "https://spotts.kr" + href,
        })
    return out


def parse_ld_event(html):
    """상세 페이지의 JSON-LD Event 에서 시작·종료 시각, 장소, 예매 링크를 뽑는다."""
    out = {}
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except Exception:
            continue
        nodes = data.get("@graph") if isinstance(data, dict) and "@graph" in data else [data]
        for node in nodes or []:
            if not isinstance(node, dict) or node.get("@type") != "Event":
                continue
            out["ld_start"] = node.get("startDate") or ""
            out["ld_end"] = node.get("endDate") or ""
            loc = node.get("location") or {}
            if isinstance(loc, dict):
                out["ld_place"] = loc.get("name") or ""
                geo = loc.get("geo") or {}
                if geo.get("latitude") and geo.get("longitude"):
                    out["geo"] = [round(float(geo["latitude"]), 5), round(float(geo["longitude"]), 5)]
            offers = node.get("offers") or {}
            if isinstance(offers, dict) and offers.get("url"):
                out["ticket"] = offers["url"]
            return out
    return out


def hhmm_from_iso(iso):
    m = re.match(r"\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})", iso or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h == 0 and mi == 0:          # 날짜만 있는(종일) 일정
        return None
    return "%02d:%02d" % (h, mi)


def duration_ok(st, en):
    """시작·종료 시각 차이가 공연 길이로 말이 되는지(75분~5시간) 확인."""
    a = int(st[:2]) * 60 + int(st[3:])
    b = int(en[:2]) * 60 + int(en[3:])
    d = b - a if b >= a else b + 1440 - a
    return 75 <= d <= 300


def enrich_spotts(events):
    """행사별 상세 페이지에서 실제 공연 시각·장소·예매 링크를 채운다."""
    for e in events:
        try:
            html = fetch(e["url"])
            info = parse_ld_event(html)
            st, en = hhmm_from_iso(info.get("ld_start")), hhmm_from_iso(info.get("ld_end"))
            if st:
                e["start_time"] = st
                e["time_exact"] = True
            if en and st and duration_ok(st, en):
                e["end_est"] = en
                e["time_exact"] = True
            if info.get("ld_place"):
                e["venue"] = info["ld_place"].split(",")[0].strip()
            if info.get("geo"):
                e["geo"] = info["geo"]
            if info.get("ticket"):
                e["ticket"] = info["ticket"]
        except Exception as ex:  # noqa: BLE001
            log("    상세 실패 %s: %s" % (e["title"][:24], ex))
        time.sleep(0.4)


def collect_spotts(today, horizon):
    events, sources = [], []
    ok = 0
    for slug, name, spot_id in VENUES:
        url = "https://spotts.kr/festivals/venue/%s" % quote(slug)
        try:
            html = fetch(url)
            items = parse_spotts_page(html, name, spot_id, slug)
            # 오늘~horizon 사이에 걸치는 것만 남긴다
            items = [e for e in items if e["start_date"] <= horizon.isoformat() and e["end_date"] >= today.isoformat()]
            enrich_spotts(items)          # 실제 공연 시각·예매 링크
            events.extend(items)
            ok += 1
            log("  %-28s %s → %d건" % (name, "OK", len(items)))
        except Exception as e:  # noqa: BLE001
            log("  %-28s 실패: %s" % (name, e))
        time.sleep(0.6)
    sources.append({"name": "Spotts", "ok": ok > 0, "venues": ok, "note": "" if ok else "공연장 페이지 응답 없음"})
    return events, sources


# ------------------------------------------------------- 네이버 스포츠
def collect_naver_sports(today, horizon):
    events, sources = [], []
    got = 0
    for upper, lower in NAVER_SERIES:
        url = ("https://api-gw.sports.naver.com/schedule/games?fields=basic,schedule"
               "&upperCategoryId=%s&categoryId=%s&fromDate=%s&toDate=%s"
               % (upper, lower, today.isoformat(), horizon.isoformat()))
        try:
            data = json.loads(fetch(url, retries=1, timeout=12))
            games = (data.get("result") or {}).get("games") or []
            got += 1
        except Exception as e:  # noqa: BLE001
            log("  %-10s 실패: %s" % (lower, e))
            continue
        kept = 0
        for g in games:
            stadium = (g.get("stadium") or "").strip()
            spot_id = None
            for key, sid in STADIUMS:
                if key in stadium:
                    spot_id = sid
                    break
            if not spot_id or g.get("cancel"):
                continue
            dt = g.get("gameDateTime") or ""
            m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", dt)
            if not m:
                continue
            day = m.group(1)
            start_min = int(m.group(2)) * 60 + int(m.group(3))
            dur = SPORT_MINUTES.get(lower, 150)
            home, away = g.get("homeTeamName") or "", g.get("awayTeamName") or ""
            events.append({
                "id": "naver:%s" % g.get("gameId"),
                "source": "네이버 스포츠",
                "venue_key": stadium,
                "venue": stadium,
                "spot": spot_id,
                "title": "%s vs %s" % (home, away),
                "category": "스포츠",
                "start_date": day,
                "end_date": day,
                "start_time": "%02d:%02d" % (start_min // 60, start_min % 60),
                "end_est": "%02d:%02d" % (((start_min + dur) // 60) % 24, (start_min + dur) % 60),
                "hint": g.get("categoryName") or "",
                "url": "https://sports.naver.com",
            })
            kept += 1
        log("  %-10s %s → %d경기(서울)" % (lower, "OK", kept))
    sources.append({"name": "네이버 스포츠", "ok": got > 0, "series": got, "note": "" if got else "일정 API 응답 없음"})
    return events, sources


# ------------------------------------------------------------- 시간 추정
def add_times(events):
    for e in events:
        if e.get("start_time"):
            if not e.get("end_est"):
                e["end_est"] = guess_end(e["start_time"], e.get("category"))
            continue
        start_min = None
        text = (e.get("title", "") + " " + e.get("hint", ""))
        # "오후 8시", "오후 7시 30분", "20:00"
        for ampm, hh, mm in re.findall(r"(오전|오후)\s*(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?", text):
            h = int(hh) % 12
            if ampm == "오후":
                h += 12
            start_min = h * 60 + int(mm or 0)
            break
        if start_min is None:
            for hh, mm in re.findall(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text):
                start_min = int(hh) * 60 + int(mm)
                break
        default = CATEGORY_DEFAULT.get(e.get("category", ""), CATEGORY_DEFAULT["공연"])
        if start_min is None:
            start_min = default[0]
        e["start_time"] = "%02d:%02d" % (start_min // 60, start_min % 60)
        e["end_est"] = guess_end(e["start_time"], e.get("category"), default[1])


def guess_end(start_time, category, duration=None):
    hh, mm = start_time.split(":")
    total = int(hh) * 60 + int(mm)
    dur = duration or CATEGORY_DEFAULT.get(category or "", CATEGORY_DEFAULT["공연"])[1]
    return "%02d:%02d" % (((total + dur) // 60) % 24, (total + dur) % 60)


def dedupe(events):
    seen, out = set(), []
    for e in events:
        key = (unicodedata.normalize("NFC", e["title"]).lower(), e["start_date"], e["venue"])
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    out.sort(key=lambda e: (e["start_date"], e.get("start_time", ""), e["title"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="오늘부터 며칠 뒤까지 담을지")
    ap.add_argument("--out", default="events.json")
    ap.add_argument("--check", action="store_true", help="기존 events.json 검사만")
    ap.add_argument("--only", choices=["all", "spotts", "sports"], default="all")
    args = ap.parse_args()

    now = datetime.now(KST)
    today = now.date()
    horizon = today + timedelta(days=max(1, args.days) - 1)

    if args.check:
        return check(args.out)

    log("[events] %s KST 기준 %s ~ %s 수집" % (now.strftime("%Y-%m-%d %H:%M"), today, horizon))
    perf, src1, games, src2 = [], [], [], []
    if args.only in ("all", "spotts"):
        log("- Spotts 공연장 일정")
        perf, src1 = collect_spotts(today, horizon)
    if args.only in ("all", "sports"):
        log("- 네이버 스포츠")
        games, src2 = collect_naver_sports(today, horizon)

    events = dedupe(perf + games)
    add_times(events)
    for e in events:
        if len(e.get("hint", "")) > 90:
            e["hint"] = e["hint"][:88] + "…"

    ok_sources = [s for s in (src1 + src2) if s["ok"]]
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "window": {"from": today.isoformat(), "to": horizon.isoformat()},
        "sources": src1 + src2,
        "counts": {"events": len(events), "performances": len(perf), "games": len(games)},
        "events": events,
    }

    if not ok_sources:
        log("[events] 모든 출처 실패 — 기존 %s 를 유지합니다" % args.out)
        return 1
    if not events:
        log("[events] 경고: 출처는 응답했지만 창(%s~%s) 안에 행사가 0건입니다" % (today, horizon))

    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, args.out)
    log("[events] 저장: %s (행사 %d건, 출처 %d/%d)" % (args.out, len(events), len(ok_sources), len(src1 + src2)))
    for e in events[:12]:
        log("   %s %s~%s %s · %s · %s" % (e["start_date"], e.get("start_time"), e.get("end_est"),
                                          e["venue"], e["title"], e["category"]))
    return 0


def check(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    assert d.get("events") is not None, "events 키 없음"
    assert d.get("generated_at"), "generated_at 없음"
    for e in d["events"]:
        for k in ("id", "title", "venue", "spot", "start_date", "end_date"):
            assert e.get(k), "필드 누락: %s (%s)" % (k, e.get("id"))
    log("[events] 검사 통과: %s, 행사 %d건, 갱신 %s" % (path, len(d["events"]), d["generated_at"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
