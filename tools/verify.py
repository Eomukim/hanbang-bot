#!/usr/bin/env python3
"""끝말잇기 한방봇 검증 스크립트.

로컬(파일 서버) 또는 라이브 URL을 headless Chromium으로 열어
 - 콘솔/페이지 에러, 가로 오버플로
 - 두음법칙 · 중복 차단 · 내 단어장 · 4단계 한방 승리 · 봇 난이도 규칙
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


def scenario_bot_levels(page, tag):
    """1단계는 한방 금지, 4단계는 즉시 한방."""
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

    # 4단계: 한방 시나리오
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
    check(st['phase'] == 'over', f'[{tag}] 4단계 봇 즉시 종료', st['phase'])
    check(is_oneshot, f'[{tag}] 4단계 봇 한방 단어 사용', last_bot)
    check(page.is_visible('#ov-result'), f'[{tag}] 결과 화면 표시')
    shot(page, f'{tag}-05-level4-oneshot')
    page.wait_for_timeout(600)


def scenario_custom(page, tag):
    page.evaluate("window.__HB.app.engine.destroy()")
    page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
    page.click('#btn-custom')
    page.fill('#custom-word', '냥냥이')
    page.fill('#custom-mean', '고양이 애칭')
    page.click('#custom-form button[type=submit]')
    page.wait_for_timeout(200)
    check(page.evaluate("window.__HB.dict.custom.has('냥냥이')"), f'[{tag}] 내 단어장 추가')
    shot(page, f'{tag}-06-custom')
    page.click('#btn-custom-close')
    page.evaluate("window.__HB.startGame({level:1, first:'me', startChar:'냥'})")
    page.wait_for_timeout(450)
    play_word(page, '냥냥이', wait=400)
    st = state(page)
    check(bool(st['chain']) and st['chain'][0]['word'] == '냥냥이', f'[{tag}] 커스텀 단어 판정 반영')
    # 저장 확인
    stored = page.evaluate("JSON.parse(localStorage.getItem('hanbang.custom.v1') || '{}')")
    check('냥냥이' in stored, f'[{tag}] 내 단어장 localStorage 저장')
    page.evaluate("""() => {
        const raw = JSON.parse(localStorage.getItem('hanbang.custom.v1') || '{}');
        delete raw['냥냥이'];
        localStorage.setItem('hanbang.custom.v1', JSON.stringify(raw));
        window.__HB.dict.removeCustom('냥냥이');
        window.__HB.app.custom = raw;
        window.__HB.app.renderCustomCount();
    }""")

    # 내가 한방 단어로 이기는 경로: 후속 단어가 없는 글자(늄)로 끝나는 커스텀 단어
    page.evaluate("""() => {
        window.__HB.app.custom['냥늄'] = { mean: '검사용', at: Date.now() };
        window.__HB.dict.addCustom('냥늄', '검사용');
        window.__HB.app.hideResult();
        window.__HB.startGame({ level: 1, first: 'me', startChar: '냥' });
    }""")
    page.wait_for_timeout(450)
    play_word(page, '냥늄', wait=1800)
    st = state(page)
    title = page.evaluate("document.getElementById('result-title').textContent")
    check(st['phase'] == 'over' and title == '승리', f'[{tag}] 한방 단어로 승리', f"{st['phase']} / {title}")
    shot(page, f'{tag}-08-player-win')
    page.evaluate("""() => {
        delete window.__HB.app.custom['냥늄'];
        window.__HB.dict.removeCustom('냥늄');
        window.__HB.app.hideResult();
    }""")

    # 시간 초과 패배
    page.evaluate("window.__HB.startGame({level:1, first:'me', timeLimit:1})")
    page.wait_for_timeout(2200)
    st = state(page)
    reason = page.evaluate("document.getElementById('result-reason').textContent")
    check(st['phase'] == 'over' and '시간' in reason, f'[{tag}] 제한 시간 초과 패배', reason)
    shot(page, f'{tag}-09-timeout')
    page.evaluate("window.__HB.app.hideResult()")


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
    splash = page.evaluate("document.querySelector('.ko-splash b')?.textContent || ''")
    check(last.get('missionHits') == 2, f'[{tag}] 미션 글자 2개 인식', str(last.get('missionHits')))
    check(last.get('score') == expect2 and expect2 == base * 2,
          f'[{tag}] 2중첩 점수 ×2', f"{base} → {last.get('score')} (기대 {expect2})")
    check('×2' in tag_text, f'[{tag}] 단어 카드에 미션 ×2 표시', tag_text)
    check(st['missionChar'] != plan['ch'] and st['missionChar'] in MISSION_CHARS,
          f'[{tag}] 성공 즉시 다음 미션 글자', f"{plan['ch']} → {st['missionChar']}")
    check(st['missionChar'] in chip_text, f'[{tag}] 미션 칩 갱신', chip_text)
    check('미션' in splash, f'[{tag}] 미션 성공 알림', splash)
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
        scenario_bot_levels(page, 'local-' + vp_name)
        scenario_custom(page, 'local-' + vp_name)
        scenario_mission(page, 'local-' + vp_name, REPORT_DIR)

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
        scenario_bot_levels(page, 'live-' + vp_name)
        scenario_mission(page, 'live-' + vp_name, REPORT_DIR)

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
