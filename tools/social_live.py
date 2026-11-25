#!/usr/bin/env python3
"""라이브(https://itda-play.pages.dev) 프로필·친구 점검 + 보고용 스크린샷.

- 게스트: 상단 버튼이 그대로 4개(설정·사전·메일·계정)이고, 계정 버튼은 로그인 창을 연다.
  프로필·친구 API 는 로그인 없이는 401(404 가 아니면 배포가 반영된 것이다).
- 점검용 계정 두 개를 실제 회원가입으로 만들어 닉네임·사진 바꾸기, 아이디 검색, 친구 요청·수락,
  친구 목록의 `메일`(받는 사람 자동 입력)까지 확인하고 끝나면 두 계정을 지워 흔적을 남기지 않는다.
  운영 Turnstile 이 사람 확인을 띄우면 그 확인을 대신 풀지 않는다(봇 방지 우회 금지).
  토큰이 저절로 오지 않으면 계정 부분은 SKIP 하고 게스트 점검만 마친다 — 로그인 흐름은
  tools/social_check.py(로컬)가 전부 덮는다.

usage:
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/social_live.py
"""
import json
import os
import random
import string
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
URL = os.environ.get('ITDA_URL', 'https://itda-play.pages.dev')
SHOT_DIR = os.environ.get('ITDA_SHOTS', '/workspace/downloads/itda/2026-11-25-profile-friends')
PASSWORD = 'itda-Profile-25'

PASS = 0
FAIL = 0
SKIP = 0
SHOTS = {}


def check(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ✓ {label}')
    else:
        FAIL += 1
        print(f'  ✗ {label}' + (f' — {detail}' if detail else ''))


def skip(label, detail=''):
    global SKIP
    SKIP += 1
    print(f'  - SKIP {label}' + (f' — {detail}' if detail else ''))


def shot(page, name, cls=None):
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f'{name}.png')
    if cls:
        page.locator(cls).screenshot(path=path)
    else:
        page.screenshot(path=path, full_page=False)
    SHOTS[name] = path


def api(page, path, method='GET', body=None):
    payload = json.dumps(body) if body is not None else 'null'
    return page.evaluate(
        """async ([path, method, payload]) => {
            const res = await fetch(path, {
              method, credentials: 'same-origin',
              headers: payload === 'null' ? {accept: 'application/json'}
                : {'content-type': 'application/json', accept: 'application/json'},
              body: payload === 'null' ? undefined : payload,
            });
            let data = null;
            try { data = await res.json(); } catch (e) { data = null; }
            return {status: res.status, data, cache: res.headers.get('cache-control') || ''};
        }""",
        [path, method, payload],
    )


def wait_ready(page):
    page.wait_for_function('() => window.__ITDA && window.__ITDA.ready === true', timeout=90000)
    page.wait_for_timeout(400)


def wait_turnstile(page, timeout=40):
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


def signup_ui(page, username):
    page.click('#btn-account')
    page.wait_for_selector('#ov-auth:not([hidden])', timeout=8000)
    page.click('#auth-tabs [data-mode="signup"]')
    page.fill('#auth-username', username)
    page.fill('#auth-password', PASSWORD)
    page.fill('#auth-password2', PASSWORD)
    token = wait_turnstile(page)
    if not token:
        return False, False
    page.click('#auth-submit')
    try:
        page.wait_for_function("() => document.getElementById('ov-auth').hidden === true", timeout=30000)
        return True, True
    except Exception:
        return False, True


def open_account(page):
    if page.is_visible('#ov-account'):
        return
    page.click('#btn-account')
    page.wait_for_selector('#ov-account:not([hidden])', timeout=8000)
    page.wait_for_timeout(400)


def make_photo(path):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (240, 180), (250, 246, 236))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 120, 180], fill=(196, 80, 59))
    draw.ellipse([80, 45, 160, 135], fill=(240, 200, 120))
    image.save(path, 'JPEG', quality=88)
    return path


def run(headless=True):
    global SKIP
    suffix = ''.join(random.choice(string.digits) for _ in range(4))
    name_a = '라이브친구' + suffix
    name_b = '라이브메일' + suffix
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=headless,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])

        def new_ctx(width=1280, height=900, mobile=False):
            return browser.new_context(viewport={'width': width, 'height': height},
                                       device_scale_factor=2 if mobile else 1,
                                       is_mobile=mobile, has_touch=mobile, locale='ko-KR')

        # ── 게스트 ──────────────────────────────────────────────
        print('· 라이브 게스트')
        ctx = new_ctx()
        guest = ctx.new_page()
        guest.on('pageerror', lambda e: errors.append(str(e)))
        guest.goto(URL, wait_until='domcontentloaded')
        wait_ready(guest)
        order = guest.eval_on_selector_all('.top-actions .top-btn', 'els => els.map(e => e.id)')
        check(order[:3] == ['btn-settings', 'btn-dict', 'btn-mail'],
              '상단 오른쪽 버튼은 설정·사전·메일 3개', json.dumps(order))
        prof = guest.eval_on_selector_all('.top-profile .top-btn', 'els => els.map(e => e.id)')
        check(prof[:1] == ['btn-account'], '프로필(계정) 버튼은 왼쪽 위', json.dumps(prof))
        check(guest.locator('#btn-friends').count() == 0, '다섯 번째(친구) 아이콘을 만들지 않음')
        check(guest.is_visible('#btn-mail') and guest.inner_text('#btn-mail').strip() == '',
              '메일함 버튼은 아이콘만')
        for path, label in [
            ('/api/friends', '친구 목록'),
            ('/api/friends/search?q=ab', '친구 검색'),
            ('/api/friends/summary', '친구 요약'),
            ('/api/account/avatar?u=u_00000000000000000000000000000000', '프로필 사진'),
        ]:
            res = api(guest, path)
            check(res['status'] == 401, f'게스트 {label} 401(배포 반영)', str(res['status']))
        res = api(guest, '/api/account/profile', 'POST', {'nickname': '손님'})
        check(res['status'] == 401, '게스트 프로필 변경 401', str(res['status']))
        guest.click('#btn-account')
        guest.wait_for_selector('#ov-auth:not([hidden])', timeout=8000)
        check(guest.is_visible('#ov-auth'), '게스트가 계정 버튼을 누르면 로그인 창')
        shot(guest, 'live-desktop-guest-auth')
        guest.keyboard.press('Escape')
        guest.wait_for_timeout(300)
        shot(guest, 'live-desktop-home')
        ctx.close()

        # ── 두 계정 만들기 ───────────────────────────────────────
        print('\n· 라이브 점검 계정 (실제 회원가입)')
        ctx_a = new_ctx()
        a = ctx_a.new_page()
        a.on('pageerror', lambda e: errors.append(str(e)))
        a.goto(URL, wait_until='domcontentloaded')
        wait_ready(a)
        created_a, token_a = signup_ui(a, name_a)
        if not token_a:
            skip('계정 만들기', 'Turnstile 사람 확인이 자동으로 오지 않음')
            check(not errors, '콘솔·페이지 오류 없음(게스트)', ' / '.join(errors[:3]))
            ctx_a.close()
            browser.close()
            print(f'\n결과: {PASS} 통과 · {FAIL} 실패 · {SKIP} 건너뜀')
            print('스크린샷:', json.dumps(SHOTS, ensure_ascii=False, indent=1))
            return 0 if FAIL == 0 else 1
        check(created_a, f'점검 계정 A({name_a}) 가입',
              a.inner_text('#auth-error') if a.is_visible('#auth-error') else '')

        print('\n· 라이브 프로필')
        open_account(a)
        check(a.inner_text('#account-handle') == f'@{name_a}', '내 아이디 표시', a.inner_text('#account-handle'))
        a.click('#btn-profile-edit')
        a.wait_for_selector('#profile-edit:not([hidden])', timeout=5000)
        a.fill('#profile-nickname', '라이브 친구')
        photo = make_photo('/tmp/itda-social-live.jpg')
        a.set_input_files('#avatar-file', photo)
        a.wait_for_selector('#profile-photo-img:not([hidden])', timeout=8000)
        a.wait_for_timeout(400)
        preview = a.eval_on_selector('#profile-photo-img', 'img => ({w: img.naturalWidth, h: img.naturalHeight})')
        check(preview['w'] == 160 and preview['h'] == 160, '사진을 160×160 으로 줄임', json.dumps(preview))
        shot(a, 'live-desktop-profile-edit')
        a.click('#btn-profile-save')
        a.wait_for_timeout(1500)
        check(a.inner_text('#account-name') == '라이브 친구', '라이브 닉네임 저장', a.inner_text('#account-name'))
        shown = a.eval_on_selector('#account-avatar-img',
                                   'img => ({src: img.getAttribute("src") || "", hidden: img.hidden})')
        check('/api/account/avatar?u=' in shown['src'] and not shown['hidden'],
              '라이브 프로필 사진 표시', json.dumps(shown, ensure_ascii=False))
        shot(a, 'live-desktop-account-profile')
        me = api(a, '/api/auth/me')
        check(me['data']['user']['nickname'] == '라이브 친구' and me['data']['user']['avatarAt'] > 0,
              '라이브 /api/auth/me 에 닉네임·사진 시각', json.dumps(me['data'], ensure_ascii=False)[:200])

        # ── B 계정 · 친구 ────────────────────────────────────────
        print('\n· 라이브 친구')
        ctx_b = new_ctx()
        b = ctx_b.new_page()
        b.on('pageerror', lambda e: errors.append(str(e)))
        b.goto(URL, wait_until='domcontentloaded')
        wait_ready(b)
        created_b, token_b = signup_ui(b, name_b)
        check(token_b and created_b, f'점검 계정 B({name_b}) 가입',
              b.inner_text('#auth-error') if b.is_visible('#auth-error') else '')
        if created_b:
            open_account(b)
            b.click('#account-tabs [data-account-tab="friends"]')
            b.wait_for_selector('#account-view-friends:not([hidden])', timeout=5000)
            b.fill('#friend-search-input', '@' + name_a)
            b.click('#friend-search-btn')
            b.wait_for_selector('#friend-results .friend-item', timeout=10000)
            b.wait_for_timeout(300)
            result = b.inner_text('#friend-results .friend-item')
            check('라이브 친구' in result and '@' + name_a in result, '라이브 검색 결과에 닉네임·@아이디',
                  result.replace('\n', ' ')[:140])
            shot(b, 'live-desktop-friends-search')
            b.click('#friend-results .friend-btn.primary')
            b.wait_for_timeout(1500)
            check('친구 요청을 보냈어요' in b.inner_text('.toast'), '라이브 친구 요청', b.inner_text('.toast'))

            # A 화면에서 수락
            a.reload(wait_until='domcontentloaded')
            wait_ready(a)
            a.wait_for_selector('#account-badge:not([hidden])', timeout=15000)
            check(a.is_visible('#account-badge'), '받은 요청 빨간 점(라이브)')
            open_account(a)
            a.click('#account-tabs [data-account-tab="friends"]')
            a.wait_for_selector('#friend-list .friend-item', timeout=10000)
            shot(a, 'live-desktop-friends-incoming')
            a.click('#friend-list .friend-btn.primary')
            a.wait_for_timeout(1500)
            check('친구가 됐어요' in a.inner_text('.toast'), '라이브 수락', a.inner_text('.toast'))
            a.click('#friend-tabs [data-friend-tab="friends"]')
            a.wait_for_timeout(700)
            check(a.locator('#friend-list .friend-item').count() == 1, '라이브 친구 목록 1명',
                  str(a.locator('#friend-list .friend-item').count()))
            shot(a, 'live-desktop-friends-list')

            # 친구 목록 → 메일 보내기(받는 사람 자동 입력)
            a.click('#friend-list .friend-btn.ghost:not(.danger)')
            a.wait_for_selector('#ov-mail:not([hidden])', timeout=8000)
            a.wait_for_selector('#mail-view-compose:not([hidden])', timeout=8000)
            a.wait_for_timeout(400)
            check(a.input_value('#mail-to') == '@' + name_b, '친구 메일 받는 사람 자동 입력',
                  a.input_value('#mail-to'))
            shot(a, 'live-desktop-friend-compose')
            a.click('#btn-mail-close')
            a.wait_for_timeout(300)

            # 모바일 화면
            a.set_viewport_size({'width': 390, 'height': 844})
            a.wait_for_timeout(400)
            open_account(a)
            a.click('#account-tabs [data-account-tab="friends"]')
            a.click('#friend-tabs [data-friend-tab="friends"]')
            a.wait_for_timeout(700)
            mobile = a.evaluate("""() => {
                const sheet = document.querySelector('#ov-account .sheet');
                return { over: sheet.scrollWidth - sheet.clientWidth,
                         fits: sheet.getBoundingClientRect().right <= innerWidth + 1 };
            }""")
            check(mobile['over'] <= 1 and mobile['fits'], '라이브 390px 친구 창이 넘치지 않음', json.dumps(mobile))
            shot(a, 'live-mobile-friends')
            a.click('#btn-account-close')
            a.wait_for_timeout(300)
            shot(a, 'live-mobile-home')

        # ── 정리: 두 계정 삭제 ───────────────────────────────────
        print('\n· 라이브 점검 계정 정리')
        res = api(a, '/api/auth/delete', 'POST', {'password': PASSWORD})
        check(res['status'] == 200 and res['data'].get('ok'), 'A 계정 삭제', json.dumps(res['data'], ensure_ascii=False)[:160])
        res = api(b, '/api/auth/delete', 'POST', {'password': PASSWORD})
        check(res['status'] == 200 and res['data'].get('ok'), 'B 계정 삭제', json.dumps(res['data'], ensure_ascii=False)[:160])
        check(not errors, '콘솔·페이지 오류 없음', ' / '.join(errors[:3]))

        ctx_a.close()
        ctx_b.close()
        browser.close()

    try:
        os.remove('/tmp/itda-social-live.jpg')
    except OSError:
        pass

    print(f'\n결과: {PASS} 통과 · {FAIL} 실패 · {SKIP} 건너뜀')
    print('스크린샷:', json.dumps(SHOTS, ensure_ascii=False, indent=1))
    return 0 if FAIL == 0 else 1


def main():
    sys.exit(run())


if __name__ == '__main__':
    main()
