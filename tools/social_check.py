#!/usr/bin/env python3
"""프로필(닉네임 · 사진) · 친구(아이디 검색 · 요청 · 수락 · 삭제 · 메일) 전 흐름 점검.

로컬 `wrangler pages dev`(+로컬 D1)에서 아래를 차례로 확인한다.

 1. 게스트: 친구·프로필 API 401, 프로필 사진 401
 2. 닉네임: 앞뒤 공백 정리 · 1~16자 · 제어문자 거부 · 아이디(@아이디)는 그대로 ·
    상단 계정 버튼/계정 창/메일함에 닉네임 + @아이디가 함께 보이는지
 3. 프로필 사진: 화면에서 160×160 으로 줄여 올리기 · 저장·표시 · 사진 지우기 ·
    서버 검증(SVG·GIF·머리글자 불일치·28KB 초과·40KB 본문 413) · `?v=` 캐시 주소
 4. 아이디 검색: @ 유무 · 2자 미만 거부 · 최대 8건 · 자기 자신 제외 · 민감 필드 없음 ·
    사용자당 분당 40회 제한(429)
 5. 친구: 요청 · 중복 차단 · 자기 요청 차단 · 맞요청 자동 수락 · 수락·거절·취소·삭제 ·
    권한(남의 요청 404) · 계정 삭제 시 친구 행 정리 · CSRF 출처 403 · no-store
 6. 화면: 계정 탭(내 계정 · 친구) · 빨간 점(받은 요청) · 친구 목록의 `메일` →
    메일함 새 메일 쓰기에 @아이디 채움 · 친구 삭제 2단계 · 16자 닉네임 레이아웃 ·
    320/360/390px 가로 오버플로 0 · XSS 글자 렌더링
 7. 스크린샷(데스크톱·모바일)

usage:
    LD_LIBRARY_PATH=/workspace/.local/pwlibs python3 tools/social_check.py --local
"""
import argparse
import base64
import json
import os
import random
import shutil
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRANGLER = '/workspace/tools-npm/node_modules/.bin/wrangler'
CHROME = os.environ.get('ITDA_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
PORT = 8793
LOCAL_URL = f'http://127.0.0.1:{PORT}'
PASSWORD = 'itda-Profile-25'
TEST_PREFIX = '점검친구'

PASS = 0
FAIL = 0
SHOTS = {}
SHOT_DIR = os.path.join(ROOT, 'downloads', 'itda', '2026-11-25-profile-friends')
MIGRATIONS = [
    os.path.join('db', 'migrations', '2026-11-25-mail-trash-edit.sql'),
    os.path.join('db', 'migrations', '2026-11-25-profile-friends.sql'),
]


def check(cond, label, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ✓ {label}')
    else:
        FAIL += 1
        print(f'  ✗ {label}' + (f' — {detail}' if detail else ''))


def ensure_local_config():
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
    """로컬 D1(itda-db)에 SQL 한 줄을 실행한다.

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
    proc = subprocess.run(
        [WRANGLER, 'd1', 'execute', 'itda-db', '--local', '--file', path],
        cwd=ROOT, env=wrangler_env(), capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def d1_value(sql):
    """첫 행 첫 값을 돌려준다(없으면 None)."""
    out = d1(sql)
    rows = out[0].get('results') if out else None
    if not rows:
        return None
    row = rows[0]
    return next(iter(row.values())) if row else None


def apply_migrations():
    for relative in MIGRATIONS:
        path = os.path.join(ROOT, relative)
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as handle:
            sql = handle.read()
        for raw in sql.split(';'):
            lines = [line for line in raw.splitlines() if not line.strip().startswith('--')]
            statement = '\n'.join(lines).strip()
            if not statement:
                continue
            try:
                d1(statement)
            except Exception:
                pass


def clean_previous_runs():
    """중간에 끊긴 예전 점검이 남긴 데이터를 지운다(이름 규칙 `점검…` 만)."""
    statements = [
        "DELETE FROM friendships WHERE requester_id IN (SELECT id FROM users WHERE username LIKE '점검%')"
        " OR addressee_id IN (SELECT id FROM users WHERE username LIKE '점검%')",
        "DELETE FROM mails WHERE sender_username LIKE '점검%' OR recipient_username LIKE '점검%'",
        'DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username LIKE \'점검%\')',
        "DELETE FROM users WHERE username LIKE '점검%'",
        'DELETE FROM auth_throttle',
    ]
    try:
        # 여러 문장을 한 번에 — wrangler 기동(4~5초)을 문장 수만큼 되풀이하지 않는다.
        d1(';\n'.join(statements))
    except Exception:
        for statement in statements:
            try:
                d1(statement)
            except Exception:
                pass


def reset_read_throttle():
    """조회 제한이 점검 흐름을 429 로 비우지 않게 점검용 로컬 D1 의 읽기 창만 비운다."""
    try:
        d1("DELETE FROM auth_throttle WHERE key LIKE 'read:%' OR key LIKE 'friend:%' OR key LIKE 'profile:%'")
    except Exception:
        pass


def start_local():
    proc = subprocess.Popen(
        [WRANGLER, 'pages', 'dev', '.', '--port', str(PORT), '--ip', '127.0.0.1'],
        cwd=ROOT, env=wrangler_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(90):
        try:
            urllib.request.urlopen(f'{LOCAL_URL}/api/auth/config', timeout=2)
            return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise RuntimeError('로컬 서버가 뜨지 않았습니다')


def api(page, path, method='GET', body=None, headers=None):
    payload = json.dumps(body) if body is not None else 'null'
    return page.evaluate(
        """async ([path, method, payload, headers]) => {
            const res = await fetch(path, {
              method,
              credentials: 'same-origin',
              headers: Object.assign(payload === 'null'
                ? {accept: 'application/json'}
                : {'content-type': 'application/json', accept: 'application/json'}, headers || {}),
              body: payload === 'null' ? undefined : payload,
            });
            let data = null;
            try { data = await res.json(); } catch (e) { data = null; }
            return {status: res.status, data, cache: res.headers.get('cache-control') || '',
                    type: res.headers.get('content-type') || ''};
        }""",
        [path, method, payload, headers or {}],
    )


def raw_post(page, path, body=None, headers=None):
    """브라우저 대신 실제 HTTP 로 POST — Origin 처럼 스크립트가 못 붙이는 헤더를 시험한다."""
    cookies = page.context.cookies(LOCAL_URL)
    cookie_header = '; '.join(f"{item['name']}={item['value']}" for item in cookies)
    data = json.dumps(body).encode('utf-8') if body is not None else b''
    req = urllib.request.Request(LOCAL_URL + path, data=data, method='POST')
    req.add_header('content-type', 'application/json')
    if cookie_header:
        req.add_header('cookie', cookie_header)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return {'status': res.status, 'data': json.loads(res.read().decode('utf-8') or '{}')}
    except urllib.error.HTTPError as err:
        try:
            payload = json.loads(err.read().decode('utf-8') or '{}')
        except Exception:
            payload = {}
        return {'status': err.code, 'data': payload}


def fetch_bytes(page, path):
    return page.evaluate(
        """async (path) => {
            const res = await fetch(path, {credentials: 'same-origin'});
            const buf = new Uint8Array(await res.arrayBuffer());
            let text = '';
            for (let i = 0; i < Math.min(buf.length, 24); i += 1) text += String.fromCharCode(buf[i]);
            return {status: res.status, type: res.headers.get('content-type') || '',
                    cache: res.headers.get('cache-control') || '', length: buf.length, head: text};
        }""",
        path,
    )


def wait_ready(page):
    page.wait_for_function('() => window.__ITDA && window.__ITDA.ready === true', timeout=60000)
    page.wait_for_timeout(350)


def signup(page, username, password=PASSWORD):
    return api(page, '/api/auth/register', 'POST', {
        'username': username, 'password': password, 'turnstileToken': 'local-test-token',
    })


def login(page, username, password=PASSWORD):
    return api(page, '/api/auth/login', 'POST', {
        'username': username, 'password': password, 'turnstileToken': 'local-test-token',
    })


def shot(page, name, cls=None):
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f'{name}.png')
    if cls:
        page.locator(cls).screenshot(path=path)
    else:
        page.screenshot(path=path, full_page=False)
    SHOTS[name] = path


def new_name(suffix):
    return TEST_PREFIX + suffix


def open_account(page):
    if page.is_visible('#ov-account'):
        return
    page.click('#btn-account')
    page.wait_for_selector('#ov-account:not([hidden])', timeout=8000)
    page.wait_for_timeout(350)


def close_account(page):
    if page.is_visible('#ov-account'):
        page.click('#btn-account-close')
        page.wait_for_timeout(300)


def account_tab(page, key):
    page.click(f'#account-tabs [data-account-tab="{key}"]')
    page.wait_for_timeout(600)


def friend_tab(page, key):
    page.click(f'#friend-tabs [data-friend-tab="{key}"]')
    page.wait_for_timeout(500)


def make_photo(path, size=(240, 180)):
    """가운데를 정사각으로 잘라내는지 보려고 가로로 긴 사진을 하나 만든다."""
    from PIL import Image, ImageDraw
    image = Image.new('RGB', size, (250, 246, 236))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, size[0] // 2, size[1]], fill=(196, 80, 59))
    draw.ellipse([size[0] // 3, size[1] // 4, size[0] * 2 // 3, size[1] * 3 // 4], fill=(240, 200, 120))
    image.save(path, 'JPEG', quality=88)
    return path


def b64(text):
    if isinstance(text, str):
        text = text.encode('utf-8')
    return base64.b64encode(text).decode('ascii')


def png_data_url():
    """1×1 PNG(매직바이트가 맞는 가장 작은 이미지)."""
    return ('data:image/png;base64,'
            + 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==')


def run(headless=True):
    names = {
        'a': new_name('가01'),
        'b': new_name('나02'),
        'c': new_name('다03'),
        'd': new_name('라04'),
        'e': new_name('마05'),
    }
    # 검색 결과 8건 상한을 넘기려고 같은 접두사를 쓰는 계정을 더 만든다.
    extra = [new_name(f'{index:02d}{index:02d}') for index in range(6, 10)]
    created = list(names.values()) + extra

    clean_previous_runs()

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=headless,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])

        def open_page(user=None, width=1280, height=900, mobile=False, app=False):
            """app=True 면 사전(73만 단어)까지 다 뜬 화면이 필요하다(화면 점검용).
            API 만 쓰는 페이지는 사전을 기다리지 않아 점검 시간을 크게 줄인다."""
            ctx = browser.new_context(
                viewport={'width': width, 'height': height},
                device_scale_factor=2 if mobile else 1,
                is_mobile=mobile, has_touch=mobile, locale='ko-KR',
            )
            page = ctx.new_page()
            page.goto(LOCAL_URL, wait_until='domcontentloaded')
            if app:
                wait_ready(page)
            if user:
                login(page, user)
                if app:
                    page.reload(wait_until='domcontentloaded')
                    wait_ready(page)
            return ctx, page

        def drop(ctx):
            try:
                ctx.close()
            except Exception:
                pass

        # ── 준비: 계정 ────────────────────────────────────────────────
        print('· 준비: 점검 계정')
        ctx_seed, seed = open_page()
        signup_fail = []
        for username in created:
            res = signup(seed, username)
            if res['status'] != 200:
                signup_fail.append((username, res))
        check(not signup_fail, f'점검 계정 {len(created)}개 준비',
              json.dumps(signup_fail[:1], ensure_ascii=False)[:240])
        drop(ctx_seed)

        # ── 1. 게스트 ─────────────────────────────────────────────────
        print('\n· 게스트')
        ctx_guest, guest = open_page()
        for path, label in [
            ('/api/friends', '친구 목록'),
            ('/api/friends/search?q=aa', '친구 검색'),
            ('/api/friends/summary', '친구 요약'),
            ('/api/account/avatar?u=u_00000000000000000000000000000000', '프로필 사진'),
        ]:
            res = api(guest, path)
            check(res['status'] == 401, f'비로그인 {label} 401', str(res['status']))
        res = api(guest, '/api/friends/request', 'POST', {'username': names['a']})
        check(res['status'] == 401, '비로그인 친구 요청 401', str(res['status']))
        res = api(guest, '/api/account/profile', 'POST', {'nickname': '손님'})
        check(res['status'] == 401, '비로그인 프로필 변경 401', str(res['status']))

        guest.click('#btn-account')
        guest.wait_for_selector('#ov-auth:not([hidden])', timeout=8000)
        check(guest.is_visible('#ov-auth'), '게스트가 계정 버튼을 누르면 로그인 창')
        guest.click('#btn-auth-close')
        guest.wait_for_timeout(300)
        drop(ctx_guest)

        # ── 2. 닉네임 ─────────────────────────────────────────────────
        print('\n· 닉네임')
        ctx_a, a = open_page(names['a'], app=True)
        res = api(a, '/api/auth/me')
        user = res['data']['user']
        check(user.get('nickname') == '' and user.get('displayName') == names['a'],
              '처음에는 닉네임이 없고 아이디가 이름', json.dumps(user, ensure_ascii=False))
        check(user.get('avatarAt') == 0, '처음에는 프로필 사진 없음', str(user.get('avatarAt')))

        res = api(a, '/api/account/profile', 'POST', {'nickname': '  잇다 친구  '})
        check(res['status'] == 200 and res['data']['user']['nickname'] == '잇다 친구',
              '닉네임 앞뒤 공백 정리', json.dumps(res['data'], ensure_ascii=False)[:200])
        check(res['data']['user']['username'] == names['a'], '아이디는 그대로')
        check(res['data']['user']['displayName'] == '잇다 친구', '표시 이름이 닉네임으로')

        for body, code, label in [
            ({'nickname': ''}, 'nickname_required', '빈 닉네임 거부'),
            ({'nickname': '   '}, 'nickname_required', '공백만 있는 닉네임 거부'),
            ({'nickname': '가' * 17}, 'nickname_long', '17자 닉네임 거부'),
            ({'nickname': '잇다\n친구'}, 'nickname_invalid', '줄바꿈 닉네임 거부'),
            ({'nickname': '잇다\u200b친구'}, 'nickname_invalid', '제로폭 글자 거부'),
            ({}, 'nothing_to_change', '바꿀 내용 없음 거부'),
        ]:
            res = api(a, '/api/account/profile', 'POST', body)
            check(res['status'] == 400 and res['data'].get('error') == code,
                  label, json.dumps(res['data'], ensure_ascii=False)[:160])

        a.reload(wait_until='domcontentloaded')
        wait_ready(a)
        label = a.get_attribute('#btn-account', 'aria-label') or ''
        check('잇다 친구' in label, '상단 계정 버튼 이름에 닉네임', label)
        open_account(a)
        check(a.inner_text('#account-name') == '잇다 친구', '계정 창에 닉네임', a.inner_text('#account-name'))
        check(a.inner_text('#account-handle') == f'@{names["a"]}', '계정 창에 @아이디', a.inner_text('#account-handle'))
        check(a.inner_text('#account-avatar-letter') == '잇', '사진이 없으면 닉네임 첫 글자 아바타',
              a.inner_text('#account-avatar-letter'))
        shot(a, 'local-desktop-account-profile')

        # ── 3. 프로필 사진 ────────────────────────────────────────────
        print('\n· 프로필 사진')
        # 서버 검증: SVG·GIF·머리글자 불일치·너무 큰 문자열
        for avatar, code, label in [
            ('data:image/svg+xml;base64,' + b64('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
             'avatar_invalid', 'SVG 사진 거부'),
            ('data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==',
             'avatar_invalid', 'GIF 사진 거부'),
            ('data:image/png;base64,' + b64('<html><script>alert(1)</script></html>'),
             'avatar_invalid', 'PNG 라고 속인 HTML 거부'),
            ('data:image/png;base64,' + 'A' * (29 * 1024),
             'avatar_too_large', '28KB 넘는 문자열 거부'),
        ]:
            res = api(a, '/api/account/profile', 'POST', {'avatar': avatar})
            check(res['status'] == 400 and res['data'].get('error') == code,
                  label, json.dumps(res['data'], ensure_ascii=False)[:160])

        res = api(a, '/api/account/profile', 'POST', {'avatar': png_data_url()})
        check(res['status'] == 200 and res['data']['user']['avatarAt'] > 0,
              'PNG 사진 저장', json.dumps(res['data'], ensure_ascii=False)[:200])
        saved = d1_value(f"SELECT avatar_data FROM users WHERE username = '{names['a']}'")
        check(isinstance(saved, str) and saved.startswith('data:image/png;base64,'),
              'D1 에 Data URL 로 저장', str(saved)[:40])
        check(len(saved or '') <= 28 * 1024, '저장 문자열 28KB 이하', str(len(saved or '')))

        avatarat = d1_value(f"SELECT avatar_updated_at FROM users WHERE username = '{names['a']}'")
        got = fetch_bytes(a, f'/api/account/avatar?u={user["id"]}&v={avatarat}')
        check(got['status'] == 200 and got['type'].startswith('image/png'),
              '프로필 사진 200 · image/png', json.dumps(got, ensure_ascii=False)[:160])
        check(got['length'] > 40 and got['head'].startswith('\x89PNG'), 'PNG 바이트 그대로',
              json.dumps(got, ensure_ascii=False)[:160])
        check('immutable' in got['cache'] or 'max-age' in got['cache'], '사진 응답 캐시 주소(?v=)', got['cache'])

        res = api(a, '/api/account/avatar?u=u_zzz')
        check(res['status'] == 400, '잘못된 사용자 id 400', str(res['status']))

        # 화면: 파일 선택 → 160×160 으로 줄여 저장
        open_account(a)
        if a.is_hidden('#profile-edit'):
            a.click('#btn-profile-edit')
            a.wait_for_timeout(300)
        photo = make_photo('/tmp/itda-social-photo.jpg')
        a.set_input_files('#avatar-file', photo)
        a.wait_for_selector('#profile-photo-img:not([hidden])', timeout=8000)
        a.wait_for_timeout(400)
        preview = a.eval_on_selector('#profile-photo-img',
                                     'img => ({src: img.src, w: img.naturalWidth, h: img.naturalHeight})')
        check(preview['src'].startswith('data:image/'), '고른 사진 미리 보기', json.dumps(preview)[:120])
        check(preview['w'] == 160 and preview['h'] == 160, '160×160 정사각으로 줄임', json.dumps(preview))
        draft_len = a.evaluate("() => { const i = document.getElementById('profile-photo-img'); return i.src.length; }")
        check(draft_len <= 24 * 1024 + 64, '보내는 사진 24KB 이하', str(draft_len))
        shot(a, 'local-desktop-profile-edit')
        a.click('#btn-profile-save')
        a.wait_for_timeout(1200)
        shown = a.eval_on_selector('#account-avatar-img',
                                   'img => ({src: img.getAttribute("src") || "", hidden: img.hidden})')
        check('/api/account/avatar?u=' in shown['src'] and not shown['hidden'],
              '계정 창에 사진 표시', json.dumps(shown, ensure_ascii=False))
        check(not a.is_visible('#profile-edit'), '저장하면 편집 칸이 닫힘')
        shot(a, 'local-desktop-account-photo')

        # 화면에서 `사진 지우기` → 저장
        a.click('#btn-profile-edit')
        a.wait_for_selector('#profile-edit:not([hidden])', timeout=5000)
        check(a.is_visible('#btn-avatar-remove'), '사진이 있으면 사진 지우기 버튼')
        a.click('#btn-avatar-remove')
        a.wait_for_timeout(300)
        a.click('#btn-profile-save')
        a.wait_for_timeout(1500)
        check(a.is_visible('#account-avatar-letter') and not a.is_visible('#account-avatar-img'),
              '사진을 지우면 첫 글자 아바타')
        missing = fetch_bytes(a, f'/api/account/avatar?u={user["id"]}&v=1')
        check(missing['status'] == 404, '지운 뒤 사진 404', str(missing['status']))

        # 413: 40KB 본문
        big = 'x' * (40 * 1024)
        res = api(a, '/api/account/profile', 'POST', {'nickname': big})
        check(res['status'] == 413 and res['data'].get('error') == 'payload_too_large',
              '32KB 넘는 본문 413', json.dumps(res['data'], ensure_ascii=False)[:160])

        # ── 4. 아이디 검색 ────────────────────────────────────────────
        print('\n· 아이디 검색')
        reset_read_throttle()
        res = api(a, '/api/friends/search?q=점')
        check(res['status'] == 400 and res['data'].get('error') == 'query_short',
              '1글자 검색 거부', json.dumps(res['data'], ensure_ascii=False)[:160])
        res = api(a, '/api/friends/search?q=@' + names['b'])
        rows = (res['data'] or {}).get('results') or []
        check(res['status'] == 200 and len(rows) == 1 and rows[0]['username'] == names['b'],
              '@ 붙여 정확 검색', json.dumps(rows, ensure_ascii=False)[:200])
        check(rows and rows[0]['relation'] == 'none', '처음 관계는 none', json.dumps(rows[:1], ensure_ascii=False))
        for key in ('password', 'password_hash', 'google_sub', 'expires_at', 'token_hash'):
            check(key not in json.dumps(res['data'], ensure_ascii=False), f'검색 응답에 {key} 없음')
        res = api(a, '/api/friends/search?q=' + TEST_PREFIX)
        check(res['status'] == 200 and len(res['data']['results']) == 8,
              '검색 결과 8건 상한', str(len((res['data'] or {}).get('results') or [])))
        usernames = [row['username'] for row in res['data']['results']]
        check(names['a'] not in usernames, '검색 결과에 자기 자신 없음')
        res = api(a, '/api/friends/search?q=없는아이디')
        check(res['status'] == 200 and res['data']['results'] == [], '없는 아이디는 빈 결과')
        check('no-store' in res['cache'], '검색 응답이 no-store', res['cache'])
        res = api(a, '/api/friends/search?q=' + '%' * 1)
        check(res['status'] == 400, '연산자만 있는 검색 거부', str(res['status']))

        # 사용자당 분당 40회
        limited = None
        for _ in range(42):
            res = api(a, '/api/friends/search?q=' + names['b'])
            if res['status'] == 429:
                limited = res
                break
        check(limited is not None and limited['data'].get('error') == 'rate_limited',
              '검색 폭주 429(분당 40회)', json.dumps(limited or {}, ensure_ascii=False)[:160])
        d1("DELETE FROM auth_throttle WHERE key LIKE 'friend:%'")

        # ── 5. 친구 ───────────────────────────────────────────────────
        print('\n· 친구 요청 · 수락')
        res = api(a, '/api/friends/request', 'POST', {'username': names['a']})
        check(res['status'] == 400 and res['data'].get('error') == 'self_request',
              '자기 자신 요청 거부', json.dumps(res['data'], ensure_ascii=False)[:160])
        res = api(a, '/api/friends/request', 'POST', {'username': '없는아이디9'})
        check(res['status'] == 404 and res['data'].get('error') == 'user_not_found',
              '없는 아이디 요청 404', json.dumps(res['data'], ensure_ascii=False)[:160])
        res = api(a, '/api/friends/request', 'POST', {'username': names['b']})
        check(res['status'] == 200 and res['data'].get('requested') and res['data']['counts']['outgoing'] == 1,
              'A → B 친구 요청', json.dumps(res['data'], ensure_ascii=False)[:200])
        res = api(a, '/api/friends/request', 'POST', {'username': names['b']})
        check(res['status'] == 409 and res['data'].get('error') == 'already_requested',
              '같은 요청 중복 차단', json.dumps(res['data'], ensure_ascii=False)[:160])

        # B 로그인 · 받은 요청 → 맞요청 자동 수락
        ctx_b, b = open_page(names['b'])
        res = api(b, '/api/friends/summary')
        check(res['status'] == 200 and res['data']['incoming'] == 1, 'B 받은 요청 1',
              json.dumps(res['data'], ensure_ascii=False))
        res = api(b, '/api/friends/request', 'POST', {'username': names['a']})
        check(res['status'] == 200 and res['data'].get('accepted'),
              '맞요청은 바로 친구가 됨', json.dumps(res['data'], ensure_ascii=False)[:200])
        res = api(a, '/api/friends/request', 'POST', {'username': names['b']})
        check(res['status'] == 409 and res['data'].get('error') == 'already_friends',
              '이미 친구면 409', json.dumps(res['data'], ensure_ascii=False)[:160])

        res = api(a, '/api/friends')
        check(res['status'] == 200 and len(res['data']['friends']) == 1
              and res['data']['friends'][0]['username'] == names['b'],
              'A 친구 목록에 B', json.dumps(res['data'], ensure_ascii=False)[:200])
        check('no-store' in res['cache'], '친구 목록 응답이 no-store', res['cache'])
        check(set(res['data']['friends'][0]) >= {'id', 'username', 'displayName', 'avatarAt'},
              '친구 항목에 필요한 값', json.dumps(res['data']['friends'][0], ensure_ascii=False)[:200])

        # 거절 · 취소
        res = api(a, '/api/friends/request', 'POST', {'username': names['c']})
        check(res['status'] == 200 and res['data']['counts']['outgoing'] == 1, 'A → C 요청')
        res = api(b, '/api/friends/respond', 'POST', {'username': names['c'], 'action': 'accept'})
        check(res['status'] == 404, '남의 요청 수락 404', json.dumps(res['data'], ensure_ascii=False)[:160])
        ctx_c, c = open_page(names['c'])
        res = api(c, '/api/friends/respond', 'POST', {'username': names['a'], 'action': 'decline'})
        check(res['status'] == 200 and res['data'].get('done'), 'C 거절', json.dumps(res['data'], ensure_ascii=False)[:160])
        res = api(a, '/api/friends')
        check(res['data']['counts']['outgoing'] == 0, '거절하면 보낸 요청에서 사라짐')

        res = api(a, '/api/friends/request', 'POST', {'username': names['c']})
        res = api(a, '/api/friends/respond', 'POST', {'username': names['c'], 'action': 'cancel'})
        check(res['status'] == 200 and res['data']['counts']['outgoing'] == 0, '보낸 요청 취소')

        res = api(a, '/api/friends/request', 'POST', {'username': names['c']})
        check(res['status'] == 200, 'A → C 다시 요청')
        res = api(c, '/api/friends/respond', 'POST', {'userId': user['id'], 'action': 'accept'})
        check(res['status'] == 200 and res['data']['counts']['friends'] == 1,
              'C 수락(userId 로도)', json.dumps(res['data'], ensure_ascii=False)[:160])

        # 권한: B 가 A-C 친구를 끊으려 하면 404
        res = api(b, '/api/friends/remove', 'POST', {'username': names['c']})
        check(res['status'] == 404, '남의 친구 삭제 404', json.dumps(res['data'], ensure_ascii=False)[:160])
        drop(ctx_b)
        drop(ctx_c)

        res = api(a, '/api/friends/remove', 'POST', {'username': names['b']})
        check(res['status'] == 200 and res['data']['counts']['friends'] == 1, 'B 친구 삭제',
              json.dumps(res['data'], ensure_ascii=False)[:160])
        res = api(a, '/api/friends/remove', 'POST', {'username': names['b']})
        check(res['status'] == 404, '이미 끊은 친구 다시 삭제 404', str(res['status']))

        # CSRF 출처 — 브라우저 fetch 는 Origin 을 못 붙이므로 실제 HTTP 요청으로 확인한다.
        res = raw_post(a, '/api/friends/request', {'username': names['d']},
                       {'origin': 'https://evil.example'})
        check(res['status'] == 403 and res['data'].get('error') == 'forbidden_origin',
              '다른 출처 친구 요청 403', json.dumps(res['data'], ensure_ascii=False)[:160])
        res = raw_post(a, '/api/account/profile', {'nickname': '나쁜곳'}, {'origin': 'null'})
        check(res['status'] == 403, 'Origin: null 프로필 변경 403', str(res['status']))

        # ── 6. 화면 ───────────────────────────────────────────────────
        print('\n· 화면: 계정 탭 · 검색 · 요청 · 수락 · 메일 · 삭제')
        reset_read_throttle()
        # A 화면: 친구 탭에서 D 검색 → 요청
        open_account(a)
        check(a.get_attribute('#account-tabs [data-account-tab="profile"]', 'aria-selected') == 'true',
              '계정 창은 내 계정 탭부터')
        account_tab(a, 'friends')
        check(a.is_visible('#account-view-friends') and not a.is_visible('#account-view-profile'),
              '친구 탭으로 전환')
        check(a.inner_text('#account-title') == '친구', '창 제목이 친구', a.inner_text('#account-title'))
        a.fill('#friend-search-input', '@' + names['d'])
        a.click('#friend-search-btn')
        a.wait_for_selector('#friend-results .friend-item', timeout=8000)
        a.wait_for_timeout(300)
        result_text = a.inner_text('#friend-results .friend-item')
        check('@' + names['d'] in result_text and names['d'] in result_text,
              '검색 결과에 닉네임·@아이디', result_text.replace('\n', ' ')[:120])
        shot(a, 'local-desktop-friends-search')
        a.click('#friend-results .friend-btn.primary')
        a.wait_for_timeout(1200)
        check('친구 요청을 보냈어요' in a.inner_text('.toast'), '요청 보냄 안내', a.inner_text('.toast'))

        # B 화면: 새로 열면 계정 버튼에 빨간 점(받은 요청)은 없고(A와 친구 끊김), D 는 받음
        ctx_d, d = open_page(names['d'], app=True)
        d.wait_for_selector('#account-badge:not([hidden])', timeout=12000)
        check(d.is_visible('#account-badge'), '받은 요청이 있으면 계정 버튼에 빨간 점')
        check('받은 친구 요청' in (d.get_attribute('#btn-account', 'aria-label') or ''),
              '계정 버튼 이름에 요청 수', d.get_attribute('#btn-account', 'aria-label') or '')
        shot(d, 'local-desktop-account-badge')
        open_account(d)
        check(d.is_visible('#account-friend-dot'), '친구 버튼에도 빨간 점')
        account_tab(d, 'friends')
        check(d.is_visible('#friend-dot-incoming'), '받은 요청 탭에 빨간 점')
        check(d.get_attribute('#friend-tabs [data-friend-tab="incoming"]', 'aria-selected') == 'true',
              '받은 요청 탭부터')
        item_text = d.inner_text('#friend-list .friend-item')
        check('잇다 친구' in item_text, '받은 요청에 A 닉네임', item_text.replace('\n', ' ')[:120])
        shot(d, 'local-desktop-friends-incoming')
        d.click('#friend-list .friend-btn.primary')
        d.wait_for_timeout(1200)
        check('친구가 됐어요' in d.inner_text('.toast'), '수락 안내', d.inner_text('.toast'))
        check(not d.is_visible('#account-badge'), '수락하면 빨간 점 사라짐')
        friend_tab(d, 'friends')
        check(d.locator('#friend-list .friend-item').count() == 1, '친구 탭에 1명',
              str(d.locator('#friend-list .friend-item').count()))
        check('@' + names['a'] in d.inner_text('#friend-list'), '친구 목록에 @아이디')
        shot(d, 'local-desktop-friends-list')

        # 친구 목록 → 메일 보내기
        d.click('#friend-list .friend-btn.ghost:not(.danger)')
        d.wait_for_selector('#ov-mail:not([hidden])', timeout=8000)
        d.wait_for_selector('#mail-view-compose:not([hidden])', timeout=8000)
        d.wait_for_timeout(400)
        check(d.input_value('#mail-to') == '@' + names['a'], '메일 받는 사람에 @아이디 자동 입력',
              d.input_value('#mail-to'))
        check(d.is_hidden('#ov-account'), '메일을 쓰면 계정 창은 닫힘')
        shot(d, 'local-desktop-friend-compose')
        d.fill('#mail-subject', '친구 메일')
        d.fill('#mail-content', '친구 목록에서 바로 보냈어요.')
        d.click('#mail-compose-submit')
        d.wait_for_timeout(1400)
        check('메일을 보냈어요' in d.inner_text('.toast'), '친구에게 메일 발송', d.inner_text('.toast'))
        d.click('#btn-mail-close')
        d.wait_for_timeout(300)

        # A 받은 메일함: 닉네임 + @아이디
        res = api(a, '/api/mail/inbox')
        mail = (res['data'] or {}).get('mails') or []
        check(len(mail) == 1 and mail[0]['senderUsername'] == names['d'],
              'A 받은 메일 1통', json.dumps(mail, ensure_ascii=False)[:200])
        check(mail and mail[0].get('senderNickname') == '', '닉네임이 없으면 빈값', json.dumps(mail[:1], ensure_ascii=False)[:160])
        close_account(a)
        a.click('#btn-mail')
        a.wait_for_selector('#ov-mail:not([hidden])', timeout=8000)
        a.wait_for_timeout(700)
        inbox_text = a.inner_text('#mail-list')
        check('@' + names['d'] in inbox_text, '메일함 목록에 @아이디', inbox_text.replace('\n', ' ')[:140])

        # 닉네임을 정한 사람의 메일은 닉네임과 @아이디가 함께
        api(d, '/api/account/profile', 'POST', {'nickname': '메일친구'})
        api(a, '/api/mail/inbox')
        a.click('#btn-mail-close')
        a.wait_for_timeout(300)
        a.click('#btn-mail')
        a.wait_for_selector('#ov-mail:not([hidden])', timeout=8000)
        a.wait_for_timeout(800)
        inbox_text = a.inner_text('#mail-list')
        check('메일친구' in inbox_text and '@' + names['d'] in inbox_text,
              '메일함에 닉네임 + @아이디', inbox_text.replace('\n', ' ')[:160])
        a.click('#mail-list .mail-open')
        a.wait_for_selector('#mail-view-detail:not([hidden])', timeout=8000)
        meta = a.inner_text('#mail-detail-meta')
        check('메일친구' in meta and '@' + names['d'] in meta, '메일 상세 보낸 사람에 닉네임 + @아이디', meta)
        shot(a, 'local-desktop-mail-nickname')
        a.click('#btn-mail-close')
        a.wait_for_timeout(300)

        # 친구 삭제 2단계 (A 의 친구 중 C 를 먼저 정리해 한 명만 남긴다)
        api(a, '/api/friends/remove', 'POST', {'username': names['c']})
        open_account(a)
        account_tab(a, 'friends')
        friend_tab(a, 'friends')
        a.wait_for_timeout(800)
        check(a.locator('#friend-list .friend-item').count() == 1, 'A 친구 1명', str(a.locator('#friend-list .friend-item').count()))
        a.click('#friend-list .friend-btn.danger')
        a.wait_for_timeout(250)
        check('정말 삭제?' in a.inner_text('#friend-list .friend-btn.danger'), '친구 삭제는 한 번 더 확인',
              a.inner_text('#friend-list .friend-btn.danger'))
        shot(a, 'local-desktop-friends-delete-armed')
        a.click('#friend-list .friend-btn.danger')
        a.wait_for_timeout(1200)
        check('친구를 끊었어요' in a.inner_text('.toast'), '친구 삭제 완료', a.inner_text('.toast'))
        check(a.locator('#friend-list .friend-item').count() == 0, '친구 목록이 빔')

        # XSS: 닉네임에 태그를 넣어도 글자로만 보인다
        res = api(a, '/api/account/profile', 'POST', {'nickname': '<b>해커</b>'})
        check(res['status'] == 200 and res['data']['user']['nickname'] == '<b>해커</b>',
              '태그가 든 닉네임도 저장', json.dumps(res['data'], ensure_ascii=False)[:160])
        a.evaluate("() => window.__ITDA.app.accountPanel.refreshUser({ force: true })")
        a.wait_for_timeout(900)
        xss = a.evaluate("""() => {
            const box = document.getElementById('account-name');
            return {text: box.textContent, tags: box.querySelectorAll('*').length};
        }""")
        check(xss['text'] == '<b>해커</b>' and xss['tags'] == 0, '닉네임은 글자로만 렌더링',
              json.dumps(xss, ensure_ascii=False))
        res = api(a, '/api/account/profile', 'POST', {'nickname': '잇다 친구'})

        # ── 7. 계정 삭제 정리 ─────────────────────────────────────────
        print('\n· 계정 삭제 정리')
        drop(ctx_d)
        res = api(a, '/api/friends/request', 'POST', {'username': names['e']})
        check(res['status'] == 200, 'E 에게 요청')
        ctx_e, e = open_page(names['e'])
        api(e, '/api/friends/request', 'POST', {'username': names['a']})
        res = api(e, '/api/auth/delete', 'POST', {'password': PASSWORD})
        check(res['status'] == 200, 'E 계정 삭제', json.dumps(res['data'], ensure_ascii=False)[:160])
        left = d1_value("SELECT COUNT(*) FROM friendships WHERE requester_id IN "
                        f"(SELECT id FROM users WHERE username = '{names['e']}') OR addressee_id IN "
                        f"(SELECT id FROM users WHERE username = '{names['e']}')")
        check(int(left or 0) == 0, '삭제한 계정의 친구 행 정리', str(left))
        drop(ctx_e)

        # ── 8. 좁은 화면 ──────────────────────────────────────────────
        # 좁은 화면에서도 친구 한 줄(사진·이름·버튼)이 넘치지 않는지 보려고 친구를 하나 만든다.
        ctx_c2, c2 = open_page(names['c'])
        res = api(a, '/api/friends/request', 'POST', {'username': names['c']})
        check(res['status'] == 200, '좁은 화면 점검용 친구 요청', json.dumps(res['data'], ensure_ascii=False)[:120])
        res = api(c2, '/api/friends/respond', 'POST', {'userId': user['id'], 'action': 'accept'})
        check(res['status'] == 200, '좁은 화면 점검용 친구 수락')
        drop(ctx_c2)
        a.click('#btn-account-close')
        a.wait_for_timeout(300)
        a.set_viewport_size({'width': 390, 'height': 844})
        a.wait_for_timeout(300)
        open_account(a)
        account_tab(a, 'friends')
        friend_tab(a, 'friends')
        a.wait_for_timeout(800)
        check(a.locator('#friend-list .friend-item').count() == 1, '좁은 화면 점검용 친구 1명',
              str(a.locator('#friend-list .friend-item').count()))

        print('\n· 화면 크기 320 · 360 · 390')
        for width, height, tag in [(320, 640, '320'), (360, 640, '360'), (390, 844, '390')]:
            a.set_viewport_size({'width': width, 'height': height})
            a.wait_for_timeout(400)
            if a.is_hidden('#ov-account'):
                open_account(a)
            account_tab(a, 'friends')
            friend_tab(a, 'friends')
            a.wait_for_timeout(400)
            metrics = a.evaluate("""() => {
                const sheet = document.querySelector('#ov-account .sheet');
                const item = document.querySelector('#friend-list .friend-item');
                const btn = document.getElementById('btn-friends-open');
                return {
                  sheetOver: sheet.scrollWidth - sheet.clientWidth,
                  listOver: item ? item.scrollWidth - item.clientWidth : 0,
                  fits: sheet.getBoundingClientRect().right <= innerWidth + 1
                        && sheet.getBoundingClientRect().bottom <= innerHeight + 1,
                  btn: btn.getBoundingClientRect().width,
                };
            }""")
            check(metrics['sheetOver'] <= 1 and metrics['listOver'] <= 1 and metrics['fits'],
                  f'{tag}px 계정·친구 창이 넘치지 않음', json.dumps(metrics))
            shot(a, f'local-mobile-{tag}-friends')

        # ── 9. 정리 ───────────────────────────────────────────────────
        print('\n· 정리')
        quoted = ','.join("'%s'" % name for name in created)
        statements = [
            f'DELETE FROM friendships WHERE requester_id IN (SELECT id FROM users WHERE username IN ({quoted}))'
            f' OR addressee_id IN (SELECT id FROM users WHERE username IN ({quoted}))',
            f'DELETE FROM mails WHERE sender_id IN (SELECT id FROM users WHERE username IN ({quoted}))'
            f' OR recipient_id IN (SELECT id FROM users WHERE username IN ({quoted}))',
            f'DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username IN ({quoted}))',
            f'DELETE FROM users WHERE username IN ({quoted})',
            "DELETE FROM auth_throttle",
        ]
        try:
            d1(';\n'.join(statements))
        except Exception:
            for statement in statements:
                try:
                    d1(statement)
                except Exception:
                    pass
        remaining = d1_value(f"SELECT COUNT(*) FROM users WHERE username IN ({quoted})")
        check(int(remaining or 0) == 0, '점검 데이터 정리', str(remaining))
        try:
            os.remove('/tmp/itda-social-photo.jpg')
        except OSError:
            pass

        drop(ctx_a)
        drop(ctx_b)
        drop(ctx_c)
        drop(ctx_d)
        browser.close()

    print(f'\n결과: {PASS} 통과 · {FAIL} 실패')
    print('스크린샷:', json.dumps(SHOTS, ensure_ascii=False, indent=1))
    return 0 if FAIL == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--local', action='store_true', default=True)
    ap.add_argument('--shots-dir', default=None)
    ap.add_argument('--headed', action='store_true')
    args = ap.parse_args()
    global SHOT_DIR
    if args.shots_dir:
        SHOT_DIR = args.shots_dir

    made_config = ensure_local_config()
    d1_file(os.path.join('db', 'schema.sql'))
    apply_migrations()
    proc = start_local()
    try:
        code = run(headless=not args.headed)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        if made_config:
            try:
                os.remove(os.path.join(ROOT, 'wrangler.toml'))
            except OSError:
                pass
    sys.exit(code)


if __name__ == '__main__':
    main()
