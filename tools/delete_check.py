#!/usr/bin/env python3
"""계정 삭제(2단계 확인) 흐름 점검.

로컬 wrangler pages dev(테스트 Turnstile 키)나 라이브 주소에 붙여서
회원가입 → 내 계정 → 계정 삭제 → 틀린 비밀번호 거부 → 정상 삭제 → 삭제된 계정으로 재로그인 불가
까지 확인한다. 로컬에서는 users 행에 직접 구글 전용 계정을 넣어 확인 문구 경로도 점검한다.

usage:
    python3 tools/delete_check.py --local
    python3 tools/delete_check.py --url https://itda-play.pages.dev --shots-dir downloads/itda/2026-11-24-delete
"""
import argparse
import base64
import hashlib
import json
import os
import random
import shutil
import string
import subprocess
import sys
import time
import urllib.request

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
    """Pages dev 는 표준 이름(wrangler.toml)만 읽는다. 커밋하지 않는 wrangler.local.toml 을 임시로 복사한다."""
    src = os.path.join(ROOT, 'wrangler.local.toml')
    dst = os.path.join(ROOT, 'wrangler.toml')
    if os.path.exists(dst):
        return False
    if os.path.exists(src):
        shutil.copy(src, dst)
        return True
    raise RuntimeError('wrangler.local.toml 이 없어 로컬 바인딩을 만들 수 없습니다')


def wrangler_env():
    env = dict(os.environ)
    env['PATH'] = '/workspace/.local/node/bin:' + env.get('PATH', '')
    env['WRANGLER_SEND_METRICS'] = 'false'
    return env


def d1(sql):
    """로컬 D1(itda-db)에 SQL 한 줄을 실행하고 JSON 결과를 돌려준다.

    브라우저·workerd 가 함께 떠 있을 때 workerd 새 프로세스가 일시적으로 뜨지 못하는
    경우(빈 stderr·EAGAIN)가 있어 세 번까지 다시 시도한다.
    """
    last = None
    for attempt in range(3):
        proc = subprocess.run(
            [WRANGLER, 'd1', 'execute', 'itda-db', '--local', '--json', '--command', sql],
            cwd=ROOT, env=wrangler_env(), capture_output=True, text=True, timeout=120,
        )
        if proc.returncode == 0:
            text = proc.stdout.strip()
            start = text.find('[') if text.find('[') >= 0 else text.find('{')
            return json.loads(text[start:]) if start >= 0 else []
        last = proc
        time.sleep(2 + attempt * 2)
    detail = (last.stderr or last.stdout or f'exit {last.returncode}').strip() if last else ''
    raise RuntimeError(detail or 'd1 실행 실패')


def d1_file(path):
    """로컬 D1 에 SQL 파일을 적용한다(스키마처럼 여러 줄일 때)."""
    proc = subprocess.run(
        [WRANGLER, 'd1', 'execute', 'itda-db', '--local', '--file', path],
        cwd=ROOT, env=wrangler_env(), capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def start_local():
    proc = subprocess.Popen(
        [WRANGLER, 'pages', 'dev', '.', '--port', '8789', '--ip', '127.0.0.1'],
        cwd=ROOT, env=wrangler_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(90):
        try:
            urllib.request.urlopen('http://127.0.0.1:8789/api/auth/config', timeout=2)
            return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise RuntimeError('로컬 서버가 뜨지 않았습니다')


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


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
            return {status: res.status, data, headers: {
              cache: res.headers.get('cache-control') || '',
              cookie: res.headers.get('set-cookie') || '',
            }};
        }""",
        [path, method, payload],
    )


def wait_ready(page):
    page.wait_for_function('() => window.__ITDA && window.__ITDA.ready === true', timeout=60000)
    page.wait_for_timeout(300)


def wait_turnstile(page, timeout=45):
    """Turnstile 토큰이 들어올 때까지 기다린다(로컬 테스트 키는 즉시 통과)."""
    try:
        page.wait_for_function(
            """() => {
                const input = document.querySelector('#auth-turnstile input[name="cf-turnstile-response"]');
                return !!input && String(input.value).length > 10;
            }""",
            timeout=timeout * 1000,
        )
        return True
    except Exception:
        return False


def solve_turnstile(page, timeout=45):
    """Turnstile 토큰을 기다리고, 사람 확인 위젯이 떠 있으면 한 번 눌러 본다."""
    if wait_turnstile(page, timeout=8):
        return True
    try:
        box = page.locator('#auth-turnstile').bounding_box()
        if box and box['height'] > 10:
            page.mouse.click(box['x'] + 28, box['y'] + box['height'] / 2)
    except Exception:
        pass
    return wait_turnstile(page, timeout=timeout)


def signup(page, username, password):
    page.click('#btn-account')
    page.wait_for_selector('#ov-auth:not([hidden])', timeout=8000)
    page.click('#auth-tabs [data-mode="signup"]')
    page.fill('#auth-username', username)
    page.fill('#auth-password', password)
    page.fill('#auth-password2', password)
    ok_token = solve_turnstile(page)
    page.click('#auth-submit')
    try:
        page.wait_for_function("() => document.getElementById('ov-auth').hidden === true", timeout=30000)
        return ok_token, True
    except Exception:
        return ok_token, False


def run(url, shot_dir, local):
    os.makedirs(shot_dir, exist_ok=True)
    suffix = ''.join(random.choice(string.digits) for _ in range(5))
    username = ('로컬삭제' if local else '삭제점검') + suffix
    password = 'itda-Delete-24'
    shots = {}

    def shot(page, name, cls=None):
        path = os.path.join(shot_dir, f'{name}.png')
        if cls:
            page.locator(cls).screenshot(path=path)
        else:
            page.screenshot(path=path, full_page=False)
        shots[name] = path

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, locale='ko-KR')
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(f'console.{m.type}: {m.text}') if m.type == 'error' else None)

        page.goto(url, wait_until='domcontentloaded')
        wait_ready(page)

        print('· 가입 후 내 계정 창')
        token_ok, signed_up = signup(page, username, password)
        check(token_ok, 'Turnstile 확인을 마침')
        check(signed_up, f'점검 계정({username}) 가입',
              page.inner_text('#auth-error') if page.is_visible('#auth-error') else '')
        if not signed_up:
            print('  ! 로그인 세션을 만들지 못해(봇 확인) 나머지 점검을 건너뜁니다.')
            try:
                page.screenshot(path=os.path.join(shot_dir, 'signup-blocked.png'))
                page.locator('#auth-turnstile').screenshot(path=os.path.join(shot_dir, 'turnstile-widget.png'))
            except Exception:
                pass
            browser.close()
            print(f'\n결과: {PASS} 통과 · {FAIL} 실패')
            return 1
        page.click('#btn-account')
        page.wait_for_selector('#ov-account:not([hidden])', timeout=8000)
        page.wait_for_timeout(500)
        check(page.is_visible('#btn-delete-account'), '내 계정 창에 계정 삭제 버튼이 보임')
        box_logout = page.locator('#btn-logout').bounding_box()
        box_delete = page.locator('#btn-delete-account').bounding_box()
        check(bool(box_logout and box_delete) and box_delete['y'] > box_logout['y'] + box_logout['height'] - 2,
              '계정 삭제 버튼이 로그아웃 아래에 있음',
              json.dumps([box_logout, box_delete]))
        shot(page, 'desktop-account-with-delete')
        shot(page, 'desktop-account-sheet', cls='.account-sheet')

        print('· 1단계 → 2단계 확인 화면')
        page.click('#btn-delete-account')
        page.wait_for_selector('#account-delete-view:not([hidden])', timeout=5000)
        page.wait_for_timeout(400)
        check(page.is_visible('#account-delete-view'), '2단계 확인 화면이 열림')
        check(not page.is_visible('#account-main'), '계정 정보 화면은 숨겨짐')
        warn = page.inner_text('#account-delete-view')
        check('되돌릴 수 없' in warn, '복구 불가 경고 문구가 보임')
        check(page.is_disabled('#btn-delete-confirm'), '아무것도 입력하지 않으면 영구 삭제가 잠김')
        check(page.get_attribute('#account-delete-confirm', 'type') == 'password', '아이디 계정은 비밀번호 입력칸')
        shot(page, 'desktop-delete-confirm-view')
        shot(page, 'desktop-delete-sheet', cls='.account-sheet')

        print('· 틀린 비밀번호 거부')
        page.fill('#account-delete-confirm', 'wrong-password-123')
        check(not page.is_disabled('#btn-delete-confirm'), '비밀번호를 입력하면 영구 삭제가 열림')
        page.click('#btn-delete-confirm')
        page.wait_for_selector('#account-delete-error:not([hidden])', timeout=15000)
        err = page.inner_text('#account-delete-error')
        check('비밀번호가 맞지 않' in err, '틀린 비밀번호는 거부', err)
        me = api(page, '/api/auth/me')
        check(me['data'] and me['data'].get('user') and me['data']['user']['username'] == username,
              '거부된 뒤에도 계정이 남아 있음', json.dumps(me, ensure_ascii=False))
        shot(page, 'desktop-delete-wrong-password')

        print('· 정상 삭제')
        page.fill('#account-delete-confirm', password)
        page.click('#btn-delete-confirm')
        try:
            page.wait_for_function("() => document.getElementById('ov-account').hidden === true", timeout=25000)
            closed = True
        except Exception:
            closed = False
        check(closed, '삭제 뒤 계정 창이 닫힘',
              page.inner_text('#account-delete-error') if page.is_visible('#account-delete-error') else '')
        page.wait_for_timeout(400)
        label = page.get_attribute('#btn-account', 'aria-label') or ''
        check('로그인' in label and '내 계정' not in label, '게스트(비로그인) 상태로 바뀜', label)
        me = api(page, '/api/auth/me')
        check(me['data'] and me['data'].get('user') is None, '삭제 뒤 세션이 사라짐', json.dumps(me, ensure_ascii=False))
        toast = page.inner_text('.toast') if page.locator('.toast').count() else ''
        check('계정을 삭제했어요' in toast, '삭제 안내 토스트', toast)
        cookie = ctx.cookies()
        check(all(c['name'] != 'itda_session' for c in cookie), '세션 쿠키가 지워짐', json.dumps(cookie))
        shot(page, 'desktop-after-delete')

        print('· 삭제된 계정으로 재로그인')
        page.click('#btn-account')
        page.wait_for_selector('#ov-auth:not([hidden])', timeout=8000)
        page.fill('#auth-username', username)
        page.fill('#auth-password', password)
        solve_turnstile(page)
        page.click('#auth-submit')
        page.wait_for_timeout(3000)
        err = page.inner_text('#auth-error') if page.is_visible('#auth-error') else ''
        check('맞지 않' in err, '삭제된 계정은 로그인할 수 없음', err)
        me = api(page, '/api/auth/me')
        check(me['data'] and me['data'].get('user') is None, '재로그인 시도 뒤에도 비로그인', json.dumps(me, ensure_ascii=False))
        shot(page, 'desktop-relogin-after-delete')
        page.click('#btn-auth-close')
        page.wait_for_timeout(300)

        print('· API 보호')
        nope = api(page, '/api/auth/delete', 'POST', {'password': password})
        check(nope['status'] == 401 and nope['data'].get('error') == 'not_signed_in',
              '세션 없이 삭제 요청은 401 not_signed_in', json.dumps(nope, ensure_ascii=False))
        check('no-store' in nope['headers']['cache'], '삭제 응답에 Cache-Control: no-store', nope['headers']['cache'])
        get_res = api(page, '/api/auth/delete', 'GET')
        check(get_res['status'] == 405, 'GET 요청은 허용되지 않음', str(get_res['status']))
        bad = api(page, '/api/auth/delete', 'POST', None)
        check(bad['status'] == 401, '본문 없는 삭제 요청도 401', json.dumps(bad, ensure_ascii=False))

        if not local:
            print('· 기존 test1 계정 보존 확인(가입 시도는 중복으로 거절되어야 함)')
            page.click('#btn-account')
            page.wait_for_selector('#ov-auth:not([hidden])', timeout=8000)
            page.click('#auth-tabs [data-mode="signup"]')
            page.fill('#auth-username', 'test1')
            page.fill('#auth-password', 'probe-Password-1')
            page.fill('#auth-password2', 'probe-Password-1')
            solve_turnstile(page)
            page.click('#auth-submit')
            page.wait_for_timeout(3000)
            err = page.inner_text('#auth-error') if page.is_visible('#auth-error') else ''
            check('이미 쓰고 있는 아이디' in err, 'test1 계정이 그대로 남아 있음(중복 아이디로 거절)', err)
            shot(page, 'desktop-test1-still-exists')
            page.click('#btn-auth-close')
            page.wait_for_timeout(300)

        print('· 모바일: 삭제 확인 화면')
        mobile_name = ('로컬모바일' if local else '삭제모바일') + suffix
        mobile = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2,
                                     is_mobile=True, has_touch=True, locale='ko-KR')
        m = mobile.new_page()
        m.on('pageerror', lambda e: errors.append(str(e)))
        m.goto(url, wait_until='domcontentloaded')
        wait_ready(m)
        ok_token, signed = signup(m, mobile_name, password)
        check(signed, f'모바일 점검 계정({mobile_name}) 가입',
              m.inner_text('#auth-error') if m.is_visible('#auth-error') else '')
        m.click('#btn-account')
        m.wait_for_selector('#ov-account:not([hidden])', timeout=8000)
        m.wait_for_timeout(300)
        shot(m, 'mobile-account-with-delete')
        m.click('#btn-delete-account')
        m.wait_for_selector('#account-delete-view:not([hidden])', timeout=5000)
        m.wait_for_timeout(400)
        overflow = m.evaluate('() => ({scroll: document.documentElement.scrollWidth, win: window.innerWidth})')
        check(overflow['scroll'] <= overflow['win'] + 1, '모바일에서 가로 스크롤 없음', json.dumps(overflow))
        box = m.locator('.account-sheet').bounding_box()
        check(bool(box) and box['y'] >= 0 and box['y'] + box['height'] <= 844 + 1,
              '모바일에서 삭제 확인 창이 화면 안에 들어옴', json.dumps(box))
        shot(m, 'mobile-delete-confirm-view')
        shot(m, 'mobile-delete-sheet', cls='.account-sheet')

        print('· 모바일 취소 → 닫기, 점검 계정 정리')
        m.click('#btn-delete-cancel')
        m.wait_for_timeout(300)
        check(m.is_visible('#account-main') and not m.is_visible('#account-delete-view'),
              '취소하면 계정 정보 화면으로 돌아옴')
        check(m.is_visible('#btn-logout'), '취소 뒤에도 로그인 상태 유지')
        cleaned = api(m, '/api/auth/delete', 'POST', {'password': password})
        check(cleaned['status'] == 200 and cleaned['data'].get('ok'), '모바일 점검 계정 정리(삭제)',
              json.dumps(cleaned, ensure_ascii=False))
        mobile.close()

        if local:
            print('· 다른 계정은 남는지(짝 계정 보존)')
            now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            d1(f"""INSERT OR REPLACE INTO users (id, username, password_hash, google_sub, display_name, stats_json, created_at, updated_at)
                   VALUES ('u_delcheck_bystander', 'test1', NULL, 'delcheck-bystander', 'test1', '{{}}', '{now}', '{now}')""")
            keep_token = b64url(os.urandom(32))
            keep_hash = b64url(hashlib.sha256(keep_token.encode()).digest())
            d1(f"""INSERT OR REPLACE INTO sessions (token_hash, user_id, expires_at, created_at)
                   VALUES ('{keep_hash}', 'u_delcheck_bystander', {int(time.time() * 1000) + 86400000}, '{now}')""")

            print('· 구글 전용 계정(확인 문구) 경로')
            guser = {'id': 'u_delcheck_google', 'username': '삭제구글' + suffix, 'sub': 'delcheck-' + suffix}
            token = b64url(os.urandom(32))
            token_hash = b64url(hashlib.sha256(token.encode()).digest())
            now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            d1(f"""INSERT OR REPLACE INTO users (id, username, password_hash, google_sub, display_name, stats_json, created_at, updated_at)
                   VALUES ('{guser['id']}', '{guser['username']}', NULL, '{guser['sub']}', '{guser['username']}', '{{}}', '{now}', '{now}')""")
            d1(f"""INSERT OR REPLACE INTO sessions (token_hash, user_id, expires_at, created_at)
                   VALUES ('{token_hash}', '{guser['id']}', {int(time.time() * 1000) + 86400000}, '{now}')""")

            gctx = browser.new_context(viewport={'width': 1280, 'height': 900}, locale='ko-KR')
            gctx.add_cookies([{'name': 'itda_session', 'value': token,
                               'domain': '127.0.0.1', 'path': '/', 'httpOnly': True, 'secure': False, 'sameSite': 'Lax'}])
            g = gctx.new_page()
            g.on('pageerror', lambda e: errors.append(str(e)))
            g.goto(url, wait_until='domcontentloaded')
            wait_ready(g)
            g.click('#btn-account')
            g.wait_for_selector('#ov-account:not([hidden])', timeout=8000)
            check('구글' in g.inner_text('#account-provider'), '구글 계정으로 표시됨', g.inner_text('#account-provider'))
            g.click('#btn-delete-account')
            g.wait_for_selector('#account-delete-view:not([hidden])', timeout=5000)
            g.wait_for_timeout(400)
            check(g.inner_text('#account-delete-label').strip() == '확인 문구', '구글 계정은 확인 문구 입력칸',
                  g.inner_text('#account-delete-label'))
            check(g.get_attribute('#account-delete-confirm', 'type') == 'text', '구글 계정 입력칸은 글자 입력')
            g.fill('#account-delete-confirm', '아무거나')
            check(g.is_disabled('#btn-delete-confirm'), '맞지 않는 문구로는 영구 삭제가 잠김')
            shot(g, 'local-google-delete-confirm')
            wrong = api(g, '/api/auth/delete', 'POST', {'confirm': '아무거나'})
            check(wrong['status'] == 400 and wrong['data'].get('error') == 'confirm_mismatch',
                  '서버도 틀린 확인 문구를 거부', json.dumps(wrong, ensure_ascii=False))
            me = api(g, '/api/auth/me')
            check(me['data'] and me['data'].get('user') and me['data']['user']['username'] == guser['username'],
                  '거부된 뒤에도 구글 계정이 남아 있음')
            g.fill('#account-delete-confirm', f"@{guser['username']}")
            check(not g.is_disabled('#btn-delete-confirm'), '@아이디를 넣으면 영구 삭제가 열림')
            g.click('#btn-delete-confirm')
            try:
                g.wait_for_function("() => document.getElementById('ov-account').hidden === true", timeout=25000)
                gone = True
            except Exception:
                gone = False
            check(gone, '구글 계정 삭제 완료',
                  g.inner_text('#account-delete-error') if g.is_visible('#account-delete-error') else '')
            rows = d1(f"SELECT COUNT(*) AS n FROM users WHERE id = '{guser['id']}'")
            count = rows[0]['results'][0]['n'] if rows and rows[0].get('results') else -1
            check(count == 0, 'D1 users 행이 실제로 지워짐', str(count))
            sessions = d1(f"SELECT COUNT(*) AS n FROM sessions WHERE user_id = '{guser['id']}'")
            scount = sessions[0]['results'][0]['n'] if sessions and sessions[0].get('results') else -1
            check(scount == 0, 'D1 sessions 행도 지워짐', str(scount))
            gctx.close()

            rows = d1("SELECT COUNT(*) AS n FROM users WHERE id = 'u_delcheck_bystander'")
            count = rows[0]['results'][0]['n'] if rows and rows[0].get('results') else -1
            check(count == 1, '삭제 뒤에도 다른 계정(test1) 행은 그대로', str(count))
            rows = d1("SELECT COUNT(*) AS n FROM sessions WHERE user_id = 'u_delcheck_bystander'")
            count = rows[0]['results'][0]['n'] if rows and rows[0].get('results') else -1
            check(count == 1, '다른 계정의 세션도 그대로', str(count))
            d1("DELETE FROM sessions WHERE user_id = 'u_delcheck_bystander'")
            d1("DELETE FROM users WHERE id = 'u_delcheck_bystander'")

        if errors:
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
    ap.add_argument('--shots-dir', default=os.path.join(ROOT, 'downloads', 'delete-check'))
    args = ap.parse_args()

    proc = None
    made_config = False
    url = args.url
    if args.local or not url:
        made_config = ensure_local_config()
        proc = start_local()
        url = 'http://127.0.0.1:8789'
        d1_file(os.path.join('db', 'schema.sql'))
    try:
        code = run(url.rstrip('/'), args.shots_dir, local=bool(args.local or not args.url))
    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=15)
        if made_config:
            try:
                os.remove(os.path.join(ROOT, 'wrangler.toml'))
            except OSError:
                pass
    sys.exit(code)


if __name__ == '__main__':
    main()
