#!/usr/bin/env python3
"""Build the Hanbang Bot word data from word sources.

Usage:
    python3 build/build_data.py path/to/db.sql [path/to/kkuko-words.txt]

The first source is the KKuTu `db.sql` dump (GPL-3.0); the optional second source
is the Kkuko Utils open DB word list collected with `build/collect_kkuko.py`
(CC BY-NC-SA 4.0, attribution in NOTICE.md). Both are merged, de-duplicated and
re-indexed together.

Outputs (into ./data):
    words.txt   one word per line: "word" or "word<TAB>flag" when flag != 0.
                Sorted by code point, so every starting syllable occupies one
                contiguous range (the browser derives the start index from this).
    stats.json  precomputed per-syllable successor counts (nextCount), plus
                one-shot / induced word lists and source metadata.
"""
import json
import os
import re
import sys
import time
import datetime

HANGUL = re.compile(r"^[가-힣]+$")

# 원본 데이터의 KOR_FLAG 비트 (Server/lib/const.js)
FLAG_LOANWORD = 1
FLAG_RECOGNIZED = 2
FLAG_SPACED = 4
FLAG_SATURI = 8
FLAG_OLD = 16
FLAG_MUNHWA = 32

MIN_LEN = 2

# 브랜드 이름과 겹치는 표제어는 사전에서 뺀다 (게임 화면에 옛 이름이 뜨지 않도록).
BLOCKED_WORDS = {"끄투"}

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


def parse_copy_block(text):
    marker = "COPY kkutu_ko (_id, type, mean, hit, flag, theme) FROM stdin;\n"
    start = text.index(marker) + len(marker)
    end = text.index("\n" + chr(92) + ".\n", start)
    for line in text[start:end].split("\n"):
        fields = line.split("\t")
        if len(fields) < 6:
            continue
        yield fields[0], fields[4], fields[5]


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


def read_open_db(path):
    """오픈DB 단어 목록. 한 줄에 단어 하나, 뒤에 탭+flag가 붙어도 읽는다."""
    rows = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line:
                continue
            rows += 1
            word, _, flag = line.partition("\t")
            try:
                flag = int(flag or 0)
            except ValueError:
                flag = 0
            yield word.strip(), flag
    print("open db rows  :", rows)


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: build_data.py <db.sql> [kkuko-words.txt]")
    src = sys.argv[1]
    open_db = sys.argv[2] if len(sys.argv) > 2 else None
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(out_dir, exist_ok=True)

    text = open(src, encoding="utf-8").read().replace("\r\n", "\n")
    words = {}
    raw = 0
    for word, flag, theme in parse_copy_block(text):
        raw += 1
        if len(word) < MIN_LEN or not HANGUL.match(word):
            continue
        try:
            flag = int(flag or 0)
        except ValueError:
            flag = 0
        if flag & FLAG_SPACED:          # 띄어쓰기가 필요한 어휘는 끝말잇기에 쓸 수 없다
            continue
        if word in BLOCKED_WORDS:
            continue
        if word in words:
            words[word] |= flag
        else:
            words[word] = flag

    base_count = len(words)
    open_rows = 0
    added = 0
    added_words = []
    if open_db:
        for word, flag in read_open_db(open_db):
            open_rows += 1
            if len(word) < MIN_LEN or not HANGUL.match(word):
                continue
            if word in BLOCKED_WORDS:
                continue
            if word in words:
                words[word] |= flag
            else:
                words[word] = flag
                added += 1
                added_words.append(word)

    # 오픈DB에서 새로 들어온 단어 중 검증용 표본 (3~10글자, 고르게 뽑기)
    pool = [w for w in added_words if 3 <= len(w) <= 10]
    step = max(1, len(pool) // 30)
    added_samples = pool[::step][:30]

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
        "version": 2,
        "source": "공개 사전 덤프 + 오픈DB — 출처 표기는 NOTICE.md",
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rawRows": raw,
        "baseWords": base_count,
        "openDbRows": open_rows,
        "addedFromOpenDb": added,
        "openDbSamples": added_samples,
        "total": len(ordered),
        "maxLen": max(len(w) for w in ordered),
        "starts": len(starts),
        "syllables": dict(sorted(starts.items())),
        "oneShotCount": len(one_shot),
        "oneShotSamples": one_shot[:40],
        "inducedCount": len(induced),
        "inducedSamples": induced[:40],
        "flagCounts": flag_counts,
    }
    with open(os.path.join(out_dir, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(words_path)
    print("rows          :", raw)
    print("base words    :", base_count)
    print("open db added :", added)
    print("valid words   :", len(ordered))
    print("start syll.   :", len(starts))
    print("one-shot words:", len(one_shot), one_shot[:8])
    print("induced words :", len(induced), induced[:8])
    print("words.txt     : %.1f KB" % (size / 1024.0))
    print("stats.json    : %.1f KB" % (os.path.getsize(os.path.join(out_dir, "stats.json")) / 1024.0))


if __name__ == "__main__":
    t0 = time.time()
    main()
    print("done in %.1fs" % (time.time() - t0))
