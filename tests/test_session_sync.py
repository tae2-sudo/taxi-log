"""세션/동기화 버그 수정 검증 — Case A~D + 회귀 확인.

index.html 인라인 스크립트를 quickjs로 실행하고, 구글 드라이브 통신만 스텁으로 바꿔
syncNow()/mergeStates()/syncPayload()의 실제 코드 경로를 그대로 통과시킨다.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

ctx = h.ctx
results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  · ' + str(detail)) if detail else ''))


MOCK = r"""
var uploadedPayloads = [];
var remoteDoc = null;
ensureToken = function(){ accessToken = 'TESTTOKEN'; tokenExp = Date.now() + 3600000; return accessToken; };
findSyncFile = function(){ return remoteDoc ? {id:'file1'} : null; };
downloadSyncFile = function(){ return JSON.parse(JSON.stringify(remoteDoc)); };
uploadSync = function(payload, fileId){
  uploadedPayloads.push(JSON.parse(JSON.stringify(payload)));
  remoteDoc = JSON.parse(JSON.stringify(payload));
  return {id:'file1'};
};
syncMeta = {email:'test@example.com', lastSyncAt:0, fileId:''};
syncing = false;
function resetCase(){
  uploadedPayloads = [];
  remoteDoc = null;
  state = defaultState();
  syncMeta = {email:'test@example.com', lastSyncAt:0, fileId:''};
  syncing = false;
}
"""

ctx.eval(MOCK)


def run_sync():
    ctx.eval('syncNow({silent:true})')
    h.drain()
    # 타이머로 예약된 자동 동기화까지 흘려보낸다.
    for _ in range(5):
        try:
            ctx.eval('__runTimers()')
            h.drain()
        except Exception:
            pass


def j(expr):
    return ctx.eval('JSON.stringify(' + expr + ')')


# ---------------------------------------------------------------- Case A
ctx.eval('resetCase()')
ctx.eval("""
state = normalizeState({
  settings:{}, settingsUpdated: 1,
  days:{'2026-11-19': {u: 1000, runs:[{s:'2026-11-19T04:00', e:''}]}},
  session:{start:'2026-11-19T04:00', dayKey:'2026-11-19'}
});
""")
a_payload = h.json.loads(ctx.eval("""JSON.stringify((function(){
  var p = syncPayload(state);
  return {hasSession: !!p.session, start: p.session && p.session.start, dayKey: p.session && p.session.dayKey};
})())"""))
check('A-1 syncPayload(state)에 session 포함', a_payload['hasSession'] and a_payload['start'] == '2026-11-19T04:00', a_payload)

run_sync()
a_up = h.json.loads(ctx.eval("""JSON.stringify({
  count: uploadedPayloads.length,
  hasSession: !!(uploadedPayloads[0] && uploadedPayloads[0].session),
  start: uploadedPayloads[0] && uploadedPayloads[0].session && uploadedPayloads[0].session.start,
  runKept: !!(uploadedPayloads[0] && uploadedPayloads[0].days['2026-11-19'] &&
              uploadedPayloads[0].days['2026-11-19'].runs[0] &&
              uploadedPayloads[0].days['2026-11-19'].runs[0].s === '2026-11-19T04:00' &&
              !uploadedPayloads[0].days['2026-11-19'].runs[0].e)
})"""))
check('A-2 START 상태에서 syncNow가 올린 페이로드에 session·미종료 run 포함',
      a_up['count'] == 1 and a_up['hasSession'] and a_up['start'] == '2026-11-19T04:00' and a_up['runKept'], a_up)

# ---------------------------------------------------------------- Case B
ctx.eval('resetCase()')
ctx.eval("""
remoteDoc = {
  version:1, appVersion:'1.0', settings:{}, settingsUpdated: 0,
  days:{'2026-11-19': {u: 5000, runs:[{s:'2026-11-19T04:00', e:''}]}},
  deleted:{}, meta:{created: 1},
  session:{start:'2026-11-19T04:00', dayKey:'2026-11-19'}
};
state = defaultState();   /* 새 브라우저 / 재로그인: 로컬에 아무 기록 없음 */
""")
run_sync()
b = h.json.loads(ctx.eval("""JSON.stringify({
  session: state.session && state.session.start,
  dayKey: state.session && state.session.dayKey,
  runOpen: !!(state.days['2026-11-19'] && state.days['2026-11-19'].runs.length &&
              !state.days['2026-11-19'].runs[0].e),
  stopBtn: (function(){ try { render(); } catch(e){ return 'render-error:'+e.message; } return document.getElementById('app').innerHTML.indexOf('data-act="stop"') >= 0; })()
})"""))
check('B 빈 로컬 + 진행 중 remote → mergeStates 후 STOP 복원',
      b['session'] == '2026-11-19T04:00' and b['dayKey'] == '2026-11-19' and b['runOpen'] and b['stopBtn'] is True, b)

# Case B-2: 오늘·어제가 아닌 날짜의 세션도 session 필드로 복원되는지
# (recoverSession은 오늘·어제만 보므로, session 자체가 동기화돼야 하는 경로를 따로 확인)
ctx.eval('resetCase()')
ctx.eval("""
remoteDoc = {
  version:1, appVersion:'1.0', settings:{}, settingsUpdated: 0,
  days:{'2026-11-16': {u: 5000, runs:[{s:'2026-11-16T22:00', e:''}]}},
  deleted:{}, meta:{created: 1},
  session:{start:'2026-11-16T22:00', dayKey:'2026-11-16'}
};
state = defaultState();
""")
run_sync()
b2 = h.json.loads(ctx.eval("""JSON.stringify({
  session: state.session && state.session.start,
  dayKey: state.session && state.session.dayKey,
  runOpen: !!(state.days['2026-11-16'] && state.days['2026-11-16'].runs.length && !state.days['2026-11-16'].runs[0].e)
}) """))
check('B-2 오늘·어제가 아닌 날짜도 session 필드로 STOP 복원',
      b2['session'] == '2026-11-16T22:00' and b2['dayKey'] == '2026-11-16' and b2['runOpen'], b2)

# ---------------------------------------------------------------- Case C
ctx.eval('resetCase()')
ctx.eval("""
state = normalizeState({
  settings:{}, settingsUpdated: 0,
  days:{'2026-11-18': {u: 100, runs:[{s:'2026-11-18T21:00', e:''}]}},
  session:{start:'2026-11-18T21:00', dayKey:'2026-11-18'}
});
var localBefore = JSON.stringify(state);
remoteDoc = {
  version:1, appVersion:'1.0', settings:{}, settingsUpdated: 0,
  days:{'2026-11-18': {u: 999999, runs:[{s:'2026-11-17T08:00', e:'2026-11-17T18:00'}]}},
  deleted:{}, meta:{created: 1}, session:null
};
var cMerged = mergeStates(state, remoteDoc);
""")
c_merge = h.json.loads(ctx.eval("""JSON.stringify((function(){
  var d = cMerged.days['2026-11-18'];
  var open = (d.runs||[]).filter(function(r){ return r.s === '2026-11-18T21:00' && !r.e; });
  return {
    session: cMerged.session && cMerged.session.start,
    dayKey: cMerged.session && cMerged.session.dayKey,
    openRun: open.length,
    runCount: (d.runs||[]).length,
    localUntouched: JSON.stringify(state) === localBefore && state.days['2026-11-18'].runs.length === 1
  };
})())"""))
check('C-1 mergeStates: u가 더 큰 remote에도 미종료 run·session 보존',
      c_merge['openRun'] == 1 and c_merge['session'] == '2026-11-18T21:00' and c_merge['runCount'] == 2, c_merge)
check('C-2 mergeStates가 로컬 state를 변형하지 않음', c_merge['localUntouched'], '')

run_sync()
c_after = h.json.loads(ctx.eval("""JSON.stringify({
  session: state.session && state.session.start,
  openRun: ((state.days['2026-11-18'] || {}).runs || []).filter(function(r){ return r.s === '2026-11-18T21:00' && !r.e; }).length,
  stopBtn: (function(){ try { render(); } catch(e){ return 'render-error:'+e.message; } return document.getElementById('app').innerHTML.indexOf('data-act="stop"') >= 0; })()
})"""))
check('C-3 syncNow 후에도 STOP 버튼 유지', c_after['session'] == '2026-11-18T21:00' and c_after['openRun'] == 1 and c_after['stopBtn'] is True, c_after)

# ---------------------------------------------------------------- Case D
ctx.eval('resetCase()')
ctx.eval("""
state = normalizeState({
  settings:{}, settingsUpdated: 0,
  days:{'2026-11-18': {u: 100, runs:[{s:'2026-11-18T21:00', e:''}]}},
  session:{start:'2026-11-18T21:00', dayKey:'2026-11-18'}
});
remoteDoc = {
  version:1, appVersion:'1.0', settings:{}, settingsUpdated: 0,
  days:{'2026-11-18': {u: 999999, runs:[{s:'2026-11-18T21:00', e:'2026-11-19T05:30'}]}},
  deleted:{}, meta:{created: 1}, session:null
};
var dMerged = mergeStates(state, remoteDoc);
""")
d_merge = h.json.loads(ctx.eval("""JSON.stringify((function(){
  var runs = dMerged.days['2026-11-18'].runs || [];
  return {
    session: dMerged.session,
    runs: runs.length,
    ended: runs[0] && runs[0].e === '2026-11-19T05:30',
    open: runs.filter(function(r){ return !r.e; }).length
  };
})())"""))
check('D-1 mergeStates: 끝난 쪽(r.e)이 있으면 세션 정리·미종료 기록 없음',
      d_merge['session'] is None and d_merge['runs'] == 1 and d_merge['ended'] and d_merge['open'] == 0, d_merge)

run_sync()
d_after = h.json.loads(ctx.eval("""JSON.stringify({
  session: state.session,
  ended: !!(state.days['2026-11-18'] && state.days['2026-11-18'].runs[0] && state.days['2026-11-18'].runs[0].e),
  stopBtn: (function(){ try { render(); } catch(e){ return 'render-error:'+e.message; } return document.getElementById('app').innerHTML.indexOf('data-act="stop"') >= 0; })()
})"""))
check('D-2 syncNow 후 STOP 상태 유지(세션 없음·종료 시각 유지)',
      d_after['session'] is None and d_after['ended'] and d_after['stopBtn'] is False, d_after)

# --------------------------------------------------------- 회귀: 기존 병합 규칙
ctx.eval('resetCase()')
reg = h.json.loads(ctx.eval("""JSON.stringify((function(){
  var a = {settings:{plate:'L'}, settingsUpdated: 10,
           days:{'2026-11-10': {u: 50, sales:'1000'}, '2026-11-11': {u: 50, sales:'2000'}},
           deleted:{}, meta:{created: 5}, session:null};
  var b = {settings:{plate:'R'}, settingsUpdated: 20,
           days:{'2026-11-10': {u: 80, sales:'3000'}, '2026-11-11': {u: 20, sales:'1000'}},
           deleted:{'2026-11-11': 60}, meta:{created: 9}, session:null};
  var m = mergeStates(a, b);
  return {
    newerDayWins: m.days['2026-11-10'].sales === '3000',
    deletedDayRemoved: !m.days['2026-11-11'] && !!m.deleted['2026-11-11'],
    settingsNewer: m.settings.plate === 'R',
    settingsUpdated: m.settingsUpdated,
    created: m.meta.created
  };
})())"""))
check('회귀: 최신 u 날짜 채택·삭제 표시·설정 최신값·생성 시각 유지',
      reg['newerDayWins'] and reg['deletedDayRemoved'] and reg['settingsNewer'] and reg['settingsUpdated'] == 20 and reg['created'] == 5, reg)

# ------------------------------------------------- 회귀: START → STOP → 동기화
ctx.eval('resetCase()')
ctx.eval("""
state = defaultState();
var started = startRunAt(new Date());
""")
start_sync = h.json.loads(ctx.eval("""JSON.stringify({
  session: state.session && state.session.start,
  timersScheduled: __timers.length,
  token: !!accessToken
})"""))
# startRunAt의 syncSessionNow는 토큰이 이미 있으면 타이머로 예약한다.
ctx.eval('__runTimers()')
h.drain()
started_payload = h.json.loads(ctx.eval("""JSON.stringify({
  uploaded: uploadedPayloads.length,
  hasSession: !!(uploadedPayloads[0] && uploadedPayloads[0].session)
})"""))
check('E-1 START 직후 클라우드 동기화 예약·세션 포함 업로드',
      start_sync['session'] and start_sync['timersScheduled'] >= 1 and started_payload['uploaded'] == 1 and started_payload['hasSession'], dict(start_sync, **started_payload))

ctx.eval("""
stopRunAt(new Date(Date.now() + 60000));
__runTimers();
""")
h.drain()
stop_payload = h.json.loads(ctx.eval("""JSON.stringify({
  session: state.session,
  uploaded: uploadedPayloads.length,
  lastSession: uploadedPayloads[uploadedPayloads.length-1] && uploadedPayloads[uploadedPayloads.length-1].session,
  lastRunEnded: (function(){
    var p = uploadedPayloads[uploadedPayloads.length-1];
    var k = Object.keys(p.days)[0];
    return k && p.days[k].runs[0].e ? true : false;
  })()
})"""))
check('E-2 STOP 직후 업로드에 종료 시각 반영·세션 비움',
      stop_payload['session'] is None and stop_payload['lastSession'] is None and stop_payload['lastRunEnded'], stop_payload)

# --------------------------------------------- 회귀: 토큰 만료 시 조용히 갱신
ctx.eval('resetCase()')
ctx.eval("""
accessToken = null;
state = defaultState();
var refreshed = 0;
var __origEnsure = ensureToken;
ensureToken = function(interactive){ refreshed++; accessToken = 'NEWTOKEN'; tokenExp = Date.now() + 3600000; return Promise.resolve(accessToken); };
startRunAt(new Date());
ensureToken = __origEnsure;
""")
refresh = h.json.loads(ctx.eval("""JSON.stringify({refreshed: refreshed, timers: __timers.length, token: accessToken})"""))
check('E-3 토큰 만료 상태에서 START → 조용히 토큰 갱신 후 동기화 예약',
      refresh['refreshed'] == 1 and refresh['timers'] >= 1, refresh)

# ------------------------------------------- 회귀: recoverSession (미종료 기록 되살리기)
ctx.eval('resetCase()')
rec = h.json.loads(ctx.eval("""JSON.stringify((function(){
  var t = new Date();
  var key = dateKey(t);
  state = normalizeState({settings:{}, settingsUpdated:0,
    days:{}, deleted:{}, meta:{created:1}, session:null});
  state.days[key] = {u: 1, off:false, runs:[{s: dtInput(t), e:''}]};
  var ok = recoverSession();
  return {ok: ok, session: state.session && state.session.start, dayKey: state.session && state.session.dayKey};
})())"""))
check('회귀: recoverSession이 오늘 미종료 기록으로 세션 복원', rec['ok'] and rec['session'], rec)

print()
failed = [r for r in results if not r[1]]
print('%d/%d 통과' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
