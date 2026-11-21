#!/usr/bin/env python3
"""보고용 라이브 스크린샷과 최종 점검.

- 데스크톱(1280x800)·모바일(390x844)에서 콘솔/페이지 에러 0, 가로 오버플로 0
- 페이지 텍스트·타이틀·메타태그에 옛 이름(끄투/kkutu) 0건
- 4단계 한방 봇 동작 확인
- downloads/hanbang-bot/ 에 setup.png, mobile-game.png, oneshot.png 저장

usage:
    python3 tools/report_shots.py --url https://hanbang-bot.onrender.com
"""
import argparse
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

CHROME = os.environ.get('HB_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
OUT = os.environ.get('SHOT_OUT', '/workspace/downloads/hanbang-bot')
BAD = ('끄투', 'kkutu', 'kkutu-killer')

FAILS = []


def check(cond, label, detail=''):
    print(('  PASS  ' if cond else '  FAIL  ') + label + (f'  [{detail}]' if detail else ''))
    if not cond:
        FAILS.append(label)
    return cond


def new_page(browser, vp):
    ctx = browser.new_context(viewport=vp, device_scale_factor=2 if vp['width'] < 500 else 1,
                              is_mobile=vp['width'] < 500, has_touch=vp['width'] < 500, locale='ko-KR')
    page = ctx.new_page()
    console, errors = [], []
    page.on('console', lambda m: console.append(m.text[:300]) if m.type == 'error' else None)
    page.on('pageerror', lambda e: errors.append(str(e)[:300]))
    return ctx, page, console, errors


def wait_ready(page, timeout=90000):
    page.wait_for_function('window.__HB && window.__HB.ready === true', timeout=timeout)
    page.wait_for_selector('#scr-setup:not([hidden])', timeout=timeout)


def overflow(page):
    return page.evaluate("""() => ({
        doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        body: document.body.scrollWidth - document.body.clientWidth,
    })""")


def brand_hits(page):
    return page.evaluate("""(bad) => {
        const hay = [
            document.title,
            document.body.innerText,
            ...[...document.querySelectorAll('meta')].map((m) => (m.getAttribute('content') || '')),
            ...[...document.querySelectorAll('[aria-label],[title],[placeholder]')]
                .map((el) => [el.getAttribute('aria-label'), el.getAttribute('title'), el.getAttribute('placeholder')].join(' ')),
        ].join('\\n').toLowerCase();
        const out = {};
        for (const b of bad) {
            const key = b.toLowerCase();
            const n = hay.split(key).length - 1;
            if (n) out[b] = n;
        }
        return out;
    }""", list(BAD))


def wait_my_turn(page, timeout=8000):
    end = time.time() + timeout / 1000
    while time.time() < end:
        st = page.evaluate('window.__HB.state()')
        if not st or st['phase'] == 'over':
            return st
        if st['phase'] == 'me' and page.evaluate("!document.getElementById('word-input').disabled"):
            return st
        page.wait_for_timeout(120)
    return page.evaluate('window.__HB.state()')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='https://hanbang-bot.onrender.com')
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    summary = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox', '--disable-dev-shm-usage'])

        # ── 데스크톱: 설정 화면 ─────────────────────────────
        print('== desktop 1280x800 ==')
        ctx, page, console, errors = new_page(browser, {'width': 1280, 'height': 800})
        page.goto(args.url, wait_until='domcontentloaded')
        wait_ready(page)
        size = page.evaluate('window.__HB.dict.size')
        check(size > 300000, '사전 로드', f'{size}단어')
        check(sum(overflow(page).values()) <= 0, '설정 화면 가로 오버플로 0', str(overflow(page)))
        hits = brand_hits(page)
        check(not hits, "설정 화면 옛 이름 0건", json.dumps(hits, ensure_ascii=False))
        page.screenshot(path=os.path.join(OUT, 'setup.png'))
        summary['desktop_setup'] = {'url': page.url, 'words': size, 'brand_hits': hits}

        # ── 데스크톱: 4단계 한방 ─────────────────────────────
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
        check(pick is not None, '한방 시나리오 탐색', str(pick))
        page.evaluate(f"window.__HB.startGame({{level:4, first:'me', startChar:'{pick['start']}'}})")
        page.wait_for_timeout(500)
        page.fill('#word-input', pick['word'])
        page.click('#btn-submit')
        page.wait_for_timeout(3600)
        st = page.evaluate('window.__HB.state()')
        bot_words = [c['word'] for c in st['chain'] if c['who'] == 'bot']
        last_bot = bot_words[-1] if bot_words else ''
        is_oneshot = page.evaluate("([w]) => !!w && window.__HB.dict.isOneShot(w)", [last_bot])
        check(st['phase'] == 'over' and is_oneshot, '4단계 봇 한방 즉사', f'{last_bot} / {st["phase"]}')
        check(page.is_visible('#ov-result'), '결과 화면 표시')
        check(sum(overflow(page).values()) <= 0, '결과 화면 가로 오버플로 0', str(overflow(page)))
        hits = brand_hits(page)
        check(not hits, '게임·결과 화면 옛 이름 0건', json.dumps(hits, ensure_ascii=False))
        page.screenshot(path=os.path.join(OUT, 'oneshot.png'))
        summary['desktop_oneshot'] = {'dealt': pick['word'], 'bot': last_bot, 'phase': st['phase']}
        summary['desktop_console_errors'] = console
        summary['desktop_page_errors'] = errors
        check(not console, '콘솔 에러 0', json.dumps(console, ensure_ascii=False)[:300])
        check(not errors, '페이지 에러 0', json.dumps(errors, ensure_ascii=False)[:300])
        ctx.close()

        # ── 모바일: 대전 화면 ───────────────────────────────
        print('== mobile 390x844 ==')
        ctx, page, console, errors = new_page(browser, {'width': 390, 'height': 844})
        page.goto(args.url, wait_until='domcontentloaded')
        wait_ready(page)
        check(sum(overflow(page).values()) <= 0, '모바일 설정 가로 오버플로 0', str(overflow(page)))
        page.click('.level[data-lv="2"]')
        page.click('#btn-start')
        page.wait_for_selector('#scr-game:not([hidden])')
        page.wait_for_timeout(400)
        for _ in range(2):
            st = wait_my_turn(page, 9000)
            if not st or st['phase'] != 'me':
                break
            w = page.evaluate("""() => {
                const d = window.__HB.dict, st = window.__HB.state();
                const used = new Set(st.chain.map((c) => c.word));
                const cands = d.candidatesFor(st.needChar, used).filter((x) => x.length >= 2);
                return cands[Math.min(2, cands.length - 1)] || null;
            }""")
            if not w:
                break
            page.fill('#word-input', w)
            page.click('#btn-submit')
            page.wait_for_timeout(2400)
        st = wait_my_turn(page, 9000)
        check(st and len(st['chain']) >= 3, '모바일 대전 진행', f"{len(st['chain']) if st else 0}단어")
        check(sum(overflow(page).values()) <= 0, '모바일 대전 가로 오버플로 0', str(overflow(page)))
        hits = brand_hits(page)
        check(not hits, '모바일 화면 옛 이름 0건', json.dumps(hits, ensure_ascii=False))
        page.screenshot(path=os.path.join(OUT, 'mobile-game.png'))
        summary['mobile_game'] = {'chain': [c['word'] for c in st['chain']], 'brand_hits': hits}
        summary['mobile_console_errors'] = console
        summary['mobile_page_errors'] = errors
        check(not console, '모바일 콘솔 에러 0', json.dumps(console, ensure_ascii=False)[:300])
        check(not errors, '모바일 페이지 에러 0', json.dumps(errors, ensure_ascii=False)[:300])
        ctx.close()
        browser.close()

    print('\n=== 요약 ===')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if FAILS:
        print(f'실패 {len(FAILS)}건: {FAILS}')
        sys.exit(1)
    print('모든 점검 통과 · 스크린샷:', OUT)


if __name__ == '__main__':
    main()
