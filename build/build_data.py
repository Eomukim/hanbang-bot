#!/usr/bin/env python3
"""Build the ITDA word data from the Kkuko Utils open DB.

Usage:
    python3 build/build_data.py                    # build/kkuko-words.txt 로 새로 빌드
    python3 build/build_data.py path/to/words.txt  # 다른 목록으로 빌드
    python3 build/build_data.py --easy-only        # easy_words.txt만 바뀌었을 때 stats.json의 easy만 갱신

사전의 원천은 끄코 유틸리티 오픈DB 목록(`build/collect_kkuko.py` 가 모으는
`build/kkuko-words.txt`, CC BY-NC-SA 4.0, 출처 표기는 NOTICE.md) 하나다.
예전에 쓰던 KKuTu `db.sql` 덤프는 더 이상 읽지 않는다(2026-11 지시).

이 목록에는 동사·형용사의 사전형과 활용형, 문장형 표제어가 섮여 있다
(`가다`, `가로질러간다`, `가만히사랑을바라보다` …). 끝말잇기에서 이어 쓰는 것은
명사이므로, 형태소 분석기(kiwipiepy)로 품사를 보고 용언·서술형을 걷어낸다.
`endswith('다')` 로 지우면 `바다`·`사이다`·`판다`·`캐나다`·`아나콘다`·`파고다`
같은 진짜 명사까지 날아가므로, 형태소 태그로 판정하고 명사 예외 목록을 둔다.

Out of ./data:
    words.txt   one word per line: "word" or "word<TAB>flag" when flag != 0.
                Sorted by code point, so every starting syllable occupies one
                contiguous range (the browser derives the start index from this).
    stats.json  precomputed per-syllable successor counts (nextCount), plus
                one-shot / induced word lists and source metadata.
                It also carries the syllable duel graph (graph): for every
                syllable the win/lose status and depth of the perfect-play
                retrograde analysis, and the one-shot words that start there.
                The Lv.5 bot reads it at runtime.
                And the everyday-word bands (easy): 1~3 = 국립국어원 학습용
                어휘 A/B/C 단계 표준어, 5~7 = 같은 목록의 외래어. Lv.1·Lv.2 가
                낯선 방언·옛말·어인정 대신 일상 단어를 고를 때 쓴다.
                (목록 원본은 build/easy_words.txt, 만드는 법은 build/build_easy.py)

`build/nonwords.txt` 에는 이번 빌드에서 걷어낸 용언·서술형과 그 형태소 분석을
남긴다(무엇이 왜 빠졌는지 눈으로 확인할 수 있게).
"""
import argparse
import json
import os
import re
import sys
import time
import datetime
from collections import deque

HANGUL = re.compile(r"^[가-힣]+$")

# 원본 데이터의 KOR_FLAG 비트 (지금 원천에는 flag 가 없다 — 호환용으로만 남긴다)
FLAG_LOANWORD = 1
FLAG_RECOGNIZED = 2
FLAG_SPACED = 4
FLAG_SATURI = 8
FLAG_OLD = 16
FLAG_MUNHWA = 32

MIN_LEN = 2

# 브랜드 이름과 겹치는 표제어는 사전에서 뺀다 (게임 화면에 옛 이름이 뜨지 않도록).
BLOCKED_WORDS = {"끄투"}

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
KKUKO_PATH = os.path.join(BUILD_DIR, "kkuko-words.txt")
NONWORDS_PATH = os.path.join(BUILD_DIR, "nonwords.txt")

# 일상 어휘 목록(build/build_easy.py 가 만드는 파일). 없으면 easy 정보 없이 빌드한다.
EASY_PATH = os.path.join(BUILD_DIR, "easy_words.txt")
# 이 비트가 붙은 표제어는 일상어로 치지 않는다: 어인정 2 · 방언 8 · 옛말 16 · 문화어 32
EASY_EXCLUDE = FLAG_RECOGNIZED | FLAG_SATURI | FLAG_OLD | FLAG_MUNHWA
# 외래어(flag 1) 일상어는 단계에 4를 더해 뒤 순위로 둔다 (예: 컴퓨터·커피)
EASY_LOANWORD_SHIFT = 4

# ── 용언·서술형 필터 ────────────────────────────────────────
# 형태소 태그(kiwipiepy)로 판정한다. '-' 뒤 접미사(VV-I 등)는 떼고 본다.
PREDICATE_TAGS = {"VV", "VA", "VX", "XSV", "XSA", "VCP", "VCN"}   # 용언·서술격
ENDING_TAGS = {"EF", "EC", "EP", "ETM", "ETN"}                    # 어미
NOUN_TAGS = {"NNG", "NNP", "NNB", "NNBC", "NNM", "NR", "NP", "UN", "SL", "SN"}
# 명사 예외: 형태소 분석이 용언으로 읽어도 끝말잇기에서는 명사로 쓰는 말.
# (사용자 확인 목록 + 표준국어대사전에 명사로 올라 있는 -다 표제어)
NOUN_KEEP = {
    "바다", "사이다", "판다", "캐나다", "우간다", "아나콘다", "가나다", "가루다", "파고다",
    "큰판다", "수다", "소다", "과다", "카렌다", "골고다", "날란다", "네비다", "아난다",
    "아만다", "벨린다", "미린다", "보만다", "로톤다", "샤로다", "클로다", "카우다",
    "아레다", "페레다", "엘레다", "브리다", "스피다", "누아다", "부란다", "우란다",
    "타게다", "아일다", "이베다", "사비다", "자모다", "다후다", "히시다", "루코다",
}
PREDICATE_SAMPLE = ["가다", "가끔가다", "가로질러간다", "가만히사랑을바라보다", "먹는다", "예쁘다"]
NOUN_SAMPLE = ["바다", "사이다", "판다", "캐나다", "우간다", "아나콘다", "가나다", "가루다", "파고다"]


def morpheme_tags(kiwi, word):
    """형태소 태그 집합('-I' 같은 접미사는 뗀다)."""
    return {t.tag.split("-")[0] for t in kiwi.tokenize(word)}


def is_predicate(kiwi, word):
    """동사·형용사·서술형 표제어인가.

    끝말잇기는 명사만 잇는 게임이라 용언(사전형 -다)·활용형·문장형(~니다·~겠다·
    ~한다)은 사전에서 뺀다. 다만 `바다`·`판다`처럼 진짜 명사는 남긴다.
     - -다 로 끝나지 않으면(용언의 사전형·활용형은 모두 -다) 손대지 않는다.
     - 명사 예외 목록에 있으면 남긴다.
     - 마지막 형태소가 명사면 남긴다(`먼바다`·`옛수다` 같은 명사 합성어).
     - 형태소에 용언·서술격 또는 어미가 있으면 용언/문장형으로 본다.
    """
    if not word.endswith("다"):
        return False
    if word in NOUN_KEEP:
        return False
    tokens = kiwi.tokenize(word)
    if not tokens:
        return False
    if tokens[-1].tag.split("-")[0] in NOUN_TAGS:
        return False
    tags = {t.tag.split("-")[0] for t in tokens}
    return bool(tags & (PREDICATE_TAGS | ENDING_TAGS))

# Hangul syllable arithmetic
HANGUL_BASE = 0xAC00
CHOSEONG = 19
JUNGSEONG = 21
JONGSEONG = 28
RIEUL = 5
NIEUN = 2
IEUNG = 11
# 중성 순서: ㅏ0 ㅐ1 ㅑ2 ㅒ3 ㅓ4 ㅔ5 ㅕ6 ㅖ7 ㅗ8 ㅘ9 ㅙ10 ㅚ11
#             ㅛ12 ㅜ13 ㅝ14 ㅞ15 ㅟ16 ㅠ17 ㅡ18 ㅢ19 ㅣ20
# ㄹ·ㄴ 뒤에서 ㅇ으로 바뀌는 모음
I_VOWELS = {2, 3, 6, 7, 12, 17, 20}


def twoeum(ch):
    """Standard Korean initial-sound rule applied to a syllable."""
    k = ord(ch) - HANGUL_BASE
    if k < 0 or k >= CHOSEONG * JUNGSEONG * JONGSEONG:
        return None
    cho, jung, jong = k // (JUNGSEONG * JONGSEONG), (k % (JUNGSEONG * JONGSEONG)) // JONGSEONG, k % JONGSEONG
    if cho == RIEUL:
        new = IEUNG if jung in I_VOWELS else NIEUN
        return chr(HANGUL_BASE + (new * JUNGSEONG + jung) * JONGSEONG + jong)
    if cho == NIEUN and jung in I_VOWELS:
        return chr(HANGUL_BASE + (IEUNG * JUNGSEONG + jung) * JONGSEONG + jong)
    return None


def allowed_starts(ch):
    """이 음절로 단어를 시작할 때 인정되는 시작 글자(원래 글자 + 두음 변환 글자)."""
    alt = twoeum(ch)
    return [ch, alt] if alt and alt != ch else [ch]


def duel_nodes(ch):
    """ch 로 시작하는 단어를 낼 수 있는 '이어야 할 글자' 노드들.

    엔진은 이어야 할 글자 X 에 대해 allowed_starts(X) 로 시작하는 단어를 인정한다.
    그래서 단어의 첫 글자 c 는 X = c 뿐 아니라, 두음법칙 결과가 c 가 되는 X 에서도
    낼 수 있다(예: '이'로 시작하는 단어는 '이'·'리'·'니' 에서 모두 낼 수 있다).
    """
    out = {ch}
    k = ord(ch) - HANGUL_BASE
    if k < 0 or k >= CHOSEONG * JUNGSEONG * JONGSEONG:
        return out
    cho, jung, jong = k // (JUNGSEONG * JONGSEONG), (k % (JUNGSEONG * JONGSEONG)) // JONGSEONG, k % JONGSEONG
    if cho == IEUNG and jung in I_VOWELS:
        # ㅇ + ㅑㅒㅕㅖㅛㅠㅣ 는 ㄹ·ㄴ 에서 두음 변환된 결과일 수 있다
        out.add(chr(HANGUL_BASE + (RIEUL * JUNGSEONG + jung) * JONGSEONG + jong))
        out.add(chr(HANGUL_BASE + (NIEUN * JUNGSEONG + jung) * JONGSEONG + jong))
    elif cho == NIEUN and jung not in I_VOWELS:
        # ㄴ + 그 밖의 모음 은 ㄹ 에서 두음 변환된 결과 (리을+ㅣ 는 ㅇ 으로 가므로 제외)
        out.add(chr(HANGUL_BASE + (RIEUL * JUNGSEONG + jung) * JONGSEONG + jong))
    return out


def build_graph(ordered, starts):
    """음절 대전 그래프의 완전 정보(승/패/무)를 역방향 분석으로 계산한다.

    노드 = 이어야 할 글자. 간선 = 그 글자로 시작하는 단어 하나(끝 글자로 이동).
      - 후속 단어가 없는 글자 = 지는 자리(패배 노드, depth 0)
      - 지는 자리로 보낼 수 있는 글자 = 이기는 자리(승리 노드)
      - 모든 수가 이기는 자리로만 이어지면 지는 자리
      - 위 두 규칙으로 확정되지 않는 노드(순환)는 무승부
    """
    twoeum_cache = {}

    def two(ch):
        if ch not in twoeum_cache:
            twoeum_cache[ch] = twoeum(ch)
        return twoeum_cache[ch]

    def group_count(ch):
        n = starts.get(ch, 0)
        alt = two(ch)
        if alt:
            n += starts.get(alt, 0)
        return n

    nodes = set(starts)
    for w in ordered:
        nodes.add(w[-1])
    for ch in list(nodes):
        nodes.update(duel_nodes(ch))

    pred = {ch: [] for ch in nodes}
    for w in ordered:
        end = w[-1]
        for start in duel_nodes(w[0]):
            pred[end].append(start)

    outdeg = {ch: group_count(ch) for ch in nodes}
    status = {}   # 'W' | 'L' (없으면 무승부)
    depth = {}
    remaining = dict(outdeg)
    longest_child = {ch: 0 for ch in nodes}
    queue = deque()

    for ch in nodes:
        if outdeg[ch] == 0:
            status[ch] = 'L'
            depth[ch] = 0
            queue.append(ch)

    while queue:
        node = queue.popleft()
        if status[node] == 'L':
            for prev in pred[node]:
                if prev in status:
                    continue
                status[prev] = 'W'
                depth[prev] = depth[node] + 1
                queue.append(prev)
        else:
            for prev in pred[node]:
                if prev in status:
                    continue
                remaining[prev] -= 1
                if depth[node] + 1 > longest_child[prev]:
                    longest_child[prev] = depth[node] + 1
                if remaining[prev] == 0:
                    status[prev] = 'L'
                    depth[prev] = longest_child[prev]
                    queue.append(prev)

    wins = {ch: depth[ch] for ch in nodes if status.get(ch) == 'W'}
    loses = {ch: depth[ch] for ch in nodes if status.get(ch) == 'L'}

    # 한방 단어: 후속 단어가 없는 글자로 끝나는 단어. 그 단어가 시작되는 글자마다 모아 둔다.
    shots = {}
    one_shots = [w for w in ordered if group_count(w[-1]) == 0]
    for w in sorted(one_shots, key=lambda x: (-len(x), x)):
        for start in duel_nodes(w[0]):
            shots.setdefault(start, []).append(w)

    return {
        'version': 1,
        'nodes': len(nodes),
        'statusCounts': {'win': len(wins), 'lose': len(loses), 'draw': len(nodes) - len(wins) - len(loses)},
        'maxWinDepth': max(wins.values()) if wins else 0,
        'maxLoseDepth': max(loses.values()) if loses else 0,
        'win': dict(sorted(wins.items())),
        'lose': dict(sorted(loses.items())),
        'shots': dict(sorted(shots.items())),
    }


def read_easy(path):
    """일상 어휘 목록: 한 줄에 '단어<TAB>단계'. '#' 로 시작하는 줄은 설명이다."""
    rows = {}
    if not os.path.exists(path):
        print("easy list    : (없음) %s" % path)
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line or line.startswith("#"):
                continue
            word, _, tier = line.partition("\t")
            try:
                tier = int(tier or 0)
            except ValueError:
                continue
            if word and tier:
                rows[word] = tier
    print("easy list    :", len(rows), "words from", path)
    return rows


def easy_bands(words, easy):
    """사전에 실제로 남은 단어만 골라 단계별로 묶는다.

    방언·옛말·문화어·어인정 표제어는 뺀다(일상어 판정과 원본 flag 가 어긋나는 경우).
    표준어는 적힌 단계 그대로, 외래어는 +4 단계로 뒤에 둔다.
    """
    bands = {}
    dropped = 0
    for word, tier in easy.items():
        flag = words.get(word)
        if flag is None:
            continue
        if flag & EASY_EXCLUDE:
            dropped += 1
            continue
        band = tier + (EASY_LOANWORD_SHIFT if flag & FLAG_LOANWORD else 0)
        bands.setdefault(band, []).append(word)
    for band in bands:
        bands[band].sort()
    return bands, dropped


def read_wordlist(path):
    """단어 목록(한 줄에 단어 하나, 뒤에 탭+flag가 붙어도 읽는다) → {단어: flag}."""
    rows = 0
    words = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line:
                continue
            rows += 1
            word, _, flag = line.partition("\t")
            word = word.strip()
            try:
                flag = int(flag or 0)
            except ValueError:
                flag = 0
            if not HANGUL.match(word) or len(word) < MIN_LEN:
                continue
            if word in BLOCKED_WORDS:
                continue
            words[word] = words.get(word, 0) | flag
    print("word rows     :", rows)
    return words


def filter_predicates(words):
    """용언·서술형 표제어를 걷어낸다(형태소 분석). 걷어낸 목록도 돌려준다."""
    try:
        from kiwipiepy import Kiwi
    except ImportError:
        sys.exit("kiwipiepy 가 필요합니다: python3 -m pip install kiwipiepy\n"
                 "(동사·형용사·활용형을 형태소로 판별해 걷어냅니다)")
    kiwi = Kiwi(num_workers=-1)
    kept = {}
    removed = {}
    for word, flag in words.items():
        if is_predicate(kiwi, word):
            removed[word] = "/".join(f"{t.form}:{t.tag}" for t in kiwi.tokenize(word))
        else:
            kept[word] = flag
    with open(NONWORDS_PATH, "w", encoding="utf-8") as f:
        f.write("# 이번 빌드에서 걷어낸 용언·서술형 표제어 — 단어<TAB>형태소 분석\n")
        for word in sorted(removed):
            f.write("%s\t%s\n" % (word, removed[word]))
    print("filtered      :", len(removed), "용언/서술형 제거 →", NONWORDS_PATH)
    for word in PREDICATE_SAMPLE:
        print("  removed?", word, "->", "제거" if word in removed else ("남음" if word in kept else "없음"))
    for word in NOUN_SAMPLE:
        print("  kept?   ", word, "->", "남음" if word in kept else "없음")
    return kept, removed


def read_words_txt(path):
    """data/words.txt(단어<TAB>flag) → {단어: flag}. 일상 어휘만 다시 계산할 때 쓴다."""
    words = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line:
                continue
            word, _, flag = line.partition("\t")
            try:
                flag = int(flag or 0)
            except ValueError:
                flag = 0
            words[word] = flag
    return words


def rebuild_easy_only():
    """db.sql 원본 없이 data/words.txt + data/stats.json 만으로 `easy` 구간만 다시 계산한다.

    easy_words.txt(일상 어휘 목록)가 바뀌었는데 전체 사전을 다시 만들 필요는 없을 때 쓴다.
    단어 목록·그래프·한방/유도 목록은 그대로 두고 stats.json 의 easy 부분만 갱신한다.
    """
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    words_path = os.path.join(out_dir, "words.txt")
    stats_path = os.path.join(out_dir, "stats.json")
    words = read_words_txt(words_path)
    with open(stats_path, encoding="utf-8") as f:
        stats = json.load(f)
    easy = read_easy(EASY_PATH)
    bands, dropped = easy_bands(words, easy)
    stats["easy"] = {
        "version": 2,
        "source": "국립국어원 한국어 학습용 어휘 목록 + TOPIK 어휘 목록(명사) — 출처 표기는 NOTICE.md",
        "total": sum(len(v) for v in bands.values()),
        "bands": {str(k): " ".join(v) for k, v in sorted(bands.items())},
    }
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, separators=(",", ":"))
    print("words.txt     :", len(words))
    print("easy list     :", len(easy))
    print("easy words    :", stats["easy"]["total"],
          {k: len(v) for k, v in sorted(bands.items())}, "(dropped %d)" % dropped)
    print("stats.json    : %.1f KB" % (os.path.getsize(stats_path) / 1024.0))


def main():
    ap = argparse.ArgumentParser(
        description="끄코 오픈DB 단어 목록으로 잇다 사전(words.txt·stats.json)을 빌드한다.")
    ap.add_argument("source", nargs="?", default=KKUKO_PATH,
                    help="단어 목록(기본: build/kkuko-words.txt)")
    ap.add_argument("--easy-only", action="store_true",
                    help="easy_words.txt만 바뀌었을 때 stats.json의 easy만 다시 계산")
    args = ap.parse_args()

    if args.easy_only:
        rebuild_easy_only()
        return

    out_dir = os.path.join(os.path.dirname(BUILD_DIR), "data")
    os.makedirs(out_dir, exist_ok=True)

    # 원천은 오픈DB 목록 하나뿐이다(옛 db.sql 덤프는 더 이상 읽지 않는다).
    words = read_wordlist(args.source)
    raw_count = len(words)
    words, removed = filter_predicates(words)

    # 원천 목록 표본(검증용): 3~10글자 단어를 고르게 30개
    pool = sorted(w for w in words if 3 <= len(w) <= 10)
    step = max(1, len(pool) // 30)
    source_samples = pool[::step][:30]

    ordered = sorted(words)
    starts = {}
    for w in ordered:
        starts[w[0]] = starts.get(w[0], 0) + 1

    def group_count(ch):
        n = starts.get(ch, 0)
        alt = twoeum(ch)
        if alt:
            n += starts.get(alt, 0)
        return n

    one_shot = [w for w in ordered if group_count(w[-1]) == 0]
    induced = [w for w in ordered if 0 < group_count(w[-1]) <= 5]
    graph = build_graph(ordered, starts)
    # 일상 어휘: 사전에 남은 단어만, 단계별로 공백으로 이어 붙여 저장한다(전송량 절약).
    easy = read_easy(EASY_PATH)
    bands, easy_dropped = easy_bands(words, easy)

    words_path = os.path.join(out_dir, "words.txt")
    with open(words_path, "w", encoding="utf-8") as f:
        for w in ordered:
            flag = words[w]
            f.write(w if not flag else "%s\t%d" % (w, flag))
            f.write("\n")

    flag_counts = {}
    for w in ordered:
        for bit, name in ((FLAG_LOANWORD, "loanword"), (FLAG_RECOGNIZED, "recognized"),
                          (FLAG_SATURI, "saturi"), (FLAG_OLD, "old"), (FLAG_MUNHWA, "munhwa")):
            if words[w] & bit:
                flag_counts[name] = flag_counts.get(name, 0) + 1

    stats = {
        "version": 4,
        "source": "끄코 유틸리티 오픈DB 단어 목록(CC BY-NC-SA 4.0) — 출처 표기는 NOTICE.md",
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rawRows": raw_count,
        "sourceSamples": source_samples,
        "removedPredicates": len(removed),
        "removedSamples": sorted(removed)[:40],
        "total": len(ordered),
        "maxLen": max(len(w) for w in ordered),
        "starts": len(starts),
        "syllables": dict(sorted(starts.items())),
        "oneShotCount": len(one_shot),
        "oneShotSamples": one_shot[:40],
        "inducedCount": len(induced),
        "inducedSamples": induced[:40],
        "flagCounts": flag_counts,
        "easy": {
            "version": 2,
            "source": "국립국어원 한국어 학습용 어휘 목록 + TOPIK 어휘 목록 — 출처 표기는 NOTICE.md",
            "total": sum(len(v) for v in bands.values()),
            "bands": {str(k): " ".join(v) for k, v in sorted(bands.items())},
        },
        "graph": graph,
    }
    with open(os.path.join(out_dir, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(words_path)
    print("source        :", args.source)
    print("word rows     :", raw_count)
    print("removed verbs :", len(removed), sorted(removed)[:8])
    print("valid words   :", len(ordered))
    print("start syll.   :", len(starts))
    print("one-shot words:", len(one_shot), one_shot[:8])
    print("induced words :", len(induced), induced[:8])
    print("easy words    :", sum(len(v) for v in bands.values()),
          {k: len(v) for k, v in sorted(bands.items())}, "(dropped %d)" % easy_dropped)
    print("graph nodes   :", graph['nodes'], graph['statusCounts'],
          "maxDepth", graph['maxWinDepth'], graph['maxLoseDepth'])
    print("words.txt     : %.1f KB" % (size / 1024.0))
    print("stats.json    : %.1f KB" % (os.path.getsize(os.path.join(out_dir, "stats.json")) / 1024.0))


if __name__ == "__main__":
    t0 = time.time()
    main()
    print("done in %.1fs" % (time.time() - t0))
