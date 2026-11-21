#!/usr/bin/env python3
"""끄코 유틸리티 오픈DB(공개 오픈API)에서 최신 한국어 단어 목록을 모은다.

`https://kkuko-utils.vercel.app/api/words/search` 는 로그인 없이 공개된 오픈API다.
`mode=kor-start&q=<음절>&limit=-1` 로 해당 음절로 시작하는 단어를 제한 없이 받는다.
(`manner=x` 로 매너/전어/에티켓 필터를 모두 끄고, `duem=false` 로 두음 확장을 끈다.)
API는 끄코에서 끝말잇기 사용 가능(k_canuse) 단어만 돌려준다.

진행 상황은 build/kkuko-raw.jsonl 에 음절 단위로 남고, 중단했다 다시 실행하면
이미 받은 음절은 건너뛴다.
출력: build/kkuko-words.txt  (한 줄에 단어 하나, 코드 포인트 순, 중복 제거)

사용:
    python3 build/collect_kkuko.py                 # 전체 음절 수집
    python3 build/collect_kkuko.py --limit 240     # 앞 240음절만 (시험)
    python3 build/collect_kkuko.py --concurrency 6
"""
import argparse
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = 'https://kkuko-utils.vercel.app'
CHROME = os.environ.get('HB_CHROME', '/workspace/.local/pw/chromium-1255/chrome-linux64/chrome')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'build', 'kkuko-raw.jsonl')
OUT = os.path.join(ROOT, 'build', 'kkuko-words.txt')

FIRST, LAST = 0xAC00, 0xD7A3          # 가 … 힣
BATCH = 240                           # evaluate 한 번에 처리할 음절 수
PAGE_JS = """
async ({chars, base, concurrency, minLength, maxLength}) => {
  const queue = chars.slice();
  const out = [];
  const worker = async () => {
    for (;;) {
      const ch = queue.shift();
      if (!ch) return;
      const url = `${base}/api/words/search?mode=kor-start&q=${encodeURIComponent(ch)}`
        + `&limit=-1&sortBy=abc&manner=x&duem=false&minLength=${minLength}&maxLength=${maxLength}`;
      for (let attempt = 0; attempt < 5; attempt += 1) {
        try {
          const res = await fetch(url);
          const text = await res.text();
          if (res.ok) {
            const rows = JSON.parse(text);
            out.push({ ch, words: rows.map((r) => r.word) });
            break;
          }
          if (attempt === 4) out.push({ ch, error: res.status });
        } catch (e) {
          if (attempt === 4) out.push({ ch, error: String(e) });
        }
        await new Promise((r) => setTimeout(r, 1200 * (attempt + 1)));
      }
    }
  };
  await Promise.all(Array.from({ length: concurrency }, worker));
  return out;
}
"""


def load_done():
    done = set()
    words = set()
    if not os.path.exists(RAW):
        return done, words
    with open(RAW, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if 'words' in item:
                done.add(item['ch'])
                words.update(item['words'])
    return done, words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--concurrency', type=int, default=4)
    args = ap.parse_args()

    chars = [chr(c) for c in range(FIRST, LAST + 1)]
    done, seen = load_done()
    chars = [ch for ch in chars if ch not in done]
    if args.limit:
        chars = chars[:args.limit]

    errors = []
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled'],
        )
        ctx = browser.new_context(
            locale='ko-KR',
            user_agent=('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'),
            viewport={'width': 1280, 'height': 800},
        )
        page = ctx.new_page()
        page.goto(f'{BASE}/word', wait_until='domcontentloaded', timeout=60000)
        if 'Checkpoint' in page.title():
            time.sleep(5)

        for i in range(0, len(chars), BATCH):
            chunk = chars[i:i + BATCH]
            result = page.evaluate(PAGE_JS, {
                'chars': chunk, 'base': BASE,
                'concurrency': args.concurrency,
                'minLength': 2, 'maxLength': 100,
            })
            with open(RAW, 'a', encoding='utf-8') as f:
                for item in result:
                    if 'error' in item:
                        errors.append(item)
                        continue
                    f.write(json.dumps(item, ensure_ascii=False) + '\n')
                    seen.update(item['words'])
                    done.add(item['ch'])
            print('%5d/%d  done=%d  words=%d  errors=%d  %.1fs' % (
                min(i + BATCH, len(chars)), len(chars), len(done), len(seen),
                len(errors), time.time() - t0), flush=True)
            time.sleep(0.4)

        browser.close()

    words = sorted(seen)
    with open(OUT, 'w', encoding='utf-8') as f:
        for w in words:
            f.write(w + '\n')

    print('syllables done     :', len(done))
    print('errors             :', len(errors), errors[:5])
    print('unique words       :', len(words))
    print('output             :', OUT, '%.1f KB' % (os.path.getsize(OUT) / 1024.0))
    if errors:
        sys.exit(1)


if __name__ == '__main__':
    main()
