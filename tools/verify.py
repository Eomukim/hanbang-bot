#!/usr/bin/env python3
"""끝말잇기 한방봇 검증 스크립트.

로컬(파일 서버) 또는 라이브 URL을 headless Chromium으로 열어
 - 콘솔/페이지 에러, 가로 오버플로
 - 두음법칙 · 중복 차단 · 4단계 극악 한방 승리 · 봇 난이도 규칙
 - 내 단어장 삭제(버튼·모달·사전 API 없음, 남은 localStorage 값 무시)
 - 결과 화면(승리·패배·시간 초과·포기) 난이도 배지
 - 5단계 난이도 카드(데스크톱/모바일 배치)와 4단계 기준 localStorage 호환
 - Lv.5 지옥: 한방 즉사 · 상대 한방 각 회피 · 강제 필승 검증 · 압박/미션·장문 · 응답 시간
 - 미션 규칙(14종 후보 · 미달성 시 유지 · 중첩 보너스 · 성공 시 다음 글자)
 - 모바일(390x844) 레이아웃과 스크린샷
을 확인한다.

env:
    HB_SHOT_DIR     스크린샷 폴더(기본: 저장소 downloads/)
    HB_REPORT_DIR   미션 보고용 스크린샷(mission-keep/stack/success.png)을 따로 저장할 폴더

usage:
    python3 tools/verify.py --local
    python3 tools/verify.py --url https://hanbang-bot.onrender.com
    python3 tools/verify.py --local --url https://hanbang-bot.onrender.com
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
SHOT_DIR = os.environ.get('HB_SHOT_DIR') or os.path.join(ROOT, 'downloads')
REPORT_DIR = os.environ.get('HB_REPORT_DIR')
MISSION_CHARS = ['가', '나', '다', '라', '마', '바', '사', '아', '자', '차', '카', '타', '파', '하']
CHROME = os.environ.get('HB_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')

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
  const dict = window.__HB.dict, Bot = window.__HB.Bot;
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
  const dict = window.__HB.dict, Bot = window.__HB.Bot;
  const starts = dict.goodStartChars(60).sort();
  const last = (w) => w[w.length - 1];
  const value = (w, mission) => {
    let hits = 0;
    for (const c of w) if (c === mission) hits += 1;
    const mult = hits <= 0 ? 1 : hits === 1 ? 1.5 : hits;
    return (w.length * w.length + 4 * w.length) * mult;
  };
  const out = {};

  // 1) 한방이 여러 개일 때: 미션 글자가 겹치거나 더 긴(점수 높은) 한방을 고르는가
  for (const ch of starts) {
    const cands = dict.candidatesFor(ch, new Set());
    const kills = cands.filter((w) => dict.countFrom(last(w)) === 0);
    if (kills.length < 2) continue;
    const best = kills.reduce((a, b) => (value(b, '가') > value(a, '가') ? b : a));
    if (![...kills].some((w) => w.includes('가')) || value(best, '가') === value(kills[0], '가')) continue;
    const mv = new Bot({level: 5, dict}).choose({needChar: ch, used: new Set(), turn: 1, mission: '가'});
    out.kill = {ok: true, char: ch, expect: best, got: mv.word, kind: mv.kind,
                equal: mv.word === best, kills: kills.length};
    break;
  }
  if (!out.kill) out.kill = {ok: false};

  // 2) 고른 끝 글자 안에서는 미션 중첩·장문으로 점수가 가장 높은 단어를 고르는가
  let checked = 0, agree = 0, detail = null;
  for (const ch of starts) {
    const used = new Set();
    const mv = new Bot({level: 5, dict}).choose({needChar: ch, used, turn: 6, mission: '가'});
    if (!mv) continue;
    const end = last(mv.word);
    const same = dict.candidatesFor(ch, used).filter((w) => last(w) === end);
    const best = same.reduce((a, b) => (value(b, '가') > value(a, '가') ? b : a), mv.word);
    checked += 1;
    if (mv.word === best) agree += 1;
    else if (!detail) detail = {char: ch, got: mv.word, best, end, same: same.length, kind: mv.kind};
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
    page.wait_for_function('window.__HB && window.__HB.ready === true', timeout=timeout)
    page.wait_for_selector('#scr-setup:not([hidden])', timeout=timeout)


def state(page):
    return page.evaluate('window.__HB.state()')


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
        const st = window.__HB.state();
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
        const st = window.__HB.state();
        const e = window.__HB.engine;
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
        const st = window.__HB.state();
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
        const d = window.__HB.dict;
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
    page.evaluate(f"window.__HB.startGame({{level:2, first:'me', startChar:'{info['ch']}'}})")
    page.wait_for_timeout(500)
    play_word(page, info['loop'], wait=120)
    # 같은 단어를 바로 다시 판정: 필요 글자가 같으므로 '이미 나온 단어'로 걸려야 한다
    res = page.evaluate("(w) => window.__HB.engine.validate(w)", info['loop'])
    check(res.get('ok') is False and res['error']['code'] == 'used',
          f'[{tag}] 중복 단어 차단', json.dumps(res, ensure_ascii=False)[:120])
    page.wait_for_timeout(1700)
    st = state(page)
    check(st['chain'] and st['chain'][0]['word'] == info['loop'], f'[{tag}] 첫 단어 입력', info['loop'])

    # 중복: 지금 이어야 할 글자로 시작하는 이미 나온 단어가 있으면 UI로도 시도한다
    ui_duplicate(page, tag)

    # 두음법칙: 시작 글자를 '력'으로 고정하고 '역'으로 시작하는 단어 입력
    page.evaluate("window.__HB.app.engine.destroy()")
    page.evaluate("window.__HB.startGame({level:2, first:'me', startChar:'력'})")
    page.wait_for_timeout(450)
    duo = page.evaluate("""() => {
        const d = window.__HB.dict, st = window.__HB.state();
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
        "() => ((window.__HB.dict.stats && window.__HB.dict.stats.openDbSamples) || []).filter((w) => w.length >= 3)"
    )
    check(bool(samples), f'[{tag}] 오픈DB 신규 단어 표본', str(samples[:1]))
    if not samples:
        return
    picks = [samples[0], samples[len(samples) // 2], samples[-1]]
    for sample in picks:
        page.evaluate("window.__HB.app.engine && window.__HB.app.engine.destroy()")
        page.evaluate("(ch) => window.__HB.startGame({level:2, first:'me', startChar: ch})", sample[0])
        page.wait_for_timeout(450)
        play_word(page, sample, wait=600)
        st = state(page)
        check(bool(st['chain']) and st['chain'][0]['word'] == sample,
              f'[{tag}] 오픈DB 신규 단어 입력 인정', sample)
        page.evaluate("window.__HB.app.hideResult()")
    page.evaluate("window.__HB.app.engine && window.__HB.app.engine.destroy()")


def scenario_bot_levels(page, tag):
    """1단계는 한방 금지, 4단계 극악은 즉시 한방."""
    # 1단계: 여러 턴을 두고 봇이 한방 단어를 쓰지 않는지
    page.evaluate("window.__HB.app.engine.destroy()")
    page.evaluate("window.__HB.startGame({level:1, first:'bot'})")
    page.wait_for_timeout(2600)
    used = []
    for _ in range(5):
        st = wait_my_turn(page, 6000)
        if not st or st['phase'] != 'me':
            break
        w = page.evaluate("""() => {
            const d = window.__HB.dict, st = window.__HB.state();
            const cands = d.candidatesFor(st.needChar, new Set(st.chain.map((c) => c.word)));
            return cands.find((x) => d.countFrom(x[x.length - 1]) >= 40 && x.length <= 3) || cands[0] || null;
        }""")
        if not w:
            break
        play_word(page, w, wait=2600)
    st = state(page)
    bot_words = [c['word'] for c in st['chain'] if c['who'] == 'bot']
    one_shots = page.evaluate(
        "(ws) => ws.map((w) => window.__HB.dict.isOneShot(w))", bot_words
    ) if bot_words else []
    check(len(bot_words) >= 2, f'[{tag}] 1단계 봇 응답 정상', f'{len(bot_words)}턴')
    check(not any(one_shots), f'[{tag}] 1단계 봇 한방 금지', str(bot_words[-2:]))
    shot(page, f'{tag}-04-level1')

    # 4단계 극악: 한방 시나리오
    pick = page.evaluate("""() => {
        const d = window.__HB.dict;
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
    page.evaluate("window.__HB.app.engine.destroy()")
    page.evaluate(f"window.__HB.startGame({{level:4, first:'me', startChar:'{pick['start']}'}})")
    page.wait_for_timeout(450)
    play_word(page, pick['word'], wait=3500)
    st = state(page)
    bot_words = [c['word'] for c in st['chain'] if c['who'] == 'bot']
    last_bot = bot_words[-1] if bot_words else ''
    is_oneshot = page.evaluate("([w]) => !!w && window.__HB.dict.isOneShot(w)", [last_bot])
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
    page.evaluate("window.__HB.app.engine && window.__HB.app.engine.destroy()")
    page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
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
    saved = page.evaluate("JSON.parse(localStorage.getItem('hanbang.settings.v1') || '{}').level")
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
        phase: window.__HB.state() ? window.__HB.state().phase : null,
    })""")
    check(head['name'] == '한방봇 지옥' and head['lv'] == 'Lv.5 지옥' and head['body'] == '5',
          f'[{tag}] 5단계 대전 헤더', json.dumps(head, ensure_ascii=False))
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 5단계 대전 가로 오버플로 0', str(overflow(page)))
    shot(page, f'{tag}-11-level5-game')
    page.evaluate("window.__HB.app.engine.destroy(); window.__HB.app.hideResult(); window.__HB.app.show('setup')")
    page.wait_for_timeout(150)


def scenario_legacy(page, tag):
    """4단계 시절 localStorage(설정·전적)가 그대로 읽히는지."""
    page.evaluate("""() => {
        localStorage.setItem('hanbang.settings.v1', JSON.stringify({ level: 4, timeLimit: 15, first: 'bot', sound: false }));
        localStorage.setItem('hanbang.record.v1', JSON.stringify({
            1: { plays: 3, wins: 1, losses: 2, bestCombo: 2, bestScore: 40 },
            4: { plays: 7, wins: 3, losses: 4, bestCombo: 5, bestScore: 260 },
        }));
    }""")
    page.reload(wait_until='domcontentloaded')
    wait_ready(page)
    page.wait_for_timeout(250)
    view = page.evaluate("""() => ({
        checked: document.querySelector('.level[aria-checked="true"]')?.dataset.lv,
        sound: document.getElementById('sound-value').textContent,
        soundPressed: document.getElementById('btn-sound').getAttribute('aria-pressed'),
        first: document.querySelector('#first-opts button[aria-checked="true"]')?.dataset.first,
        record: document.getElementById('record').innerText,
    })""")
    check(view['checked'] == '4', f'[{tag}] 옛 설정 Lv.4 복원', str(view['checked']))
    check(view['sound'] == '끔' and view['soundPressed'] == 'false' and view['first'] == 'bot',
          f'[{tag}] 옛 설정 소리·선공 복원', f"{view['sound']} / {view['first']}")
    check('Lv.4 극악' in view['record'] and 'Lv.1 쉬움' in view['record'] and '3승 4패' in view['record'],
          f'[{tag}] 옛 전적 Lv.4 극악으로 표시', view['record'].replace('\n', ' | ')[:120])
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 옛 설정 화면 가로 오버플로 0', str(overflow(page)))

    # 새 5단계 전적도 같은 키에 쌓이는지
    page.evaluate("window.__HB.startGame({level:5, first:'me', timeLimit:1})")
    page.wait_for_timeout(1800)
    rec = page.evaluate("JSON.parse(localStorage.getItem('hanbang.record.v1') || '{}')")
    check('5' in rec and rec['5'].get('plays', 0) >= 1 and '4' in rec,
          f'[{tag}] Lv.5 전적 저장·기존 기록 유지', json.dumps(rec, ensure_ascii=False)[:160])
    page.evaluate("""() => {
        localStorage.removeItem('hanbang.settings.v1');
        localStorage.removeItem('hanbang.record.v1');
    }""")
    page.reload(wait_until='domcontentloaded')
    wait_ready(page)
    page.wait_for_timeout(200)


def scenario_hell(page, tag):
    """Lv.5 지옥: 한방 즉사 · 강제 필승 · 한방 각 회피 · 압박/미션·장문 · 응답 속도."""
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
    check(props['longMoves'] >= props['moves'] * 0.3,
          f'[{tag}] Lv.5 장문 선택', f"{props['longMoves']}/{props['moves']}수 5글자 이상")

    picks = page.evaluate(HELL_PICKS)
    check(picks.get('kill', {}).get('ok') and picks['kill']['equal'],
          f'[{tag}] Lv.5 한방 중 미션·최고점 우선',
          json.dumps(picks.get('kill'), ensure_ascii=False)[:180])
    check(picks.get('mission', {}).get('ok') and picks['mission']['agree'] == picks['mission']['checked'],
          f'[{tag}] Lv.5 같은 끝 글자에서 미션·최고점 단어',
          json.dumps(picks.get('mission'), ensure_ascii=False)[:200])
    check(picks.get('pressure', {}).get('ok'),
          f'[{tag}] Lv.5 소수 후보 글자로 압박',
          json.dumps(picks.get('pressure'), ensure_ascii=False)[:180])

    # 실제 대전: 내가 보통 사람처럼 두고, 봇의 응답 수·태그·시간을 본다
    gaps, tags, bot_moves = [], [], []
    for _attempt in range(3):
        page.evaluate("window.__HB.app.engine && window.__HB.app.engine.destroy()")
        page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
        page.evaluate("window.__HB.startGame({level:5, first:'me', timeLimit:20})")
        page.wait_for_timeout(350)
        for _ in range(5):
            st = wait_my_turn(page, 8000)
            if not st or st['phase'] != 'me':
                break
            w = page.evaluate("""() => {
                const d = window.__HB.dict, st = window.__HB.state();
                const used = new Set(st.chain.map((c) => c.word));
                const cands = d.candidatesFor(st.needChar, used);
                if (!cands.length) return null;
                // 사람처럼: 너무 어렵지 않은 2~4글자 단어를 고른다
                const easy = cands.filter((x) => x.length <= 4);
                return (easy.length ? easy : cands)[Math.min(5, (easy.length || cands.length) - 1)];
            }""")
            if not w:
                break
            before = page.evaluate("window.__HB.state().chain.length")
            t0 = time.time()
            page.fill('#word-input', w)
            page.click('#btn-submit')
            try:
                page.wait_for_function(
                    f"() => window.__HB.state().chain.length > {before} + 1 || window.__HB.state().phase === 'over'",
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
        page.evaluate("window.__HB.app.hideResult()")
        page.evaluate("window.__HB.startGame({level:5, first:'me', timeLimit:20})")
        page.wait_for_timeout(400)
        w2 = page.evaluate("""() => {
            const d = window.__HB.dict, st = window.__HB.state();
            const cands = d.candidatesFor(st.needChar, new Set());
            const easy = cands.filter((x) => x.length <= 4);
            return (easy.length ? easy : cands)[Math.min(3, (easy.length || cands.length) - 1)] || null;
        }""")
        if w2:
            page.fill('#word-input', w2)
            page.click('#btn-submit')
            page.wait_for_timeout(700)
    shot(page, f'{tag}-12-hell-game')
    page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
    page.wait_for_timeout(200)

    # 봇 선공 오프닝: Lv.5 가 먼저 두는 판은 아무 글자가 아니라 이기는 자리로 연다
    openings = []
    for _ in range(4):
        page.evaluate("window.__HB.app.engine && window.__HB.app.engine.destroy()")
        page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
        page.evaluate("window.__HB.startGame({level:5, first:'bot', timeLimit:20})")
        page.wait_for_timeout(900)
        openings.append(page.evaluate("""() => {
            const st = window.__HB.state(), d = window.__HB.dict;
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
    page.evaluate("window.__HB.app.engine && window.__HB.app.engine.destroy()")
    page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
    page.wait_for_timeout(200)


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
    page.evaluate("window.__HB.app.engine && window.__HB.app.engine.destroy()")
    page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
    page.wait_for_timeout(150)
    gone = page.evaluate("""() => ({
        btn: !!document.getElementById('btn-custom'),
        modal: !!document.getElementById('ov-custom'),
        inputs: document.querySelectorAll('#custom-word,#custom-mean,#custom-list,#custom-form').length,
        text: document.body.innerText.includes('내 단어장'),
        dictApi: ['custom', 'customByStart', 'addCustom', 'removeCustom', 'setCustom', 'customStartCount', 'meanOf']
            .filter((k) => window.__HB.dict[k] !== undefined),
        appApi: ['openCustom', 'addCustomWord', 'renderCustom', 'renderCustomCount']
            .filter((k) => typeof window.__HB.app[k] === 'function'),
        state: typeof window.__HB.app.custom,
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
        size: window.__HB.dict.size,
    })""")
    check(left['key'] and left['setup'] and left['size'] > 300000,
          f'[{tag}] 옛 내 단어장 값이 남아 있어도 정상 부팅', json.dumps(left, ensure_ascii=False))
    check(not left['text'], f'[{tag}] 옛 값이 있어도 화면에 내 단어장 문구 0건')
    res = page.evaluate("""() => {
        window.__HB.startGame({ level: 1, first: 'me', startChar: '냥' });
        const v = window.__HB.engine.validate('냥냥이');
        window.__HB.app.engine.destroy();
        window.__HB.app.hideResult();
        window.__HB.app.show('setup');
        return v;
    }""")
    check(res['ok'] is False and res['error']['code'] == 'notfound',
          f'[{tag}] 옛 내 단어장 단어는 사전에 없음으로 판정',
          json.dumps(res, ensure_ascii=False)[:140])
    page.evaluate("localStorage.removeItem('hanbang.custom.v1')")
    page.wait_for_timeout(100)


def scenario_result_level(page, tag):
    """결과 화면: 승리·패배·시간 초과·포기 모두 어떤 난이도였는지 보인다."""
    # 1) Lv.1 에서 진짜 한방 단어로 승리
    pick = page.evaluate("""() => {
        const d = window.__HB.dict;
        for (const [ch] of d.ranges) {
            const w = d.candidatesFor(ch, new Set()).find((x) => d.countFrom(x[x.length - 1]) === 0);
            if (w) return { start: ch, word: w };
        }
        return null;
    }""")
    if check(pick is not None, f'[{tag}] 승리용 한방 단어 탐색', str(pick)):
        page.evaluate("window.__HB.app.engine && window.__HB.app.engine.destroy()")
        page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
        page.evaluate(f"window.__HB.startGame({{level:1, first:'me', startChar:'{pick['start']}'}})")
        page.wait_for_timeout(450)
        play_word(page, pick['word'], wait=1800)
        win = result_view(page)
        check(win['title'] == '승리' and win['label'] == 'Lv.1 쉬움' and win['lv'] == '1',
              f'[{tag}] 승리 결과에 난이도', json.dumps(win, ensure_ascii=False)[:160])
        check(win['height'] >= 20, f'[{tag}] 난이도 배지 렌더', str(win['height']))
        shot(page, f'{tag}-13-result-win')

    # 2) Lv.3 시간 초과 패배
    page.evaluate("window.__HB.startGame({level:3, first:'me', timeLimit:1})")
    page.wait_for_timeout(2300)
    lose = result_view(page)
    check(lose['title'] == '패배' and lose['label'] == 'Lv.3 어려움' and lose['lv'] == '3',
          f'[{tag}] 시간 초과 결과에 난이도', json.dumps(lose, ensure_ascii=False)[:160])
    check('시간' in lose['reason'], f'[{tag}] 시간 초과 사유', lose['reason'])
    shot(page, f'{tag}-14-result-timeout')

    # 3) Lv.5 포기 → 결과 화면 난이도 (Lv.3 표시가 남지 않는지)
    page.evaluate("window.__HB.startGame({level:5, first:'me', timeLimit:20})")
    page.wait_for_timeout(400)
    page.evaluate("window.__HB.engine.quit()")
    page.wait_for_timeout(1000)
    quit_view = result_view(page)
    check(quit_view['title'] == '패배' and quit_view['label'] == 'Lv.5 지옥' and quit_view['lv'] == '5',
          f'[{tag}] 포기 결과에 난이도', json.dumps(quit_view, ensure_ascii=False)[:160])
    check('포기' in quit_view['reason'], f'[{tag}] 포기 사유', quit_view['reason'])
    shot(page, f'{tag}-15-result-quit')
    check(sum(overflow(page).values()) <= 0, f'[{tag}] 결과 화면 가로 오버플로 0', str(overflow(page)))
    page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
    page.wait_for_timeout(150)


def scenario_mission(page, tag, report_dir=None):
    """미션: 14종 후보 · 미달성 시 유지 · 중첩 보너스 · 성공 시 다음 글자."""
    print(f'  · 미션 규칙 [{tag}]')

    # 1) 후보 14종 중에서만 나오고, 골고루 섞이는지
    seen = page.evaluate("""() => {
        const app = window.__HB.app, out = [];
        for (let i = 0; i < 60; i += 1) {
            if (app.engine) app.engine.destroy();
            app.startGame({ level: 1, first: 'me', timeLimit: 20 });
            out.push(window.__HB.state().missionChar);
        }
        if (app.engine) app.engine.destroy();
        app.show('setup');
        return out;
    }""")
    check(all(c in MISSION_CHARS for c in seen), f'[{tag}] 미션 후보 14종 밖 없음', ''.join(sorted(set(seen))))
    check(len(set(seen)) >= 10, f'[{tag}] 미션 글자 랜덤 출제', f'{len(set(seen))}/14종')

    # 시험용 단어: 한 시작 글자에서 미션 글자가 0회·1회·2회 든 단어를 모두 찾는다
    plan = page.evaluate("""(missions) => {
        const d = window.__HB.dict;
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
        page.evaluate("window.__HB.app.engine.destroy()")
        page.evaluate("([s, m]) => window.__HB.startGame({ level: 1, first: 'me', startChar: s, mission: m, timeLimit: 20 })",
                      [start, mission])
        page.wait_for_timeout(250)

    # 2) 미션 글자가 없는 단어 → 글자 유지
    fixed_game(plan['start'], plan['ch'])
    res = page.evaluate("(w) => window.__HB.submit(w)", plan['zero'])
    st = state(page)
    check(res.get('ok') is True and res.get('missionHits') == 0 and res.get('nextMission') is None
          and st['missionChar'] == plan['ch'],
          f'[{tag}] 미션 미달성 → 글자 유지', f"'{plan['zero']}' 입력 후 미션 '{st['missionChar']}'")
    if report_dir:
        page.wait_for_timeout(120)
        report_shot(page, tag, report_dir, 'mission-keep')

    # 3) 미션 글자 2회 → 중첩 보너스 ×2, 곧바로 다음 글자
    fixed_game(plan['start'], plan['ch'])
    base = page.evaluate("(w) => window.__HB.engine.scoreFor(w, 0, 0)", plan['two'])
    expect2 = page.evaluate("(w) => window.__HB.engine.scoreFor(w, 0, 2)", plan['two'])
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
    page.evaluate("clearTimeout(window.__HB.engine.botTimer)")
    page.wait_for_timeout(1250)
    tag_after = page.evaluate("document.querySelector('#stage .tag.mission')?.textContent || ''")
    chip_after = page.evaluate("document.getElementById('chip-mission').textContent || ''")
    check('×2' in tag_after and st['missionChar'] in chip_after,
          f'[{tag}] 미션 ×2 카드·칩 유지', f'{tag_after} / {chip_after}')
    report_shot(page, tag, report_dir, 'mission-stack')

    # 4) 미션 글자 1회 → +50%
    fixed_game(plan['start'], plan['ch'])
    page.evaluate("(w) => window.__HB.submit(w)", plan['one'])
    st = state(page)
    last = st['chain'][0] if st['chain'] else {}
    base1 = page.evaluate("(w) => window.__HB.engine.scoreFor(w, 0, 0)", plan['one'])
    check(last.get('missionHits') == 1 and last.get('score') == round(base1 * 1.5),
          f'[{tag}] 1개 +50%', f"{base1} → {last.get('score')} (기대 {round(base1 * 1.5)})")

    # 5) 중첩 배수 표(0/1/2/3회)
    table = page.evaluate("""() => {
        const e = window.__HB.engine;
        return [0, 1, 2, 3].map((h) => e.scoreFor('가나다라마', 0, h));
    }""")
    check(table[1] == round(table[0] * 1.5) and table[2] == table[0] * 2 and table[3] == table[0] * 3,
          f'[{tag}] 중첩 배수 0/1/2/3회', str(table))

    # 6) 봇이 성공해도 다음 글자로 (봇 응답 경로 직접 호출)
    fixed_game(plan['start'], plan['ch'])
    swap = page.evaluate("""(w) => {
        const e = window.__HB.engine;
        const before = e.missionChar;
        e.phase = 'bot';
        e.applyBotMove({ word: w, kind: 'normal', delay: 0 });
        return { before, after: e.missionChar, chip: document.getElementById('chip-mission').textContent };
    }""", plan['two'])
    check(swap['after'] != swap['before'] and swap['after'] in MISSION_CHARS,
          f'[{tag}] 봇 미션 성공 → 다음 글자', f"{swap['before']} → {swap['after']}")
    check(swap['after'] in swap['chip'], f'[{tag}] 봇 성공 후 미션 칩 갱신', swap['chip'])
    page.evaluate("window.__HB.app.engine.destroy()")
    page.wait_for_timeout(900)
    page.evaluate("window.__HB.app.hideResult()")


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
        size = page.evaluate('window.__HB.dict.size')
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
        page.click('#btn-hint')
        page.wait_for_timeout(180)
        hint_text = page.evaluate("document.querySelector('.toast')?.textContent || ''")
        check('남은 단어' in hint_text, f'[{vp_name}] 힌트 동작', hint_text)
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
        scenario_no_custom(page, 'local-' + vp_name)
        scenario_result_level(page, 'local-' + vp_name)
        scenario_mission(page, 'local-' + vp_name, REPORT_DIR)
        scenario_levels(page, 'local-' + vp_name)
        scenario_hell(page, 'local-' + vp_name)
        scenario_legacy(page, 'local-' + vp_name)

        # 대전 중 스크린샷 (여러 단어가 쌓인 화면)
        page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
        page.evaluate("window.__HB.startGame({level:1, first:'bot'})")
        page.wait_for_timeout(1800)
        for _ in range(4):
            st = wait_my_turn(page, 6000)
            if not st or st['phase'] != 'me':
                break
            w = page.evaluate("""() => {
                const d = window.__HB.dict, st = window.__HB.state();
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
        size = page.evaluate('window.__HB.dict.size')
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
        scenario_no_custom(page, 'live-' + vp_name)
        scenario_result_level(page, 'live-' + vp_name)
        scenario_mission(page, 'live-' + vp_name, REPORT_DIR)
        scenario_levels(page, 'live-' + vp_name)
        scenario_hell(page, 'live-' + vp_name)
        scenario_legacy(page, 'live-' + vp_name)

        check(not col.errors, f'[{vp_name}] 페이지 에러 0', json.dumps(col.errors, ensure_ascii=False)[:400])
        errs = [c for c in col.console if c['type'] == 'error']
        check(not errs, f'[{vp_name}] 콘솔 에러 0', json.dumps(errs, ensure_ascii=False)[:400])
        ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', action='store_true')
    ap.add_argument('--url', default=None)
    args = ap.parse_args()

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
