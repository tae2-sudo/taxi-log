"""night.html 검증 하네스 (화장실 카테고리·필터·내 등록·확장 데이터 병합).

night.html 인라인 스크립트를 quickjs로 실행하고 DOM·fetch를 스텁으로 바꾼 뒤
 - 스크립트가 예외 없이 부팅되는지
 - 카테고리 칩(전체/빌딩·상가/공중/주유·충전소/즐겨찾기) 분류가 맞는지
 - 🟢 지금 열림 / 🌙 24시간 상시 필터가 openState와 일치하는지
 - 내 화장실 등록·삭제가 목록·지도 데이터에 반영되는지
 - toilets-extra.json 병합 후 50m 중복이 남지 않는지
를 확인한다.

실행: python3 tests/night_check.py
"""
import json
import os
import re
import sys

import quickjs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.environ.get("NIGHT_HTML") or os.path.join(ROOT, "night.html")
EXTRA = os.environ.get("NIGHT_EXTRA") or os.path.join(ROOT, "toilets-extra.json")

src = open(HTML, encoding="utf-8").read()
m = re.search(r"<script>\n(.*)\n</script>", src, re.S)
if not m:
    sys.exit("script block not found")
code = m.group(1)
extra_json = open(EXTRA, encoding="utf-8").read()

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
function __el(){
  var self = {
  style:{}, classList:{_s:{}, add:function(c){this._s[c]=1;}, remove:function(c){delete this._s[c];},
    toggle:function(c,v){ if(v===undefined) v=!this._s[c]; if(v) this._s[c]=1; else delete this._s[c]; return !!this._s[c]; },
    contains:function(c){ return !!this._s[c]; }},
  appendChild:function(){}, removeChild:function(){}, remove:function(){}, click:function(){},
  addEventListener:function(){}, removeEventListener:function(){},
  setAttribute:function(k,v){ this['_attr_'+k]=v; }, getAttribute:function(k){ return this['_attr_'+k]||null; },
  focus:function(){}, blur:function(){},
  querySelector:function(){ return null; }, querySelectorAll:function(){ return []; },
  closest:function(){ return null; }, insertAdjacentHTML:function(){}, insertBefore:function(){}, contains:function(){ return false; },
  textContent:'', innerHTML:'', value:'', files:[], children:[], childNodes:[], dataset:{},
  getBoundingClientRect:function(){ return {top:0,left:0,width:0,height:0,bottom:0,right:0}; },
  getContext:function(){ return null; } };
  return self;
}
var __els = {};
function __chip(cat){ var e=__el(); e['_attr_data-cat']=cat; return e; }
var __chips = [__chip('all'), __chip('building'), __chip('public'), __chip('gas')];
var document = {
  readyState:'complete',
  getElementById:function(id){ if(!__els[id]) __els[id] = __el(); return __els[id]; },
  querySelector:function(sel){ if(sel && sel.indexOf('chip[data-cat="all"]')>=0) return __chips[0]; return null; },
  querySelectorAll:function(sel){ if(sel && sel.indexOf('.chip[data-cat]')>=0) return __chips; return []; },
  createElement:function(){ return __el(); }, createTextNode:function(){ return __el(); },
  addEventListener:function(){}, removeEventListener:function(){},
  body:__el(), documentElement:__el(), head:__el(), activeElement:null, visibilityState:'visible', hidden:false,
  execCommand:function(){ return false; } };
var navigator = { onLine:true, geolocation:null, userAgent:'harness', language:'ko' };
var location = { protocol:'https:', hostname:'tae2-sudo.github.io', href:'https://tae2-sudo.github.io/taxi-log/night.html', origin:'https://tae2-sudo.github.io', search:'', hash:'' };
var window = {
  addEventListener:function(){}, removeEventListener:function(){},
  location:location, navigator:navigator, document:document, localStorage:localStorage,
  scrollTo:function(){}, open:function(){ return null; },
  setTimeout:setTimeout, clearTimeout:clearTimeout, setInterval:setInterval, clearInterval:clearInterval,
  requestAnimationFrame:function(){ return 0; }, cancelAnimationFrame:function(){},
  innerWidth:400, innerHeight:800, devicePixelRatio:1, isSecureContext:true };
var alert = function(){}, confirm = function(){ return true; };
var performance = {now:function(){ return Date.now(); }};
var __EXTRA = __EXTRA_JSON__;
var fetch = function(url){
  if(String(url).indexOf('toilets-extra.json') >= 0){
    return Promise.resolve({ ok:true, json:function(){ return Promise.resolve(__EXTRA); } });
  }
  return Promise.resolve({ ok:false, status:404, json:function(){ return Promise.resolve({}); } });
};
"""

ctx = quickjs.Context()
ctx.eval(PRELUDE.replace("__EXTRA_JSON__", extra_json))
try:
    ctx.eval(code)
except Exception as e:
    sys.exit("script eval failed: %s" % e)


def drain():
    while True:
        try:
            pending = ctx.execute_pending_job()
        except Exception:
            pending = False
        if not pending:
            break


drain()


def call(expr):
    out = ctx.eval("JSON.stringify((function(){" + expr + "})())")
    return json.loads(out)


fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


print("== 부팅")
check(call("return window.__NIGHT_READY === true") is True, "boot 완료(__NIGHT_READY)")
base = call("return ROWS.length")
added = call("return EXTRA.rows.length")
alln = call("return ALL.length")
check(base == 4507, "서울 원본 4,507곳 유지 (실제 %d)" % base)
check(added > 5000, "확장 데이터 병합 %d곳" % added)
check(base + added - 800 <= alln <= base + added, "ALL = 서울+확장 (50m 중복 제거 후 %d곳)" % alln)
check(call("return EXTRA.state") == "ok", "toilets-extra.json fetch 성공")

print("== 카테고리 분류")
cats = call("var c={building:0,public:0,gas:0,mine:0}; for(var i=0;i<ALL.length;i++){c[catOf(ALL[i])]++;} return c;")
check(cats["building"] > 2000, "빌딩·상가 %d곳" % cats["building"])
check(cats["public"] > 5000, "공중 %d곳" % cats["public"])
check(cats["gas"] > 500, "주유·충전소 %d곳" % cats["gas"])
check(call("return catOf([37.5,127.0,'x','', '', '', 2, '', 0, ''])") == "building", "업무시설(site 2) → 빌딩·상가")
check(call("return catOf([37.5,127.0,'x','', '', '', 16, '', 0, ''])") == "building", "개방화장실(site 16) → 빌딩·상가")
check(call("return catOf([37.5,127.0,'x','', '', '', 6, '', 0, ''])") == "public", "공중화장실(site 6) → 공중")
check(call("return catOf([37.5,127.0,'x','', '', '', 4, '', 256, ''])") == "gas", "주유소(flags GAS) → 주유·충전소")

print("== 시간 필터")
check(call("return openState('24시간')") is True, "openState('24시간') = 열림")
check(call("return openState('영업시작~종료')") is None, "openState('영업시작~종료') = 미상")
check(call("return openState('정시')") is None, "openState('정시') = 미상")
check(call("return openState('22:00~06:00')") is not None, "openState('22:00~06:00') 자정 넘김 처리")
ctx.eval("S.cat='all'; S.nowOpen=true; S.only24=false; S.favOnly=false; S.q='';")
bad_open = call("var b=0; for(var i=0;i<VIEW.length;i++){ if(!isOpenNow(VIEW[i])) b++; } return b;")
ctx.eval("render();")
bad_open = call("var b=0; for(var i=0;i<VIEW.length;i++){ if(!isOpenNow(VIEW[i])) b++; } return b;")
check(bad_open == 0, "🟢 지금 열림 필터 결과는 모두 지금 열림")
ctx.eval("S.only24=true; render();")
bad24 = call("var b=0; for(var i=0;i<VIEW.length;i++){ if(VIEW[i][7] !== '24시간') b++; } return b;")
check(bad24 == 0, "🌙 24시간 상시만 필터 결과는 모두 24시간")
check(call("return VIEW.length") > 100, "24시간 상시 %d곳" % call("return VIEW.length"))
ctx.eval("S.only24=false; S.nowOpen=false; render();")

print("== 내 화장실 등록·삭제")
ctx.eval("S.cat='mine'; S.pos=null; S.q=''; render();")
before = call("return VIEW.length")
ctx.eval("""MINE.unshift({id:'mtest1', name:'테스트빌딩 2층', lat:37.4955, lng:126.8455,
  hours:'24시간', floor:'2층 계단 옆', pw:'1234*', ts:1}); saveMine(); refresh(); render();""")
after = call("return VIEW.length")
check(after == before + 1, "내 등록 추가 시 ⭐ 목록에 1곳 증가 (%d→%d)" % (before, after))
check(call("return mineOf(VIEW[0]) ? mineOf(VIEW[0]).pw : ''") == "1234*", "내 등록 카드에 비밀번호 메모 유지")
check(call("return localStorage.getItem('night.mine.v1').indexOf('테스트빌딩') >= 0") is True, "localStorage에 저장")
ctx.eval("delMine('mtest1'); render();")
check(call("return VIEW.length") == before, "삭제 시 목록에서 제거")
ctx.eval("S.cat='all';")

print("== 50m 중복 / 좌표 검증")
dup = call("""var h=haversine, n=0, g={};
for(var i=0;i<ALL.length;i++){ var r=ALL[i];
  var cx=Math.floor(r[0]*2000), cy=Math.floor(r[1]*2000), found=false;
  for(var dx=-1;dx<=1&&!found;dx++) for(var dy=-1;dy<=1&&!found;dy++){
    var cell=g[(cx+dx)+'_'+(cy+dy)]||[];
    for(var j=0;j<cell.length;j++){ if(h({lat:r[0],lng:r[1]},{lat:cell[j][0],lng:cell[j][1]})<50){ found=true; n++; break; } }
  }
  var k=cx+'_'+cy; (g[k]||(g[k]=[])).push(r);
}
return n;""")
check(dup == 0, "ALL 안에 50m 이내 중복 없음 (%d건)" % dup)
bad = call("var n=0; for(var i=0;i<ALL.length;i++){ var r=ALL[i]; if(!(isFinite(r[0])&&isFinite(r[1])&&r[0]>33&&r[0]<39.5&&r[1]>124&&r[1]<131)) n++; } return n;")
check(bad == 0, "좌표 범위(위경도) 이상값 없음 (%d건)" % bad)
nocoord = call("var n=0; for(var i=0;i<ALL.length;i++){ if(ALL[i][0]===0||ALL[i][1]===0) n++; } return n;")
check(nocoord == 0, "0,0 좌표 없음")

print("== 렌더링")
ctx.eval("S.nowOpen=true; S.cat='all'; render();")
html = ctx.eval("document.getElementById('list').innerHTML")
check(isinstance(html, str) and "article class=\"card" in html, "카드 렌더링")
check("badges" in html and "내 화장실" not in html, "배지 렌더링")
check(call("return document.getElementById('status').innerHTML.indexOf('곳') >= 0") is True, "상태줄 표시")
ctx.eval("S.cat='gas'; render();")
check(call("return VIEW.length") > 0, "주유·충전소 칩 결과 있음")
ctx.eval("S.cat='building'; render();")
check(call("return VIEW.length") > 0, "빌딩·상가 칩 결과 있음")
ctx.eval("S.cat='public'; render();")
check(call("return VIEW.length") > 0, "공중 칩 결과 있음")

print("== 주변 실시간 검색 링크")
links = call("return nearLinks().map(function(l){return l.u;})")
check(any("kakao.com/link/search" in u for u in links), "카카오맵 검색 링크")
check(any("naver.com/p/search" in u for u in links), "네이버지도 검색 링크")
check(any("google.com/maps/search" in u for u in links), "구글 지도 검색 링크")

print()
if fails:
    print("실패 %d건" % len(fails))
    sys.exit(1)
print("모든 검사 통과")
