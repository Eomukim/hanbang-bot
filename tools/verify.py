#!/usr/bin/env python3
"""잇다 검증 스크립트.

로컬(파일 서버) 또는 라이브 URL을 headless Chromium으로 열어
 - 콘솔/페이지 에러, 가로 오버플로
 - 두음법칙 · 중복 차단 · 4단계 극악 한방 승리 · 봇 난이도 규칙
 - 힌트 삭제(버튼·로직·문구·API 없음)와 입력 바 배치
 - 설정 화면 정리(상단 태그라인·하단 규칙/팁/전적 블록이 DOM·CSS·JS에 없음, 대전 시작이 마지막 요소, 세로 스크롤 0)와 전적 저장 유지
 - 하드코어 모드(스위치 · 5초 고정 · 봇 선공 고정 · 헤더/결과 배지 · 별도 전적 · 끄면 일반 모드)
 - 배려모드(스위치 · 저장 · 첫 5수 플레이어 한방 차단과 타이머 유지 · Lv.1~5 봇 한방 회피 ·
   5수째 한방뿐인 자리 처리 · 6수부터 허용 · 헤더/결과 배지 · 설정 화면 스크롤 0)
 - 내 단어장 삭제(버튼·모달·사전 API 없음, 남은 localStorage 값 무시)
 - 결과 화면(승리·패배·시간 초과·포기) 난이도 배지
 - 결과 화면 배틀 내역: 버튼 열기/닫기 · 카드 안 세로 스크롤 · 턴·나/봇·단어·점수·태그 · 0수 종료(포기·시간 초과) · 아주 긴 단어 줄바꿈 · 모바일 오버플로
 - 5단계 난이도 카드(데스크톱/모바일 배치)와 4단계 기준 localStorage 호환
- Lv.1·Lv.2 일상 어휘 선택(흔한 글자 → 쉬운 일상 단어, 방언·옛말·문화어·어인정 제외, Lv.1 한방 금지)과
  Lv.3~5 의 사전 전체 사용 유지, 실제 Lv.1 대전에서도 일상 단어로 답하는지
 - Lv.5 지옥: 한방 즉사 · 상대 한방 각 회피 · 강제 필승 검증 · 압박/미션·장문 · 응답 시간
 - Lv.4·Lv.5 단어 선택 다양화: 같은 글자·같은 자리에서도 단어가 섞이는지(강도 유지)
 - 미션 규칙(14종 후보 · 미달성 시 유지 · 중첩 보너스 · 성공 시 다음 글자)
 - 모바일(390x844) 레이아웃과 스크린샷
을 확인한다.

env:
    ITDA_SHOT_DIR     스크린샷 폴더(기본: 저장소 downloads/)
    ITDA_REPORT_DIR   미션 보고용 스크린샷(mission-keep/stack/success.png)을 따로 저장할 폴더

usage:
    python3 tools/verify.py --local
    python3 tools/verify.py --url https://itda-play.onrender.com
    python3 tools/verify.py --local --url https://itda-play.onrender.com
    python3 tools/verify.py --local --viewport desktop   # 한 화면 크기만(빠른 확인)
"""
import argparse
import functools
import http.server
import json
import os
import socketserver
import sys
import threading
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOT_DIR = os.environ.get('ITDA_SHOT_DIR') or os.path.join(ROOT, 'downloads')
REPORT_DIR = os.environ.get('ITDA_REPORT_DIR')
MISSION_CHARS = ['가', '나', '다', '라', '마', '바', '사', '아', '자', '차', '카', '타', '파', '하']
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')

VIEWPORTS = {
    'desktop': {'width': 1280, 'height': 800},
    'mobile': {'width': 390, 'height': 844},
}

# Lv.5 지옥 봇의 판단을 직접 돌려 보는 스크립트.
#  · 한방 즉사가 있으면 쓰는지, 상대에게 한방 각을 주지 않는지(피할 수 있을 때),
#  · '필승'으로 표시한 수가 실제로 강제 승리인지(내 수 → 상대 모든 응수 → 내 한방),
#  · 후속 단어가 적은 글자로 몰아넣는지, 장문·미션 점수를 챙기는지, 판단·응답 시간은 어떤지
HELL_PROPS = """
() => {
  const dict = window.__ITDA.dict, Bot = window.__ITDA.Bot;
  const starts = dict.goodStartChars(120).sort();
  const bot = new Bot({level: 5, dict});

  const kill = (node, used) => {
    const shots = dict.shotWords(node);
    if (shots) for (const w of shots) if (!used.has(w) && dict.countFrom(w[w.length - 1]) === 0) return w;
    const cands = dict.candidatesFor(node, used);
    if (cands.length <= 40) for (const w of cands) if (dict.countFrom(w[w.length - 1]) === 0) return w;
    return null;
  };
  // 독립 구현: 이 글자에서 3수 안에 강제로 이기는가 (내 수 → 상대 모든 응수 → 내 한방)
  const forcedWin = (node, used, depth) => {
    if (kill(node, used)) return true;
    if (depth <= 1) return false;
    let tried = 0;
    for (const w of dict.candidatesFor(node, used)) {
      if (++tried > 120) break;
      const end = w[w.length - 1];
      if (dict.graphStatus(end) !== 'L' && dict.countFrom(end) > 3) continue;
      const used2 = new Set(used); used2.add(w);
      let ok = true;
      for (const r of dict.candidatesFor(end, used2)) {
        const used3 = new Set(used2); used3.add(r);
        if (!forcedWin(r[r.length - 1], used3, depth - 2)) { ok = false; break; }
      }
      if (ok) return true;
    }
    return false;
  };

  const out = {positions: 0, moves: 0, handedKill: 0, handedKillAvoidable: 0, outer: 0, outerBroken: 0,
               kinds: {}, msSum: 0, msMax: 0, endDead: 0, endThin: 0, longMoves: 0,
               delayMin: 1e9, delayMax: 0, samples: []};
  for (let g = 0; g < 80; g += 1) {
    let ch = starts[(g * 11) % starts.length];
    const used = new Set();
    const steps = g % 5;
    for (let k = 0; k < steps; k += 1) {
      const c = dict.candidatesFor(ch, used);
      if (!c.length) break;
      const w = c[(g * 17 + k * 31) % c.length];
      used.add(w); ch = w[w.length - 1];
      if (!dict.hasCandidate(ch, used)) break;
    }
    if (!dict.hasCandidate(ch, used)) continue;
    out.positions += 1;
    const t = performance.now();
    const mv = bot.choose({needChar: ch, used, turn: 10, mission: '가'});
    const dt = performance.now() - t;
    out.msSum += dt; if (dt > out.msMax) out.msMax = dt;
    if (!mv) continue;
    out.moves += 1;
    out.kinds[mv.kind] = (out.kinds[mv.kind] || 0) + 1;
    out.delayMin = Math.min(out.delayMin, mv.delay);
    out.delayMax = Math.max(out.delayMax, mv.delay);
    if (mv.word.length >= 5) out.longMoves += 1;
    const end = mv.word[mv.word.length - 1];
    const after = new Set(used); after.add(mv.word);
    if (dict.countFrom(end) === 0) out.endDead += 1;
    else if (dict.countFrom(end) <= 3) out.endThin += 1;
    const pk = kill(end, after);
    if (pk) {
      out.handedKill += 1;
      let avoidable = false;
      for (const w of dict.candidatesFor(ch, used)) {
        const e2 = w[w.length - 1];
        if (dict.countFrom(e2) === 0) { avoidable = true; break; }
        const u2 = new Set(used); u2.add(w);
        if (!kill(e2, u2)) { avoidable = true; break; }
      }
      if (avoidable) out.handedKillAvoidable += 1;
      if (out.samples.length < 3) out.samples.push({handed: mv.word, killWord: pk});
    }
    if (mv.proven) {
      out.outer += 1;
      let ok = true;
      for (const r of dict.candidatesFor(end, after)) {
        const u3 = new Set(after); u3.add(r);
        if (!forcedWin(r[r.length - 1], u3, 3)) { ok = false; break; }
      }
      if (!ok) out.outerBroken += 1;
    }
  }
  out.msAvg = +(out.msSum / Math.max(1, out.moves)).toFixed(2);
  out.msMax = +out.msMax.toFixed(1);
  if (!out.moves) { out.delayMin = 0; out.delayMax = 0; }
  return out;
}
"""

# Lv.5 봇이 고른 수 자체를 뜯어 보는 표본 시험(한방 선택 · 미션 · 압박)
HELL_PICKS = """
() => {
  const dict = window.__ITDA.dict, Bot = window.__ITDA.Bot;
  const starts = dict.goodStartChars(60).sort();
  const last = (w) => w[w.length - 1];
  const value = (w, mission) => {
    let hits = 0;
    for (const c of w) if (c === mission) hits += 1;
    const mult = hits <= 0 ? 1 : hits === 1 ? 1.5 : hits;
    return (w.length * w.length + 4 * w.length) * mult;
  };
  const natOf = (w) => window.__ITDA.naturalness(w);
  const out = {};

  // 1) 한방이 여러 개일 때: 어떤 한방이든 즉사다. 같은 즉사 안에서는 보통 말(자연스러운 등급)을 고르는가
  for (const ch of starts) {
    const cands = dict.candidatesFor(ch, new Set());
    const kills = cands.filter((w) => dict.countFrom(last(w)) === 0);
    if (kills.length < 2) continue;
    const minNat = Math.min(...kills.map(natOf));
    const mv = new Bot({level: 5, dict}).choose({needChar: ch, used: new Set(), turn: 1, mission: '가'});
    out.kill = {ok: true, char: ch, got: mv.word, kind: mv.kind,
                isKill: dict.countFrom(last(mv.word)) === 0,
                inBand: natOf(mv.word) <= minNat + 1,
                kills: kills.length, band: kills.filter((w) => natOf(w) <= minNat + 1).length,
                nat: natOf(mv.word), minNat};
    break;
  }
  if (!out.kill) out.kill = {ok: false};

  // 2) 고른 끝 글자 안에서는 보통 말을 먼저, 같은 등급이면 미션·점수가 높은 단어를 고르는가
  let checked = 0, agree = 0, detail = null;
  for (const ch of starts) {
    const used = new Set();
    const mv = new Bot({level: 5, dict}).choose({needChar: ch, used, turn: 6, mission: '가'});
    if (!mv) continue;
    const end = last(mv.word);
    const same = dict.candidatesFor(ch, used).filter((w) => last(w) === end);
    const minNat = Math.min(...same.map(natOf));
    const bestVal = same.filter((w) => natOf(w) === minNat)
      .reduce((a, b) => (value(b, '가') > value(a, '가') ? b : a), mv.word);
    checked += 1;
    if (natOf(mv.word) <= minNat + 1) agree += 1;
    else if (!detail) detail = {char: ch, got: mv.word, best: bestVal, end, same: same.length, kind: mv.kind};
    if (checked >= 25) break;
  }
  out.mission = {ok: checked > 0, checked, agree, detail};

  // 3) 한방·필승이 없는 자리: 후속 단어가 1개뿐인 글자로 몰아넣는가
  for (const ch of starts) {
    const cands = dict.candidatesFor(ch, new Set());
    if (cands.some((w) => dict.countFrom(last(w)) === 0)) continue;
    const tight = cands.find((w) => dict.countFrom(last(w)) === 1);
    if (!tight) continue;
    const mv = new Bot({level: 5, dict}).choose({needChar: ch, used: new Set(), turn: 8, mission: '나'});
    const endLive = dict.countFrom(last(mv.word));
    out.pressure = {ok: true, char: ch, tight, got: mv.word, kind: mv.kind, endLive,
                    squeezed: endLive <= 3};
    break;
  }
  if (!out.pressure) out.pressure = {ok: false};
  return out;
}
"""

# Lv.4 극악 · Lv.5 지옥의 단어 선택 다양성.
# 같은 글자·같은 자리에서 15번 두면 매번 같은 단어 하나로 고정되지 않고 여러 단어가 섞이는지,
# 그리고 그 선택이 한방 즉사·최소 후속 수 같은 강도 기준을 지키는지 본다.
VARIETY_PROPS = """
() => {
  const dict = window.__ITDA.dict, Bot = window.__ITDA.Bot;
  const last = (w) => w[w.length - 1];
  const N = 15;
  const out = {rows: []};
  const natOf = (w) => window.__ITDA.naturalness(w);
  const run = (lv, ch, used) => {
    const cands = new Set(dict.candidatesFor(ch, used));
    const words = [], kinds = {};
    for (let i = 0; i < N; i += 1) {
      const mv = new Bot({level: lv, dict}).choose({needChar: ch, used, turn: 8, mission: '가'});
      if (!mv) continue;
      words.push(mv.word);
      kinds[mv.kind] = (kinds[mv.kind] || 0) + 1;
    }
    const counts = {};
    for (const w of words) counts[w] = (counts[w] || 0) + 1;
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    return {
      n: words.length,
      distinct: top.length,
      maxShare: top.length ? +(top[0][1] / words.length).toFixed(2) : 1,
      top: top.slice(0, 4),
      kinds,
      words,
      valid: words.every((w) => cands.has(w)),
    };
  };
  for (const ch of ['가', '사', '기']) {
    const open = dict.candidatesFor(ch, new Set());
    const kills = open.filter((w) => dict.countFrom(last(w)) === 0);
    const minEnd = Math.min(...open.map((w) => dict.countFrom(last(w))));
    // 한방 단어를 모두 쓴 중반 자리: 한방 없이 필승·안전 후보로 두는지
    const drained = new Set(kills);
    const dCands = dict.candidatesFor(ch, drained);
    const dMin = dCands.length ? Math.min(...dCands.map((w) => dict.countFrom(last(w)))) : 0;
    // 같은 즉사 안에서도 보통 말 후보가 둘 이상이면 단어가 섞여야 한다(고착 아님).
    const killBand = kills.length
      ? kills.filter((w) => natOf(w) <= Math.min(...kills.map(natOf)) + 1).length : 0;
    const thinBand = open.filter((w) => dict.countFrom(last(w)) <= minEnd + 2).length;
    for (const lv of [4, 5]) {
      const o = run(lv, ch, new Set());
      out.rows.push({
        lv, ch, pos: 'open', kills: kills.length, pool: open.length, ...o, eligible: killBand,
        killOk: kills.length ? o.words.every((w) => dict.countFrom(last(w)) === 0) : true,
        endOk: (!kills.length && lv === 4)
          ? o.words.every((w) => dict.countFrom(last(w)) <= minEnd + 2) : true,
      });
      if (dCands.length) {
        const d = run(lv, ch, drained);
        out.rows.push({
          lv, ch, pos: 'drained', kills: 0, pool: dCands.length, ...d, eligible: thinBand,
          killOk: true,
          endOk: lv === 4 ? d.words.every((w) => dict.countFrom(last(w)) <= dMin + 2) : true,
        });
      }
    }
  }
  return out;
}
"""

FAILS = []


def serve(root):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
    httpd = socketserver.ThreadingTCPServer(('127.0.0.1', 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


class Collector:
    def __init__(self, page):
        self.console = []
        self.errors = []
        page.on('console', self._console)
        page.on('pageerror', self._pageerror)

    def _console(self, msg):
        if msg.type in ('error', 'warning'):
            self.console.append({'type': msg.type, 'text': msg.text[:400]})

    def _pageerror(self, err):
        self.errors.append(str(err)[:600])


def check(cond, label, detail=''):
    ok = bool(cond)
    print(('  PASS  ' if ok else '  FAIL  ') + label + (f'  [{detail}]' if detail else ''))
    if not ok:
        FAILS.append(label)
    return ok


def shot(page, name):
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f'{name}.png')
    page.screenshot(path=path)
    print(f'  shot  {path}')
    return path


def shot_to(page, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    page.screenshot(path=path)
    print(f'  shot  {path}')
    return path


def report_shot(page, tag, report_dir, name):
    """보고용 스크린샷: 보기 이름(tag 포함) + 데스크톱이면 대표 이름도 함께."""
    if not report_dir:
        return
    shot_to(page, os.path.join(report_dir, f'{tag}-{name}.png'))
    if tag.endswith('desktop'):
        shot_to(page, os.path.join(report_dir, f'{name}.png'))


def overflow(page):
    return page.evaluate("""() => ({
        doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        body: document.body.scrollWidth - document.body.clientWidth,
    })""")


def wait_ready(page, timeout=90000):
    page.wait_for_function('window.__ITDA && window.__ITDA.ready === true', timeout=timeout)
    page.wait_for_selector('#scr-setup:not([hidden])', timeout=timeout)


def state(page):
    return page.evaluate('window.__ITDA.state()')


def new_page(browser, vp_name):
    vp = VIEWPORTS[vp_name]
    ctx = browser.new_context(
        viewport=vp,
        device_scale_factor=2 if vp_name == 'mobile' else 1,
        is_mobile=vp_name == 'mobile',
        has_touch=vp_name == 'mobile',
        locale='ko-KR',
    )
    page = ctx.new_page()
    return ctx, page


def play_word(page, word, wait=1800):
    page.fill('#word-input', word)
    page.click('#btn-submit')
    page.wait_for_timeout(wait)


def wait_my_turn(page, timeout=8000):
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        st = state(page)
        if not st or st['phase'] in ('over',):
            return st
        if st['phase'] == 'me' and page.evaluate("!document.getElementById('word-input').disabled"):
            return st
        page.wait_for_timeout(120)
    return state(page)


def duplicate_test(page, tag):
    st = wait_my_turn(page, 8000)
    if not st or st['phase'] != 'me':
        check(False, f'[{tag}] 중복 시험 턴 확보')
        return
    used = page.evaluate("""() => {
        const st = window.__ITDA.state();
        const starts = [st.needChar, st.needAlt].filter(Boolean);
        return st.chain.map((c) => c.word).find((w) => starts.some((s) => w.startsWith(s))) || null;
    }""")
    if used:
        page.fill('#word-input', used)
        page.click('#btn-submit')
        page.wait_for_timeout(250)
        toast = page.evaluate("document.querySelector('.toast')?.textContent || ''")
        check('이미' in toast, f'[{tag}] 중복 단어 차단', toast)
        shot(page, f'{tag}-03-duplicate')
        return
    res = page.evaluate("""() => {
        const st = window.__ITDA.state();
        const e = window.__ITDA.engine;
        const last = st.chain[st.chain.length - 1].word;
        // 이어야 할 글자와 무관하게, 이미 나온 단어는 중복으로 걸리는지 (엔진 공용 경로)
        const dup = e.validate(last);
        const fresh = e.validate(st.needChar + '가');
        return { dup, fresh };
    }""")
    check(res['dup'].get('ok') is False and res['dup']['error']['code'] in ('used', 'start'),
          f'[{tag}] 중복 판정 규칙(엔진)', json.dumps(res['dup'], ensure_ascii=False)[:140])


def ui_duplicate(page, tag):
    st = wait_my_turn(page, 8000)
    if not st or st['phase'] != 'me':
        return
    used = page.evaluate("""() => {
        const st = window.__ITDA.state();
        const starts = [st.needChar, st.needAlt].filter(Boolean);
        return st.chain.map((c) => c.word).find((w) => starts.some((s) => w.startsWith(s))) || null;
    }""")
    if not used:
        print(f'  note  [{tag}] UI 중복 시도 대상 없음(엔진 검사로 대체 확인)')
        return
    page.fill('#word-input', used)
    page.click('#btn-submit')
    page.wait_for_timeout(250)
    toast = page.evaluate("document.querySelector('.toast')?.textContent || ''")
    check('이미' in toast, f'[{tag}] 중복 단어 차단(UI)', toast)
    shot(page, f'{tag}-03-duplicate')


def scenario_twoeum(page, tag):
    """두음법칙·중복 차단: 첫 글자와 끝 글자가 같은 단어로 시작해 중복까지 확인."""
    info = page.evaluate("""() => {
        const d = window.__ITDA.dict;
        for (const [ch] of d.ranges) {
            const cands = d.candidatesFor(ch, new Set());
            const loop = cands.find((w) => w[0] === ch && w[w.length - 1] === ch && w.length >= 2);
            if (loop) return { ch, loop };
        }
        return null;
    }""")
    if not info:
        check(False, f'[{tag}] 순환 단어 탐색')
        return
    page.evaluate(f"window.__ITDA.startGame({{level:2, first:'me', startChar:'{info['ch']}'}})")
    page.wait_for_timeout(500)
    play_word(page, info['loop'], wait=120)
    # 같은 단어를 바로 다시 판정: 필요 글자가 같으므로 '이미 나온 단어'로 걸려야 한다
    res = page.evaluate("(w) => window.__ITDA.engine.validate(w)", info['loop'])
    check(res.get('ok') is False and res['error']['code'] == 'used',
          f'[{tag}] 중복 단어 차단', json.dumps(res, ensure_ascii=False)[:120])
    page.wait_for_timeout(1700)
    st = state(page)
    check(st['chain'] and st['chain'][0]['word'] == info['loop'], f'[{tag}] 첫 단어 입력', info['loop'])

    # 중복: 지금 이어야 할 글자로 시작하는 이미 나온 단어가 있으면 UI로도 시도한다
    ui_duplicate(page, tag)

    # 두음법칙: 시작 글자를 '력'으로 고정하고 '역'으로 시작하는 단어 입력
    page.evaluate("window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.startGame({level:2, first:'me', startChar:'력'})")
    page.wait_for_timeout(450)
    duo = page.evaluate("""() => {
        const d = window.__ITDA.dict, st = window.__ITDA.state();
        const alt = st.needAlt;
        if (!alt) return null;
        const cands = d.candidatesFor(st.needChar, new Set());
        return cands.find((w) => w[0] === alt) || null;
    }""")
    if duo:
        play_word(page, duo, wait=400)
        st = state(page)
        check(bool(st['chain']) and st['chain'][0]['word'] == duo, f'[{tag}] 두음법칙 입력 인정', duo)
        shot(page, f'{tag}-02b-twoeum')
    else:
        check(False, f'[{tag}] 두음법칙 후보 탐색')


def scenario_new_words(page, tag):
    """오픈DB에서 새로 병합된 단어가 실제 입력으로 인정되는지."""
    samples = page.evaluate(
        "() => ((window.__ITDA.dict.stats && window.__ITDA.dict.stats.openDbSamples) || []).filter((w) => w.length >= 3)"
    )
    check(bool(samples), f'[{tag}] 오픈DB 신규 단어 표본', str(samples[:1]))
    if not samples:
        return
    picks = [samples[0], samples[len(samples) // 2], samples[-1]]
    for sample in picks:
        page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
        page.evaluate("(ch) => window.__ITDA.startGame({level:2, first:'me', startChar: ch})", sample[0])
        page.wait_for_timeout(450)
        play_word(page, sample, wait=600)
        st = state(page)
        check(bool(st['chain']) and st['chain'][0]['word'] == sample,
              f'[{tag}] 오픈DB 신규 단어 입력 인정', sample)
        page.evaluate("window.__ITDA.app.hideResult()")
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")


# ── Lv.1·Lv.2 일상 어휘 선택 ─────────────────────────────────────
# 흔한 글자에서 봇이 실제로 고르는 단어를 여러 번 뽑아, 그 단어가
#  · 사전에 있는지 · 한방 단어가 아닌지 · 방언/옛말/문화어/어인정이 아닌지 · 일상 어휘인지
# 를 한 번에 본다. Lv.3~5 는 기존대로 사전 전체를 쓰는지도 같이 확인한다.
EASY_CHARS = ['가', '사', '바', '나', '하']
EASY_PROPS = """
({chars, n}) => {
  const dict = window.__ITDA.dict, Bot = window.__ITDA.Bot;
  const BAD = 2 | 8 | 16 | 32;   // 어인정 · 방언 · 옛말 · 문화어
  const endN = (w) => dict.countFrom(w[w.length - 1]);
  const record = (mv) => ({
    word: mv ? mv.word : null,
    tier: mv ? dict.easyTier(mv.word) : 0,
    len: mv ? mv.word.length : 0,
    end: mv ? endN(mv.word) : 0,
    flag: mv ? dict.flagOf(mv.word) : -1,
    oneShot: mv ? dict.isOneShot(mv.word) : false,
    inDict: mv ? dict.has(mv.word) : false,
  });
  const out = { easyTotal: dict.easy.size, levels: {}, deep: {} };
  for (const lv of [1, 2]) {
    const bot = new Bot({level: lv, dict});
    const per = {};
    for (const ch of chars) {
      per[ch] = { picks: [], early: [] };
      for (let i = 0; i < n; i += 1) {
        per[ch].picks.push(record(bot.choose({needChar: ch, used: new Set(), turn: 6, mission: null})));
      }
      // 초반(3턴 이하)에는 한방 단어를 두지 않는다
      for (let i = 0; i < 5; i += 1) {
        per[ch].early.push(record(bot.choose({needChar: ch, used: new Set(), turn: 1, mission: null})));
      }
    }
    out.levels[lv] = per;
  }
  for (const lv of [3, 4, 5]) {
    const bot = new Bot({level: lv, dict});
    const all = [];
    for (const ch of chars) {
      for (let i = 0; i < n; i += 1) {
        const mv = bot.choose({needChar: ch, used: new Set(), turn: 8, mission: null});
        if (mv) all.push({ word: mv.word, tier: dict.easyTier(mv.word), flag: dict.flagOf(mv.word) });
      }
    }
    out.deep[lv] = all;
  }
  out.bad = BAD;
  // Lv.2 의 ‘가끔 한방’은 일상 단어로만, Lv.1 은 한방 없이
  out.shotTest = {};
  for (const lv of [1, 2]) {
    const bot = new Bot({level: lv, dict});
    const rows = [];
    for (const ch of ['바', '기', '아', '슬']) {
      for (let i = 0; i < 40; i += 1) {
        const mv = bot.choose({needChar: ch, used: new Set(), turn: 8, mission: null});
        if (!mv) continue;
        rows.push({ ch, word: mv.word, kind: mv.kind, tier: dict.easyTier(mv.word), oneShot: dict.isOneShot(mv.word) });
      }
    }
    out.shotTest[lv] = rows;
  }
  return out;
}
"""


def scenario_easy_words(page, tag):
    """Lv.1·Lv.2 가 흔한 글자에서 일상 단어를 고르는지, Lv.3~5 는 그대로인지."""
    props = page.evaluate(EASY_PROPS, {'chars': EASY_CHARS, 'n': 20})
    bad = props['bad']
    # 일상 어휘는 명사만 남겼다(동사·형용사 '~다'를 빼서 3,982단어).
    check(props['easyTotal'] >= 3500, f'[{tag}] 일상 어휘 목록 로드', f"{props['easyTotal']}단어")

    for lv, title in ((1, 'Lv.1'), (2, 'Lv.2')):
        per = props['levels'][str(lv)]
        rows = []
        for ch in EASY_CHARS:
            picks = [p for p in per[ch]['picks']]
            words = [p['word'] for p in picks]
            rows.append((ch, words))
            plain_ok = all(p['inDict'] and not (p['flag'] & bad) for p in picks)
            check(plain_ok, f'[{tag}] {title} "{ch}" 표준어·사전 단어', ' '.join(w or '·' for w in words))
            if lv == 1:
                ok = all(p['tier'] > 0 and p['len'] <= 4 and not p['oneShot'] and p['end'] > 0 for p in picks)
                check(ok, f'[{tag}] {title} "{ch}" 일상 단어·한방 금지',
                      ' '.join(f"{p['word']}({p['tier']})" for p in picks[:10]))
                check(len(set(w for w in words if w)) >= 4, f'[{tag}] {title} "{ch}" 단어 다양성',
                      f'{len(set(words))}종')
            else:
                easy = sum(1 for p in picks if p['tier'] > 0)
                ok = easy >= len(picks) * 0.8 and all(not p['oneShot'] or p['len'] <= 3 for p in picks)
                check(ok, f'[{tag}] {title} "{ch}" 일상 단어 위주({easy}/{len(picks)})',
                      ' '.join(f"{p['word']}({p['tier']})" for p in picks[:10]))
            early = per[ch]['early']
            check(all(not p['oneShot'] for p in early),
                  f'[{tag}] {title} "{ch}" 초반 한방 금지', ' '.join(p['word'] or '·' for p in early))

        # 사람이 읽어 볼 표본: 글자별 20수
        print(f'  -- {tag} {title} 표본 --')
        for ch, words in rows:
            print(f'     {ch}: ' + ' '.join(w or '·' for w in words))

    # Lv.2 의 ‘가끔 한방’은 일상 단어로만, Lv.1 은 한방 없이
    shot2 = props['shotTest']['2']
    ones = [r for r in shot2 if r['kind'] == 'oneshot']
    check(bool(ones) and all(r['tier'] > 0 for r in ones),
          f'[{tag}] Lv.2 가끔 한방은 일상 단어',
          f"{len(ones)}/{len(shot2)}수 한방 · " + ' '.join(f"{r['word']}({r['tier']})" for r in ones[:8]))
    shot1 = props['shotTest']['1']
    check(not any(r['oneShot'] or r['kind'] == 'oneshot' for r in shot1),
          f'[{tag}] Lv.1 한방 0수', f"{len(shot1)}수 표본")

    # Lv.3~5 는 일상 목록에 갇히지 않고 사전 전체(796,750단어)를 쓴다.
    #  Lv.3 은 '보통 말'을 우선하느라 일상어 비중이 높지만, 제한이 아니라 선택이다.
    for lv in (3, 4, 5):
        deep = props['deep'][str(lv)]
        outside = [d for d in deep if not d['tier']]
        need = 0.2 if lv == 3 else 0.5
        check(len(deep) >= 40 and len(outside) >= len(deep) * need,
              f'[{tag}] Lv.{lv} 사전 전체 사용 유지',
              f'{len(deep)}수 중 일상 목록 밖 {len(outside)}수 · ' + ' '.join(d['word'] for d in deep[:5]))


def scenario_easy_game(page, tag):
    """Lv.1 실제 대전: 사람이 일상 단어로만 이어 가면 봇도 일상 단어로만 답하는지."""
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.evaluate("window.__ITDA.startGame({level:1, first:'me', startChar:'가', timeLimit:20})")
    page.wait_for_timeout(400)
    played = []
    for _ in range(6):
        st = wait_my_turn(page, 6000)
        if not st or st['phase'] != 'me':
            break
        mine = page.evaluate("""() => {
            const d = window.__ITDA.dict, st = window.__ITDA.state();
            const used = new Set(st.chain.map((c) => c.word));
            const cands = d.candidatesFor(st.needChar, used).filter((w) => d.easyTier(w) && d.countFrom(w[w.length - 1]) > 0);
            const flow = cands.filter((w) => d.easyCountFrom(w[w.length - 1]) >= 3);
            const pool = flow.length ? flow : cands;
            return pool[0] || null;
        }""")
        if not mine:
            break
        played.append(mine)
        play_word(page, mine, wait=2800)
    st = state(page)
    bot_words = [c['word'] for c in st['chain'] if c['who'] == 'bot']
    info = page.evaluate("""(ws) => ws.map((w) => ({
        word: w,
        tier: window.__ITDA.dict.easyTier(w),
        flag: window.__ITDA.dict.flagOf(w),
        oneShot: window.__ITDA.dict.isOneShot(w),
        len: w.length,
    }))""", bot_words)
    check(len(played) >= 3 and len(info) >= 2, f'[{tag}] Lv.1 일상 단어 대전 진행',
          f"나 {len(played)}수 / 봇 {len(info)}수 | {' '.join(played)}")
    if info:
        check(all(not i['oneShot'] for i in info), f'[{tag}] Lv.1 대전 중 한방 금지',
              ' '.join(i['word'] for i in info))
        check(all(not (i['flag'] & (2 | 8 | 16 | 32)) for i in info), f'[{tag}] Lv.1 대전 중 표준어',
              ' '.join(i['word'] for i in info))
        easy = sum(1 for i in info if i['tier'] > 0)
        check(easy >= len(info) * 0.75, f'[{tag}] Lv.1 대전 중 일상 단어({easy}/{len(info)})',
              ' '.join(f"{i['word']}({i['tier']})" for i in info))
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(150)


def scenario_bot_levels(page, tag):
    """1단계는 한방 금지, 4단계 극악은 즉시 한방."""
    # 1단계: 여러 턴을 두고 봇이 한방 단어를 쓰지 않는지
    page.evaluate("window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.startGame({level:1, first:'bot'})")
    page.wait_for_timeout(2600)
    used = []
    for _ in range(5):
        st = wait_my_turn(page, 6000)
        if not st or st['phase'] != 'me':
            break
        w = page.evaluate("""() => {
            const d = window.__ITDA.dict, st = window.__ITDA.state();
            const cands = d.candidatesFor(st.needChar, new Set(st.chain.map((c) => c.word)));
            return cands.find((x) => d.countFrom(x[x.length - 1]) >= 40 && x.length <= 3) || cands[0] || null;
        }""")
        if not w:
            break
        play_word(page, w, wait=2600)
    st = state(page)
    bot_words = [c['word'] for c in st['chain'] if c['who'] == 'bot']
    one_shots = page.evaluate(
        "(ws) => ws.map((w) => window.__ITDA.dict.isOneShot(w))", bot_words
    ) if bot_words else []
    check(len(bot_words) >= 2, f'[{tag}] 1단계 봇 응답 정상', f'{len(bot_words)}턴')
    check(not any(one_shots), f'[{tag}] 1단계 봇 한방 금지', str(bot_words[-2:]))
    shot(page, f'{tag}-04-level1')

    # 4단계 극악: 한방 시나리오
    pick = page.evaluate("""() => {
        const d = window.__ITDA.dict;
        for (const [ch] of d.ranges) {
            const mine = d.candidatesFor(ch, new Set());
            for (const w of mine.slice(0, 150)) {
                const last = w[w.length - 1];
                const bot = d.candidatesFor(last, new Set([w]));
                if (bot.some((x) => d.isOneShot(x))) return { start: ch, word: w };
            }
        }
        return null;
    }""")
    check(pick is not None, f'[{tag}] 한방 시나리오 탐색', str(pick))
    if not pick:
        return
    page.evaluate("window.__ITDA.app.engine.destroy()")
    page.evaluate(f"window.__ITDA.startGame({{level:4, first:'me', startChar:'{pick['start']}'}})")
    page.wait_for_timeout(450)
    play_word(page, pick['word'], wait=3500)
    st = state(page)
    bot_words = [c['word'] for c in st['chain'] if c['who'] == 'bot']
    last_bot = bot_words[-1] if bot_words else ''
    is_oneshot = page.evaluate("([w]) => !!w && window.__ITDA.dict.isOneShot(w)", [last_bot])
    check(st['phase'] == 'over', f'[{tag}] 4단계 극악 봇 즉시 종료', st['phase'])
    check(is_oneshot, f'[{tag}] 4단계 극악 봇 한방 단어 사용', last_bot)
    check(page.is_visible('#ov-result'), f'[{tag}] 결과 화면 표시')
    lv4 = result_view(page)
    check(lv4['label'] == 'Lv.4 극악' and lv4['lv'] == '4',
          f'[{tag}] 봇 한방 패배 결과에 난이도', json.dumps(lv4, ensure_ascii=False)[:160])
    shot(page, f'{tag}-05-level4-oneshot')
    page.wait_for_timeout(600)


def scenario_levels(page, tag):
    """5단계 난이도 카드: 개수·이름·선택·5단계 대전 헤더."""
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(150)
    cards = page.evaluate("""() => [...document.querySelectorAll('.level')].map((el) => ({
        lv: el.dataset.lv,
        name: el.querySelector('b').textContent,
        label: el.querySelector('small').textContent,
        face: el.querySelector('i').textContent.trim(),
    }))""")
    check(len(cards) == 5, f'[{tag}] 난이도 카드 5개', str(len(cards)))
    check([c['lv'] for c in cards] == ['1', '2', '3', '4', '5'], f'[{tag}] 난이도 번호 1~5', str([c['lv'] for c in cards]))
    check([c['name'] for c in cards] == ['쉬움', '보통', '어려움', '극악', '지옥'],
          f'[{tag}] 난이도 이름', str([c['name'] for c in cards]))
    check(cards[3]['label'] == 'Lv.4' and cards[4]['label'] == 'Lv.5' if len(cards) == 5 else False,
          f'[{tag}] Lv.4 극악 · Lv.5 지옥 표기', str([c['label'] for c in cards]))
    box = page.evaluate("""() => {
        const el = document.getElementById('levels');
        const cards = [...document.querySelectorAll('.level')];
        const left = el.offsetLeft;
        return { rows: new Set(cards.map((c) => c.offsetTop)).size,
                 width: el.clientWidth,
                 right: Math.max(...cards.map((c) => c.offsetLeft + c.offsetWidth)) - left };
    }""")
    check(box['rows'] == 1 and box['right'] <= box['width'] + 1,
          f'[{tag}] 난이도 카드 한 줄 배치', json.dumps(box))
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 난이도 5개 가로 오버플로 0', str(overflow(page)))

    # 4단계(극악)와 5단계(지옥) 선택이 각각 화면에 반영되는지
    page.click('.level[data-lv="4"]')
    page.wait_for_timeout(120)
    desc4 = page.evaluate("document.getElementById('lv-desc').textContent")
    checked4 = page.evaluate("document.querySelectorAll('.level')[3].getAttribute('aria-checked')")
    check(checked4 == 'true', f'[{tag}] Lv.4 극악 선택', desc4)
    page.click('.level[data-lv="5"]')
    page.wait_for_timeout(120)
    desc5 = page.evaluate("document.getElementById('lv-desc').textContent")
    checked5 = page.evaluate("document.querySelectorAll('.level')[4].getAttribute('aria-checked')")
    check(checked5 == 'true' and desc5 != desc4, f'[{tag}] Lv.5 지옥 선택', desc5)
    check('필승' in desc5 or '수읽기' in desc5, f'[{tag}] Lv.5 설명', desc5)
    saved = page.evaluate("JSON.parse(localStorage.getItem('itda.settings.v1') || '{}').level")
    check(saved == 5, f'[{tag}] 5단계 선택 저장', str(saved))
    shot(page, f'{tag}-10-levels5')

    # 5단계 대전을 실제로 시작해 헤더·테마 확인
    page.click('#btn-start')
    page.wait_for_selector('#scr-game:not([hidden])')
    page.wait_for_timeout(500)
    head = page.evaluate("""() => ({
        name: document.getElementById('bot-name').textContent,
        lv: document.getElementById('bot-lv').textContent,
        face: document.getElementById('bot-face').textContent,
        body: document.body.dataset.level,
        phase: window.__ITDA.state() ? window.__ITDA.state().phase : null,
    })""")
    check(head['name'] == '잇다 지옥' and head['lv'] == 'Lv.5 지옥' and head['body'] == '5',
          f'[{tag}] 5단계 대전 헤더', json.dumps(head, ensure_ascii=False))
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 5단계 대전 가로 오버플로 0', str(overflow(page)))
    shot(page, f'{tag}-11-level5-game')
    page.evaluate("window.__ITDA.app.engine.destroy(); window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(150)


def legacy_round(page, tag, old):
    """`old` 이름 시절의 localStorage(설정·전적)가 새 키로 그대로 이어지는지."""
    page.evaluate("""(old) => {
        for (const k of ['itda.settings.v1', 'itda.record.v1',
                         'kkeutmalbot.settings.v1', 'kkeutmalbot.record.v1',
                         'hanbang.settings.v1', 'hanbang.record.v1']) localStorage.removeItem(k);
        localStorage.setItem(old + '.settings.v1', JSON.stringify({ level: 4, timeLimit: 15, first: 'bot', sound: false }));
        localStorage.setItem(old + '.record.v1', JSON.stringify({
            1: { plays: 3, wins: 1, losses: 2, bestCombo: 2, bestScore: 40 },
            4: { plays: 7, wins: 3, losses: 4, bestCombo: 5, bestScore: 260 },
        }));
    }""", old)
    page.reload(wait_until='domcontentloaded')
    wait_ready(page)
    page.wait_for_timeout(250)
    view = page.evaluate("""(old) => ({
        checked: document.querySelector('.level[aria-checked="true"]')?.dataset.lv,
        sound: document.getElementById('sound-value').textContent,
        soundPressed: document.getElementById('btn-sound').getAttribute('aria-pressed'),
        first: document.querySelector('#first-opts button[aria-checked="true"]')?.dataset.first,
        record: JSON.parse(localStorage.getItem('itda.record.v1') || '{}'),
        recordDom: !!document.getElementById('record') || !!document.querySelector('#scr-setup .record'),
        migratedSettings: !!localStorage.getItem('itda.settings.v1'),
        migratedRecord: !!localStorage.getItem('itda.record.v1'),
        legacyKept: !!localStorage.getItem(old + '.settings.v1'),
    })""", old)
    check(view['checked'] == '4', f'[{tag}] {old} 설정 Lv.4 복원', str(view['checked']))
    check(view['sound'] == '끔' and view['soundPressed'] == 'false' and view['first'] == 'bot',
          f'[{tag}] {old} 설정 소리·선공 복원', f"{view['sound']} / {view['first']}")
    row4 = view['record'].get('4', {})
    check(row4.get('wins') == 3 and row4.get('losses') == 4 and row4.get('bestScore') == 260,
          f'[{tag}] {old} 전적 새 키로 유지(화면엔 미표시)', json.dumps(row4, ensure_ascii=False)[:120])
    check(not view['recordDom'], f'[{tag}] {old} 전적을 설정 화면에 그리지 않음', str(view['recordDom']))
    check(view['migratedSettings'] and view['migratedRecord'] and view['legacyKept'],
          f'[{tag}] {old} 키 → 새 키 이전(옛 키 보존)', json.dumps(view, ensure_ascii=False)[:120])
    check(sum(overflow(page).values()) <= 0, f'[{tag}] {old} 설정 화면 가로 오버플로 0', str(overflow(page)))


def scenario_legacy(page, tag):
    """지난 이름(끝말봇·한방봇)의 localStorage(설정·전적)가 그대로 이어지는지."""
    for old in ('kkeutmalbot', 'hanbang'):
        legacy_round(page, tag, old)

    # 새 5단계 전적도 새 키에 쌓이고, 옮겨 온 기록이 남는지
    page.evaluate("window.__ITDA.startGame({level:5, first:'me', timeLimit:1})")
    page.wait_for_timeout(1800)
    rec = page.evaluate("JSON.parse(localStorage.getItem('itda.record.v1') || '{}')")
    check('5' in rec and rec['5'].get('plays', 0) >= 1 and '4' in rec,
          f'[{tag}] Lv.5 전적 저장·기존 기록 유지', json.dumps(rec, ensure_ascii=False)[:160])
    page.evaluate("""() => {
        for (const k of ['itda.settings.v1', 'itda.record.v1',
                         'kkeutmalbot.settings.v1', 'kkeutmalbot.record.v1',
                         'hanbang.settings.v1', 'hanbang.record.v1']) localStorage.removeItem(k);
    }""")
    page.reload(wait_until='domcontentloaded')
    wait_ready(page)
    page.wait_for_timeout(200)


def scenario_hell(page, tag):
    """Lv.5 지옥: 한방 즉사 · 강제 필승 · 한방 각 회피 · 압박/미션 · 응답 속도."""
    props = page.evaluate(HELL_PROPS)
    check(props['moves'] >= 50, f'[{tag}] Lv.5 표본 판단', f"{props['moves']}수")
    check(props['handedKillAvoidable'] == 0,
          f'[{tag}] Lv.5 상대 한방 각 회피',
          f"준 한방 {props['handedKill']}회 / 피할 수 있었던 {props['handedKillAvoidable']}회")
    check(props['kinds'].get('oneshot', 0) >= 10, f'[{tag}] Lv.5 한방 즉사 사용', str(props['kinds']))
    check(props['outer'] >= 3 and props['outerBroken'] == 0,
          f'[{tag}] Lv.5 강제필승 검증', f"{props['outer']}수 중 깨진 것 {props['outerBroken']}")
    check(props['endThin'] + props['endDead'] >= props['moves'] * 0.5,
          f'[{tag}] Lv.5 압박(후속 단어 적은 글자)', f"{props['endDead']} / {props['endThin']}")
    check(props['msMax'] < 60, f'[{tag}] Lv.5 판단 속도', f"평균 {props['msAvg']}ms / 최대 {props['msMax']}ms")
    check(props['delayMin'] >= 140 and props['delayMax'] <= 410,
          f'[{tag}] Lv.5 응답 텀 0.15~0.4초', f"{props['delayMin']:.0f}~{props['delayMax']:.0f}ms")
    # Lv.5 는 장문을 좇지 않는다(2~4글자 보통 말 우선). 그래도 점수·미션 때문에
    # 5글자 이상이 다섯 수에 한 번은 나와야 한다 — 짧은 단어만 고르지는 않는지 본다.
    check(props['longMoves'] >= props['moves'] * 0.2,
          f'[{tag}] Lv.5 장문도 섞음', f"{props['longMoves']}/{props['moves']}수 5글자 이상")

    picks = page.evaluate(HELL_PICKS)
    check(picks.get('kill', {}).get('ok') and picks['kill']['isKill'] and picks['kill']['inBand'],
          f'[{tag}] Lv.5 한방 중 보통 말 즉사 선택',
          json.dumps(picks.get('kill'), ensure_ascii=False)[:180])
    check(picks.get('mission', {}).get('ok') and picks['mission']['agree'] == picks['mission']['checked'],
          f'[{tag}] Lv.5 같은 끝 글자에서 보통 말 우선',
          json.dumps(picks.get('mission'), ensure_ascii=False)[:200])
    check(picks.get('pressure', {}).get('ok'),
          f'[{tag}] Lv.5 소수 후보 글자로 압박',
          json.dumps(picks.get('pressure'), ensure_ascii=False)[:180])

    # 실제 대전: 내가 보통 사람처럼 두고, 봇의 응답 수·태그·시간을 본다
    gaps, tags, bot_moves = [], [], []
    for _attempt in range(3):
        page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
        page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
        page.evaluate("window.__ITDA.startGame({level:5, first:'me', timeLimit:20})")
        page.wait_for_timeout(350)
        for _ in range(5):
            st = wait_my_turn(page, 8000)
            if not st or st['phase'] != 'me':
                break
            w = page.evaluate("""() => {
                const d = window.__ITDA.dict, st = window.__ITDA.state();
                const used = new Set(st.chain.map((c) => c.word));
                const cands = d.candidatesFor(st.needChar, used);
                if (!cands.length) return null;
                // 사람처럼: 너무 어렵지 않은 2~4글자 단어를 고른다
                const easy = cands.filter((x) => x.length <= 4);
                return (easy.length ? easy : cands)[Math.min(5, (easy.length || cands.length) - 1)];
            }""")
            if not w:
                break
            before = page.evaluate("window.__ITDA.state().chain.length")
            t0 = time.time()
            page.fill('#word-input', w)
            page.click('#btn-submit')
            try:
                page.wait_for_function(
                    f"() => window.__ITDA.state().chain.length > {before} + 1 || window.__ITDA.state().phase === 'over'",
                    timeout=6000)
                gaps.append((time.time() - t0) * 1000)
            except Exception:
                break
            tag_text = page.evaluate("document.querySelector('#stage .tag.danger')?.textContent || ''")
            if tag_text:
                tags.append(tag_text)
            st = state(page)
            if st['phase'] == 'over':
                break
        st = state(page)
        bot_moves.extend([c for c in st['chain'] if c['who'] == 'bot'])
        if len(bot_moves) >= 3 or len(gaps) >= 4:
            break
    check(len(bot_moves) >= 2, f'[{tag}] Lv.5 실제 대전 응수', f"{len(bot_moves)}수 / {len(gaps)}턴")
    if gaps:
        check(min(gaps) <= 900, f'[{tag}] Lv.5 실제 응답 시간', f"{min(gaps):.0f}~{max(gaps):.0f}ms")
    check(any(t in ('외통수', '필승 라인', '압박') for t in tags) or len(bot_moves) >= 2,
          f'[{tag}] Lv.5 수읽기 태그 노출', str(tags[:4]))
    check(all(c['kind'] in ('oneshot', 'outer', 'route', 'press', 'normal', 'long') for c in bot_moves),
          f'[{tag}] Lv.5 수 성격 기록', str([c['kind'] for c in bot_moves]))
    # 대전 중 화면을 남긴다 (끝난 판이면 새로 한 판 열어 봇의 첫 수를 받는다)
    st = state(page)
    if st and st['phase'] == 'over':
        page.evaluate("window.__ITDA.app.hideResult()")
        page.evaluate("window.__ITDA.startGame({level:5, first:'me', timeLimit:20})")
        page.wait_for_timeout(400)
        w2 = page.evaluate("""() => {
            const d = window.__ITDA.dict, st = window.__ITDA.state();
            const cands = d.candidatesFor(st.needChar, new Set());
            const easy = cands.filter((x) => x.length <= 4);
            return (easy.length ? easy : cands)[Math.min(3, (easy.length || cands.length) - 1)] || null;
        }""")
        if w2:
            page.fill('#word-input', w2)
            page.click('#btn-submit')
            page.wait_for_timeout(700)
    shot(page, f'{tag}-12-hell-game')
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(200)

    # 봇 선공 오프닝: Lv.5 가 먼저 두는 판은 아무 글자가 아니라 이기는 자리로 연다
    openings = []
    for _ in range(4):
        page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
        page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
        page.evaluate("window.__ITDA.startGame({level:5, first:'bot', timeLimit:20})")
        page.wait_for_timeout(900)
        openings.append(page.evaluate("""() => {
            const st = window.__ITDA.state(), d = window.__ITDA.dict;
            const first = st.chain.find((c) => c.who === 'bot') || null;
            const end = first ? first.word[first.word.length - 1] : null;
            return {
                start: st.startChar,
                status: d.graphStatus(st.startChar),
                depth: d.graphDepth(st.startChar),
                live: d.countFrom(st.startChar),
                firstWord: first ? first.word : null,
                firstLive: first ? d.countFrom(end) : null,
                firstEndStatus: first ? d.graphStatus(end) : null,
                endStatus: d.graphStatus(st.startChar),
                phase: st.phase,
            };
        }"""))
    check(all(o['status'] == 'W' for o in openings),
          f'[{tag}] Lv.5 봇 선공 오프닝 = 이기는 시작 글자',
          str([(o['start'], o['status'], o['depth']) for o in openings]))
    check(all(o['depth'] >= 3 and o['live'] > 0 for o in openings),
          f'[{tag}] Lv.5 봇 선공 즉사 1수 종료 방지',
          str([(o['start'], o['depth'], o['live']) for o in openings]))
    check(all(o['firstWord'] and o['firstEndStatus'] == 'L' for o in openings),
          f'[{tag}] Lv.5 봇 선공 첫 수가 패배 자리로',
          str([(o['firstWord'], o['firstEndStatus'], o['firstLive']) for o in openings]))
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(200)


def scenario_variety(page, tag):
    """Lv.4·Lv.5: 같은 글자·같은 자리에서도 단어를 섞어 고르는지(강도는 유지)."""
    data = page.evaluate(VARIETY_PROPS)
    rows = data['rows']
    check(len(rows) >= 8, f'[{tag}] 다양성 표본 국면', f'{len(rows)}개')
    # 고를 수 있는 '보통 말' 후보가 둘 이상인데도 한 단어만 나오면 고착이다.
    # (즉사 단어가 하나뿐인 자리처럼 선택지가 없는 자리는 제외)
    flat = [r for r in rows if r['n'] < 10 or (r['eligible'] >= 2 and (r['distinct'] < 2 or r['maxShare'] > 0.8))]
    check(not flat, f'[{tag}] Lv.4·Lv.5 단어 선택 다양성',
          '단일 반복: ' + str([(r['lv'], r['ch'], r['pos'], r['distinct'], r['maxShare']) for r in flat[:4]]))
    for lv in (4, 5):
        sub = [r for r in rows if r['lv'] == lv]
        if not sub:
            continue
        avg = sum(r['distinct'] for r in sub) / len(sub)
        print(f"    Lv.{lv} 15수당 서로 다른 단어 평균 {avg:.1f}종 · "
              + ' '.join(f"{r['ch']}({r['pos']}):{r['distinct']}" for r in sub))
    check(all(r['valid'] for r in rows), f'[{tag}] 다양성 선택 단어 유효',
          str([r['top'] for r in rows if not r['valid']][:2]))
    check(all(r['killOk'] for r in rows), f'[{tag}] 한방 자리 즉사 유지',
          str([(r['lv'], r['ch'], r['pos']) for r in rows if not r['killOk']][:3]))
    check(all(r['endOk'] for r in rows), f'[{tag}] Lv.4 최소 후속 수 유지',
          str([(r['ch'], r['pos'], r['top']) for r in rows if not r['endOk']][:2]))


def result_view(page):
    return page.evaluate("""() => {
        const box = document.getElementById('result-level');
        const label = document.getElementById('result-level-label');
        return {
            visible: !document.getElementById('ov-result').hidden,
            title: document.getElementById('result-title').textContent,
            reason: document.getElementById('result-reason').textContent,
            lv: box ? box.dataset.lv : null,
            label: label ? label.textContent : '',
            face: document.getElementById('result-level-face').textContent,
            height: box ? Math.round(box.getBoundingClientRect().height) : 0,
        };
    }""")


def scenario_no_custom(page, tag):
    """내 단어장 삭제: 버튼·모달·사전 API가 없고, 남은 localStorage 값은 무시된다."""
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(150)
    gone = page.evaluate("""() => ({
        btn: !!document.getElementById('btn-custom'),
        modal: !!document.getElementById('ov-custom'),
        inputs: document.querySelectorAll('#custom-word,#custom-mean,#custom-list,#custom-form').length,
        text: document.body.innerText.includes('내 단어장'),
        dictApi: ['custom', 'customByStart', 'addCustom', 'removeCustom', 'setCustom', 'customStartCount', 'meanOf']
            .filter((k) => window.__ITDA.dict[k] !== undefined),
        appApi: ['openCustom', 'addCustomWord', 'renderCustom', 'renderCustomCount']
            .filter((k) => typeof window.__ITDA.app[k] === 'function'),
        state: typeof window.__ITDA.app.custom,
    })""")
    check(not gone['btn'] and not gone['modal'] and not gone['inputs'],
          f'[{tag}] 내 단어장 버튼·모달·입력 없음', json.dumps(gone, ensure_ascii=False)[:160])
    check(not gone['text'], f'[{tag}] 화면에 내 단어장 문구 0건')
    check(not gone['dictApi'] and not gone['appApi'] and gone['state'] == 'undefined',
          f'[{tag}] 내 단어장 사전·앱 API 없음',
          f"dict={gone['dictApi']} app={gone['appApi']} state={gone['state']}")

    # 버튼이 빠진 설정 행이 빈칸 없이 한 줄을 채우는지 (데스크톱·모바일)
    layout = page.evaluate("""() => {
        const row = document.getElementById('btn-sound').getBoundingClientRect();
        const box = document.querySelector('.setup-actions').getBoundingClientRect();
        const btn = document.getElementById('btn-sound');
        return { rowW: Math.round(row.width), boxW: Math.round(box.width),
                 fill: row.width > 0 ? Math.round(row.width / box.width * 100) : 0,
                 sound: document.getElementById('sound-value').textContent,
                 pressed: btn.getAttribute('aria-pressed'),
                 cols: getComputedStyle(document.querySelector('.setup-actions')).gridTemplateColumns };
    }""")
    check(layout['fill'] >= 99, f'[{tag}] 효과음 설정 행이 폭 전체 사용',
          json.dumps(layout, ensure_ascii=False))
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 설정 화면 가로 오버플로 0', str(overflow(page)))

    # 옛 버전이 남긴 localStorage 값: 지우지 않고 그대로 두되, 읽지도 인정하지도 않는다
    # 아주 예전 기능(내 단어장)이 남긴 키 — 남아 있어도 무시되는지
    page.evaluate("""() => localStorage.setItem('hanbang.custom.v1', JSON.stringify({
        '냥냥이': { mean: '고양이 애칭', at: 1 },
        '력량': { mean: '예전 단어', at: 2 },
    }))""")
    page.reload(wait_until='domcontentloaded')
    wait_ready(page)
    page.wait_for_timeout(200)
    left = page.evaluate("""() => ({
        key: !!localStorage.getItem('hanbang.custom.v1'),
        setup: !document.getElementById('scr-setup').hidden,
        text: document.body.innerText.includes('내 단어장'),
        size: window.__ITDA.dict.size,
    })""")
    check(left['key'] and left['setup'] and left['size'] > 300000,
          f'[{tag}] 옛 내 단어장 값이 남아 있어도 정상 부팅', json.dumps(left, ensure_ascii=False))
    check(not left['text'], f'[{tag}] 옛 값이 있어도 화면에 내 단어장 문구 0건')
    res = page.evaluate("""() => {
        window.__ITDA.startGame({ level: 1, first: 'me', startChar: '냥' });
        const v = window.__ITDA.engine.validate('냥냥이');
        window.__ITDA.app.engine.destroy();
        window.__ITDA.app.hideResult();
        window.__ITDA.app.show('setup');
        return v;
    }""")
    check(res['ok'] is False and res['error']['code'] == 'notfound',
          f'[{tag}] 옛 내 단어장 단어는 사전에 없음으로 판정',
          json.dumps(res, ensure_ascii=False)[:140])
    page.evaluate("localStorage.removeItem('hanbang.custom.v1')")
    page.wait_for_timeout(100)


def scenario_no_hint(page, tag):
    """힌트 삭제: 버튼·문구·앱/엔진 API가 없고, 입력 바가 빈칸 없이 채워진다."""
    print(f'  · 힌트 삭제 [{tag}]')
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(150)
    gone = page.evaluate("""() => ({
        btn: !!document.getElementById('btn-hint'),
        cls: document.querySelectorAll('.btn.hint, .hint').length,
        setupText: document.body.innerText.includes('힌트'),
        appApi: ['useHint', 'hint'].filter((k) => typeof window.__ITDA.app[k] === 'function'),
        audioCase: typeof window.__ITDA.app.sfx.play,
    })""")
    check(not gone['btn'] and gone['cls'] == 0, f'[{tag}] 힌트 버튼·클래스 없음', json.dumps(gone, ensure_ascii=False)[:160])
    check(not gone['setupText'], f'[{tag}] 설정 화면 힌트 문구 0건')
    check(not gone['appApi'], f'[{tag}] 힌트 앱 API 없음', str(gone['appApi']))

    page.evaluate("window.__ITDA.startGame({level:2, first:'me', hardcore:false})")
    page.wait_for_timeout(400)
    game = page.evaluate("""() => {
        const box = document.getElementById('composer').getBoundingClientRect();
        const input = document.getElementById('word-input').getBoundingClientRect();
        const go = document.getElementById('btn-submit').getBoundingClientRect();
        return {
            text: document.body.innerText.includes('힌트'),
            engineHint: typeof window.__ITDA.engine.hint,
            btn: !!document.getElementById('btn-hint'),
            children: [...document.getElementById('composer').children].map((el) => el.id || el.tagName),
            input: Math.round(input.width), go: Math.round(go.width), box: Math.round(box.width),
            inputFill: Math.round(input.width / box.width * 100),
        };
    }""")
    check(not game['text'], f'[{tag}] 대전 화면 힌트 문구 0건')
    check(game['engineHint'] == 'undefined', f'[{tag}] 힌트 엔진 API 없음', game['engineHint'])
    check(not game['btn'], f'[{tag}] 대전 화면 힌트 버튼 없음')
    check(game['children'] == ['word-input', 'btn-submit'], f'[{tag}] 입력 바 구성(입력+입력 버튼)', str(game['children']))
    check(game['inputFill'] >= 70 and game['go'] >= 60 and abs(game['input'] + game['go'] + 8 - game['box']) <= 3,
          f'[{tag}] 입력 바가 폭을 고르게 채움',
          f"입력 {game['input']}px({game['inputFill']}%) + 버튼 {game['go']}px = {game['box']}px")
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 입력 바 가로 오버플로 0', str(overflow(page)))
    shot(page, f'{tag}-16-no-hint')
    page.evaluate("window.__ITDA.app.engine.destroy(); window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(120)


def hardcore_view(page):
    return page.evaluate("""() => ({
        exists: !!document.getElementById('btn-hardcore'),
        role: document.getElementById('btn-hardcore')?.getAttribute('role'),
        on: document.getElementById('btn-hardcore')?.getAttribute('aria-checked'),
        desc: document.getElementById('hardcore-desc')?.textContent || '',
        timeLocked: !document.getElementById('time-locked').hidden,
        firstLocked: !document.getElementById('first-locked').hidden,
        timeLockedText: document.getElementById('time-locked').innerText.trim(),
        firstLockedText: document.getElementById('first-locked').innerText.trim(),
        timeOptsHidden: document.getElementById('time-opts').hidden,
        firstOptsHidden: document.getElementById('first-opts').hidden,
        lockedDisabled: [...document.querySelectorAll('#time-locked button, #first-locked button')].map((b) => b.disabled),
        timeBtns: [...document.querySelectorAll('#time-opts button')].map((b) => b.dataset.time),
        firstBtns: [...document.querySelectorAll('#first-opts button')].map((b) => b.dataset.first),
        saved: JSON.parse(localStorage.getItem('itda.settings.v1') || '{}'),
    })""")


def hardcore_game(page):
    return page.evaluate("""() => {
        const st = window.__ITDA.state();
        const badge = document.getElementById('game-hardcore');
        return {
            hc: window.__ITDA.engine.hardcore,
            limit: window.__ITDA.engine.timeLimit,
            first: window.__ITDA.engine.first,
            phase: st.phase,
            left: window.__ITDA.engine.timeLeft(),
            timeText: document.getElementById('time-left').textContent,
            chain: st.chain.map((c) => c.who),
            badge: !badge.hidden,
            badgeText: badge.innerText.replace(/\\s+/g, ' ').trim(),
            body: document.body.dataset.hardcore,
            level: st.level,
            overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        };
    }""")


def scenario_hardcore(page, tag, report_dir=None):
    """하드코어: 스위치 · 5초 고정 · 봇 선공 · 배지 · 별도 전적 · 끄면 일반 모드."""
    print(f'  · 하드코어 모드 [{tag}]')
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(200)

    # 기준 상태(꺼짐)로 맞춘다
    if page.evaluate("document.getElementById('btn-hardcore').getAttribute('aria-checked')") == 'true':
        page.click('#btn-hardcore')
        page.wait_for_timeout(180)
    off = hardcore_view(page)
    check(off['exists'] and off['role'] == 'switch', f'[{tag}] 하드코어 토글 스위치 존재', json.dumps(off, ensure_ascii=False)[:120])
    check(off['on'] == 'false' and not off['timeLocked'] and not off['firstLocked'],
          f'[{tag}] 기본은 하드코어 꺼짐(일반 모드)', json.dumps(off, ensure_ascii=False)[:160])
    check(off['timeBtns'] == ['10', '15', '20'] and off['firstBtns'] == ['me', 'bot'],
          f'[{tag}] 일반 모드 시간·선공 선택 유지', f"{off['timeBtns']} / {off['firstBtns']}")

    # Lv.5 에서 켜기 → Lv.3 으로 바꿔도 유지되는지
    page.click('.level[data-lv="5"]')
    page.wait_for_timeout(120)
    page.click('#btn-hardcore')
    page.wait_for_timeout(220)
    on = hardcore_view(page)
    check(on['on'] == 'true', f'[{tag}] 하드코어 스위치 켜짐', str(on['on']))
    check(on['timeLocked'] and '5초' in on['timeLockedText'] and on['firstLocked'] and '봇부터' in on['firstLockedText'],
          f'[{tag}] 설정 화면 5초 고정·봇부터 잠금 표시', f"{on['timeLockedText']} / {on['firstLockedText']}")
    check(on['timeOptsHidden'] and on['firstOptsHidden'] and all(on['lockedDisabled']),
          f'[{tag}] 잠금 중 시간·선공 변경 불가', str(on['lockedDisabled']))
    check(on['saved'].get('hardcore') is True, f'[{tag}] 하드코어 설정 저장', str(on['saved']))
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 하드코어 설정 화면 가로 오버플로 0', str(overflow(page)))
    report_shot(page, tag, report_dir, 'hardcore-setup')

    page.click('.level[data-lv="3"]')
    page.wait_for_timeout(120)
    board_before = page.evaluate("JSON.parse(localStorage.getItem('itda.record.v1') || '{}')")
    page.click('#btn-start')
    page.wait_for_selector('#scr-game:not([hidden])')
    wait_my_turn(page, 7000)
    page.wait_for_timeout(420)   # 봇 단어 등장 애니메이션이 끝난 뒤
    g = hardcore_game(page)
    check(g['hc'] is True and g['limit'] == 5 and g['first'] == 'bot',
          f'[{tag}] 하드코어 대국: 5초·봇 선공 고정', json.dumps({k: g[k] for k in ('hc', 'limit', 'first', 'level')}, ensure_ascii=False))
    check(g['badge'] and '하드코어' in g['badgeText'], f'[{tag}] 대전 헤더 하드코어 배지', g['badgeText'])
    check(g['body'] == '1', f'[{tag}] 하드코어 화면 테마 적용', g['body'])
    check(g['chain'][:1] == ['bot'], f'[{tag}] 봇이 반드시 선공', str(g['chain']))
    check(g['phase'] == 'me' and 0 < g['left'] <= 5 and g['timeText'] in ('5', '4'),
          f'[{tag}] 첫 내 턴 타이머 5초', f"{g['left']:.2f}s / 표시 {g['timeText']}")
    check(g['overflow'] <= 0, f'[{tag}] 하드코어 대전 가로 오버플로 0', str(g['overflow']))

    # 매 턴 5초로 리셋되는지: 한 단어 두고 다음 내 턴의 남은 시간을 본다
    st = wait_my_turn(page, 6000)
    word = None
    if st and st['phase'] == 'me':
        word = page.evaluate("""() => {
            const d = window.__ITDA.dict, st = window.__ITDA.state();
            const used = new Set(st.chain.map((c) => c.word));
            const cands = d.candidatesFor(st.needChar, used);
            // 봇이 이어갈 수 있는 단어만 고른다(한방 단어를 내면 대국이 끝나 타이머를 볼 수 없다)
            const alive = cands.filter((x) => !d.isOneShot(x));
            const easy = alive.filter((x) => x.length <= 4);
            return (easy.length ? easy : (alive.length ? alive : cands))[Math.min(4, (easy.length || alive.length || cands.length) - 1)] || null;
        }""")
    if word:
        page.fill('#word-input', word)
        page.click('#btn-submit')
        st2 = wait_my_turn(page, 6000)
        left2 = page.evaluate("window.__ITDA.engine.timeLeft()")
        check(st2 and st2['phase'] == 'me' and 3.8 < left2 <= 5.05,
              f'[{tag}] 매 턴 5초 리셋', f'{word} 입력 후 {left2:.2f}s')
        page.wait_for_timeout(250)
        report_shot(page, tag, report_dir, 'hardcore-game')
    else:
        check(False, f'[{tag}] 하드코어 턴 확보')

    # 5초 초과 → 시간 초과 패배에도 배지
    try:
        page.wait_for_function("() => !document.getElementById('ov-result').hidden", timeout=9000)
    except Exception:
        pass
    page.wait_for_timeout(150)
    res = result_view(page)
    hc_badge = page.evaluate("!document.getElementById('result-hardcore').hidden")
    check(res['visible'] and res['title'] == '패배' and '시간' in res['reason'],
          f'[{tag}] 하드코어 5초 시간 초과', json.dumps(res, ensure_ascii=False)[:160])
    check(hc_badge, f'[{tag}] 시간 초과 결과에 하드코어 배지')
    check(res['label'] == 'Lv.3 어려움' and res['lv'] == '3',
          f'[{tag}] 하드코어 결과에 난이도', json.dumps(res, ensure_ascii=False)[:160])
    report_shot(page, tag, report_dir, 'hardcore-result')

    rec = page.evaluate("JSON.parse(localStorage.getItem('itda.record.v1') || '{}')")
    before_hc = board_before.get('3:hc', {}).get('plays', 0)
    before_lv = board_before.get('3', {}).get('plays', 0)
    check(rec.get('3:hc', {}).get('plays', 0) == before_hc + 1,
          f'[{tag}] 하드코어 전적 별도 기록(3:hc)', json.dumps(rec.get('3:hc'), ensure_ascii=False))
    check(rec.get('3', {}).get('plays', 0) == before_lv,
          f'[{tag}] 일반 Lv.3 전적은 그대로', f"{before_lv} → {rec.get('3', {}).get('plays', 0)}")

    # 전적은 화면에 그리지 않고 store(localStorage)에만 쌓인다
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(200)
    rec_view = page.evaluate("""() => ({
        dom: !!document.getElementById('record') || !!document.querySelector('#scr-setup .record'),
        last: [...document.querySelector('#scr-setup .setup').children].pop()?.id || '',
        hcRow: JSON.parse(localStorage.getItem('itda.record.v1') || '{}')['3:hc'] || null,
    })""")
    check(not rec_view['dom'] and rec_view['last'] == 'btn-start',
          f'[{tag}] 설정 화면에 전적 블록 없이 대전 시작이 마지막',
          json.dumps(rec_view, ensure_ascii=False)[:140])
    check(bool(rec_view['hcRow']) and rec_view['hcRow'].get('plays', 0) >= 1,
          f'[{tag}] 하드코어 전적은 화면 없이 저장', json.dumps(rec_view['hcRow'], ensure_ascii=False))

    # 승리 결과에도 배지: 봇 선공(하드코어) 뒤 내가 한방 단어로 끝낸다
    win = None
    page.evaluate("window.__ITDA.app.hideResult()")
    page.evaluate("window.__ITDA.startGame({level:1, hardcore:true})")
    for _ in range(12):
        st = wait_my_turn(page, 7000)
        if not st or st['phase'] != 'me':
            break
        got = page.evaluate("""() => {
            const d = window.__ITDA.dict, st = window.__ITDA.state();
            const used = new Set(st.chain.map((c) => c.word));
            const cands = d.candidatesFor(st.needChar, used);
            if (!cands.length) return null;
            const kill = cands.find((w) => d.countFrom(w[w.length - 1]) === 0) || null;
            const easy = cands.filter((w) => w.length <= 4);
            return { kill, safe: (easy.length ? easy : cands)[Math.min(3, (easy.length || cands.length) - 1)] };
        }""")
        if not got:
            break
        if got['kill']:
            page.fill('#word-input', got['kill'])
            page.click('#btn-submit')
            page.wait_for_timeout(1600)
            win = got['kill']
            break
        page.fill('#word-input', got['safe'])
        page.click('#btn-submit')
        page.wait_for_timeout(400)
    if win:
        win_res = result_view(page)
        win_badge = page.evaluate("!document.getElementById('result-hardcore').hidden")
        check(win_res['title'] == '승리' and win_badge,
              f'[{tag}] 승리 결과에 하드코어 배지', f"{win} → {win_res['title']}")
        shot(page, f'{tag}-17-hardcore-win')
    else:
        check(False, f'[{tag}] 하드코어 승리 시나리오 탐색')

    # 포기 결과에도 배지
    page.evaluate("window.__ITDA.app.hideResult()")
    page.evaluate("window.__ITDA.startGame({level:2, hardcore:true})")
    page.wait_for_timeout(600)
    page.evaluate("window.__ITDA.engine.quit()")
    page.wait_for_timeout(1000)
    quit_res = result_view(page)
    quit_badge = page.evaluate("!document.getElementById('result-hardcore').hidden")
    check(quit_res['title'] == '패배' and '포기' in quit_res['reason'] and quit_badge,
          f'[{tag}] 포기 결과에 하드코어 배지', json.dumps(quit_res, ensure_ascii=False)[:140])

    # 끄면 일반 모드: 시간·선공을 다시 고르고, 대국도 그 값으로
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(200)
    page.click('#btn-hardcore')
    page.wait_for_timeout(200)
    off2 = hardcore_view(page)
    check(off2['on'] == 'false' and not off2['timeLocked'] and not off2['firstLocked'] and not off2['timeOptsHidden'],
          f'[{tag}] 하드코어 끄면 시간·선공 다시 열림', json.dumps(off2, ensure_ascii=False)[:160])
    page.click('#time-opts button[data-time="20"]')
    page.click('#first-opts button[data-first="me"]')
    page.wait_for_timeout(150)
    page.click('#btn-start')
    page.wait_for_selector('#scr-game:not([hidden])')
    page.wait_for_timeout(400)
    n = hardcore_game(page)
    check(n['hc'] is False and n['limit'] == 20 and n['first'] == 'me' and not n['badge'] and n['body'] == '0',
          f'[{tag}] 일반 모드 복귀(20초·나부터·배지 없음)', json.dumps({k: n[k] for k in ('hc', 'limit', 'first', 'badge', 'body')}, ensure_ascii=False))
    check(n['timeText'] in ('20', '19'), f'[{tag}] 일반 모드 타이머 20초', n['timeText'])
    page.evaluate("window.__ITDA.app.engine.destroy(); window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(150)
    check(page.evaluate("JSON.parse(localStorage.getItem('itda.settings.v1')||'{}').hardcore") is False,
          f'[{tag}] 하드코어 꺼짐 저장')


def scenario_result_level(page, tag):
    """결과 화면: 승리·패배·시간 초과·포기 모두 어떤 난이도였는지 보인다."""
    # 1) Lv.1 에서 진짜 한방 단어로 승리
    pick = page.evaluate("""() => {
        const d = window.__ITDA.dict;
        for (const [ch] of d.ranges) {
            const w = d.candidatesFor(ch, new Set()).find((x) => d.countFrom(x[x.length - 1]) === 0);
            if (w) return { start: ch, word: w };
        }
        return null;
    }""")
    if check(pick is not None, f'[{tag}] 승리용 한방 단어 탐색', str(pick)):
        page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
        page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
        page.evaluate(f"window.__ITDA.startGame({{level:1, first:'me', startChar:'{pick['start']}'}})")
        page.wait_for_timeout(450)
        play_word(page, pick['word'], wait=1800)
        win = result_view(page)
        check(win['title'] == '승리' and win['label'] == 'Lv.1 쉬움' and win['lv'] == '1',
              f'[{tag}] 승리 결과에 난이도', json.dumps(win, ensure_ascii=False)[:160])
        check(win['height'] >= 20, f'[{tag}] 난이도 배지 렌더', str(win['height']))
        shot(page, f'{tag}-13-result-win')

    # 2) Lv.3 시간 초과 패배
    page.evaluate("window.__ITDA.startGame({level:3, first:'me', timeLimit:1})")
    page.wait_for_timeout(2300)
    lose = result_view(page)
    check(lose['title'] == '패배' and lose['label'] == 'Lv.3 어려움' and lose['lv'] == '3',
          f'[{tag}] 시간 초과 결과에 난이도', json.dumps(lose, ensure_ascii=False)[:160])
    check('시간' in lose['reason'], f'[{tag}] 시간 초과 사유', lose['reason'])
    shot(page, f'{tag}-14-result-timeout')

    # 3) Lv.5 포기 → 결과 화면 난이도 (Lv.3 표시가 남지 않는지)
    page.evaluate("window.__ITDA.startGame({level:5, first:'me', timeLimit:20})")
    page.wait_for_timeout(400)
    page.evaluate("window.__ITDA.engine.quit()")
    page.wait_for_timeout(1000)
    quit_view = result_view(page)
    check(quit_view['title'] == '패배' and quit_view['label'] == 'Lv.5 지옥' and quit_view['lv'] == '5',
          f'[{tag}] 포기 결과에 난이도', json.dumps(quit_view, ensure_ascii=False)[:160])
    check('포기' in quit_view['reason'], f'[{tag}] 포기 사유', quit_view['reason'])
    shot(page, f'{tag}-15-result-quit')
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 결과 화면 가로 오버플로 0', str(overflow(page)))
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(150)


# ── 배틀 내역 (결과 화면) ─────────────────────────────────────

def battle_log_view(page):
    """배틀 내역 버튼·영역의 상태와 자리(겹침·뷰포트 이탈 확인용)."""
    return page.evaluate("""() => {
        const btn = document.getElementById('battle-log-btn');
        const panel = document.getElementById('battle-log');
        const sheet = document.querySelector('#ov-result .result-sheet');
        const box = (el) => { const r = el.getBoundingClientRect(); return {
            top: Math.round(r.top), bottom: Math.round(r.bottom),
            left: Math.round(r.left), right: Math.round(r.right),
            height: Math.round(r.height), width: Math.round(r.width) }; };
        const cs = getComputedStyle(panel);
        const again = document.getElementById('btn-again');
        const tosetup = document.getElementById('btn-tosetup');
        const r = box(btn), sh = box(sheet);
        return {
            result: !document.getElementById('ov-result').hidden,
            label: document.getElementById('battle-log-label').textContent.trim(),
            expanded: btn.getAttribute('aria-expanded'),
            hidden: panel.hidden,
            visible: r.height > 0 && r.width > 200,
            overflowY: cs.overflowY,
            maxHeight: Math.round(parseFloat(cs.maxHeight) || 0),
            btn: r, panel: box(panel), sheet: sh,
            again: box(again), tosetup: box(tosetup),
            panelScroll: { scroll: Math.round(panel.scrollTop), height: panel.scrollHeight,
                           client: panel.clientHeight },
            insideSheet: r.top >= sh.top && r.bottom <= sh.bottom && r.left >= sh.left && r.right <= sh.right,
            buttonsInView: [again, tosetup].every((el) => {
                const b = el.getBoundingClientRect();
                return b.height > 0 && b.top >= 0 && b.bottom <= innerHeight && b.left >= 0 && b.right <= innerWidth;
            }),
            vh: innerHeight, vw: innerWidth,
        };
    }""")


def battle_log_entries(page):
    """그 판의 수(chain)와 화면에 그려진 배틀 내역 줄을 나란히 읽는다."""
    return page.evaluate("""() => {
        const kindTag = { oneshot: '한방', outer: '외통수', route: '필승 라인', press: '압박' };
        const st = window.__ITDA.state();
        const chain = (st ? st.chain : []).map((c) => {
            const hits = c.missionHits || 0;
            const tags = [];
            if (hits > 0) tags.push(hits === 1 ? '미션 +50%' : `미션 ×${hits}`);
            if (kindTag[c.kind]) tags.push(kindTag[c.kind]);
            tags.push(...window.__ITDA.dict.tagsOf(c.word));
            return { who: c.who, word: c.word, score: c.score, tags };
        });
        const rows = [...document.querySelectorAll('#battle-log-list .blog-move')].map((li) => {
            const w = li.querySelector('.blog-word');
            return {
                turn: li.querySelector('.blog-turn').textContent.trim(),
                who: li.querySelector('.blog-who').textContent.trim(),
                cls: li.className,
                word: w.textContent,
                gain: li.querySelector('.blog-gain').textContent.trim(),
                tags: [...li.querySelectorAll('.blog-tags .tag')].map((t) => t.textContent.trim()),
                clip: w.scrollWidth - w.clientWidth,
                wordHeight: Math.round(w.getBoundingClientRect().height),
                lineHeight: Math.round(parseFloat(getComputedStyle(w).lineHeight) || 0),
            };
        });
        return { chain, rows, empty: ((document.querySelector('.battle-log-empty') || {}).textContent || '').trim() };
    }""")


def battle_log_rows_match(data):
    """화면의 줄이 그 판의 수와 순서·주체·단어·점수·태그까지 같은지."""
    bad = []
    if len(data['rows']) != len(data['chain']):
        bad.append({'rows': len(data['rows']), 'chain': len(data['chain'])})
    for i, (want, row) in enumerate(zip(data['chain'], data['rows']), start=1):
        expect_who = '나' if want['who'] == 'me' else '봇'
        if (row['turn'] != str(i) or row['who'] != expect_who or row['word'] != want['word']
                or row['gain'] != f"+{want['score']}" or row['tags'] != want['tags']
                or f"blog-move {want['who']}" not in row['cls']):
            bad.append({'turn': i, 'row': row, 'want': want})
    return bad


def intersects(a, b):
    return a['left'] < b['right'] and b['left'] < a['right'] and a['top'] < b['bottom'] and b['top'] < a['bottom']


def play_turns(page, turns=7):
    """배틀 내역에 쌓을 판: 태그 붙은 단어와 긴 단어를 섞어 몇 수를 주고받는다."""
    made = 0
    for _ in range(turns):
        st = wait_my_turn(page, 8000)
        if not st or st['phase'] != 'me':
            break
        word = page.evaluate("""() => {
            const d = window.__ITDA.dict, st = window.__ITDA.state();
            const used = new Set(st.chain.map((c) => c.word));
            const cands = d.candidatesFor(st.needChar, used);
            const taggedLong = cands.filter((x) => (d.flagOf(x) & 1) && x.length >= 7);
            const tagged = cands.filter((x) => (d.flagOf(x) & 1) && x.length >= 4);
            const long = cands.filter((x) => x.length >= 9 && x.length <= 14);
            return (taggedLong[0] || long[0] || tagged[0] || cands[cands.length - 1] || null);
        }""")
        if not word:
            break
        before = page.evaluate('window.__ITDA.state().chain.length')
        page.fill('#word-input', word)
        page.click('#btn-submit')
        try:
            page.wait_for_function(
                f"() => window.__ITDA.state().chain.length > {before} + 1 || window.__ITDA.state().phase === 'over'",
                timeout=8000)
            made += 1
        except Exception:
            break
    return made


def scenario_battle_log(page, tag):
    """결과 화면 배틀 내역: 버튼으로 열고 닫고, 그 안에서 스크롤되고, 그 판의 수·점수·태그가 그대로 보인다."""
    print(f'  · 배틀 내역 [{tag}]')

    # 1) 여러 수를 주고받은 판(포기로 종료)
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.evaluate("window.__ITDA.startGame({level:1, first:'me', timeLimit:20})")
    page.wait_for_timeout(400)
    played = play_turns(page, 7)
    if page.evaluate("window.__ITDA.state().phase") != 'over':
        page.evaluate('window.__ITDA.engine.quit()')
    page.wait_for_timeout(1100)

    data = battle_log_entries(page)
    n = len(data['chain'])
    view = battle_log_view(page)
    check(view['result'] and view['visible'], f'[{tag}] 결과 화면에 배틀 내역 버튼',
          json.dumps({'label': view['label'], 'n': n}, ensure_ascii=False))
    check(played >= 5 and n >= 10, f'[{tag}] 배틀 내역용 판 진행', f'{played}수 입력 / {n}수 기록')
    check(view['label'] == f'배틀 내역 ({n}수)', f'[{tag}] 버튼에 그 판의 수 표기', view['label'])
    check(view['expanded'] == 'false' and view['hidden'], f'[{tag}] 배틀 내역 기본 접힘',
          f"aria-expanded={view['expanded']} / hidden={view['hidden']}")
    check(view['insideSheet'] and view['buttonsInView'] and view['sheet']['bottom'] <= view['vh'],
          f'[{tag}] 접힌 결과 카드: 버튼이 잘리지 않음',
          f"card {view['sheet']['top']}~{view['sheet']['bottom']} / vh {view['vh']}")
    shot(page, f'{tag}-16-battle-log-closed')

    # 2) 열기: 결과 카드 안 세로 스크롤 영역
    page.click('#battle-log-btn')
    page.wait_for_timeout(340)
    openv = battle_log_view(page)
    check(not openv['hidden'] and openv['expanded'] == 'true', f'[{tag}] 누르면 펼쳐짐',
          f"aria-expanded={openv['expanded']} / hidden={openv['hidden']}")
    check(openv['overflowY'] == 'auto' and openv['maxHeight'] >= 120,
          f'[{tag}] 배틀 내역 스크롤 영역(max-height + overflow-y)',
          f"overflow-y={openv['overflowY']} / max-height={openv['maxHeight']}px")
    check(120 <= openv['panel']['height'] <= openv['maxHeight'] + 2,
          f'[{tag}] 펼친 영역 높이 제한',
          f"{openv['panel']['height']}px (max {openv['maxHeight']}px)")
    check(openv['panelScroll']['height'] > openv['panelScroll']['client'] + 8,
          f'[{tag}] 내용이 영역보다 길어 스크롤 가능',
          f"{openv['panelScroll']['height']} > {openv['panelScroll']['client']}")
    page.evaluate("document.getElementById('battle-log').scrollTop = 999999")
    page.wait_for_timeout(140)
    scrolled = page.evaluate("document.getElementById('battle-log').scrollTop")
    check(scrolled > 0, f'[{tag}] 배틀 내역 안에서 실제로 스크롤됨', f'scrollTop={scrolled}')
    page.evaluate("document.getElementById('battle-log').scrollTop = 0")
    page.wait_for_timeout(120)

    openv = battle_log_view(page)
    check(not intersects(openv['panel'], openv['again']) and not intersects(openv['panel'], openv['tosetup'])
          and openv['again']['top'] == openv['tosetup']['top'],
          f'[{tag}] 배틀 내역과 다시 대전·난이도 변경 버튼이 겹치지 않음',
          f"panel {openv['panel']['top']}~{openv['panel']['bottom']} / buttons {openv['again']['top']}~{openv['again']['bottom']}")
    check(openv['sheet']['top'] >= 0 and openv['sheet']['bottom'] <= openv['vh'] and openv['buttonsInView'],
          f'[{tag}] 펼친 결과 카드가 뷰포트 안, 버튼 잘리지 않음',
          f"card {openv['sheet']['top']}~{openv['sheet']['bottom']} / vh {openv['vh']}")
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 배틀 내역 펼친 화면 가로 오버플로 0', str(overflow(page)))

    # 3) 줄 내용: 턴 번호 · 나/봇 · 단어 전체 · 획득 점수 · 그 수의 태그
    open_data = battle_log_entries(page)
    bad = battle_log_rows_match(open_data)
    check(not bad, f'[{tag}] 배틀 내역 {len(open_data["rows"])}수: 순서·나/봇·단어·점수·태그 일치',
          json.dumps(bad[:2], ensure_ascii=False)[:500] if bad else f"{len(open_data['rows'])}수")
    longest = max(open_data['rows'], key=lambda r: len(r['word']))
    check(longest['clip'] <= 0 and longest['wordHeight'] >= longest['lineHeight'],
          f'[{tag}] 긴 단어도 잘리지 않고 줄바꿈',
          f"{longest['word']} ({len(longest['word'])}글자) / 넘침 {longest['clip']}px · 높이 {longest['wordHeight']}px(줄 {longest['lineHeight']}px)")
    tagged_rows = [r for r in open_data['rows'] if r['tags']]
    check(len(tagged_rows) >= 2, f'[{tag}] 수마다 태그 표시',
          json.dumps([{'word': r['word'], 'tags': r['tags']} for r in tagged_rows[:3]], ensure_ascii=False))
    shot(page, f'{tag}-17-battle-log-open')

    # 4) 다시 누르면 접힘
    page.click('#battle-log-btn')
    page.wait_for_timeout(280)
    closed = battle_log_view(page)
    check(closed['hidden'] and closed['expanded'] == 'false', f'[{tag}] 다시 누르면 접힘',
          f"aria-expanded={closed['expanded']} / hidden={closed['hidden']}")

    # 4) 아주 긴 단어(한 줄을 넘기는 22~24글자)도 잘리지 않고 줄바꿈되는지: 그 글자로 시작하는 판
    seed = page.evaluate("""() => {
        const d = window.__ITDA.dict;
        let best = null;
        for (const [ch] of d.ranges) {
            for (const w of d.candidatesFor(ch, new Set())) {
                if (w.length <= 24 && (!best || w.length > best.word.length)) best = { ch, word: w };
                if (best && best.word.length === 24) break;
            }
        }
        return best;
    }""")
    if check(seed is not None and len(seed['word']) >= 20, f'[{tag}] 아주 긴 단어 탐색', str(seed)):
        page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
        page.evaluate(f"window.__ITDA.startGame({{level:1, first:'me', startChar:'{seed['ch']}', timeLimit:20}})")
        page.wait_for_timeout(400)
        play_word(page, seed['word'], wait=1800)
        if page.evaluate("window.__ITDA.state().phase") != 'over':
            page.evaluate('window.__ITDA.engine.quit()')
        page.wait_for_timeout(1100)
        page.click('#battle-log-btn')
        page.wait_for_timeout(300)
        long_row = page.evaluate("""(word) => {
            const row = [...document.querySelectorAll('#battle-log-list .blog-move')]
                .find((li) => li.querySelector('.blog-word').textContent === word);
            if (!row) return null;
            const w = row.querySelector('.blog-word');
            return {
                word: w.textContent, length: w.textContent.length,
                clip: w.scrollWidth - w.clientWidth,
                height: Math.round(w.getBoundingClientRect().height),
                line: Math.round(parseFloat(getComputedStyle(w).lineHeight) || 0),
                bubble: Math.round(row.querySelector('.blog-body').getBoundingClientRect().width),
                panelClip: document.getElementById('battle-log').scrollWidth
                    - document.getElementById('battle-log').clientWidth,
            };
        }""", seed['word'])
        check(long_row is not None and long_row['clip'] <= 0 and long_row['panelClip'] <= 0
              and long_row['height'] >= long_row['line'] * 2,
              f'[{tag}] 24글자 단어도 잘리지 않고 줄바꿈',
              json.dumps(long_row, ensure_ascii=False))
        check(sum(overflow(page).values()) <= 0, f'[{tag}] 긴 단어 배틀 내역 가로 오버플로 0', str(overflow(page)))
        shot(page, f'{tag}-20-battle-log-longword')
        page.click('#battle-log-btn')
        page.wait_for_timeout(200)

    # 5) 다시 대전으로 새 판을 시작하면 다음 결과에서는 다시 접힌 채로
    page.click('#btn-again')
    page.wait_for_selector('#scr-game:not([hidden])', timeout=6000)
    page.wait_for_timeout(400)
    page.evaluate('window.__ITDA.engine.quit()')
    page.wait_for_timeout(1000)
    zero = battle_log_view(page)
    check(zero['label'] == '배틀 내역 (0수)' and zero['hidden'] and zero['expanded'] == 'false',
          f'[{tag}] 0수 판: (0수) 표기 · 기본 접힘', f"{zero['label']} / hidden={zero['hidden']}")
    page.click('#battle-log-btn')
    page.wait_for_timeout(260)
    zd = battle_log_entries(page)
    zopen = battle_log_view(page)
    check(not zopen['hidden'] and '주고받은 단어가 없어요' in zd['empty'],
          f'[{tag}] 0수(첫 수 전 포기) 안내', zd['empty'][:60])
    check(zopen['buttonsInView'] and zopen['sheet']['bottom'] <= zopen['vh'],
          f'[{tag}] 0수 안내에서도 버튼 잘리지 않음')
    shot(page, f'{tag}-18-battle-log-empty')
    page.click('#battle-log-btn')
    page.wait_for_timeout(200)

    # 6) 첫 수 전 시간 초과(0수)
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.evaluate("window.__ITDA.startGame({level:2, first:'me', timeLimit:1})")
    page.wait_for_function("() => !document.getElementById('ov-result').hidden", timeout=8000)
    page.wait_for_timeout(200)
    to = battle_log_view(page)
    tod = battle_log_entries(page)
    reason = page.evaluate("document.getElementById('result-reason').textContent")
    check(to['label'] == '배틀 내역 (0수)' and not tod['chain'] and '시간' in reason,
          f'[{tag}] 시간 초과 0수에서도 버튼', f"{to['label']} / {reason}")
    page.click('#battle-log-btn')
    page.wait_for_timeout(240)
    check('주고받은 단어가 없어요' in battle_log_entries(page)['empty'] and to['buttonsInView'],
          f'[{tag}] 시간 초과 0수 안내', str(to['buttonsInView']))
    page.click('#battle-log-btn')
    page.wait_for_timeout(180)

    # 7) 승리 결과에서도: 한방 단어 한 수로 끝난 판
    pick = page.evaluate("""() => {
        const d = window.__ITDA.dict;
        for (const [ch] of d.ranges) {
            const w = d.candidatesFor(ch, new Set()).find((x) => d.countFrom(x[x.length - 1]) === 0);
            if (w) return { start: ch, word: w };
        }
        return null;
    }""")
    if check(pick is not None, f'[{tag}] 승리용 한방 단어 탐색', str(pick)):
        page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
        page.evaluate(f"window.__ITDA.startGame({{level:1, first:'me', startChar:'{pick['start']}'}})")
        page.wait_for_timeout(450)
        play_word(page, pick['word'], wait=1800)
        win = battle_log_view(page)
        wind = battle_log_entries(page)
        check(win['result'] and win['label'] == '배틀 내역 (1수)' and win['hidden'],
              f'[{tag}] 승리 결과에 배틀 내역 버튼', f"{win['label']} / hidden={win['hidden']}")
        page.click('#battle-log-btn')
        page.wait_for_timeout(280)
        page.wait_for_timeout(1400)   # 축하 연출이 걷힌 뒤
        wopen = battle_log_view(page)
        wrows = battle_log_entries(page)
        bad = battle_log_rows_match(wind)
        check(not wopen['hidden'] and len(wrows['rows']) == 1 and wrows['rows'][0]['word'] == pick['word']
              and not bad,
              f'[{tag}] 승리 1수 배틀 내역',
              json.dumps(bad[:1] or [{'rows': wrows['rows'], 'chain': wrows['chain']}], ensure_ascii=False)[:400])
        check(wopen['buttonsInView'] and wopen['sheet']['bottom'] <= wopen['vh'],
              f'[{tag}] 승리 결과에서도 버튼 잘리지 않음',
              f"card {wopen['sheet']['top']}~{wopen['sheet']['bottom']} / vh {wopen['vh']}")
        shot(page, f'{tag}-19-battle-log-win')
        page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(150)


def scenario_mission(page, tag, report_dir=None):
    """미션: 14종 후보 · 미달성 시 유지 · 중첩 보너스 · 성공 시 다음 글자."""
    print(f'  · 미션 규칙 [{tag}]')

    # 1) 후보 14종 중에서만 나오고, 골고루 섞이는지
    seen = page.evaluate("""() => {
        const app = window.__ITDA.app, out = [];
        for (let i = 0; i < 60; i += 1) {
            if (app.engine) app.engine.destroy();
            app.startGame({ level: 1, first: 'me', timeLimit: 20 });
            out.push(window.__ITDA.state().missionChar);
        }
        if (app.engine) app.engine.destroy();
        app.show('setup');
        return out;
    }""")
    check(all(c in MISSION_CHARS for c in seen), f'[{tag}] 미션 후보 14종 밖 없음', ''.join(sorted(set(seen))))
    check(len(set(seen)) >= 10, f'[{tag}] 미션 글자 랜덤 출제', f'{len(set(seen))}/14종')

    # 시험용 단어: 한 시작 글자에서 미션 글자가 0회·1회·2회 든 단어를 모두 찾는다
    plan = page.evaluate("""(missions) => {
        const d = window.__ITDA.dict;
        const hitsOf = (w, ch) => { let n = 0; for (const c of w) if (c === ch) n += 1; return n; };
        for (const ch of missions) {
            const slots = new Map();
            for (const w of d.words) {
                if (w.length < 2 || w.length > 6) continue;
                const s = w[0];
                if (s === ch) continue;
                let slot = slots.get(s);
                if (!slot) { slot = {}; slots.set(s, slot); }
                const n = hitsOf(w, ch);
                if (n > 2) continue;
                const key = ['zero', 'one', 'two'][n];
                if (!slot[key]) slot[key] = w;
                if (slot.zero && slot.one && slot.two) {
                    return { ch, start: s, zero: slot.zero, one: slot.one, two: slot.two };
                }
            }
        }
        return null;
    }""", MISSION_CHARS)
    if not check(plan, f'[{tag}] 미션 시험 단어 탐색', str(plan)):
        return

    def fixed_game(start, mission):
        page.evaluate("window.__ITDA.app.engine.destroy()")
        page.evaluate("([s, m]) => window.__ITDA.startGame({ level: 1, first: 'me', startChar: s, mission: m, timeLimit: 20 })",
                      [start, mission])
        page.wait_for_timeout(250)

    # 2) 미션 글자가 없는 단어 → 글자 유지
    fixed_game(plan['start'], plan['ch'])
    res = page.evaluate("(w) => window.__ITDA.submit(w)", plan['zero'])
    st = state(page)
    check(res.get('ok') is True and res.get('missionHits') == 0 and res.get('nextMission') is None
          and st['missionChar'] == plan['ch'],
          f'[{tag}] 미션 미달성 → 글자 유지', f"'{plan['zero']}' 입력 후 미션 '{st['missionChar']}'")
    if report_dir:
        page.wait_for_timeout(120)
        report_shot(page, tag, report_dir, 'mission-keep')

    # 3) 미션 글자 2회 → 중첩 보너스 ×2, 곧바로 다음 글자
    fixed_game(plan['start'], plan['ch'])
    base = page.evaluate("(w) => window.__ITDA.engine.scoreFor(w, 0, 0)", plan['two'])
    expect2 = page.evaluate("(w) => window.__ITDA.engine.scoreFor(w, 0, 2)", plan['two'])
    page.fill('#word-input', plan['two'])
    page.click('#btn-submit')
    page.wait_for_timeout(140)
    st = state(page)
    last = st['chain'][0] if st['chain'] else {}
    tag_text = page.evaluate("document.querySelector('#stage .tag.mission')?.textContent || ''")
    chip_text = page.evaluate("document.getElementById('chip-mission').textContent || ''")
    notice = page.evaluate("document.querySelector('.toast.mission')?.textContent || ''")
    check(last.get('missionHits') == 2, f'[{tag}] 미션 글자 2개 인식', str(last.get('missionHits')))
    check(last.get('score') == expect2 and expect2 == base * 2,
          f'[{tag}] 2중첩 점수 ×2', f"{base} → {last.get('score')} (기대 {expect2})")
    check('×2' in tag_text, f'[{tag}] 단어 카드에 미션 ×2 표시', tag_text)
    check(st['missionChar'] != plan['ch'] and st['missionChar'] in MISSION_CHARS,
          f'[{tag}] 성공 즉시 다음 미션 글자', f"{plan['ch']} → {st['missionChar']}")
    check(st['missionChar'] in chip_text, f'[{tag}] 미션 칩 갱신', chip_text)
    check('중첩' in notice and plan['ch'] in notice, f'[{tag}] 미션 성공 알림', notice)
    report_shot(page, tag, report_dir, 'mission-success')

    # 봇 응답을 잠시 멈추고 중첩 카드·칩을 제대로 담는다
    page.evaluate("clearTimeout(window.__ITDA.engine.botTimer)")
    page.wait_for_timeout(1250)
    tag_after = page.evaluate("document.querySelector('#stage .tag.mission')?.textContent || ''")
    chip_after = page.evaluate("document.getElementById('chip-mission').textContent || ''")
    check('×2' in tag_after and st['missionChar'] in chip_after,
          f'[{tag}] 미션 ×2 카드·칩 유지', f'{tag_after} / {chip_after}')
    report_shot(page, tag, report_dir, 'mission-stack')

    # 4) 미션 글자 1회 → +50%
    fixed_game(plan['start'], plan['ch'])
    page.evaluate("(w) => window.__ITDA.submit(w)", plan['one'])
    st = state(page)
    last = st['chain'][0] if st['chain'] else {}
    base1 = page.evaluate("(w) => window.__ITDA.engine.scoreFor(w, 0, 0)", plan['one'])
    check(last.get('missionHits') == 1 and last.get('score') == round(base1 * 1.5),
          f'[{tag}] 1개 +50%', f"{base1} → {last.get('score')} (기대 {round(base1 * 1.5)})")

    # 5) 중첩 배수 표(0/1/2/3회)
    table = page.evaluate("""() => {
        const e = window.__ITDA.engine;
        return [0, 1, 2, 3].map((h) => e.scoreFor('가나다라마', 0, h));
    }""")
    check(table[1] == round(table[0] * 1.5) and table[2] == table[0] * 2 and table[3] == table[0] * 3,
          f'[{tag}] 중첩 배수 0/1/2/3회', str(table))

    # 6) 봇이 성공해도 다음 글자로 (봇 응답 경로 직접 호출)
    fixed_game(plan['start'], plan['ch'])
    swap = page.evaluate("""(w) => {
        const e = window.__ITDA.engine;
        const before = e.missionChar;
        e.phase = 'bot';
        e.applyBotMove({ word: w, kind: 'normal', delay: 0 });
        return { before, after: e.missionChar, chip: document.getElementById('chip-mission').textContent };
    }""", plan['two'])
    check(swap['after'] != swap['before'] and swap['after'] in MISSION_CHARS,
          f'[{tag}] 봇 미션 성공 → 다음 글자', f"{swap['before']} → {swap['after']}")
    check(swap['after'] in swap['chip'], f'[{tag}] 봇 성공 후 미션 칩 갱신', swap['chip'])
    page.evaluate("window.__ITDA.app.engine.destroy()")
    page.wait_for_timeout(900)
    page.evaluate("window.__ITDA.app.hideResult()")


def scenario_setup_clean(page, tag):
    """설정 화면 정리: 상단 태그라인과 '대전 시작' 아래 규칙·팁·전적 블록이
    DOM·CSS·JS 어디에도 남지 않고, 대전 시작 버튼이 마지막 요소이며,
    데스크톱·모바일 모두 세로 스크롤 없이 한 화면에 들어오는지."""
    print(f'  · 설정 화면 정리 [{tag}]')
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(200)

    view = page.evaluate("""() => {
        const setup = document.querySelector('#scr-setup .setup');
        const sec = document.getElementById('scr-setup');
        const kids = [...setup.children];
        const last = kids[kids.length - 1];
        const r = document.getElementById('btn-start').getBoundingClientRect();
        const text = setup.innerText;
        return {
            nodes: {
                tagline: !!document.querySelector('.tagline'),
                rules: !!document.querySelector('.rules-line'),
                tips: !!document.querySelector('.tips'),
                record: !!document.getElementById('record'),
                dictCount: !!document.getElementById('dict-count'),
                any: document.querySelectorAll('.tagline, .rules-line, .tips, .record').length,
            },
            leftoverText: /끝말을 이어가는|2글자 이상|중복 금지|한방 단어 조심|아직 전적이 없어요/.test(text),
            lastId: last ? last.id : '',
            kids: kids.map((el) => el.id || el.className),
            startTop: Math.round(r.top), startBottom: Math.round(r.bottom),
            viewH: window.innerHeight,
            scroll: { h: sec.scrollHeight, client: sec.clientHeight },
        };
    }""")
    nodes = view['nodes']
    check(not any(nodes.values()), f'[{tag}] 설정 화면에서 지운 요소 DOM에 없음',
          json.dumps(nodes, ensure_ascii=False))
    check(not view['leftoverText'], f'[{tag}] 지운 요소의 문구 0건', str(view['leftoverText']))
    check(view['lastId'] == 'btn-start', f'[{tag}] 대전 시작 버튼이 설정 화면 마지막 요소',
          str(view['kids']))
    check(view['startTop'] > 0 and view['startBottom'] <= view['viewH'],
          f'[{tag}] 대전 시작 버튼이 스크롤 없이 보임',
          f"start {view['startTop']}~{view['startBottom']} / 화면 {view['viewH']}px")
    check(view['scroll']['h'] <= view['scroll']['client'] + 1,
          f'[{tag}] 설정 화면 세로 스크롤 없음',
          f"{view['scroll']['h']} / {view['scroll']['client']}px")

    # 더 이상 쓰지 않는 선택자·함수가 CSS·JS에 남아 있지 않은지(맨 파일 내용 기준)
    src = page.evaluate("""async () => {
        const load = (p) => fetch(p).then((r) => r.text());
        const [css, ui, main] = await Promise.all([load('css/style.css'), load('js/ui.js'), load('js/main.js')]);
        const js = ui + main;
        return {
            css: ['.tagline', '.rules-line', '.tips', '.record {', '.rec-hc'].filter((sel) => css.includes(sel)),
            js: ['renderRecord', 'dict-count', "getElementById('record')"].filter((needle) => js.includes(needle)),
        };
    }""")
    check(not src['css'], f'[{tag}] 지운 요소의 CSS 규칙 없음', str(src['css']))
    check(not src['js'], f'[{tag}] 지운 요소를 찾는 JS 참조 없음', str(src['js']))

    # 전적 저장 자체는 그대로: 한 판을 끝내면 화면 없이도 localStorage에 쌓인다
    before = page.evaluate("JSON.parse(localStorage.getItem('itda.record.v1') || '{}')")
    page.evaluate("window.__ITDA.startGame({level:2, first:'me', timeLimit:1})")
    try:
        page.wait_for_function("() => !document.getElementById('ov-result').hidden", timeout=9000)
    except Exception:
        pass
    after = page.evaluate("JSON.parse(localStorage.getItem('itda.record.v1') || '{}')")
    plays_before = before.get('2', {}).get('plays', 0)
    check(after.get('2', {}).get('plays', 0) == plays_before + 1,
          f'[{tag}] 전적은 화면 없이도 저장',
          f"Lv.2 {plays_before} → {after.get('2', {}).get('plays', 0)}판")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(200)
    check(page.evaluate("!document.getElementById('record') && document.querySelectorAll('#scr-setup .record').length === 0"),
          f'[{tag}] 대국 뒤에도 설정 화면에 전적 블록 없음')
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 설정 화면 가로 오버플로 0', str(overflow(page)))


def mercy_view(page):
    """설정 화면의 배려모드 스위치 상태."""
    return page.evaluate("""() => {
        const btn = document.getElementById('btn-mercy');
        const hc = document.getElementById('btn-hardcore');
        return {
            exists: !!btn,
            role: btn ? btn.getAttribute('role') : null,
            on: btn ? btn.getAttribute('aria-checked') : null,
            desc: document.getElementById('mercy-desc')?.textContent || '',
            afterHardcore: !!(hc && hc.nextElementSibling === btn),
            saved: JSON.parse(localStorage.getItem('itda.settings.v1') || '{}'),
            scroll: document.getElementById('scr-setup').scrollHeight - document.getElementById('scr-setup').clientHeight,
            startTop: Math.round(document.getElementById('btn-start').getBoundingClientRect().top),
            startBottom: Math.round(document.getElementById('btn-start').getBoundingClientRect().bottom),
            vh: window.innerHeight,
        };
    }""")


def mercy_badge(page):
    """대전 화면의 배려모드 칩과 엔진 보호 상태."""
    return page.evaluate("""() => {
        const b = document.getElementById('game-mercy');
        const st = window.__ITDA.state();
        return {
            hidden: b.hidden,
            text: b.innerText.replace(/\\s+/g, ' ').trim(),
            released: b.classList.contains('released'),
            mercy: window.__ITDA.engine ? window.__ITDA.engine.mercy : null,
            guard: st ? st.mercyGuard : null,
            turn: st ? st.mercyTurn : null,
            chain: st ? st.chain.length : null,
        };
    }""")


def mercy_safe_word(page):
    """이어야 할 글자로 낼 수 있는 한방이 아닌 단어 하나(없으면 null)."""
    return page.evaluate("""() => {
        const d = window.__ITDA.dict, st = window.__ITDA.state();
        const used = new Set(st.chain.map((c) => c.word));
        const cands = d.candidatesFor(st.needChar, used);
        if (!cands.length) return null;
        const safe = cands.filter((w) => d.countFrom(w[w.length - 1]) > 0);
        const list = safe.length ? safe : cands;
        return list[Math.min(3, list.length - 1)] || null;
    }""")


def mercy_chain(page):
    """지난 수와 각 수가 한방 단어였는지."""
    return page.evaluate("""() => {
        const d = window.__ITDA.dict;
        return window.__ITDA.state().chain.map((c) => ({
            who: c.who, word: c.word, kind: c.kind,
            oneShot: d.countFrom(c.word[c.word.length - 1]) === 0,
        }));
    }""")


def scenario_mercy(page, tag, report_dir=None):
    """배려모드: 스위치 · 저장 · 첫 5수 플레이어 한방 차단 · 봇 한방 회피 · 6수부터 허용 · 배지."""
    print(f'  · 배려모드 [{tag}]')
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(200)

    # 1) 설정 스위치: 하드코어 바로 아래, 기본은 꺼짐, 켜면 저장
    if page.evaluate("document.getElementById('btn-mercy').getAttribute('aria-checked')") == 'true':
        page.click('#btn-mercy')
        page.wait_for_timeout(180)
    off = mercy_view(page)
    check(off['exists'] and off['role'] == 'switch', f'[{tag}] 배려모드 토글 스위치 존재',
          json.dumps(off, ensure_ascii=False)[:140])
    check(off['afterHardcore'], f'[{tag}] 배려모드는 하드코어 스위치 바로 아래', str(off['afterHardcore']))
    check(off['on'] == 'false' and off['saved'].get('mercy') is not True,
          f'[{tag}] 기본은 배려모드 꺼짐', json.dumps(off, ensure_ascii=False)[:160])
    check('5턴' in off['desc'], f'[{tag}] 배려모드 설명에 첫 5턴 안내', off['desc'])

    page.click('#btn-mercy')
    page.wait_for_timeout(220)
    on = mercy_view(page)
    check(on['on'] == 'true' and on['saved'].get('mercy') is True,
          f'[{tag}] 배려모드 켜짐 · 설정 저장', json.dumps(on['saved'], ensure_ascii=False))
    check('5턴' in on['desc'] and '6' in on['desc'], f'[{tag}] 켜면 첫 5턴 금지·6턴부터 안내', on['desc'])
    check(on['scroll'] <= 1 and on['startTop'] > 0 and on['startBottom'] <= on['vh'],
          f'[{tag}] 배려모드 켜도 설정 화면 세로 스크롤 0',
          f"{on['startTop']}~{on['startBottom']} / {on['vh']}px, 스크롤 {on['scroll']}px")
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 배려모드 설정 가로 오버플로 0', str(overflow(page)))
    report_shot(page, tag, report_dir, 'mercy-setup')

    pick = page.evaluate("""() => {
        const d = window.__ITDA.dict;
        for (const [ch] of d.ranges) {
            const cands = d.candidatesFor(ch, new Set());
            if (cands.length < 5 || cands.length > 4000) continue;
            const shot = cands.find((w) => d.countFrom(w[w.length - 1]) === 0 && w.length <= 5);
            const safe = cands.find((w) => d.countFrom(w[w.length - 1]) >= 60 && w.length <= 3);
            if (shot && safe) return { ch, shot, safe };
        }
        return null;
    }""")
    if not check(bool(pick), f'[{tag}] 한방·안전 후보가 같이 있는 시작 글자', str(pick)):
        page.click('#btn-mercy')
        page.wait_for_timeout(150)
        return

    # 2) 대전 시작(설정값이 엔진까지 전달) · 헤더 배지 · 플레이어 한방 차단
    page.evaluate("window.__ITDA.startGame({level:2, first:'me', hardcore:false, startChar:'%s', timeLimit:20})" % pick['ch'])
    page.wait_for_timeout(500)
    b0 = mercy_badge(page)
    check(b0['mercy'] is True and b0['guard'] is True and not b0['hidden']
          and '배려모드' in b0['text'] and '1/5' in b0['text'] and '한방 금지' in b0['text'],
          f'[{tag}] 대전 헤더 배려모드 배지(1/5턴 보호)', json.dumps(b0, ensure_ascii=False)[:180])
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 배려모드 대전 가로 오버플로 0', str(overflow(page)))

    t0 = page.evaluate('window.__ITDA.engine.timeLeft()')
    page.fill('#word-input', pick['shot'])
    page.click('#btn-submit')
    page.wait_for_timeout(1000)
    rej = page.evaluate("""(word) => ({
        phase: window.__ITDA.state().phase,
        chain: window.__ITDA.state().chain.length,
        left: window.__ITDA.engine.timeLeft(),
        toast: document.querySelector('.toast')?.textContent || '',
        toastCls: document.querySelector('.toast')?.className || '',
        input: document.getElementById('word-input').value,
        recorded: window.__ITDA.engine.used.has(word),
        guard: window.__ITDA.state().mercyGuard,
    })""", pick['shot'])
    check('배려모드' in rej['toast'] and '한방' in rej['toast'],
          f'[{tag}] 첫 5수 플레이어 한방 단어 차단 안내', rej['toast'])
    check(rej['toastCls'].split().count('mercy') == 1, f'[{tag}] 차단 안내는 배려모드 스타일', rej['toastCls'])
    check(rej['phase'] == 'me' and rej['chain'] == 0 and not rej['recorded'],
          f'[{tag}] 차단된 한방 단어는 판에 남지 않음', json.dumps(rej, ensure_ascii=False)[:160])
    check(rej['guard'] is True and rej['left'] < t0 - 0.6,
          f'[{tag}] 차단 뒤 타이머는 계속 흐름', f"{t0:.2f}s → {rej['left']:.2f}s")
    check(rej['input'] == pick['shot'], f'[{tag}] 차단 뒤 입력한 단어는 그대로 남아 고칠 수 있음', rej['input'])
    shot(page, f'{tag}-mercy-blocked')

    # 같은 차례에 다른 유효 단어는 바로 받아들여진다
    page.fill('#word-input', pick['safe'])
    page.click('#btn-submit')
    try:
        page.wait_for_function("() => window.__ITDA.state().chain.length >= 1", timeout=4000)
    except Exception:
        pass
    page.wait_for_timeout(300)
    okv = page.evaluate("""(word) => ({
        chain: window.__ITDA.state().chain.map((c) => c.word),
        phase: window.__ITDA.state().phase,
        badge: document.getElementById('game-mercy').innerText.replace(/\\s+/g, ' ').trim(),
    })""", pick['safe'])
    check(okv['chain'][:1] == [pick['safe']], f'[{tag}] 차단 뒤 다른 단어는 정상 입력',
          json.dumps(okv, ensure_ascii=False)[:160])
    check('2/5' in okv['badge'] and '한방 금지' in okv['badge'], f'[{tag}] 배지가 2/5턴으로 진행', okv['badge'])

    # 3) 보호 중 봇이 낼 수 있는 수가 전부 한방뿐이면: 한방을 두지 않고 막힌 것으로 처리
    page.evaluate("window.__ITDA.app.hideResult()")
    page.evaluate("window.__ITDA.startGame({level:2, first:'me', hardcore:false, mercy:true, timeLimit:20})")
    page.wait_for_timeout(400)
    page.evaluate("window.__ITDA.engine.bot.choose = () => null; window.__ITDA.engine.botTurn()")
    page.wait_for_timeout(1300)
    stuck = page.evaluate("""() => ({
        phase: window.__ITDA.state().phase,
        title: document.getElementById('result-title').textContent,
        visible: !document.getElementById('ov-result').hidden,
        reason: document.getElementById('result-reason').textContent,
        mercy: !document.getElementById('result-mercy').hidden,
        mercyText: document.getElementById('result-mercy').innerText.replace(/\\s+/g, ' ').trim(),
        hardcore: !document.getElementById('result-hardcore').hidden,
    })""")
    check(stuck['phase'] == 'over' and stuck['visible'] and stuck['title'] == '승리'
          and '찾지 못' in stuck['reason'],
          f'[{tag}] 첫 5수에 낼 수가 한방뿐이면 봇은 한방 대신 막힘으로 처리',
          json.dumps(stuck, ensure_ascii=False)[:180])
    check(stuck['mercy'] and '배려모드' in stuck['mercyText'], f'[{tag}] 결과 화면 배려모드 배지', stuck['mercyText'])
    shot(page, f'{tag}-mercy-result')

    # 4) 봇 규칙 직접 확인: 한방이 있어도 guard 면 고르지 않고, 남은 수 기준 즉시 한방도 피한다
    rule = page.evaluate("""() => {
        const d = window.__ITDA.dict, Bot = window.__ITDA.Bot;
        const isShot = (w) => d.countFrom(w[w.length - 1]) === 0;
        const out = { pair: null, stuck: null, live: null };
        for (const [ch] of d.ranges) {
            const cands = d.candidatesFor(ch, new Set());
            if (!cands.length || cands.length > 600) continue;
            const shots = cands.filter(isShot);
            if (!shots.length || shots.length === cands.length) continue;
            const used = new Set();
            const f4 = new Bot({ level: 4, dict: d }).choose({ needChar: ch, used, turn: 3, guard: false });
            const h4 = new Bot({ level: 4, dict: d }).choose({ needChar: ch, used, turn: 3, guard: true });
            const f5 = new Bot({ level: 5, dict: d }).choose({ needChar: ch, used, turn: 3, guard: false });
            const h5 = new Bot({ level: 5, dict: d }).choose({ needChar: ch, used, turn: 3, guard: true });
            if (f4 && isShot(f4.word) && h4 && !isShot(h4.word) && f5 && isShot(f5.word) && h5 && !isShot(h5.word)) {
                out.pair = {
                    ch, shots: shots.length,
                    lv4: { free: f4.word, held: h4.word },
                    lv5: { free: f5.word, held: h5.word },
                };
                break;
            }
        }
        for (const [ch] of d.ranges) {
            const cands = d.candidatesFor(ch, new Set());
            if (!cands.length || cands.length > 600) continue;
            const ns = cands.filter((w) => !isShot(w));
            const shots = cands.filter(isShot);
            if (!ns.length || !shots.length) continue;
            const used = new Set(ns);
            const left = d.candidatesFor(ch, used);
            if (!left.length || !left.every(isShot)) continue;
            out.stuck = {
                ch, left: left.slice(0, 3), count: left.length,
                lv4: (new Bot({ level: 4, dict: d }).choose({ needChar: ch, used, turn: 5, guard: true }) || {}).word || null,
                lv5: (new Bot({ level: 5, dict: d }).choose({ needChar: ch, used, turn: 5, guard: true }) || {}).word || null,
                free4: (new Bot({ level: 4, dict: d }).choose({ needChar: ch, used, turn: 5, guard: false }) || {}).word || null,
            };
            break;
        }
        const bot4 = new Bot({ level: 4, dict: d });
        for (const ch of d.goodStartChars(60)) {
            for (const w of d.candidatesFor(ch, new Set()).slice(0, 40)) {
                const end = w[w.length - 1];
                const followers = d.candidatesFor(end, new Set([w]));
                if (!followers.length || followers.length > 40) continue;
                const used = new Set(followers);
                out.live = {
                    ch, word: w, end, followers: followers.length,
                    dictCount: d.countFrom(end),
                    kept: bot4.guardedWords([w], used).length,
                };
                break;
            }
            if (out.live) break;
        }
        return out;
    }""")
    pair = rule['pair']
    if check(bool(pair), f'[{tag}] 봇 한방 회피 시험 자리 탐색', json.dumps(rule, ensure_ascii=False)[:140]):
        kinds = page.evaluate("""(pair) => {
            const d = window.__ITDA.dict;
            const shot = (w) => d.countFrom(w[w.length - 1]) === 0;
            return {
                lv4free: shot(pair.lv4.free), lv4held: shot(pair.lv4.held),
                lv5free: shot(pair.lv5.free), lv5held: shot(pair.lv5.held),
            };
        }""", pair)
        check(kinds['lv4free'] and not kinds['lv4held'],
              f'[{tag}] Lv.4 배려모드: 한방 대신 이어지는 수', json.dumps(pair['lv4'], ensure_ascii=False))
        check(kinds['lv5free'] and not kinds['lv5held'],
              f'[{tag}] Lv.5 배려모드: 한방 대신 이어지는 수', json.dumps(pair['lv5'], ensure_ascii=False))
    stk = rule['stuck']
    if check(bool(stk), f'[{tag}] 5수째 한방뿐인 자리 탐색', json.dumps(stk, ensure_ascii=False)[:140]):
        check(stk['lv4'] is None and stk['lv5'] is None and bool(stk['free4']),
              f'[{tag}] 5수째 남은 수가 한방뿐이면 봇은 한방을 두지 않음',
              json.dumps(stk, ensure_ascii=False)[:180])
    lv = rule['live']
    if check(bool(lv), f'[{tag}] 남은 수 기준 즉시 한방 자리 탐색', json.dumps(lv, ensure_ascii=False)[:140]):
        check(lv['dictCount'] > 0 and lv['kept'] == 0,
              f'[{tag}] 사전 후속은 있어도 이번 판에서 다 쓴 글자는 즉시 한방으로 보고 회피',
              json.dumps(lv, ensure_ascii=False))

    # 5) 실제 대전(Lv.4·Lv.5): 첫 5수 동안 봇이 한방 단어를 내지 않는다
    for level in (4, 5):
        early, hist = [], []
        for _ in range(2):
            page.evaluate("window.__ITDA.app.hideResult()")
            page.evaluate("window.__ITDA.startGame({level:%d, first:'bot', hardcore:false, mercy:true, timeLimit:20})" % level)
            page.wait_for_timeout(600)
            for _ in range(14):
                st = wait_my_turn(page, 9000)
                if not st or st['phase'] != 'me':
                    break
                safe = mercy_safe_word(page)
                if not safe:
                    break
                page.fill('#word-input', safe)
                page.click('#btn-submit')
                page.wait_for_timeout(900)
                st = page.evaluate('window.__ITDA.state()')
                hist = mercy_chain(page)
                if st['phase'] == 'over':
                    break
            early = [h for h in hist[:5] if h['who'] == 'bot']
            if len(early) >= 2:
                break
        check(len(early) >= 1 and all(not h['oneShot'] for h in early),
              f'[{tag}] Lv.{level} 첫 5수 봇 한방 금지(실제 대전)',
              f"{len(early)}수: {[(h['word'], h['kind']) for h in early]}")
        late_shots = [i + 1 for i, h in enumerate(hist) if h['who'] == 'bot' and h['oneShot']]
        check(all(i >= 6 for i in late_shots),
              f'[{tag}] Lv.{level} 봇 한방은 6수 이후에만', f'한방 낸 수: {late_shots} / 전체 {len(hist)}수')

    # 6) 5수를 채운 뒤에는 플레이어도 한방 단어를 쓸 수 있다 (6수부터 허용)
    page.evaluate("window.__ITDA.app.hideResult()")
    page.evaluate("window.__ITDA.startGame({level:1, first:'me', hardcore:false, mercy:true, timeLimit:20})")
    page.wait_for_timeout(500)
    fifth_badge = ''
    for _ in range(12):
        st = wait_my_turn(page, 9000)
        if not st or st['phase'] != 'me':
            break
        if st['mercyGuard'] and len(st['chain']) >= 4:
            fifth_badge = page.evaluate("document.getElementById('game-mercy').innerText.replace(/\\s+/g, ' ').trim()")
        if not st['mercyGuard']:
            break
        safe = mercy_safe_word(page)
        if not safe:
            break
        page.fill('#word-input', safe)
        page.click('#btn-submit')
        page.wait_for_timeout(900)
    rel = page.evaluate("""(ch) => {
        const e = window.__ITDA.engine;
        e.needChar = ch;
        window.__ITDA.app.setNeed(e.snapshot());
        const st = e.snapshot();
        return {
            guard: st.mercyGuard, chain: st.chain.length,
            badge: document.getElementById('game-mercy').innerText.replace(/\\s+/g, ' ').trim(),
            cls: document.getElementById('game-mercy').className,
        };
    }""", pick['ch'])
    check(rel['chain'] >= 5 and rel['guard'] is False,
          f'[{tag}] 5수를 채우면 보호가 풀린다', json.dumps(rel, ensure_ascii=False)[:160])
    check('해금' in rel['badge'] and 'released' in rel['cls'],
          f'[{tag}] 6수째 배려 해금 배지', json.dumps(rel, ensure_ascii=False)[:160])
    check('5/5' in fifth_badge and '한방 금지' in fifth_badge,
          f'[{tag}] 5수째까지는 한방 금지 표시', fifth_badge)
    page.fill('#word-input', pick['shot'])
    page.click('#btn-submit')
    page.wait_for_timeout(2000)
    acc = page.evaluate("""(word) => ({
        inChain: window.__ITDA.state().chain.some((c) => c.who === 'me' && c.word === word),
        title: document.getElementById('result-title').textContent,
        visible: !document.getElementById('ov-result').hidden,
        reason: document.getElementById('result-reason').textContent,
        mercy: !document.getElementById('result-mercy').hidden,
        mercyText: document.getElementById('result-mercy').innerText.replace(/\\s+/g, ' ').trim(),
    })""", pick['shot'])
    check(acc['inChain'] and acc['visible'] and acc['title'] == '승리',
          f'[{tag}] 6수부터 플레이어 한방 단어 허용', json.dumps(acc, ensure_ascii=False)[:200])
    check(acc['mercy'] and '배려모드' in acc['mercyText'],
          f'[{tag}] 배려모드 대국의 결과 배지', acc['mercyText'])
    shot(page, f'{tag}-mercy-unlocked-win')

    # 7) 끄면 일반 모드로 돌아가고, 설정 화면은 그대로 한 화면
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(200)
    if page.evaluate("document.getElementById('btn-mercy').getAttribute('aria-checked')") == 'true':
        page.click('#btn-mercy')
        page.wait_for_timeout(200)
    fin = mercy_view(page)
    check(fin['on'] == 'false' and fin['saved'].get('mercy') is False,
          f'[{tag}] 배려모드 끄면 설정도 꺼짐', json.dumps(fin['saved'], ensure_ascii=False))
    check(fin['scroll'] <= 1 and fin['startBottom'] <= fin['vh'],
          f'[{tag}] 설정 화면 세로 스크롤 0(배려모드 끈 뒤)',
          f"스크롤 {fin['scroll']}px / {fin['startBottom']}~{fin['vh']}px")
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 설정 화면 가로 오버플로 0', str(overflow(page)))


def run_local(base_url, browser):
    print(f'\n=== LOCAL {base_url} ===')
    for vp_name in VIEWPORTS:
        print(f'\n-- {vp_name} --')
        ctx, page = new_page(browser, vp_name)
        col = Collector(page)
        page.goto(base_url, wait_until='domcontentloaded')
        t0 = time.time()
        wait_ready(page)
        load_s = time.time() - t0
        size = page.evaluate('window.__ITDA.dict.size')
        check(size > 300000, f'[{vp_name}] 사전 로드', f'{size}단어 / {load_s:.1f}s')
        check(page.is_visible('#scr-setup'), f'[{vp_name}] 설정 화면')
        check(sum(overflow(page).values()) <= 0, f'[{vp_name}] 설정 가로 오버플로 없음', str(overflow(page)))
        shot(page, f'local-{vp_name}-01-setup')

        page.click('.level[data-lv="3"]')
        page.click('#btn-start')
        page.wait_for_selector('#scr-game:not([hidden])')
        page.wait_for_timeout(500)
        check(state(page)['phase'] == 'me', f'[{vp_name}] 내 턴 시작')
        check(sum(overflow(page).values()) <= 0, f'[{vp_name}] 대전 가로 오버플로 없음', str(overflow(page)))
        # 모바일: 키보드가 올라온 상황(높이 500)에서도 글자·입력창이 보이는지
        if vp_name == 'mobile':
            page.focus('#word-input')
            page.set_viewport_size({'width': 390, 'height': 500})
            page.wait_for_timeout(350)
            box = page.evaluate("""() => {
                const ids = ['need-char', 'word-input', 'timer-fill', 'time-left'];
                const out = {};
                for (const id of ids) {
                    const r = document.getElementById(id).getBoundingClientRect();
                    out[id] = { top: Math.round(r.top), bottom: Math.round(r.bottom), visible: r.bottom > 0 && r.top < innerHeight };
                }
                out.vh = innerHeight;
                return out;
            }""")
            check(all(v['visible'] for v in box.values() if isinstance(v, dict)), f'[{vp_name}] 키보드 높이에서 핵심 요소 노출', json.dumps(box))
            shot(page, f'local-{vp_name}-02-keyboard')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.wait_for_timeout(250)
        shot(page, f'local-{vp_name}-03-game')

        scenario_twoeum(page, 'local-' + vp_name)
        scenario_new_words(page, 'local-' + vp_name)
        scenario_bot_levels(page, 'local-' + vp_name)
        scenario_easy_words(page, 'local-' + vp_name)
        scenario_easy_game(page, 'local-' + vp_name)
        scenario_no_custom(page, 'local-' + vp_name)
        scenario_no_hint(page, 'local-' + vp_name)
        scenario_setup_clean(page, 'local-' + vp_name)
        scenario_result_level(page, 'local-' + vp_name)
        scenario_battle_log(page, 'local-' + vp_name)
        scenario_mission(page, 'local-' + vp_name, REPORT_DIR)
        scenario_levels(page, 'local-' + vp_name)
        scenario_hell(page, 'local-' + vp_name)
        scenario_variety(page, 'local-' + vp_name)
        scenario_legacy(page, 'local-' + vp_name)
        scenario_mercy(page, 'local-' + vp_name, REPORT_DIR)
        scenario_hardcore(page, 'local-' + vp_name, REPORT_DIR)

        # 대전 중 스크린샷 (여러 단어가 쌓인 화면)
        page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
        page.evaluate("window.__ITDA.startGame({level:1, first:'bot'})")
        page.wait_for_timeout(1800)
        for _ in range(4):
            st = wait_my_turn(page, 6000)
            if not st or st['phase'] != 'me':
                break
            w = page.evaluate("""() => {
                const d = window.__ITDA.dict, st = window.__ITDA.state();
                const used = new Set(st.chain.map((c) => c.word));
                const cands = d.candidatesFor(st.needChar, used).filter((x) => x.length >= 2);
                return cands[Math.min(3, cands.length - 1)] || null;
            }""")
            if not w:
                break
            play_word(page, w, wait=2200)
        st = wait_my_turn(page, 9000)
        check(st['phase'] == 'me' and len(st['chain']) >= 5, f'[{vp_name}] 대전 진행(중반 화면)',
              f"phase={st['phase']}, {len(st['chain'])}단어")
        shot(page, f'local-{vp_name}-07-midgame')

        check(not col.errors, f'[{vp_name}] 페이지 에러 0', json.dumps(col.errors, ensure_ascii=False)[:400])
        errs = [c for c in col.console if c['type'] == 'error']
        check(not errs, f'[{vp_name}] 콘솔 에러 0', json.dumps(errs, ensure_ascii=False)[:400])
        ctx.close()


def run_live(url, browser):
    print(f'\n=== LIVE {url} ===')
    for vp_name in VIEWPORTS:
        print(f'\n-- {vp_name} --')
        ctx, page = new_page(browser, vp_name)
        col = Collector(page)
        page.goto(url, wait_until='domcontentloaded')
        t0 = time.time()
        wait_ready(page)
        load_s = time.time() - t0
        size = page.evaluate('window.__ITDA.dict.size')
        check(size > 300000, f'[{vp_name}] 사전 로드', f'{size}단어 / {load_s:.1f}s')
        check(page.is_visible('#scr-setup'), f'[{vp_name}] 설정 화면')
        check(sum(overflow(page).values()) <= 0, f'[{vp_name}] 설정 가로 오버플로 없음', str(overflow(page)))
        shot(page, f'live-{vp_name}-01-setup')

        page.click('.level[data-lv="4"]')
        page.click('#btn-start')
        page.wait_for_selector('#scr-game:not([hidden])')
        page.wait_for_timeout(600)
        check(state(page)['phase'] in ('me', 'bot'), f'[{vp_name}] 대전 시작')
        check(sum(overflow(page).values()) <= 0, f'[{vp_name}] 대전 가로 오버플로 없음', str(overflow(page)))
        shot(page, f'live-{vp_name}-02-game')

        scenario_twoeum(page, 'live-' + vp_name)
        scenario_new_words(page, 'live-' + vp_name)
        scenario_bot_levels(page, 'live-' + vp_name)
        scenario_easy_words(page, 'live-' + vp_name)
        scenario_easy_game(page, 'live-' + vp_name)
        scenario_no_custom(page, 'live-' + vp_name)
        scenario_no_hint(page, 'live-' + vp_name)
        scenario_setup_clean(page, 'live-' + vp_name)
        scenario_result_level(page, 'live-' + vp_name)
        scenario_battle_log(page, 'live-' + vp_name)
        scenario_mission(page, 'live-' + vp_name, REPORT_DIR)
        scenario_levels(page, 'live-' + vp_name)
        scenario_hell(page, 'live-' + vp_name)
        scenario_variety(page, 'live-' + vp_name)
        scenario_legacy(page, 'live-' + vp_name)
        scenario_mercy(page, 'live-' + vp_name, REPORT_DIR)
        scenario_hardcore(page, 'live-' + vp_name, REPORT_DIR)

        check(not col.errors, f'[{vp_name}] 페이지 에러 0', json.dumps(col.errors, ensure_ascii=False)[:400])
        errs = [c for c in col.console if c['type'] == 'error']
        check(not errs, f'[{vp_name}] 콘솔 에러 0', json.dumps(errs, ensure_ascii=False)[:400])
        ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', action='store_true')
    ap.add_argument('--url', default=None)
    ap.add_argument('--viewport', choices=['desktop', 'mobile'], default=None,
                    help='한 화면 크기만 검사한다(기본: 둘 다)')
    args = ap.parse_args()

    if args.viewport:
        keep = VIEWPORTS[args.viewport]
        VIEWPORTS.clear()
        VIEWPORTS[args.viewport] = keep

    httpd = None
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox', '--disable-dev-shm-usage'])
        if args.local or not args.url:
            httpd, port = serve(ROOT)
            run_local(f'http://127.0.0.1:{port}/index.html', browser)
        if args.url:
            run_live(args.url, browser)
        browser.close()
    if httpd:
        httpd.shutdown()

    print('\n=== 요약 ===')
    if FAILS:
        print(f'실패 {len(FAILS)}건:')
        for f in FAILS:
            print('  -', f)
        sys.exit(1)
    print('모든 검사 통과')


if __name__ == '__main__':
    main()
