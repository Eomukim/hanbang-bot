#!/usr/bin/env python3
"""보고용 스크린샷 생성: downloads/hanbang-bot/ 에 저장."""
import functools
import http.server
import json
import os
import socketserver
import threading
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get('SHOT_OUT', '/workspace/downloads/hanbang-bot')
CHROME = os.environ.get('HB_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
URL = os.environ.get('SHOT_URL', '')

os.makedirs(OUT, exist_ok=True)

httpd = None
if not URL:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    httpd = socketserver.ThreadingTCPServer(('127.0.0.1', 0), handler)
    httpd.daemon_threads = True
    URL = f'http://127.0.0.1:{httpd.server_address[1]}/index.html'
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

print('url:', URL)


def shot(page, name):
    path = os.path.join(OUT, f'{name}.png')
    page.screenshot(path=path)
    print('  ', path)


def wait_my_turn(page, timeout=10000):
    end = time.time() + timeout / 1000
    while time.time() < end:
        st = page.evaluate('window.__HB.state()')
        if st and st['phase'] in ('me', 'over') and page.evaluate("!document.getElementById('word-input').disabled"):
            return st
        if st and st['phase'] == 'over':
            return st
        page.wait_for_timeout(100)
    return page.evaluate('window.__HB.state()')


def play(page, word, wait=2400):
    page.fill('#word-input', word)
    page.click('#btn-submit')
    page.wait_for_timeout(wait)


def pick_word(page, min_len=2, prefer_count=40):
    return page.evaluate("""([minLen, prefer]) => {
        const d = window.__HB.dict, st = window.__HB.state();
        const used = new Set(st.chain.map((c) => c.word));
        const cands = d.candidatesFor(st.needChar, used).filter((w) => w.length >= minLen);
        const nice = cands.filter((w) => d.countFrom(w[w.length - 1]) >= prefer);
        const pool = nice.length ? nice : cands;
        return pool.length ? pool[Math.floor(pool.length / 2)] : null;
    }""", [min_len, prefer_count])


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox', '--disable-dev-shm-usage'])

    for vp_name, vp in (('desktop', {'width': 1280, 'height': 800}), ('mobile', {'width': 390, 'height': 844})):
        ctx = browser.new_context(viewport=vp, device_scale_factor=2, is_mobile=(vp_name == 'mobile'),
                                  has_touch=(vp_name == 'mobile'), locale='ko-KR')
        page = ctx.new_page()
        page.goto(URL, wait_until='domcontentloaded')
        page.wait_for_function('window.__HB && window.__HB.ready === true', timeout=90000)
        page.wait_for_selector('#scr-setup:not([hidden])')
        page.wait_for_timeout(400)
        shot(page, f'{vp_name}-1-setup')

        # 3단계 대전 중반
        page.click('.level[data-lv="3"]')
        page.click('#btn-start')
        page.wait_for_selector('#scr-game:not([hidden])')
        page.wait_for_timeout(700)
        for _ in range(4):
            st = wait_my_turn(page)
            if not st or st['phase'] != 'me':
                break
            w = pick_word(page)
            if not w:
                break
            play(page, w, wait=2700)
        st = wait_my_turn(page)
        if st and st['phase'] == 'me':
            shot(page, f'{vp_name}-2-game')
        else:
            page.evaluate("window.__HB.app.hideResult(); window.__HB.startGame({level:2, first:'me'})")
            page.wait_for_timeout(600)
            st = wait_my_turn(page)
            w = pick_word(page) if st and st['phase'] == 'me' else None
            if w:
                play(page, w, wait=2200)
            shot(page, f'{vp_name}-2-game')

        # 모바일: 키보드가 올라온 높이
        if vp_name == 'mobile':
            page.set_viewport_size({'width': 390, 'height': 520})
            page.focus('#word-input')
            page.wait_for_timeout(500)
            shot(page, 'mobile-3-keyboard')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.wait_for_timeout(300)

        # 4단계 한방: 내가 낸 단어 뒤에 봇이 한방 단어를 꽂는 순간
        pick = page.evaluate("""() => {
            const d = window.__HB.dict;
            for (const [ch] of d.ranges) {
                const mine = d.candidatesFor(ch, new Set());
                for (const w of mine.slice(0, 150)) {
                    const last = w[w.length - 1];
                    const bot = d.candidatesFor(last, new Set([w]));
                    const os = bot.find((x) => d.isOneShot(x));
                    if (os) return { start: ch, word: w, oneshot: os };
                }
            }
            return null;
        }""")
        print('level4 scenario:', json.dumps(pick, ensure_ascii=False))
        page.evaluate(f"window.__HB.startGame({{level:4, first:'me', startChar:'{pick['start']}'}})")
        page.wait_for_timeout(600)
        play(page, pick['word'], wait=520)
        # KO 연출 타이밍
        for _ in range(14):
            if page.is_visible('.ko-splash'):
                break
            page.wait_for_timeout(80)
        page.wait_for_timeout(120)
        shot(page, f'{vp_name}-5-oneshot-ko')
        page.wait_for_timeout(1400)
        if page.is_visible('#ov-result'):
            shot(page, f'{vp_name}-6-result')
        page.evaluate("window.__HB.app.hideResult()")
        ctx.close()

    browser.close()

if httpd:
    httpd.shutdown()
print('done')
