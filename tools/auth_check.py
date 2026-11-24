#!/usr/bin/env python3
"""계정(로그인·회원가입·Turnstile) 화면 점검.

로컬 wrangler pages dev(테스트 Turnstile 키)나 라이브 주소에 붙여서
우측 상단 계정 버튼 → 회원가입 → 내 계정 → 로그아웃 → 로그인 흐름을 확인한다.

usage:
    python3 tools/auth_check.py --local
    python3 tools/auth_check.py --url https://itda-play.pages.dev --shots-dir downloads/itda/2026-11-24-auth
"""
import argparse
import json
import os
import shutil
import random
import string
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRANGLER = '/workspace/tools-npm/node_modules/.bin/wrangler'
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')

PASS = 0
FAIL = 0


def check(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ✓ {label}')
    else:
        FAIL += 1
        print(f'  ✗ {label}' + (f' — {detail}' if detail else ''))


def ensure_local_config():
    """Pages dev 는 표준 이름(wrangler.toml)만 읽는다. 저장소에 커밋하지 않는
    wrangler.local.toml 을 임시로 복사해 두고, 실행이 끝나면 지운다."""
    src = os.path.join(ROOT, 'wrangler.local.toml')
    dst = os.path.join(ROOT, 'wrangler.toml')
    if os.path.exists(dst):
        return False
    if os.path.exists(src):
        shutil.copy(src, dst)
        return True
    raise RuntimeError('wrangler.local.toml 이 없어 로컬 바인딩을 만들 수 없습니다')


def start_local():
    env = dict(os.environ)
    env['PATH'] = '/workspace/.local/node/bin:' + env.get('PATH', '')
    env['WRANGLER_SEND_METRICS'] = 'false'
    proc = subprocess.Popen(
        [WRANGLER, 'pages', 'dev', '.', '--port', '8788', '--ip', '127.0.0.1'],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    import urllib.request
    for _ in range(60):
        try:
            urllib.request.urlopen('http://127.0.0.1:8788/api/auth/config', timeout=2)
            return proc
        except Exception:
            time.sleep(1)
    raise RuntimeError('로컬 서버가 뜨지 않았습니다')


def api(page, path, method='GET', body=None):
    payload = json.dumps(body) if body is not None else 'null'
    return page.evaluate(
        """async ([path, method, payload]) => {
            const res = await fetch(path, {
              method,
              credentials: 'same-origin',
              headers: payload === 'null' ? {accept: 'application/json'} : {'content-type': 'application/json'},
              body: payload === 'null' ? undefined : payload,
            });
            let data = null;
            try { data = await res.json(); } catch (e) { data = null; }
            return {status: res.status, data};
        }""",
        [path, method, payload],
    )


def wait_ready(page):
    page.wait_for_function('() => window.__ITDA && window.__ITDA.ready === true', timeout=60000)
    page.wait_for_timeout(400)


def run(url, shot_dir, headless=True, slow=1.0):
    os.makedirs(shot_dir, exist_ok=True)
    username = '점검' + ''.join(random.choice(string.digits) for _ in range(5))
    password = 'itda-Test-24'
    shots = {}

    def shot(page, name, cls=None):
        path = os.path.join(shot_dir, f'{name}.png')
        if cls:
            page.locator(cls).screenshot(path=path)
        else:
            page.screenshot(path=path, full_page=False)
        shots[name] = path

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=headless,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, locale='ko-KR')
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(f'console.{m.type}: {m.text}') if m.type == 'error' else None)

        page.goto(url, wait_until='domcontentloaded')
        wait_ready(page)

        print('· 우측 상단 계정 버튼')
        account_btn = page.locator('#btn-account')
        check(account_btn.count() == 1, '계정 버튼이 DOM 에 있음')
        check(account_btn.is_visible(), '계정 버튼이 보임(계정 API 있음)')
        label = page.get_attribute('#btn-account', 'aria-label') or ''
        check('로그인' in label, '비로그인 상태 계정 버튼 이름이 로그인', label)
        check(page.inner_text('#btn-account').strip() == '', '계정 버튼은 아이콘만(글자 없음)', page.inner_text('#btn-account'))
        page.wait_for_timeout(300)
        shot(page, 'local-desktop-home-account' if url.startswith('http://127.') else 'live-desktop-home-account')
        shot(page, 'top-actions', cls='.top-actions')

        print('· 계정 창 열기')
        account_btn.click()
        page.wait_for_selector('#ov-auth:not([hidden])', timeout=5000)
        check(page.is_visible('#ov-auth'), '로그인·회원가입 창이 열림')
        page.wait_for_timeout(1200)
        turnstile_field = page.locator('#auth-turnstile input[name="cf-turnstile-response"]').count()
        check(turnstile_field >= 1, 'Turnstile 위젯이 그려짐', str(turnstile_field))
        shot(page, 'modal-login')

        print('· 회원가입 탭')
        page.click('#auth-tabs [data-mode="signup"]')
        page.wait_for_timeout(300)
        check(page.is_visible('#auth-password2'), '회원가입 탭에서 비밀번호 확인 칸이 보임')
        check(page.inner_text('#auth-submit-label') == '회원가입', '버튼 문구가 회원가입')
        page.fill('#auth-username', username)
        page.fill('#auth-password', password)
        page.fill('#auth-password2', password)
        page.wait_for_timeout(600)
        shot(page, 'modal-signup')

        print('· 가입 요청')
        page.click('#auth-submit')
        try:
            page.wait_for_function(
                "() => document.getElementById('ov-auth').hidden === true", timeout=25000)
            signed_in = True
        except Exception:
            signed_in = False
        err_text = page.inner_text('#auth-error') if page.is_visible('#auth-error') else ''
        check(signed_in, '가입 후 창이 닫힘', err_text)
        label = page.get_attribute('#btn-account', 'aria-label') or ''
        check(username in label, '가입 뒤 계정 버튼 이름에 아이디', label)
        me = api(page, '/api/auth/me')
        check(me['data'] and me['data'].get('user') and me['data']['user']['username'] == username,
              '/api/auth/me 가 가입한 사용자를 반환', json.dumps(me, ensure_ascii=False))
        page.wait_for_timeout(500)
        shot(page, 'home-signed-in')

        print('· 내 계정 창')
        page.click('#btn-account')
        page.wait_for_selector('#ov-account:not([hidden])', timeout=5000)
        check(page.inner_text('#account-handle') == f'@{username}', '아이디 표시', page.inner_text('#account-handle'))
        check('아이디' in page.inner_text('#account-provider'), '가입 방식 표시', page.inner_text('#account-provider'))
        shot(page, 'modal-account')

        print('· 로그아웃')
        page.click('#btn-logout')
        page.wait_for_timeout(1200)
        label = page.get_attribute('#btn-account', 'aria-label') or ''
        check('로그인' in label and '내 계정' not in label, '로그아웃 뒤 버튼이 로그인 상태', label)
        me = api(page, '/api/auth/me')
        check(me['data'] and me['data'].get('user') is None, '로그아웃 뒤 세션이 사라짐', json.dumps(me, ensure_ascii=False))

        print('· 다시 로그인')
        page.click('#btn-account')
        page.wait_for_selector('#ov-auth:not([hidden])', timeout=5000)
        page.wait_for_timeout(1500)
        page.fill('#auth-username', username)
        page.fill('#auth-password', password)
        page.wait_for_timeout(600)
        page.click('#auth-submit')
        try:
            page.wait_for_function("() => document.getElementById('ov-auth').hidden === true", timeout=25000)
            again = True
        except Exception:
            again = False
        check(again, '아이디·비밀번호로 다시 로그인됨',
              page.inner_text('#auth-error') if page.is_visible('#auth-error') else '')

        print('· 틀린 비밀번호')
        page.click('#btn-account')
        page.wait_for_selector('#ov-account:not([hidden])', timeout=5000)
        page.click('#btn-logout')
        page.wait_for_timeout(1200)
        page.click('#btn-account')
        page.wait_for_selector('#ov-auth:not([hidden])', timeout=5000)
        page.wait_for_timeout(1500)
        page.fill('#auth-username', username)
        page.fill('#auth-password', 'wrong-password')
        page.click('#auth-submit')
        page.wait_for_timeout(2500)
        wrong_msg = page.inner_text('#auth-error') if page.is_visible('#auth-error') else ''
        check('맞지 않' in wrong_msg, '틀린 비밀번호는 거부', wrong_msg)
        shot(page, 'modal-wrong-password')
        page.click('#btn-auth-close')
        page.wait_for_timeout(400)

        print('· 모바일')
        mobile = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2,
                                     is_mobile=True, has_touch=True, locale='ko-KR')
        m = mobile.new_page()
        m.goto(url, wait_until='domcontentloaded')
        wait_ready(m)
        m.wait_for_timeout(500)
        shot(m, 'live-mobile-home-account')
        shot(m, 'mobile-top-actions', cls='.top-actions')
        m.click('#btn-account')
        m.wait_for_selector('#ov-auth:not([hidden])', timeout=5000)
        m.wait_for_timeout(1500)
        overflow = m.evaluate("() => ({scroll: document.documentElement.scrollWidth, win: window.innerWidth})")
        check(overflow['scroll'] <= overflow['win'] + 1, '모바일에서 가로 스크롤 없음', json.dumps(overflow))
        shot(m, 'live-mobile-modal-login')

        if errors:
            # 401·429 같은 의도한 응답은 브라우저가 콘솔 오류로 남긴다 — 실제 스크립트 오류만 센다.
            real = [e for e in errors if 'Failed to load resource' not in e]
            check(not real, '콘솔 오류 없음', ' / '.join(real[:3]))
        else:
            check(True, '콘솔 오류 없음')

        browser.close()

    print(f'\n결과: {PASS} 통과 · {FAIL} 실패')
    print('스크린샷:', json.dumps(shots, ensure_ascii=False, indent=1))
    return 0 if FAIL == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', action='store_true')
    ap.add_argument('--url')
    ap.add_argument('--shots-dir', default=os.path.join(ROOT, 'downloads', 'auth-check'))
    ap.add_argument('--headed', action='store_true')
    args = ap.parse_args()

    proc = None
    made_config = False
    url = args.url
    if args.local or not url:
        made_config = ensure_local_config()
        proc = start_local()
        url = 'http://127.0.0.1:8788'
    try:
        code = run(url.rstrip('/'), args.shots_dir, headless=not args.headed)
    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=10)
        if made_config:
            try:
                os.remove(os.path.join(ROOT, 'wrangler.toml'))
            except OSError:
                pass
    sys.exit(code)


if __name__ == '__main__':
    main()
