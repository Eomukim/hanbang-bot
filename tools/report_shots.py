#!/usr/bin/env python3
"""보고용 라이브 스크린샷과 최종 점검.

- 데스크톱(1280x800)·모바일(390x844)에서 콘솔/페이지 에러 0, 가로 오버플로 0
- 페이지 텍스트·타이틀·메타태그에 옛 이름(끄투/kkutu) 0건
- 난이도 5단계(Lv.4 극악 · Lv.5 지옥) 카드와 Lv.5 대전 화면
- Lv.5 지옥 봇이 실제로: 한방 즉사 · 상대 한방 각 회피 · 강제 필승 · 소수 후보 압박 · 미션/장문
- 4단계 극악 한방 봇 동작 확인
- 내 단어장 삭제(버튼·모달·사전 API 없음)와 효과음 설정 행 전체 폭
- 힌트 삭제(버튼·문구·API 없음)
- 하드코어 모드: 스위치·5초 고정·봇 선공·헤더/결과 배지·별도 전적, 끄면 일반 모드
- 결과 화면(승리·패배·포기)의 난이도 배지
- downloads/hanbang-bot/ 에 setup.png, lv5-setup.png, lv5-game.png, oneshot.png,
  result-win.png, result-lv5.png, mobile-game.png, mobile-lv5.png, mobile-result.png,
  hardcore-setup.png, hardcore-game.png, hardcore-result.png 저장

usage:
    python3 tools/report_shots.py --url https://hanbang-bot.onrender.com
"""
import argparse
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify import HELL_PROPS, HELL_PICKS, serve  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


def human_word(page, cautious=False):
    """사람처럼 2~4글자 단어를 고른다. cautious 면 봇에게 바로 한방을 내주지 않는 자리로."""
    return page.evaluate("""(cautious) => {
        const d = window.__HB.dict, st = window.__HB.state();
        const used = new Set(st.chain.map((c) => c.word));
        const cands = d.candidatesFor(st.needChar, used);
        if (!cands.length) return null;
        let pool = cands.filter((x) => x.length <= 4);
        if (!pool.length) pool = cands;
        if (cautious) {
            const killAt = (node, usedSet) => {
                const shots = d.shotWords(node);
                if (shots) for (const x of shots) if (!usedSet.has(x) && d.countFrom(x[x.length - 1]) === 0) return x;
                const cs = d.candidatesFor(node, usedSet);
                if (cs.length <= 40) for (const x of cs) if (d.countFrom(x[x.length - 1]) === 0) return x;
                return null;
            };
            const safe = cands.filter((w) => {
                const u = new Set(used); u.add(w);
                return !killAt(w[w.length - 1], u) && w.length <= 6;
            });
            const neutral = safe.filter((w) => d.graphStatus(w[w.length - 1]) === 'D');
            if (neutral.length) pool = neutral;
            else if (safe.length) pool = safe;
        }
        return pool[Math.min(cautious ? 2 : 4, pool.length - 1)];
    }""", cautious)


def live_kill(page, node, used):
    return page.evaluate("""([node, usedWords]) => {
        const d = window.__HB.dict;
        const used = new Set(usedWords);
        const shots = d.shotWords(node);
        if (shots) for (const w of shots) if (!used.has(w) && d.countFrom(w[w.length - 1]) === 0) return w;
        const cands = d.candidatesFor(node, used);
        if (cands.length <= 40) for (const w of cands) if (d.countFrom(w[w.length - 1]) === 0) return w;
        return null;
    }""", [node, used])


def result_view(page):
    return page.evaluate("""() => {
        const box = document.getElementById('result-level');
        return {
            visible: !document.getElementById('ov-result').hidden,
            title: document.getElementById('result-title').textContent,
            reason: document.getElementById('result-reason').textContent,
            lv: box ? box.dataset.lv : null,
            label: box ? document.getElementById('result-level-label').textContent : '',
        };
    }""")


def play_hell_game(page, turns=4, shot_path=None):
    """Lv.5 지옥과 실제로 한 판: 사람처럼 두고 봇의 응수·태그·시간·한방 각을 기록."""
    page.evaluate("window.__HB.app.engine && window.__HB.app.engine.destroy()")
    page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
    page.evaluate("window.__HB.startGame({level:5, first:'me', timeLimit:20})")
    page.wait_for_timeout(350)
    info = {'gaps': [], 'tags': [], 'bot': [], 'handed': 0, 'avoidable': 0, 'kills': 0, 'proven': 0, 'shot': False}
    for _ in range(turns):
        st = wait_my_turn(page, 8000)
        if not st or st['phase'] != 'me':
            break
        w = human_word(page, cautious=True)
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
            info['gaps'].append((time.time() - t0) * 1000)
        except Exception:
            break
        tag_text = page.evaluate("document.querySelector('#stage .tag.danger')?.textContent || ''")
        if tag_text:
            info['tags'].append(tag_text)
        st = page.evaluate('window.__HB.state()')
        bot = [c for c in st['chain'] if c['who'] == 'bot']
        if bot:
            last = bot[-1]
            info['bot'].append(last)
            if last['kind'] == 'oneshot':
                info['kills'] += 1
            # 'outer' = 실제 응수를 확인한 강제 필승, 'route' = 그래프상 이기는 자리(화면 표기 '필승 라인')
            if last['kind'] in ('outer', 'route'):
                info['proven'] += 1
            # 봇이 내준 자리에 내가 바로 한방을 쓸 수 있는가 = 봇이 한방 각을 내줬는가
            used = [c['word'] for c in st['chain']]
            end = last['word'][-1]
            if live_kill(page, end, used):
                info['handed'] += 1
                # 같은 자리에서 피할 수 있었는지: 봇이 다른 끝 글자를 고를 수 있었는지
                alt = page.evaluate("""([usedWords]) => {
                    const d = window.__HB.dict, st = window.__HB.state();
                    const prev = st.chain[st.chain.length - 2];
                    const used = new Set(usedWords);
                    used.delete(st.chain[st.chain.length - 1].word);
                    const cands = d.candidatesFor(prev.word[prev.word.length - 1], used);
                    for (const w of cands) {
                        const e = w[w.length - 1];
                        if (d.countFrom(e) === 0) return w;
                        const used2 = new Set(used); used2.add(w);
                        const shots = d.shotWords(e);
                        let danger = false;
                        if (shots) for (const x of shots) if (!used2.has(x) && d.countFrom(x[x.length - 1]) === 0) { danger = true; break; }
                        if (!danger) return w;
                    }
                    return null;
                }""", [used])
                if alt:
                    info['avoidable'] += 1
        if st['phase'] == 'me' and shot_path and not info['shot']:
            page.wait_for_timeout(1300)   # 한방 연출이 걷힌 뒤의 대전 화면
            page.screenshot(path=shot_path)
            info['shot'] = True
        if st['phase'] == 'over':
            break
    if shot_path and not info['shot']:
        page.wait_for_timeout(1200)
        page.screenshot(path=shot_path)
        info['shot'] = True
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='https://hanbang-bot.onrender.com')
    ap.add_argument('--local', action='store_true')
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    summary = {}

    httpd = None
    url = args.url
    if args.local:
        httpd, port = serve(ROOT)
        url = f'http://127.0.0.1:{port}/index.html'

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox', '--disable-dev-shm-usage'])

        # ── 데스크톱: 설정 화면 ─────────────────────────────
        print('== desktop 1280x800 ==')
        ctx, page, console, errors = new_page(browser, {'width': 1280, 'height': 800})
        page.goto(url, wait_until='domcontentloaded')
        wait_ready(page)
        size = page.evaluate('window.__HB.dict.size')
        check(size > 300000, '사전 로드', f'{size}단어')
        check(sum(overflow(page).values()) <= 0, '설정 화면 가로 오버플로 0', str(overflow(page)))
        hits = brand_hits(page)
        check(not hits, '설정 화면 옛 이름 0건', json.dumps(hits, ensure_ascii=False))
        page.screenshot(path=os.path.join(OUT, 'setup.png'))

        gone = page.evaluate("""() => ({
            btn: !!document.getElementById('btn-custom'),
            modal: !!document.getElementById('ov-custom'),
            text: document.body.innerText.includes('내 단어장'),
            api: ['custom', 'customByStart', 'addCustom', 'removeCustom', 'setCustom', 'customStartCount', 'meanOf']
                .filter((k) => window.__HB.dict[k] !== undefined),
            row: Math.round(document.getElementById('btn-sound').getBoundingClientRect().width),
            box: Math.round(document.querySelector('.setup-actions').getBoundingClientRect().width),
        })""")
        check(not gone['btn'] and not gone['modal'] and not gone['text'] and not gone['api'],
              '내 단어장 삭제(버튼·모달·API·문구 없음)', json.dumps(gone, ensure_ascii=False))
        check(gone['row'] >= gone['box'] - 1 and gone['row'] > 200,
              '효과음 설정 행 전체 폭', f"{gone['row']}/{gone['box']}px")

        cards = page.evaluate("""() => [...document.querySelectorAll('.level')].map((el) => ({
            lv: el.dataset.lv, name: el.querySelector('b').textContent, label: el.querySelector('small').textContent }))""")
        check(len(cards) == 5 and [c['name'] for c in cards] == ['쉬움', '보통', '어려움', '극악', '지옥'],
              '난이도 5단계 카드', str([c['name'] for c in cards]))

        # ── 데스크톱: Lv.5 선택 ─────────────────────────────
        page.click('.level[data-lv="5"]')
        page.wait_for_timeout(250)
        desc = page.evaluate("document.getElementById('lv-desc').textContent")
        check('필승' in desc or '수읽기' in desc, 'Lv.5 지옥 설명', desc)
        check(sum(overflow(page).values()) <= 0, 'Lv.5 선택 화면 가로 오버플로 0', str(overflow(page)))
        page.screenshot(path=os.path.join(OUT, 'lv5-setup.png'))

        # ── 데스크톱: Lv.5 지옥과 실제 대전 ─────────────────
        shot_path = os.path.join(OUT, 'lv5-game.png')
        game = play_hell_game(page, turns=5, shot_path=shot_path)
        for _ in range(3):   # 증거가 모자라면 판을 더 둔다 (2수 이상 + 한방/필승 수 1회)
            if len(game['bot']) >= 2 and (game['kills'] + game['proven']) >= 1:
                break
            more = play_hell_game(page, turns=5, shot_path=None)
            for key in ('gaps', 'tags', 'bot'):
                game[key].extend(more[key])
            game['handed'] += more['handed']
            game['avoidable'] += more['avoidable']
            game['kills'] += more['kills']
            game['proven'] += more['proven']
        st = page.evaluate('window.__HB.state()')
        check(len(game['bot']) >= 2, 'Lv.5 실제 대전 응수', f"{len(game['bot'])}수")
        check(game['avoidable'] == 0, 'Lv.5 상대 한방 각 회피',
              f"내준 자리 {game['handed']}회 / 피할 수 있었던 {game['avoidable']}회")
        check(game['kills'] >= 1 or game['proven'] >= 1, 'Lv.5 한방·필승 수 사용',
              f"한방 {game['kills']} · 필승 {game['proven']}")
        if game['gaps']:
            check(min(game['gaps']) <= 900, 'Lv.5 실제 응답 시간',
                  f"{min(game['gaps']):.0f}~{max(game['gaps']):.0f}ms")
        check(sum(overflow(page).values()) <= 0, 'Lv.5 대전 가로 오버플로 0', str(overflow(page)))
        hits = brand_hits(page)
        check(not hits, 'Lv.5 대전 옛 이름 0건', json.dumps(hits, ensure_ascii=False))
        summary['lv5_game'] = {
            'bot_moves': [(c['word'], c['kind']) for c in game['bot']],
            'tags': game['tags'],
            'response_ms': [round(x) for x in game['gaps']],
            'handed': game['handed'], 'avoidable': game['avoidable'],
        }

        # ── Lv.5 판단 특성 (직접 호출 표본) ─────────────────
        props = page.evaluate(HELL_PROPS)
        picks = page.evaluate(HELL_PICKS)
        check(props['handedKillAvoidable'] == 0, 'Lv.5 표본: 한방 각 회피',
              f"{props['moves']}수 중 피할 수 있었던 {props['handedKillAvoidable']}회")
        check(props['outerBroken'] == 0 and props['outer'] >= 3, 'Lv.5 표본: 강제필승 검증',
              f"{props['outer']}수 중 깨진 것 {props['outerBroken']}")
        check(props['kinds'].get('oneshot', 0) >= 5, 'Lv.5 표본: 한방 즉사', str(props['kinds']))
        check(props['endDead'] + props['endThin'] >= props['moves'] * 0.5, 'Lv.5 표본: 압박',
              f"죽은 자리 {props['endDead']} · 한두 후보 {props['endThin']}")
        check(props['longMoves'] >= props['moves'] * 0.3, 'Lv.5 표본: 장문·고득점',
              f"{props['longMoves']}/{props['moves']}수 5글자 이상")
        check(props['delayMin'] >= 140 and props['delayMax'] <= 410, 'Lv.5 응답 텀 0.15~0.4초',
              f"{props['delayMin']:.0f}~{props['delayMax']:.0f}ms")
        check(props['msMax'] < 60, 'Lv.5 판단 속도', f"평균 {props['msAvg']}ms / 최대 {props['msMax']}ms")
        check(picks.get('kill', {}).get('equal'), 'Lv.5 미션·최고점 한방 선택',
              json.dumps(picks.get('kill'), ensure_ascii=False)[:160])
        check(picks.get('pressure', {}).get('squeezed'), 'Lv.5 소수 후보 글자로 압박',
              json.dumps(picks.get('pressure'), ensure_ascii=False)[:160])
        check(picks.get('mission', {}).get('agree') == picks.get('mission', {}).get('checked'),
              'Lv.5 같은 끝 글자에서 최고점 단어 선택',
              json.dumps(picks.get('mission'), ensure_ascii=False)[:160])
        summary['lv5_props'] = {k: props[k] for k in ('moves', 'kinds', 'outer', 'outerBroken',
                                                     'handedKill', 'handedKillAvoidable',
                                                     'msAvg', 'msMax', 'delayMin', 'delayMax',
                                                     'endDead', 'endThin', 'longMoves')}
        summary['lv5_picks'] = picks

        # ── 데스크톱: 4단계 극악 한방 ───────────────────────
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
        if pick:
            page.evaluate("window.__HB.app.engine.destroy()")
            page.evaluate("window.__HB.app.hideResult()")
            page.evaluate(f"window.__HB.startGame({{level:4, first:'me', startChar:'{pick['start']}'}})")
            page.wait_for_timeout(500)
            page.fill('#word-input', pick['word'])
            page.click('#btn-submit')
            page.wait_for_timeout(3600)
            st = page.evaluate('window.__HB.state()')
            bot_words = [c['word'] for c in st['chain'] if c['who'] == 'bot']
            last_bot = bot_words[-1] if bot_words else ''
            is_oneshot = page.evaluate("([w]) => !!w && window.__HB.dict.isOneShot(w)", [last_bot])
            check(st['phase'] == 'over' and is_oneshot, '4단계 극악 봇 한방 즉사',
                  f'{last_bot} / {st["phase"]}')
            check(page.is_visible('#ov-result'), '결과 화면 표시')
            check(sum(overflow(page).values()) <= 0, '결과 화면 가로 오버플로 0', str(overflow(page)))
            lv4 = result_view(page)
            check(lv4['label'] == 'Lv.4 극악',
                  '패배 결과 화면 난이도(Lv.4 극악)', json.dumps(lv4, ensure_ascii=False))
            hits = brand_hits(page)
            check(not hits, '게임·결과 화면 옛 이름 0건', json.dumps(hits, ensure_ascii=False))
            page.screenshot(path=os.path.join(OUT, 'oneshot.png'))
            summary['desktop_oneshot'] = {'dealt': pick['word'], 'bot': last_bot, 'phase': st['phase']}

        # ── 데스크톱: 승리 결과 화면 난이도 ─────────────────
        win_pick = page.evaluate("""() => {
            const d = window.__HB.dict;
            for (const [ch] of d.ranges) {
                const w = d.candidatesFor(ch, new Set()).find((x) => d.countFrom(x[x.length - 1]) === 0);
                if (w) return { start: ch, word: w };
            }
            return null;
        }""")
        if check(win_pick is not None, '승리용 한방 단어 탐색', str(win_pick)):
            page.evaluate('window.__HB.app.engine && window.__HB.app.engine.destroy()')
            page.evaluate('window.__HB.app.hideResult()')
            page.evaluate(f"window.__HB.startGame({{level:1, first:'me', startChar:'{win_pick['start']}'}})")
            page.wait_for_timeout(450)
            page.fill('#word-input', win_pick['word'])
            page.click('#btn-submit')
            page.wait_for_timeout(1800)
            page.wait_for_timeout(1400)   # 축하 연출이 걷힌 뒤의 결과 화면
            win = result_view(page)
            check(win['title'] == '승리' and win['label'] == 'Lv.1 쉬움',
                  '승리 결과 화면 난이도(Lv.1 쉬움)', json.dumps(win, ensure_ascii=False))
            check(sum(overflow(page).values()) <= 0, '승리 결과 화면 가로 오버플로 0', str(overflow(page)))
            hits = brand_hits(page)
            check(not hits, '승리 결과 화면 옛 이름 0건', json.dumps(hits, ensure_ascii=False))
            page.screenshot(path=os.path.join(OUT, 'result-win.png'))
            summary['desktop_win'] = {'word': win_pick['word'], 'title': win['title'], 'level': win['label']}

        # ── 데스크톱: Lv.5 포기 결과 화면 난이도 ────────────
        page.evaluate('window.__HB.app.hideResult()')
        page.evaluate("window.__HB.startGame({level:5, first:'me', timeLimit:20})")
        page.wait_for_timeout(400)
        page.evaluate('window.__HB.engine.quit()')
        page.wait_for_timeout(1000)
        lv5 = result_view(page)
        check(lv5['title'] == '패배' and lv5['label'] == 'Lv.5 지옥',
              '포기 결과 화면 난이도(Lv.5 지옥)', json.dumps(lv5, ensure_ascii=False))
        page.screenshot(path=os.path.join(OUT, 'result-lv5.png'))
        summary['desktop_lv5_quit'] = {'title': lv5['title'], 'level': lv5['label'], 'reason': lv5['reason']}
        page.evaluate('window.__HB.app.hideResult()')

        # ── 데스크톱: 힌트 삭제 · 하드코어 모드 ──────────────
        page.evaluate('window.__HB.app.engine && window.__HB.app.engine.destroy()')
        page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
        page.wait_for_timeout(250)
        no_hint = page.evaluate("""() => ({
            btn: !!document.getElementById('btn-hint'),
            cls: document.querySelectorAll('.btn.hint, .hint').length,
            text: document.body.innerText.includes('힌트'),
            api: ['useHint', 'hint'].filter((k) => typeof window.__HB.app[k] === 'function'),
        })""")
        check(not no_hint['btn'] and no_hint['cls'] == 0 and not no_hint['text'] and not no_hint['api'],
              '힌트 버튼·문구·API 삭제', json.dumps(no_hint, ensure_ascii=False))

        if page.evaluate("document.getElementById('btn-hardcore').getAttribute('aria-checked')") == 'true':
            page.click('#btn-hardcore')
            page.wait_for_timeout(180)
        page.click('.level[data-lv="3"]')
        page.wait_for_timeout(120)
        page.click('#btn-hardcore')
        page.wait_for_timeout(300)
        hc_setup = page.evaluate("""() => ({
            on: document.getElementById('btn-hardcore').getAttribute('aria-checked'),
            time: document.getElementById('time-locked').innerText.trim(),
            first: document.getElementById('first-locked').innerText.trim(),
            timeLocked: document.getElementById('time-opts').hidden,
            composer: [...document.getElementById('composer').children].map((el) => el.id || el.tagName),
        })""")
        check(hc_setup['on'] == 'true' and '5초' in hc_setup['time'] and '봇부터' in hc_setup['first']
              and hc_setup['timeLocked'],
              '하드코어 설정: 5초 고정 · 봇부터 잠금', json.dumps(hc_setup, ensure_ascii=False))
        check(sum(overflow(page).values()) <= 0, '하드코어 설정 가로 오버플로 0', str(overflow(page)))
        hits = brand_hits(page)
        check(not hits, '하드코어 설정 옛 이름 0건', json.dumps(hits, ensure_ascii=False))
        page.screenshot(path=os.path.join(OUT, 'hardcore-setup.png'))

        page.click('#btn-start')
        page.wait_for_selector('#scr-game:not([hidden])')
        wait_my_turn(page, 7000)
        page.wait_for_timeout(520)   # 봇 단어 등장 애니메이션이 끝난 뒤
        hc_game = page.evaluate("""() => {
            const st = window.__HB.state();
            const badge = document.getElementById('game-hardcore');
            return {
                hardcore: window.__HB.engine.hardcore,
                limit: window.__HB.engine.timeLimit,
                first: window.__HB.engine.first,
                phase: st.phase,
                chain: st.chain.map((c) => c.who),
                badge: !badge.hidden,
                badgeText: badge.innerText.replace(/\\s+/g, ' ').trim(),
                time: document.getElementById('time-left').textContent,
                left: window.__HB.engine.timeLeft(),
                composer: [...document.getElementById('composer').children].map((el) => el.id || el.tagName),
                input: Math.round(document.getElementById('word-input').getBoundingClientRect().width),
                go: Math.round(document.getElementById('btn-submit').getBoundingClientRect().width),
                box: Math.round(document.getElementById('composer').getBoundingClientRect().width),
            };
        }""")
        check(hc_game['hardcore'] and hc_game['limit'] == 5 and hc_game['first'] == 'bot',
              '하드코어 대국 5초·봇 선공', json.dumps({k: hc_game[k] for k in ('limit', 'first', 'phase')}, ensure_ascii=False))
        check(hc_game['chain'][:1] == ['bot'], '하드코어 봇 선공 실제 확인', str(hc_game['chain']))
        check(hc_game['badge'] and '하드코어' in hc_game['badgeText'], '대전 헤더 하드코어 배지', hc_game['badgeText'])
        check(hc_game['composer'] == ['word-input', 'btn-submit']
              and hc_game['input'] >= hc_game['box'] * 0.7
              and abs(hc_game['input'] + hc_game['go'] + 8 - hc_game['box']) <= 3,
              '힌트 없는 입력 바 폭 채움',
              f"{hc_game['input']} + {hc_game['go']} = {hc_game['box']}px")
        check(sum(overflow(page).values()) <= 0, '하드코어 대전 가로 오버플로 0', str(overflow(page)))
        page.screenshot(path=os.path.join(OUT, 'hardcore-game.png'))

        # 5초를 넘겨 시간 초과 결과까지 기다린다
        try:
            page.wait_for_function("() => !document.getElementById('ov-result').hidden", timeout=9000)
        except Exception:
            pass
        page.wait_for_timeout(150)
        hc_res = result_view(page)
        hc_badge = page.evaluate("!document.getElementById('result-hardcore').hidden")
        check(hc_res['title'] == '패배' and '시간' in hc_res['reason'] and hc_badge,
              '하드코어 결과(시간 초과) 배지', json.dumps(hc_res, ensure_ascii=False))
        rec = page.evaluate("JSON.parse(localStorage.getItem('hanbang.record.v1') || '{}')")
        check(bool(rec.get('3:hc')) and rec['3:hc'].get('plays', 0) >= 1,
              '하드코어 전적 별도 기록', json.dumps(rec.get('3:hc'), ensure_ascii=False))
        check(sum(overflow(page).values()) <= 0, '하드코어 결과 가로 오버플로 0', str(overflow(page)))
        hits = brand_hits(page)
        check(not hits, '하드코어 결과 옛 이름 0건', json.dumps(hits, ensure_ascii=False))
        page.screenshot(path=os.path.join(OUT, 'hardcore-result.png'))
        summary['hardcore'] = {'setup': hc_setup, 'game': {k: hc_game[k] for k in ('limit', 'first', 'badgeText', 'time')},
                               'result': hc_res, 'record': rec.get('3:hc')}

        page.evaluate("window.__HB.app.hideResult(); window.__HB.app.show('setup')")
        page.wait_for_timeout(200)
        page.click('#btn-hardcore')
        page.wait_for_timeout(220)
        hc_off = page.evaluate("""() => ({
            on: document.getElementById('btn-hardcore').getAttribute('aria-checked'),
            timeLocked: !document.getElementById('time-locked').hidden,
            timeBtns: [...document.querySelectorAll('#time-opts button')].map((b) => b.dataset.time),
            saved: JSON.parse(localStorage.getItem('hanbang.settings.v1') || '{}').hardcore,
        })""")
        check(hc_off['on'] == 'false' and not hc_off['timeLocked'] and hc_off['timeBtns'] == ['10', '15', '20']
              and hc_off['saved'] is False,
              '하드코어 끄면 일반 모드 복귀', json.dumps(hc_off, ensure_ascii=False))

        summary['desktop_console_errors'] = console
        summary['desktop_page_errors'] = errors
        check(not console, '콘솔 에러 0', json.dumps(console, ensure_ascii=False)[:300])
        check(not errors, '페이지 에러 0', json.dumps(errors, ensure_ascii=False)[:300])
        ctx.close()

        # ── 모바일: 5단계 설정·대전 ─────────────────────────
        print('== mobile 390x844 ==')
        ctx, page, console, errors = new_page(browser, {'width': 390, 'height': 844})
        page.goto(url, wait_until='domcontentloaded')
        wait_ready(page)
        check(sum(overflow(page).values()) <= 0, '모바일 설정 가로 오버플로 0', str(overflow(page)))
        mobile_gone = page.evaluate("""() => ({
            btn: !!document.getElementById('btn-custom'),
            text: document.body.innerText.includes('내 단어장'),
            row: Math.round(document.getElementById('btn-sound').getBoundingClientRect().width),
            box: Math.round(document.querySelector('.setup-actions').getBoundingClientRect().width),
        })""")
        check(not mobile_gone['btn'] and not mobile_gone['text'], '모바일 내 단어장 삭제',
              json.dumps(mobile_gone, ensure_ascii=False))
        check(mobile_gone['row'] >= mobile_gone['box'] - 1, '모바일 효과음 설정 행 전체 폭',
              f"{mobile_gone['row']}/{mobile_gone['box']}px")
        page.click('.level[data-lv="5"]')
        page.wait_for_timeout(200)
        check(sum(overflow(page).values()) <= 0, '모바일 Lv.5 카드 가로 오버플로 0', str(overflow(page)))
        page.screenshot(path=os.path.join(OUT, 'mobile-lv5.png'))
        page.click('#btn-start')
        page.wait_for_selector('#scr-game:not([hidden])')
        page.wait_for_timeout(400)
        for _ in range(2):
            st = wait_my_turn(page, 9000)
            if not st or st['phase'] != 'me':
                break
            w = human_word(page)
            if not w:
                break
            page.fill('#word-input', w)
            page.click('#btn-submit')
            page.wait_for_timeout(1400)
        st = page.evaluate('window.__HB.state()')
        bot_moves = [c for c in st['chain'] if c['who'] == 'bot'] if st else []
        check(len(bot_moves) >= 1, '모바일 Lv.5 대전 진행', f"{len(bot_moves)}수")
        check(sum(overflow(page).values()) <= 0, '모바일 Lv.5 대전 가로 오버플로 0', str(overflow(page)))
        hits = brand_hits(page)
        check(not hits, '모바일 화면 옛 이름 0건', json.dumps(hits, ensure_ascii=False))
        page.screenshot(path=os.path.join(OUT, 'mobile-game.png'))
        summary['mobile_game'] = {'bot_moves': [(c['word'], c['kind']) for c in bot_moves], 'brand_hits': hits}

        # ── 모바일: 결과 화면 난이도 ────────────────────────
        page.evaluate('window.__HB.engine.quit()')
        page.wait_for_timeout(1000)
        mres = page.evaluate("""() => ({
            title: document.getElementById('result-title').textContent,
            label: document.getElementById('result-level-label').textContent,
            lv: document.getElementById('result-level').dataset.lv,
        })""")
        check(mres['label'] == 'Lv.5 지옥' and mres['lv'] == '5', '모바일 결과 화면 난이도',
              json.dumps(mres, ensure_ascii=False))
        check(sum(overflow(page).values()) <= 0, '모바일 결과 화면 가로 오버플로 0', str(overflow(page)))
        page.screenshot(path=os.path.join(OUT, 'mobile-result.png'))
        summary['mobile_result'] = mres

        # ── 모바일: 하드코어 설정·대전·결과 ──────────────────
        page.evaluate('window.__HB.app.hideResult(); window.__HB.app.show(\'setup\')')
        page.wait_for_timeout(200)
        if page.evaluate("document.getElementById('btn-hardcore').getAttribute('aria-checked')") == 'true':
            page.click('#btn-hardcore')
            page.wait_for_timeout(180)
        page.click('#btn-hardcore')
        page.wait_for_timeout(250)
        check(sum(overflow(page).values()) <= 0, '모바일 하드코어 설정 가로 오버플로 0', str(overflow(page)))
        page.screenshot(path=os.path.join(OUT, 'mobile-hardcore-setup.png'))
        page.click('#btn-start')
        page.wait_for_selector('#scr-game:not([hidden])')
        wait_my_turn(page, 7000)
        page.wait_for_timeout(520)
        m_hc = page.evaluate("""() => {
            const st = window.__HB.state();
            return {
                first: window.__HB.engine.first,
                limit: window.__HB.engine.timeLimit,
                chain: st.chain.map((c) => c.who),
                badge: !document.getElementById('game-hardcore').hidden,
                time: document.getElementById('time-left').textContent,
            };
        }""")
        check(m_hc['first'] == 'bot' and m_hc['limit'] == 5 and m_hc['badge'] and m_hc['chain'][:1] == ['bot'],
              '모바일 하드코어 5초·봇 선공·배지', json.dumps(m_hc, ensure_ascii=False))
        check(sum(overflow(page).values()) <= 0, '모바일 하드코어 대전 가로 오버플로 0', str(overflow(page)))
        page.screenshot(path=os.path.join(OUT, 'mobile-hardcore-game.png'))
        page.evaluate('window.__HB.engine.quit()')
        page.wait_for_timeout(1100)
        m_hc_res = page.evaluate("""() => ({
            title: document.getElementById('result-title').textContent,
            badge: !document.getElementById('result-hardcore').hidden,
            label: document.getElementById('result-level-label').textContent,
        })""")
        check(m_hc_res['title'] == '패배' and m_hc_res['badge'], '모바일 하드코어 결과 배지',
              json.dumps(m_hc_res, ensure_ascii=False))
        check(sum(overflow(page).values()) <= 0, '모바일 하드코어 결과 가로 오버플로 0', str(overflow(page)))
        page.screenshot(path=os.path.join(OUT, 'mobile-hardcore-result.png'))
        summary['mobile_hardcore'] = m_hc_res
        summary['mobile_console_errors'] = console
        summary['mobile_page_errors'] = errors
        check(not console, '모바일 콘솔 에러 0', json.dumps(console, ensure_ascii=False)[:300])
        check(not errors, '모바일 페이지 에러 0', json.dumps(errors, ensure_ascii=False)[:300])
        ctx.close()
        browser.close()

    if httpd:
        httpd.shutdown()

    print('\n=== 요약 ===')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if FAILS:
        print(f'실패 {len(FAILS)}건: {FAILS}')
        sys.exit(1)
    print('모든 점검 통과 · 스크린샷:', OUT)


if __name__ == '__main__':
    main()
