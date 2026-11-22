#!/usr/bin/env python3
"""잇다 화면 순회 점검: 설정 → 대전(5단계) → 결과/배틀 내역 → 배려모드.

verify.py 가 규칙·난이도를 보는 것과 달리, 이 스크립트는 **화면을 눈으로 보는** 용도다.
데스크톱(1280x800) · 모바일(390x844) · 작은 모바일(360x640)에서 화면마다
 - 가로 오버플로(문서/바디)
 - 화면 밖으로 나간 요소·겹친 요소(입력창/버튼/토스트)
 - 세로 스크롤이 필요한지(설정 화면은 스크롤 0이어야 한다)
를 재고 스크린샷을 남긴다.

usage:
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/ui_tour.py
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/ui_tour.py --url https://itda-play.onrender.com
"""
import argparse
import functools
import http.server
import json
import os
import socketserver
import threading
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOT_DIR = os.environ.get('ITDA_SHOT_DIR') or os.path.join(ROOT, 'downloads', 'ui-tour')
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')

VIEWPORTS = {
    'desktop': {'width': 1280, 'height': 800},
    'mobile': {'width': 390, 'height': 844},
    'small': {'width': 360, 'height': 640},
}
PROBLEMS = []


def serve(root):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
    httpd = socketserver.ThreadingTCPServer(('127.0.0.1', 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


MEASURE = """
() => {
  const doc = document.documentElement;
  const body = document.body;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const out = {
    docOverflowX: doc.scrollWidth - vw,
    bodyOverflowX: body.scrollWidth - vw,
    scrollY: doc.scrollHeight - vh,
    vw, vh,
    offscreen: [],
    overlaps: [],
    clipped: [],
  };
  const visible = (el) => {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && Number(cs.opacity) > 0.01
      && r.width > 1 && r.height > 1 && r.bottom > 0 && r.top < vh;
  };
  const label = (el) => (el.id ? '#' + el.id : el.className ? '.' + String(el.className).split(' ')[0] : el.tagName.toLowerCase());
  // 결과 오버레이가 떠 있으면 그 안만 본다(뒤 대전 화면은 가려져 있다).
  const ov = document.getElementById('ov-result');
  const scope = ov && !ov.hidden ? ov : document.getElementById('app');
  const targets = [...scope.querySelectorAll(
    'button, input, .stage-char, .need-char, .countdown, .chip, .mini, .bot-bubble, .level, .toggle-card, .result-level, .result-stats, .battle-log-btn, .battle-log, .toast, .mercy-badge, h1, h2, .logo-mark, .scoreboard, .chain li'
  )].filter(visible);
  for (const el of targets) {
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) out.offscreen.push([label(el), Math.round(r.left), Math.round(r.right), Math.round(vw)]);
    if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflowX === 'visible') {
      out.clipped.push([label(el), el.scrollWidth, el.clientWidth]);
    }
  }
  const boxes = targets.map((el) => ({ el, r: el.getBoundingClientRect(), name: label(el) }));
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i], b = boxes[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const ox = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
      const oy = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
      if (ox > 4 && oy > 4) out.overlaps.push([a.name, b.name, Math.round(ox), Math.round(oy)]);
    }
  }
  return out;
}
"""


def shot(page, name):
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f'{name}.png')
    page.screenshot(path=path)
    return path


def measure(page, tag, where):
    m = page.evaluate(MEASURE)
    bad = []
    if m['docOverflowX'] > 1 or m['bodyOverflowX'] > 1:
        bad.append(f"가로 오버플로 {m['docOverflowX']}px")
    if m['offscreen']:
        bad.append('화면 밖 ' + json.dumps(m['offscreen'][:4], ensure_ascii=False))
    if m['overlaps']:
        bad.append('겹침 ' + json.dumps(m['overlaps'][:4], ensure_ascii=False))
    if where == 'setup' and m['scrollY'] > 2:
        bad.append(f"설정 세로 스크롤 {m['scrollY']}px")
    if bad:
        PROBLEMS.append((tag, where, bad))
    print(f"  {'FAIL' if bad else 'ok  '} {tag} {where} · {m['vw']}x{m['vh']} "
          f"가로 {m['docOverflowX']}px · 세로 {m['scrollY']}px"
          + (' · ' + ' / '.join(bad) if bad else ''))
    return m


def play_word(page, word, wait=2200):
    page.fill('#word-input', word)
    page.click('#btn-submit')
    page.wait_for_timeout(wait)


def wait_my_turn(page, timeout=8000):
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        st = page.evaluate('window.__ITDA.state()')
        if not st or st['phase'] == 'over':
            return st
        if st['phase'] == 'me' and page.evaluate("!document.getElementById('word-input').disabled"):
            return st
        page.wait_for_timeout(120)
    return page.evaluate('window.__ITDA.state()')


def human_word(page):
    """사람이 낼 법한 단어: 지금 글자로 시작하는 흔한 단어."""
    return page.evaluate("""() => {
        const d = window.__ITDA.dict, st = window.__ITDA.state();
        const used = new Set(st.chain.map((c) => c.word));
        const cands = d.candidatesFor(st.needChar, used);
        const easy = cands.filter((w) => d.easyTier(w) && d.countFrom(w[w.length - 1]) >= 5);
        const pool = easy.length ? easy : cands;
        return pool[Math.floor(Math.random() * Math.min(pool.length, 40))] || null;
    }""")


def tour_setup(page, tag):
    page.wait_for_selector('#scr-setup:not([hidden])')
    page.wait_for_timeout(250)
    shot(page, f'{tag}-01-setup')
    measure(page, tag, 'setup')
    # 배려모드 켠 상태
    page.click('#btn-mercy')
    page.wait_for_timeout(200)
    shot(page, f'{tag}-02-setup-mercy')
    measure(page, tag, 'setup-mercy')
    page.click('#btn-mercy')
    page.wait_for_timeout(150)


def tour_level(page, tag, level, words=3):
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(120)
    page.evaluate(f"window.__ITDA.startGame({{level:{level}, first:'me', timeLimit:20}})")
    page.wait_for_timeout(450)
    shot(page, f'{tag}-lv{level}-a-start')
    measure(page, tag, f'lv{level}-start')
    played = []
    for _ in range(words):
        st = wait_my_turn(page, 8000)
        if not st or st['phase'] != 'me':
            break
        w = human_word(page)
        if not w:
            break
        played.append(w)
        play_word(page, w, wait=2600)
    st = page.evaluate('window.__ITDA.state()')
    shot(page, f'{tag}-lv{level}-b-mid')
    measure(page, tag, f'lv{level}-mid')
    info = page.evaluate("""() => {
        const st = window.__ITDA.state();
        return {
          phase: st.phase, need: st.needChar, mission: st.missionChar,
          chain: st.chain.map((c) => ({ who: c.who, word: c.word, kind: c.kind })),
          badge: document.getElementById('game-mercy').hidden ? null : document.getElementById('game-mercy').textContent,
        };
    }""")
    print(f"    Lv.{level} played={' '.join(played)} → phase={info['phase']} "
          f"chain={[c['word'] for c in info['chain']][-6:]}")
    return info


def tour_result(page, tag, level=3):
    """포기로 결과 화면을 열고, 배틀 내역을 펼쳐 본다."""
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.evaluate(f"window.__ITDA.startGame({{level:{level}, first:'me', timeLimit:20}})")
    page.wait_for_timeout(400)
    for _ in range(4):
        st = wait_my_turn(page, 8000)
        if not st or st['phase'] != 'me':
            break
        w = human_word(page)
        if not w:
            break
        play_word(page, w, wait=2400)
    page.click('#btn-quit')
    page.wait_for_timeout(500)
    shot(page, f'{tag}-result-a')
    measure(page, tag, 'result')
    page.click('#battle-log-btn')
    page.wait_for_timeout(350)
    shot(page, f'{tag}-result-b-log')
    measure(page, tag, 'result-log')
    log = page.evaluate("""() => {
        const box = document.getElementById('battle-log');
        const list = document.getElementById('battle-log-list');
        const rows = [...list.querySelectorAll('li')];
        return {
          open: !box.hidden,
          rows: rows.length,
          scrollable: box.scrollHeight > box.clientHeight + 2,
          listH: box.clientHeight, scrollH: box.scrollHeight,
          sample: rows.slice(0, 4).map((r) => r.textContent.replace(/\\s+/g, ' ').trim().slice(0, 60)),
          lastRowBottom: rows.length ? rows[rows.length - 1].getBoundingClientRect().bottom : null,
          sheetBottom: document.querySelector('.result-sheet').getBoundingClientRect().bottom,
        };
    }""")
    print(f"    결과/배틀 내역: {json.dumps(log, ensure_ascii=False)[:220]}")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(150)


def tour_mercy(game_page, tag):
    page = game_page
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.click('#btn-mercy')
    page.wait_for_timeout(150)
    page.evaluate("window.__ITDA.startGame({level:4, timeLimit:20})")
    page.wait_for_timeout(700)
    shot(page, f'{tag}-mercy-game')
    measure(page, tag, 'mercy-game')
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.click('#btn-mercy')
    page.wait_for_timeout(150)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=None)
    ap.add_argument('--only', default=None, help='한 화면 크기만: desktop|mobile|small')
    args = ap.parse_args()

    vps = {args.only: VIEWPORTS[args.only]} if args.only else VIEWPORTS
    httpd = None
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox', '--disable-dev-shm-usage'])
        if args.url:
            url = args.url
        else:
            httpd, port = serve(ROOT)
            url = f'http://127.0.0.1:{port}/index.html'
        for name, vp in vps.items():
            print(f'\n== {name} {vp["width"]}x{vp["height"]} ==')
            ctx = browser.new_context(viewport=vp, device_scale_factor=2, is_mobile=name != 'desktop',
                                      has_touch=name != 'desktop', locale='ko-KR')
            page = ctx.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)[:300]))
            page.on('console', lambda m: errors.append('console:' + m.text[:200]) if m.type == 'error' else None)
            t0 = time.time()
            page.goto(url, wait_until='domcontentloaded')
            page.wait_for_function('window.__ITDA && window.__ITDA.ready === true', timeout=120000)
            page.wait_for_selector('#scr-setup:not([hidden])', timeout=120000)
            print(f'  사전 로드 {time.time() - t0:.1f}s')

            tag = name
            tour_setup(page, tag)
            for lv in (1, 2, 3, 4, 5):
                tour_level(page, tag, lv, words=3 if lv <= 3 else 1)
            tour_result(page, tag, level=3)
            tour_mercy(page, tag)
            if errors:
                PROBLEMS.append((tag, 'errors', errors[:4]))
                print(f'  FAIL {tag} 페이지/콘솔 에러 {errors[:4]}')
            else:
                print(f'  ok   {tag} 페이지/콘솔 에러 0')
            ctx.close()
        browser.close()
    if httpd:
        httpd.shutdown()

    print('\n=== 화면 점검 요약 ===')
    if not PROBLEMS:
        print('문제 없음')
    else:
        for tag, where, bad in PROBLEMS:
            print(f'  {tag} / {where}: ' + ' | '.join(bad if isinstance(bad, list) else [bad]))
    print(f'스크린샷: {SHOT_DIR}')


if __name__ == '__main__':
    main()
