#!/usr/bin/env python3
"""🧪 잇다 실험실 · 다크모드 라이브 확인 (https://itda-play.pages.dev).

운영 주소에서 확인만 한다. 계정이 필요하면 화면에서 새 계정을 만들고(운영 Turnstile 확인을
기다린다 — 대신 풀지 않는다) 끝나면 그 계정을 지운다. 사람 확인이 자동으로 오지 않으면
계정 단계는 SKIP 으로 남기고 게스트 화면만 확인한다.

usage:
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/lab_live.py
"""
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

URL = 'https://itda-play.pages.dev'
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
SHOT_DIR = '/workspace/work/itda/downloads/itda/2026-11-25-lab'
PASSWORD = 'itda-Lab-live-25'
NAME = f'점검라이브{int(time.time()) % 100000}'

PASS = 0
FAIL = 0
SKIP = 0


def check(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ✓ {label}')
    else:
        FAIL += 1
        print(f'  ✗ {label}' + (f' — {detail}' if detail else ''))


def skip(label, why=''):
    global SKIP
    SKIP += 1
    print(f'  - SKIP {label}' + (f' — {why}' if why else ''))


def shot(page, name):
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f'{name}.png')
    page.screenshot(path=path)
    print(f'  shot  {path}')


def wait_turnstile(page, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        token = page.evaluate("""() => {
            const input = document.querySelector('#auth-turnstile input[name="cf-turnstile-response"]');
            return input ? input.value : '';
        }""")
        if token:
            return token
        page.wait_for_timeout(500)
    return ''


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, args=[
            '--no-sandbox', '--disable-dev-shm-usage', '--renderer-process-limit=1',
        ])
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(URL, wait_until='domcontentloaded')
        page.wait_for_function('() => window.__ITDA && window.__ITDA.ready === true', timeout=60000)
        page.wait_for_timeout(400)

        print('\n[1] 라이브 · 게스트 화면')
        check(bool(page.query_selector('#btn-lab')), '홈에 🧪 실험실 버튼')
        check(not page.query_selector('#btn-mono'), '흑백모드 토글은 없다')
        band = page.eval_on_selector_all('.top-actions .top-btn', 'els => els.map(e => e.id)')
        check(band[:5] == ['btn-settings', 'btn-dict', 'btn-lab', 'btn-mail', 'btn-account'],
              '상단 버튼 순서: 설정 · 사전 · 실험실 · 메일 · 계정', json.dumps(band))
        page.click('#btn-lab')
        page.wait_for_timeout(400)
        check(not page.is_hidden('#scr-lab'), '실험실 화면이 열린다')
        check(not page.is_hidden('#lab-gate'), '게스트에게 로그인 안내')
        check('전적' in page.inner_text('.lab-notice'), '실험실 전적·랭킹 제외 안내')
        shot(page, 'live-lab-gate-390')
        page.click('#lab-back')
        page.wait_for_timeout(300)

        print('\n[2] 라이브 · 다크모드')
        page.click('#btn-settings')
        page.wait_for_timeout(250)
        page.click('#btn-dark')
        page.wait_for_timeout(300)
        check(page.evaluate("() => document.documentElement.classList.contains('dark')"), '다크모드 켜짐')
        theme = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
        check(theme != 'rgb(239, 236, 228)', '배경이 밝은 린넨이 아니다', theme)
        check(page.evaluate("() => document.querySelector('meta[name=theme-color]').content") == '#191713',
              'theme-color 어두운 색')
        shot(page, 'live-settings-dark-390')
        page.click('#btn-settings-close')
        page.wait_for_timeout(300)
        shot(page, 'live-home-dark-390')
        page.click('#btn-lab')
        page.wait_for_timeout(400)
        shot(page, 'live-lab-gate-dark-390')
        page.click('#lab-back')
        page.wait_for_timeout(300)

        print('\n[3] 라이브 · 계정 · 방 만들기')
        page.click('#btn-account')
        page.wait_for_selector('#ov-auth:not([hidden])', timeout=8000)
        page.click('#auth-tabs [data-mode="signup"]')
        page.fill('#auth-username', NAME)
        page.fill('#auth-password', PASSWORD)
        page.fill('#auth-password2', PASSWORD)
        token = wait_turnstile(page)
        if not token:
            skip('계정 만들기', '운영 Turnstile 사람 확인이 자동으로 오지 않음')
            browser.close()
            print(f'\n결과: {PASS} 통과 · {FAIL} 실패 · {SKIP} 건너뜀')
            return 1 if FAIL else 0
        page.click('#auth-submit')
        page.wait_for_function("() => document.getElementById('ov-auth').hidden === true", timeout=30000)
        check(page.evaluate("() => window.__ITDA.app.accountPanel.user?.username") == NAME, '라이브 가입·로그인')

        page.click('#btn-lab')
        page.wait_for_timeout(400)
        page.click('#lab-create')
        page.wait_for_timeout(1800)
        room = page.evaluate("() => window.__ITDA.app.labPanel.room")
        check(bool(room and len(room['code']) == 6), '라이브 방 만들기(6자리)', json.dumps(room and room['code']))
        check(room and len(room['seats']) == 2, '기본 2자리(나 + 봇)')
        shot(page, 'live-lab-room-dark-390')

        page.click('.lab-seat-add button')
        page.wait_for_timeout(900)
        room = page.evaluate("() => window.__ITDA.app.labPanel.room")
        check(room and len(room['seats']) == 3, '자리 추가', str(room and len(room['seats'])))

        page.fill('#lab-rule-time', '30')
        page.select_option('#lab-rule-lives', '2')
        page.click('#lab-rule-save')
        page.wait_for_timeout(1200)
        room = page.evaluate("() => window.__ITDA.app.labPanel.room")
        check(room and room['rules']['timeLimit'] == 30 and room['rules']['lives'] == 2, '룰 저장(30초·목숨 2)',
              json.dumps(room and room['rules'], ensure_ascii=False))

        page.click('#lab-start')
        page.wait_for_timeout(2000)
        room = page.evaluate("() => window.__ITDA.app.labPanel.room")
        check(room and room['status'] == 'playing', '라이브 게임 시작', str(room and room['status']))
        word = page.evaluate("""() => {
            const need = window.__ITDA.app.labPanel.room.state.needChar;
            return window.__ITDA.dict.candidatesFor(need, new Set()).filter((w) => w.length >= 2 && w.length <= 8)[0];
        }""")
        if word:
            page.fill('#lab-word', word)
            page.click('#lab-submit')
            page.wait_for_timeout(1600)
            room = page.evaluate("() => window.__ITDA.app.labPanel.room")
            check(room['state']['chain'] and room['state']['chain'][-1]['word'] == word, '단어 제출·기록', str(word))
        shot(page, 'live-lab-play-dark-390')

        page.fill('#lab-god-time', '20')
        page.click('#lab-god-time-btn')
        page.wait_for_timeout(1500)
        room = page.evaluate("() => window.__ITDA.app.labPanel.room")
        check(room['rules']['timeLimit'] == 20, '신 모드: 제한 시간 20초', str(room['rules']['timeLimit']))
        page.fill('#lab-god-seal', '가')
        page.click('#lab-god-seal-btn')
        page.wait_for_timeout(1500)
        room = page.evaluate("() => window.__ITDA.app.labPanel.room")
        check('가' in (room['rules']['bannedChars'] or ''), '신 모드: 글자 봉인', str(room['rules']['bannedChars']))
        shot(page, 'live-lab-god-dark-390')

        code = room['code']
        page.click('#lab-leave')
        page.wait_for_timeout(1500)
        check(page.evaluate("() => window.__ITDA.app.labPanel.room") is None, '방 닫기')

        print('\n[4] 라이브 · 계정 정리')
        page.click('#btn-account')
        page.wait_for_selector('#ov-account:not([hidden])', timeout=8000)
        page.click('#btn-delete-account')
        page.wait_for_timeout(500)
        page.fill('#account-delete-confirm', PASSWORD)
        page.click('#btn-delete-confirm')
        page.wait_for_function("() => document.getElementById('ov-account').hidden === true", timeout=30000)
        check(page.evaluate("() => window.__ITDA.app.accountPanel.user") is None, '점검 계정 삭제')

        real = [e for e in errors if 'Failed to load resource' not in e]
        check(not real, '라이브 콘솔 오류 없음', json.dumps(real[:3], ensure_ascii=False))
        browser.close()

    print(f'\n결과: {PASS} 통과 · {FAIL} 실패 · {SKIP} 건너뜀')
    print('방 코드(지워졌는지 확인용):', code)
    print('스크린샷:', SHOT_DIR)
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
