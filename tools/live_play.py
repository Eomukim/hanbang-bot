#!/usr/bin/env python3
"""라이브 실전 플레이 점검: 사람처럼 두면서(흔한 단어 위주, 막히면 한방) 각 난이도와 실제로 겨룬다.

각 판마다 봇이 낸 단어·태그·응답 시간, 내가 이어 간 수, 끝난 이유를 남기고 스크린샷을 찍는다.

usage:
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/live_play.py --levels 1,2,3
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/live_play.py --levels 4,5 --games 2
"""
import argparse
import json
import os
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get('ITDA_SHOT_DIR') or os.path.join(ROOT, 'downloads', 'live-play')
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')


def wait_my_turn(page, timeout=9000):
    end = time.time() + timeout / 1000
    while time.time() < end:
        st = page.evaluate('window.__ITDA.state()')
        if not st or st['phase'] == 'over':
            return st
        if st['phase'] == 'me' and page.evaluate("!document.getElementById('word-input').disabled"):
            return st
        page.wait_for_timeout(100)
    return page.evaluate('window.__ITDA.state()')


def human_move(page):
    """사람처럼: 일상 명사 중 다음 사람이 답하기 쉬운 글자로 끝나는 단어를 고른다.
    그런 단어가 없으면 사전에서 아는 척할 수 있는 4글자 이하 표준어, 마지막엔 한방."""
    return page.evaluate("""() => {
        const d = window.__ITDA.dict, st = window.__ITDA.state();
        const used = new Set(st.chain.map((c) => c.word));
        const cands = d.candidatesFor(st.needChar, used);
        if (!cands.length) return null;
        const easy = cands.filter((w) => d.easyTier(w) && d.easyCountFrom(w[w.length - 1]) >= 3);
        if (easy.length) return easy[Math.floor(Math.random() * easy.length)];
        const plain = cands.filter((w) => w.length <= 4 && (d.flagOf(w) & (2 | 8 | 16 | 32)) === 0
            && d.easyCountFrom(w[w.length - 1]) >= 1);
        if (plain.length) return plain[Math.floor(Math.random() * plain.length)];
        const shots = cands.filter((w) => d.countFrom(w[w.length - 1]) === 0);
        if (shots.length) return shots[0];
        return cands[Math.floor(Math.random() * Math.min(cands.length, 50))];
    }""")


def play(page, level, tag, maxMoves=14, timeLimit=20):
    page.evaluate("window.__ITDA.app.engine && window.__ITDA.app.engine.destroy()")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    page.wait_for_timeout(120)
    page.evaluate(f"window.__ITDA.startGame({{level:{level}, first:'me', timeLimit:{timeLimit}}})")
    page.wait_for_timeout(400)
    mine = []
    t_bot = []
    for _ in range(maxMoves):
        st = wait_my_turn(page, 9000)
        if not st or st['phase'] != 'me':
            break
        w = human_move(page)
        if not w:
            break
        mine.append(w)
        page.fill('#word-input', w)
        page.click('#btn-submit')
        page.wait_for_timeout(300)
        # 봇 응답 대기
        t0 = time.time()
        while time.time() - t0 < 8:
            st = page.evaluate('window.__ITDA.state()')
            if st['phase'] in ('me', 'over'):
                break
            page.wait_for_timeout(80)
        t_bot.append(round(time.time() - t0, 2))
        if st['phase'] == 'over':
            break
    st = page.evaluate('window.__ITDA.state()')
    over = page.evaluate("!document.getElementById('ov-result').hidden")
    info = page.evaluate("""() => {
        const st = window.__ITDA.state();
        const rows = st.chain.map((c) => ({ who: c.who === 'bot' ? 'bot' : 'me', word: c.word, tags: [c.kind] }));
        const res = document.getElementById('ov-result');
        return {chain: rows, result: res.hidden ? null : {
          title: document.getElementById('result-title').textContent,
          reason: document.getElementById('result-reason').textContent,
          level: document.getElementById('result-level-label').textContent,
        }};
    }""")
    shot = os.path.join(OUT, f'{tag}-lv{level}.png')
    os.makedirs(OUT, exist_ok=True)
    page.screenshot(path=shot)
    print(f"\n  Lv.{level}: 내 {len(mine)}수 / 끝={st['phase']} / 결과={info['result']}")
    print('   내 단어: ' + ' '.join(mine))
    bot_words = [r['word'] + ('(' + ','.join(r['tags']) + ')' if r['tags'] else '') for r in info['chain'] if r['who'] == 'bot']
    print('   봇 단어: ' + ' '.join(bot_words))
    print(f"   봇 응답 텀 {t_bot} / 스크린샷 {shot}")
    page.evaluate("window.__ITDA.app.hideResult(); window.__ITDA.app.show('setup')")
    return {'level': level, 'mine': mine, 'bot': bot_words, 'result': info['result']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='https://itda-play.onrender.com')
    ap.add_argument('--levels', default='1,2,3,4,5')
    ap.add_argument('--games', type=int, default=1)
    ap.add_argument('--viewport', default='mobile')
    args = ap.parse_args()
    vp = {'desktop': {'width': 1280, 'height': 800}, 'mobile': {'width': 390, 'height': 844}}[args.viewport]
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])
        ctx = b.new_context(viewport=vp, device_scale_factor=2, is_mobile=args.viewport != 'desktop',
                            has_touch=args.viewport != 'desktop', locale='ko-KR')
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)[:200]))
        page.on('console', lambda m: errors.append('console:' + m.text[:160]) if m.type == 'error' else None)
        page.goto(args.url)
        page.wait_for_function('window.__ITDA && window.__ITDA.ready === true', timeout=120000)
        page.wait_for_selector('#scr-setup:not([hidden])', timeout=120000)
        for lv in [int(x) for x in args.levels.split(',')]:
            for g in range(args.games):
                out.append(play(page, lv, f'{args.viewport}-g{g + 1}'))
        print('\n에러:', errors or 0)
        b.close()
    print('\n요약:', json.dumps([{'lv': o['level'], 'mine': len(o['mine']), 'result': (o['result'] or {}).get('title')} for o in out], ensure_ascii=False))


if __name__ == '__main__':
    main()
