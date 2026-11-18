"""spots.html 점수·행사 연동 검증 하네스.

spots.html 인라인 스크립트를 quickjs로 실행하고 DOM·fetch는 스텁으로 바꾼 뒤
- 오류동 기준 각 시간대 TOP3가 5~7km 안쪽인지
- '전체 고수익' 모드가 먼 거점(홍대·강남)을 실제로 끌어오는지
- events.json 자동 행사가 점수와 배지에 반영되는지
를 확인한다.

실행: python3 tests/spots_check.py
"""
import json
import os
import re
import sys

import quickjs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.environ.get("SPOTS_HTML") or os.path.join(ROOT, "spots.html")
src = open(HTML, encoding="utf-8").read()
m = re.search(r"<script>\n(.*)\n</script>", src, re.S)
if not m:
    sys.exit("script block not found")
code = m.group(1)

PRELUDE = r"""
var __timers = [];
var setTimeout = function(fn, ms){ var id = __timers.length+1; __timers.push({id:id, fn:fn, ms:ms||0}); return id; };
var clearTimeout = function(id){ for(var i=0;i<__timers.length;i++){ if(__timers[i].id===id) __timers[i].fn=null; } };
var setInterval = function(){ return 0; };
var clearInterval = function(){};
var console = {log:function(){}, warn:function(){}, error:function(){}};
var localStorage = { _d:{},
  getItem:function(k){ return Object.prototype.hasOwnProperty.call(this._d,k) ? this._d[k] : null; },
  setItem:function(k,v){ this._d[k] = String(v); }, removeItem:function(k){ delete this._d[k]; } };
function __el(){ return {
  style:{}, classList:{add:function(){}, remove:function(){}, toggle:function(){}, contains:function(){return false;}},
  appendChild:function(){}, removeChild:function(){}, remove:function(){}, click:function(){},
  addEventListener:function(){}, removeEventListener:function(){},
  setAttribute:function(){}, getAttribute:function(){ return null; }, focus:function(){}, blur:function(){},
  querySelector:function(){ return null; }, querySelectorAll:function(){ return []; },
  closest:function(){ return null; }, insertBefore:function(){}, contains:function(){ return false; },
  textContent:'', innerHTML:'', value:'', files:[], children:[], childNodes:[], dataset:{},
  getBoundingClientRect:function(){ return {top:0,left:0,width:0,height:0,bottom:0,right:0}; },
  getContext:function(){ return null; } }; }
var __els = {};
var document = {
  readyState:'complete',
  getElementById:function(id){ if(!__els[id]) __els[id] = __el(); return __els[id]; },
  querySelector:function(){ return null; }, querySelectorAll:function(){ return []; },
  createElement:function(){ return __el(); }, createTextNode:function(){ return __el(); },
  addEventListener:function(){}, removeEventListener:function(){},
  body:__el(), documentElement:__el(), head:__el(), activeElement:null, visibilityState:'visible',
  execCommand:function(){ return false; } };
var navigator = { onLine:true, geolocation:null, userAgent:'harness', language:'ko' };
var location = { protocol:'https:', hostname:'tae2-sudo.github.io', href:'https://tae2-sudo.github.io/taxi-log/spots.html', origin:'https://tae2-sudo.github.io', search:'', hash:'' };
var window = {
  addEventListener:function(){}, removeEventListener:function(){},
  location:location, navigator:navigator, document:document, localStorage:localStorage,
  scrollTo:function(){}, open:function(){ return null; },
  setTimeout:setTimeout, clearTimeout:clearTimeout, setInterval:setInterval, clearInterval:clearInterval,
  requestAnimationFrame:function(){ return 0; }, cancelAnimationFrame:function(){},
  innerWidth:400, innerHeight:800, devicePixelRatio:1, isSecureContext:true };
var alert = function(){}, confirm = function(){ return true; };
var performance = {now:function(){ return Date.now(); }};
var AbortController = function(){ this.signal = null; this.abort = function(){}; };
var __EVENTS_JSON = null;
var fetch = function(url){
  return Promise.resolve({
    ok:true,
    json:function(){
      if(String(url).indexOf('events.json') >= 0){ return Promise.resolve(__EVENTS_JSON || {generated_at:'2026-11-19T06:00:00+09:00', events:[]}); }
      return Promise.resolve({current:{temperature_2m:5, apparent_temperature:3, weather_code:0, wind_speed_10m:5, precipitation:0, rain:0, snowfall:0}, hourly:{time:[], precipitation_probability:[]}});
    }
  });
};
"""

ctx = quickjs.Context()
ctx.eval(PRELUDE)
try:
    ctx.eval(code)
except Exception as e:
    sys.exit("script eval failed: %s" % e)


def call(expr):
    out = ctx.eval("JSON.stringify((function(){" + expr + "})())")
    return json.loads(out)


def drain():
    while True:
        try:
            pending = ctx.execute_pending_job()
        except Exception:
            pending = False
        if not pending:
            break


AIRPORT = {"김포공항", "명동·을지로입구", "서울역"}

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def top3(slot, mode):
    return call(
        'var a=computeAll("%s","%s").slice(0,3); return a.map(function(r){'
        'return {n:r.sp.n,km:Math.round(r.km*10)/10,score:r.score,eta:r.eta};});' % (slot, mode)
    )


def base_center():
    return call('return [S.base.lat,S.base.ln];')


print("기준 위치:", call('return S.base.name'))
for slot, label in [("dawn", "새벽 4~6시"), ("am", "출근 6:30~9:30"), ("day", "낮"),
                    ("pm", "퇴근 17~21시"), ("night", "밤 21~23시"), ("late", "심야 23~2시"),
                    ("deep", "새벽 2~4시")]:
    near = top3(slot, "near")
    yld = top3(slot, "yield")
    near_txt = ", ".join("%s %.1fkm(%d)" % (r["n"], r["km"], r["score"]) for r in near)
    yld_txt = ", ".join("%s %.1fkm(%d)" % (r["n"], r["km"], r["score"]) for r in yld)
    print("[%s] near: %s" % (label, near_txt))
    print("        yield: %s" % yld_txt)
    check(all(r["km"] <= 7.6 for r in near if r["n"] not in AIRPORT) , "%s 가까운 순 TOP3 모두 7.5km 이내(공항 제외)" % label)
    check(all(r["km"] <= 9.0 for r in near), "%s 가까운 순 TOP3 모두 9km 이내" % label)
    check(max(r["km"] for r in yld) >= max(r["km"] for r in near), "%s 전체 고수익은 가까운 순보다 먼 곳까지 본다" % label)

# 오늘 08시대(am)는 오류동 인근 구로·가산·신도림 계열이어야 한다
names_am = [r["n"] for r in top3("am", "near")]
check(any(n in names_am for n in ["구로디지털단지", "가산디지털단지", "신도림", "개봉·고척"]),
      "출근 시간대 TOP3에 서남권 근거리 거점 포함: %s" % names_am)

# 심야 가까운 순: 홍대가 TOP3에 없어야 함(집에서 바로 홍대는 손해라는 피드백)
late_near = [r["n"] for r in top3("late", "near")]
late_yield = [r["n"] for r in top3("late", "yield")]
check("홍대입구" not in late_near, "심야 가까운 순 TOP3에 홍대 없음: %s" % late_near)
check("홍대입구" in late_yield or "강남역" in late_yield, "심야 전체 고수익에는 홍대/강남 등장: %s" % late_yield)

# 자동 연동 행사가 점수·배지에 반영되는지
ctx.eval("""__EVENTS_JSON = {generated_at:"2026-11-19T06:00:00+09:00", events:[
 {"id":"t1","title":"테스트 콘서트","venue":"KSPO DOME","spot":"olympicpark","start_date":"2026-11-19","end_date":"2026-11-19","start_time":"19:30","end_est":"22:00","category":"콘서트","source":"Spotts"},
 {"id":"t2","title":"내일 경기","venue":"잠실","spot":"jamsil","start_date":"2026-11-20","end_date":"2026-11-20","start_time":"18:30","end_est":"21:45","category":"스포츠","source":"네이버 스포츠"}]};""")
ctx.eval("S.autoMeta=null; S.autoOff=[]; loadEvents();")
drain()
check(call('return S.auto.events.length') == 2, "events.json 2건 로드")
check(call('return autoToday().length') == 1, "오늘 행사 1건 분류")
check(call('return autoTomorrow().length') == 1, "내일 행사 1건 분류")
check(call('return spotHasEvent(SPOTS.filter(function(s){return s.id==="olympicpark";})[0])') is True,
      "KSPO DOME 행사가 올림픽공원 스팟 점수에 반영")
check(call('return spotHasEvent(SPOTS.filter(function(s){return s.id==="jamsil";})[0])') is False,
      "내일 행사는 오늘 점수에 넣지 않음")
# 체크 해제하면 빠져야 한다
ctx.eval('toggleAuto("t1")')
check(call('return spotHasEvent(SPOTS.filter(function(s){return s.id==="olympicpark";})[0])') is False,
      "행사 체크를 끄면 점수에서 빠짐")
ctx.eval('toggleAuto("t1")')

# 렌더링이 예외 없이 끝나는지
try:
    ctx.eval("renderAll(); renderList(); renderEvents(); renderBrief();")
    ok = True
except Exception as e:
    ok = False
    print("   render error:", e)
check(ok, "전체 렌더링 예외 없음")

print()
if fails:
    print("실패 %d건" % len(fails))
    sys.exit(1)
print("모든 검사 통과")
