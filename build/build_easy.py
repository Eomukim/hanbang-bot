#!/usr/bin/env python3
"""일상 어휘(쉬운 단어) 목록을 만든다.

Lv.1(쉬움)·Lv.2(보통) 봇이 낯선 방언·옛말·어인정·신조어 대신 일상적으로 자주 쓰는
표준어를 고르게 하려면, "이 단어가 일상어인가"를 판정할 근거가 필요하다. 이 스크립트는
공개된 한국어 교육용 어휘 목록에서 2~4글자 표제어를 뽑아 `build/easy_words.txt` 로 저장한다.

원본
  1. 국립국어원 『한국어 학습용 어휘 목록』(2003) — 1단계 A 982 · 2단계 B 2,111 · 3단계 C 2,872
     https://www.korean.go.kr/front/etcData/etcDataView.do?etc_seq=71
  2. TOPIK 『어휘 목록 공개 목록』(2015) — 초급 / 중급
     https://www.topik.go.kr
  두 목록을 표제어·품사·등급으로 합쳐 둔 공개 정리본(julienshim/combined_korean_vocabulary_list,
  MIT)의 `results.tsv` 를 읽는다. 원본 목록의 권리는 국립국어원·TOPIK 에 있다(출처는 NOTICE.md).

출력
  build/easy_words.txt   한 줄에 "단어<TAB>단계(1|2|3)"
    1 = A단계/TOPIK 초급, 2 = B단계/TOPIK 중급, 3 = C단계
  동음이의어 번호(가구03), 접사 표시(-가13)는 떼고, 같은 단어는 가장 쉬운 단계로 한 번만 적는다.

usage:
    python3 build/build_easy.py                 # 원격 results.tsv 를 받아 다시 만든다
    python3 build/build_easy.py --source x.tsv  # 내려받아 둔 파일로 만든다
"""
import argparse
import datetime
import os
import re
import sys
import urllib.request

SOURCE_URL = 'https://raw.githubusercontent.com/julienshim/combined_korean_vocabulary_list/master/results.tsv'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, 'build', 'easy_words.txt')
CACHE_PATH = os.path.join(ROOT, 'build', 'cache', 'results.tsv')

NIKL_TIER = {'A': 1, 'B': 2, 'C': 3}
TOPIK_TIER = {'초급': 1, '중급': 2}

HANGUL = re.compile(r'^[가-힣]{2,4}$')
TRAILING_NUMBER = re.compile(r'\d+$')


def read_source(path):
    if not path:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        if not os.path.exists(CACHE_PATH):
            print('download :', SOURCE_URL)
            with urllib.request.urlopen(SOURCE_URL, timeout=60) as res:
                open(CACHE_PATH, 'wb').write(res.read())
        path = CACHE_PATH
    return open(path, encoding='utf-8').read().replace('\r\n', '\n')


def parse(text):
    """results.tsv → {단어: 단계} (가장 쉬운 단계로 합친다)."""
    lines = text.split('\n')
    head = lines[0].split('\t')
    idx = {name: i for i, name in enumerate(head)}
    tiers = {}
    rows = 0
    skipped = 0
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split('\t')
        if len(fields) < len(head):
            fields += [''] * (len(head) - len(fields))
        rows += 1
        raw = fields[idx['word']].strip()
        if raw.startswith('-') or raw.endswith('-'):
            skipped += 1                      # 접사(‘-가13’)는 게임 단어가 아니다
            continue
        word = TRAILING_NUMBER.sub('', raw)
        if not HANGUL.match(word):
            skipped += 1
            continue
        found = []
        nikl = fields[idx.get('nikl_level', -1)] if 'nikl_level' in idx else ''
        topik = fields[idx.get('topik_level', -1)] if 'topik_level' in idx else ''
        if nikl in NIKL_TIER:
            found.append(NIKL_TIER[nikl])
        if topik in TOPIK_TIER:
            found.append(TOPIK_TIER[topik])
        if not found:
            skipped += 1
            continue
        tier = min(found)
        if word not in tiers or tier < tiers[word]:
            tiers[word] = tier
    return tiers, rows, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default=None, help='results.tsv 경로(없으면 원격에서 받아 캐시)')
    ap.add_argument('--out', default=OUT_PATH)
    args = ap.parse_args()

    tiers, rows, skipped = parse(read_source(args.source))
    counts = {}
    for tier in tiers.values():
        counts[tier] = counts.get(tier, 0) + 1

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('# 국립국어원 한국어 학습용 어휘 목록(A·B·C) + TOPIK 어휘 목록(초급·중급) 기반 일상 어휘\n')
        f.write('# 형식: 단어<TAB>단계(1=A/초급, 2=B/중급, 3=C) — 출처는 NOTICE.md\n')
        f.write('# generated %s — build/build_easy.py\n'
                % datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
        for word in sorted(tiers, key=lambda w: (tiers[w], w)):
            f.write('%s\t%d\n' % (word, tiers[word]))

    print('rows      :', rows, '(skipped %d)' % skipped)
    print('words     :', len(tiers), '1단계', counts.get(1, 0), '/ 2단계', counts.get(2, 0), '/ 3단계', counts.get(3, 0))
    print('written   :', args.out, '%d bytes' % os.path.getsize(args.out))


if __name__ == '__main__':
    sys.exit(main())
