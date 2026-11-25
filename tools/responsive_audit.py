#!/usr/bin/env python3
"""전 화면 크기 반응형 점검.

여러 뷰포트(초소형 폰 · 일반 폰 · 큰 폰 · 폴더블 · 태블릿 세로/가로 ·
PC 반창 · 낮은 창 · 정사각 · 대형 모니터)에서 화면별로
 - 가로 오버플로 · 화면 밖으로 나간 요소
 - 잘림(스크롤 없이 닿지 않는 요소) · 의도치 않은 겹침
 - 콘솔/페이지 에러
를 재고 스크린샷을 남긴다.

usage:
    python3 tools/responsive_audit.py                   # 전체
    python3 tools/responsive_audit.py --only 320x568,768x1024
    python3 tools/responsive_audit.py --shots /workspace/downloads/itda/2026-11-24-responsive
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
OUT = os.environ.get('ITDA_AUDIT_DIR', '/workspace/downloads/itda/2026-11-24-responsive')

# (이름, 너비, 높이, 모바일 플래그) — 실제 기기 · 창 크기 조합
VIEWPORTS = [
    ('320x568', 320, 568, True),    # 초소형 폰(iPhone SE 1세대)
    ('344x882', 344, 882, True),    # 폴더블 접힘(Galaxy Z Fold 바깥)
    ('360x640', 360, 640, True),    # 작은 안드로이드
    ('375x667', 375, 667, True),    # iPhone 8
    ('390x844', 390, 844, True),    # 일반 모바일
    ('390x480', 390, 480, True),    # 모바일 키보드가 올라온 높이
    ('430x932', 430, 932, True),    # 큰 폰(iPhone Pro Max)
    ('480x800', 480, 800, True),    # 큰 폰/작은 태블릿
    ('540x960', 540, 960, True),    # 큰 폰/작은 태블릿
    ('600x960', 600, 960, True),    # 태블릿 최소 폭(구간 경계 안쪽)
    ('673x841', 673, 841, True),    # 폴더블 펼침(Galaxy Z Fold 안쪽)
    ('744x1133', 744, 1133, True),  # 태블릿 세로(iPad mini)
    ('768x1024', 768, 1024, True),  # 태블릿 세로(iPad)
    ('820x1180', 820, 1180, True),  # 태블릿 세로(iPad Air)
    ('1024x768', 1024, 768, False), # 태블릿 가로 / 작은 노트북
    ('1180x820', 1180, 820, False), # 태블릿 가로 큰 것
    ('1280x800', 1280, 800, False), # 일반 데스크톱
    ('1366x768', 1366, 768, False), # 노트북
    ('1280x420', 1280, 420, False), # 낮은 반창(가로 모드 노트북)
    ('844x390', 844, 390, True),    # 폰 가로
    ('915x412', 915, 412, True),    # 큰 폰 가로
    ('720x720', 720, 720, False),   # 정사각 창
    ('480x480', 480, 480, True),    # 작은 정사각 창
    ('673x450', 673, 450, True),    # 폴더블 펼침 + 키보드 높이
    ('1024x500', 1024, 500, False), # 낮은 태블릿 가로
    ('1280x600', 1280, 600, False), # 낮은 노트북 창
    ('1600x900', 1600, 900, False), # 큰 노트북
    ('1920x1080', 1920, 1080, False), # FHD
    ('2560x1440', 2560, 1440, False), # QHD
]

PROBE = r"""
() => {
  const vw = document.documentElement.clientWidth;
  const vh = innerHeight;
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) === 0) return false;
    return true;
  };
  const box = (sel) => {
    const el = document.querySelector(sel);
    if (!el || !vis(el)) return null;
    const r = el.getBoundingClientRect();
    return {l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right),
            b: Math.round(r.bottom), w: Math.round(r.width), h: Math.round(r.height)};
  };
  const out = [];
  const walk = (el) => {
    for (const c of el.children) {
      const cs = getComputedStyle(c);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      const r = c.getBoundingClientRect();
      if (c.classList.contains('confetti')) continue;   // 연출용 조각은 화면 밖으로 떨어진다
      if (r.width > 0 && r.height > 0) {
        // 조상이 가로로 잘라 주는 상자 안에 있으면 화면 밖 판정에서 뺀다
        let clipped = false;
        for (let p = c.parentElement; p && p !== document.body; p = p.parentElement) {
          const px = getComputedStyle(p).overflowX;
          if (px !== 'visible') { clipped = true; break; }
        }
        if (!clipped && (r.right > vw + 1 || r.left < -1)) {
          out.push({tag: c.tagName.toLowerCase(), cls: (c.className || '').toString().slice(0, 60),
                    l: Math.round(r.left), r: Math.round(r.right)});
        }
      }
      walk(c);
    }
  };
  walk(document.body);
  const scroll = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    return {sh: el.scrollHeight, ch: el.clientHeight, sw: el.scrollWidth, cw: el.clientWidth};
  };
  return {
    vw, vh,
    doc: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
    docH: document.documentElement.scrollHeight,
    outside: out.slice(0, 8),
    scroll: {
      setup: scroll('#scr-setup'), game: scroll('#scr-game'), dict: scroll('#scr-dict'),
      dictBody: scroll('.dict-body'), sheet: scroll('#ov-result .sheet'),
      settings: scroll('#ov-settings .sheet'), chain: scroll('.chain'), arena: scroll('.arena'),
    },
    box: {
      setup: box('.setup'), topActions: box('.top-actions'), brand: box('.brand'),
      logo: box('.brand .logo-mark'), levels: box('.levels'), start: box('#btn-start'),
      gameTop: box('.game-top'), gameRow: box('.game-top-row'), botInfo: box('.bot-info'),
      score: box('.scoreboard'), quit: box('#btn-quit'), arena: box('.arena'),
      chain: box('.chain'), stage: box('.stage'), stageWord: box('.stage-word'),
      stageH2: box('.stage-word h2'), bubble: box('.bot-bubble'),
      panel: box('.turn-panel'), need: box('.need-char b'), countdown: box('#countdown'),
      timer: box('.timer'), input: box('#word-input'), submit: box('#btn-submit'),
      dictTop: box('.dict-top'), dictSearch: box('.dict-search'), dictSorts: box('.dict-sorts'),
      dictBody: box('.dict-body'), dictItem: box('.dict-item'), dictMore: box('.dict-more'),
      sheet: box('#ov-result .sheet'), resultTitle: box('#result-title'),
      resultStats: box('.result-stats'), logBtn: box('#battle-log-btn'),
      log: box('#battle-log'), actions: box('.result-actions'),
      settingsSheet: box('#ov-settings .sheet'), settingsBlock: box('.settings-block'),
      dark: box('.dark-card'), settingsClose: box('#btn-settings-close'),
    },
  };
}
"""


def serve(root):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
    httpd = socketserver.ThreadingTCPServer(('127.0.0.1', 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def inside(b, vw, vh, margin=1):
    if not b:
        return True
    return b['l'] >= -margin and b['r'] <= vw + margin and b['t'] >= -margin and b['b'] <= vh + margin


def overlap(a, b, tol=1):
    if not a or not b:
        return False
    return (a['l'] < b['r'] - tol and b['l'] < a['r'] - tol
            and a['t'] < b['b'] - tol and b['t'] < a['b'] - tol)


def probe(page):
    return page.evaluate(PROBE)


def issues_for(vp_name, st):
    """한 화면 상태에서 실제로 문제인 것만 골라 낸다."""
    vw, vh = st['vw'], st['vh']
    bad = []
    if st['doc'] > 0 or st['body'] > 0:
        bad.append(f"가로 오버플로 doc={st['doc']} body={st['body']}")
    if st['outside']:
        bad.append('화면 밖 요소 ' + json.dumps(st['outside'], ensure_ascii=False)[:300])
    return bad


def setup_checks(st):
    vw, vh, b = st['vw'], st['vh'], st['box']
    bad = issues_for('setup', st)
    for key in ('setup', 'topActions', 'brand', 'levels', 'start'):
        if b[key] and not inside(b[key], vw, vh):
            bad.append(f"{key} 화면 밖 {b[key]}")
    if st['scroll']['setup'] and st['scroll']['setup']['sh'] > st['scroll']['setup']['ch'] + 1:
        bad.append(f"세로 스크롤 {st['scroll']['setup']['sh']} > {st['scroll']['setup']['ch']}")
    if overlap(b['topActions'], b['logo']):
        bad.append('상단 버튼이 로고와 겹침')
    if b['levels'] and b['levels']['w'] < 200:
        bad.append(f"난이도 줄이 너무 좁음 {b['levels']['w']}")
    return bad


def game_checks(st, long_word=False):
    vw, vh, b = st['vw'], st['vh'], st['box']
    bad = issues_for('game', st)
    for key in ('gameTop', 'panel', 'need', 'countdown', 'timer', 'input', 'submit'):
        if b[key] and not inside(b[key], vw, vh):
            bad.append(f"{key} 화면 밖 {b[key]}")
    if b['arena'] and b['arena']['h'] < 40:
        bad.append(f"아레나 높이 부족 {b['arena']['h']}")
    if overlap(b['stage'], b['panel']):
        bad.append('단어 타일이 입력 독과 겹침')
    if overlap(b['stageWord'], b['panel']):
        bad.append('단어 타일 상자가 입력 독과 겹침')
    if b['stageH2'] and b['stage']:
        if b['stageH2']['b'] > b['stage']['b'] + 2 or b['stageH2']['t'] < b['stage']['t'] - 2:
            bad.append(f"단어 글자가 타일 밖 {b['stageH2']} vs {b['stage']}")
    if overlap(b['botInfo'], b['score']):
        bad.append('봇 정보와 점수 겹침')
    if overlap(b['score'], b['quit']):
        bad.append('점수와 나가기 버튼 겹침')
    if b['chain'] and b['arena'] and b['chain']['b'] > b['arena']['b'] + 2:
        bad.append(f"지난 단어가 아레나 밖 {b['chain']}")
    if long_word and b['stageH2'] and b['stageWord']:
        if b['stageH2']['h'] > b['stageWord']['h'] - 8:
            bad.append('긴 단어가 타일 안에서 잘림')
    return bad


def dict_checks(st):
    vw, vh, b = st['vw'], st['vh'], st['box']
    bad = issues_for('dict', st)
    for key in ('dictTop', 'dictSearch', 'dictSorts', 'dictBody'):
        if b[key] and not inside(b[key], vw, vh):
            bad.append(f"{key} 화면 밖 {b[key]}")
    if st['scroll']['dictBody'] and st['scroll']['dictBody']['ch'] < 80:
        bad.append(f"사전 본문 높이 부족 {st['scroll']['dictBody']['ch']}")
    if b['dictItem'] and not inside(b['dictItem'], vw, vh):
        bad.append(f"단어 카드 화면 밖 {b['dictItem']}")
    return bad


def sheet_checks(st, name='result'):
    vw, vh, b = st['vw'], st['vh'], st['box']
    bad = issues_for(name, st)
    key = 'sheet' if name == 'result' else 'settingsSheet'
    if b[key] and not inside(b[key], vw, vh):
        bad.append(f"{key} 화면 밖 {b[key]}")
    if st['scroll']['sheet'] and st['scroll']['sheet']['sh'] > st['scroll']['sheet']['ch'] + 1:
        bad.append(f"카드 세로 스크롤 {st['scroll']['sheet']['sh']} > {st['scroll']['sheet']['ch']}")
    if name == 'result':
        for k in ('resultTitle', 'resultStats', 'logBtn', 'actions'):
            if b[k] and not inside(b[k], vw, vh):
                bad.append(f"{k} 화면 안에 없음 {b[k]}")
        if overlap(b['actions'], b['logBtn']):
            bad.append('결과 버튼과 배틀 내역 버튼 겹침')
    else:
        for k in ('settingsBlock', 'dark', 'settingsClose'):
            if b[k] and not inside(b[k], vw, vh):
                bad.append(f"{k} 화면 안에 없음 {b[k]}")
    return bad


def wait_ready(page, timeout=120000):
    page.wait_for_function('window.__ITDA && window.__ITDA.ready === true', timeout=timeout)
    page.wait_for_selector('#scr-setup:not([hidden])', timeout=timeout)


def run_one(browser, vp_name, w, h, mobile, shots_dir):
    ctx = browser.new_context(
        viewport={'width': w, 'height': h},
        device_scale_factor=1,
        is_mobile=mobile,
        has_touch=mobile,
        locale='ko-KR',
    )
    page = ctx.new_page()
    console, errors = [], []
    page.on('console', lambda m: console.append({'type': m.type, 'text': m.text[:300]})
            if m.type in ('error', 'warning') else None)
    page.on('pageerror', lambda e: errors.append(str(e)[:400]))

    page.goto(BASE, wait_until='domcontentloaded')
    wait_ready(page)
    page.wait_for_timeout(220)
    result = {'viewport': vp_name, 'w': w, 'h': h, 'mobile': mobile, 'screens': {}}

    def shoot(tag):
        os.makedirs(shots_dir, exist_ok=True)
        page.screenshot(path=os.path.join(shots_dir, f'{vp_name}-{tag}.png'))

    # ── 설정 ──
    st = probe(page)
    result['screens']['setup'] = {'issues': setup_checks(st), 'state': st}
    shoot('setup')

    # ── 설정 모달 ──
    page.evaluate("window.__ITDA.app.openSettings()")
    page.wait_for_timeout(220)
    st = probe(page)
    result['screens']['settings'] = {'issues': sheet_checks(st, 'settings'), 'state': st}
    shoot('settings')
    page.evaluate("window.__ITDA.app.closeSettings(true)")
    page.wait_for_timeout(120)

    # ── 사전 ──
    page.evaluate("window.__ITDA.app.openDict()")
    page.fill('#dict-input', '가')
    page.wait_for_timeout(420)
    st = probe(page)
    result['screens']['dict'] = {'issues': dict_checks(st), 'state': st}
    shoot('dict')
    # 카드 열 수(데스크톱에서 2열 이상인지)
    cols = page.evaluate("""() => {
        const items = [...document.querySelectorAll('.dict-item')].slice(0, 12);
        const tops = [...new Set(items.map((e) => Math.round(e.getBoundingClientRect().top)))];
        const first = tops[0];
        return items.filter((e) => Math.round(e.getBoundingClientRect().top) === first).length;
    }""")
    result['screens']['dict']['columns'] = cols
    page.evaluate("window.__ITDA.app.show('setup')")
    page.wait_for_timeout(150)

    # ── 대전(첫 턴 · 중반 · 긴 단어) ──
    page.evaluate("window.__ITDA.startGame({level:3, first:'me', timeLimit:20})")
    page.wait_for_timeout(650)
    st = probe(page)
    result['screens']['game'] = {'issues': game_checks(st), 'state': st}
    shoot('game')

    page.evaluate("""() => {
        const ui = window.__ITDA.app;
        const words = ['가람', '마루', '우주', '주전자', '자전거', '거울', '울타리'];
        words.forEach((word, i) => {
            ui.renderStage({who: i % 2 ? 'bot' : 'me', word, score: 30 + i * 7}, null, null);
            ui.addChain({who: i % 2 ? 'bot' : 'me', word, score: 30 + i * 7});
        });
        ui.say('좋아, 이어 볼까?');
    }""")
    page.wait_for_timeout(420)
    st = probe(page)
    result['screens']['game-mid'] = {'issues': game_checks(st), 'state': st}
    shoot('game-mid')

    page.evaluate("""() => {
        const ui = window.__ITDA.app;
        ui.renderStage({who: 'bot', word: '너바나더밴드위드어걸인더리턴오브더스레드17년전으로돌', score: 999}, null, null);
    }""")
    page.wait_for_timeout(420)
    st = probe(page)
    result['screens']['game-long'] = {'issues': game_checks(st, long_word=True), 'state': st}
    shoot('game-long')

    # ── 결과 시트 (+ 배틀 내역) ──
    page.evaluate("""() => {
        const chain = [];
        const ws = ['가람', '마루', '우주', '주전자', '자전거', '거울', '울타리', '리어카',
                    '카메라', '라면', '면도기', '기차역', '역광', '광합성', '성수동'];
        ws.forEach((w, i) => chain.push({who: i % 2 ? 'bot' : 'me', word: w, score: 20 + i * 13, kind: i === 5 ? 'outer' : ''}));
        window.__ITDA.app.showResult({
            win: true, mercy: false, turns: 15, bestCombo: 3, words: 8,
            scoreMe: 1280, scoreBot: 940, chain,
            state: {level: 3},
        }, '봇이 이어갈 단어를 찾지 못했어요.');
    }""")
    page.wait_for_timeout(450)
    st = probe(page)
    result['screens']['result'] = {'issues': sheet_checks(st, 'result'), 'state': st}
    shoot('result')

    page.click('#battle-log-btn')
    page.wait_for_timeout(380)
    st = probe(page)
    result['screens']['result-log'] = {'issues': sheet_checks(st, 'result'), 'state': st}
    shoot('result-log')

    result['console'] = console
    result['errors'] = errors
    if console:
        result['screens'].setdefault('console', {'issues': []})['issues'].append(
            '콘솔 경고/에러 ' + json.dumps(console, ensure_ascii=False)[:300])
    if errors:
        result['screens'].setdefault('pageerror', {'issues': []})['issues'].append(
            '페이지 에러 ' + json.dumps(errors, ensure_ascii=False)[:300])
    ctx.close()
    return result


BASE = None


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default=None, help='쉼표로 구분한 뷰포트 이름')
    ap.add_argument('--url', default=None, help='라이브 URL(없으면 로컬 파일 서버)')
    ap.add_argument('--shots', default=OUT)
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    vps = VIEWPORTS
    if args.only:
        want = {s.strip() for s in args.only.split(',')}
        vps = [v for v in VIEWPORTS if v[0] in want]
        if not vps:
            print('해당 뷰포트 없음:', want)
            return 1

    httpd = None
    if args.url:
        BASE = args.url
    else:
        httpd, port = serve(ROOT)
        BASE = f'http://127.0.0.1:{port}/index.html'
    report = []
    fails = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox', '--disable-dev-shm-usage'])
        for name, w, h, mobile in vps:
            t0 = time.time()
            r = run_one(browser, name, w, h, mobile, args.shots)
            report.append(r)
            issues = {k: v['issues'] for k, v in r['screens'].items() if v.get('issues')}
            mark = 'OK  ' if not issues else 'FAIL'
            print(f'{mark} {name:>10}  {time.time() - t0:5.1f}s')
            for screen, items in issues.items():
                fails += 1
                for it in items:
                    print(f'       · [{screen}] {it}')
        browser.close()
    if httpd:
        httpd.shutdown()

    os.makedirs(args.shots, exist_ok=True)
    out_json = args.json or os.path.join(args.shots, 'audit.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f'\n스크린샷/리포트: {args.shots}')
    print(f'문제 화면 {fails}건')
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
