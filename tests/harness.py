"""taxi-log 동기화/세션 버그 검증 하네스.

index.html의 인라인 스크립트를 quickjs(실제 JS 엔진)로 그대로 실행하고,
DOM·네트워크는 최소 스텁으로 바꿔 mergeStates / syncPayload / syncNow를 직접 호출한다.
실행: python3 tests/harness.py
"""
import json
import os
import re
import sys

import quickjs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.environ.get('TAXI_HTML') or os.path.join(ROOT, 'index.html')

src = open(HTML, encoding='utf-8').read()
m = re.search(r'<script>\n(.*)\n</script>', src, re.S)
if not m:
    sys.exit('script block not found')
code = m.group(1)
# 부팅 트리거는 떼어 낸다(테스트에서 직접 호출).
code = code.replace("if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);\nelse boot();", "")

PRELUDE = r"""
var __timers = [];
var setTimeout = function(fn, ms){ var id = __timers.length+1; __timers.push({id:id, fn:fn, ms:ms||0}); return id; };
var clearTimeout = function(id){ for(var i=0;i<__timers.length;i++){ if(__timers[i].id===id) __timers[i].fn=null; } };
var setInterval = function(){ return 0; };
var clearInterval = function(){};
function __runTimers(){ var t = __timers; __timers = []; t.forEach(function(x){ if(x.fn) x.fn(); }); }
var console = {log:function(){}, warn:function(){}, error:function(){}};
var localStorage = {
  _d:{},
  getItem:function(k){ return Object.prototype.hasOwnProperty.call(this._d,k) ? this._d[k] : null; },
  setItem:function(k,v){ this._d[k] = String(v); },
  removeItem:function(k){ delete this._d[k]; }
};
function __el(){ return {
  style:{}, classList:{add:function(){}, remove:function(){}, toggle:function(){}, contains:function(){return false;}},
  appendChild:function(){}, removeChild:function(){}, remove:function(){}, click:function(){},
  addEventListener:function(){}, removeEventListener:function(){},
  setAttribute:function(){}, getAttribute:function(){ return null; }, focus:function(){}, blur:function(){},
  querySelector:function(){ return null; }, querySelectorAll:function(){ return []; },
  closest:function(){ return null; }, insertBefore:function(){}, contains:function(){ return false; },
  textContent:'', innerHTML:'', value:'', files:[], children:[], childNodes:[], dataset:{},
  getBoundingClientRect:function(){ return {top:0,left:0,width:0,height:0,bottom:0,right:0}; },
  getContext:function(){ return null; }
}; }
var __els = {};
var document = {
  readyState:'complete',
  getElementById:function(id){ if(!__els[id]) __els[id] = __el(); return __els[id]; },
  querySelector:function(){ return null; },
  querySelectorAll:function(){ return []; },
  createElement:function(){ return __el(); },
  createTextNode:function(){ return __el(); },
  addEventListener:function(){}, removeEventListener:function(){},
  body:__el(), documentElement:__el(), head:__el(), activeElement:null, visibilityState:'visible',
  execCommand:function(){ return false; }, createRange:function(){ return {selectNodeContents:function(){}, setStart:function(){}, setEnd:function(){}}; }
};
var navigator = { onLine:true, geolocation:null, userAgent:'harness', clipboard:null, serviceWorker:null, language:'ko' };
var location = { protocol:'https:', hostname:'tae2-sudo.github.io', href:'https://tae2-sudo.github.io/taxi-log/?v=7', origin:'https://tae2-sudo.github.io', search:'', hash:'' };
var window = {
  addEventListener:function(){}, removeEventListener:function(){},
  location:location, navigator:navigator, document:document, localStorage:localStorage,
  scrollTo:function(){}, open:function(){ return null; }, matchMedia:function(){ return {matches:false, addEventListener:function(){}}; },
  setTimeout:setTimeout, clearTimeout:clearTimeout, setInterval:setInterval, clearInterval:clearInterval,
  requestAnimationFrame:function(fn){ return 0; }, cancelAnimationFrame:function(){},
  confirm:function(){ return true; }, alert:function(){}, prompt:function(){ return null; },
  innerWidth:400, innerHeight:800, devicePixelRatio:1, google:null, isSecureContext:true
};
var alert = window.alert, confirm = window.confirm, prompt = window.prompt;
var requestAnimationFrame = window.requestAnimationFrame, cancelAnimationFrame = window.cancelAnimationFrame;
var performance = {now:function(){ return Date.now(); }};
var URL = {createObjectURL:function(){ return 'blob:x'; }, revokeObjectURL:function(){}};
var Blob = function(){};
var FileReader = function(){};
var history = {pushState:function(){}, replaceState:function(){}, back:function(){}};
"""

ctx = quickjs.Context()
ctx.eval(PRELUDE)
try:
    ctx.eval(code)
except Exception as e:
    sys.exit('script eval failed: %s' % e)


class Ctx:
    def __init__(self, ctx):
        self.ctx = ctx

    def eval(self, js):
        return self.ctx.eval(js)

    def call(self, expr):
        """expr is a JS expression returning JSON string; returns parsed python object."""
        out = self.ctx.eval("JSON.stringify((function(){" + expr + "})())")
        return json.loads(out)


def drain():
    """async 함수(Promise)의 마이크로태스크를 모두 흘려보낸다."""
    while True:
        try:
            pending = ctx.execute_pending_job()
        except Exception:
            pending = False
        if not pending:
            break


def js_json(obj):
    return json.dumps(obj, ensure_ascii=False)
