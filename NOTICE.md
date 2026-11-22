# 출처 (NOTICE)

## 단어 데이터

`data/words.txt`, `data/stats.json` 은 아래 두 공개 단어 데이터를 병합해 파생했습니다.

### 1. KKuTu 데이터베이스 덤프

- 원본: https://github.com/JJoriping/KKuTu — `db.sql`, `kkutu_ko` 테이블
- 원본 저작권: Copyright (C) 2017 JJoriping(op@jjo.kr) 및 KKuTu 기여자
- 원본 라이선스: GNU General Public License v3.0 (이 저장소의 `LICENSE` 와 같음)

이 저장소가 만든 파생물은 `db.sql` 에서 다음만 남겨 다시 만든 것입니다.

1. `kkutu_ko` 의 표제어 중 2글자 이상, 순수 한글, 띄어쓰기가 필요 없는(flag 4 제외) 단어
2. 각 단어의 flag 비트(외래어 1, 어인정 2, 방언 8, 옛말 16, 문화어 32)

원본의 뜻풀이(`mean`) 열은 공개 덤프에서 자리표시자(`＂1＂［1］（1）`)로만 제공되어
가져오지 않았습니다. 앱의 단어 카드에 뜨는 것은 뜻이 아니라 사전 표제어 정보(글자 수, 분류)입니다.

### 2. 끄코 유틸리티 오픈DB (CC BY-NC-SA 4.0)

- 원본: 끄코 유틸리티 — https://kkuko-utils.vercel.app/word (오픈DB)
- 수집 경로: 공개 오픈API `GET /api/words/search` (https://kkuko-utils.vercel.app/openapi/word)
  — 로그인 없이 공개된 API이며, `build/collect_kkuko.py` 로 시작 음절별 전체 목록을 받았습니다.
- 라이선스: **CC BY-NC-SA 4.0** (저작자표시-비영리-동일조건변경허락 4.0)
  https://creativecommons.org/licenses/by-nc-sa/4.0/deed.ko
- 병합한 범위: 오픈DB가 "끝말잇기 사용가능"으로 표시한 단어 중 2글자 이상 순수 한글.
  오픈DB의 뜻·주제(어인정)·flag 정보는 API가 제공하지 않아 가져오지 않았고,
  단어의 flag 비트는 위 1번(db.sql)에서 온 값만 남습니다.
  오픈DB에서 "끝말잇기 불가"로 분류된 단어와 숫자·영문이 섞인 표제어는 넣지 않았습니다.
- 변경 내용: 위 1번 단어 목록과 중복을 제거해 병합하고, 시작 음절별 후속 단어 수와
  한방·유도 단어를 다시 계산했습니다. 원본 데이터 자체를 수정하지는 않았습니다.

이 저장소는 위 오픈DB 데이터를 **비영리** 목적으로만 사용하며, 같은 조건(CC BY-NC-SA 4.0)으로
공유합니다. 오픈DB 데이터를 다시 쓰려면 끄코 유틸리티를 출처로 밝히고 같은 라이선스를 따라야 합니다.

### 3. 일상 어휘 목록 (`build/easy_words.txt` → `data/stats.json` 의 `easy`)

Lv.1(쉬움)·Lv.2(보통) 봇이 낯선 방언·옛말·어인정 대신 일상적으로 쓰는 단어를 고르도록,
한국어 교육용 어휘 목록에서 표제어와 단계만 뽑아 씁니다.

- 국립국어원 『한국어 학습용 어휘 목록』(2003) — 1단계 A 982 · 2단계 B 2,111 · 3단계 C 2,872
  https://www.korean.go.kr/front/etcData/etcDataView.do?etc_seq=71
  → 등급을 그대로 단계로 적었습니다(1 = A, 2 = B, 3 = C).
- TOPIK 『어휘 목록 공개 목록』(2015) — 초급/중급
  https://www.topik.go.kr
  → 위 목록에 없는 단어는 초급 = 1단계, 중급 = 2단계로 적었습니다.
- 두 목록을 표제어·품사·등급으로 합쳐 둔 공개 정리본
  https://github.com/julienshim/combined_korean_vocabulary_list (MIT, `results.tsv`)를 읽어
  `build/build_easy.py` 로 만들었습니다. 원본 목록의 권리는 국립국어원과 TOPIK 에 있으며,
  이 저장소는 두 저작물의 출처를 위와 같이 밝힙니다.
- 변경 내용: 동음이의어 번호(`가구03`)와 접사 표시(`-가13`)를 떼고, 같은 단어는 가장 쉬운 등급 하나로
  합쳐 **단어와 단계만** 저장했습니다. 뜻풀이·예문·한자는 가져오지 않았습니다.
  `build_data.py` 는 이 중 796,750단어 사전에 실제로 남은 단어만, 방언(8)·옛말(16)·문화어(32)·
  어인정(2) 표제어는 빼고 싣습니다. 외래어(1)는 단계에 4를 더해 뒤 순위로 둡니다.

## 폰트

`fonts/` 에 함께 넣은 두 폰트는 화면을 시안과 같은 모양으로 그리기 위한 것입니다.

- **Jua** (주아체) — Copyright (c) 2018, Woowahan Brothers. SIL Open Font License 1.1.
  https://fonts.google.com/specimen/Jua
- **Pretendard** — Copyright (c) 2021, Kil Hyung-jin. SIL Open Font License 1.1.
  https://github.com/orioncactus/pretendard

두 폰트 모두 OFL 1.1 에 따라 원본 파일 그대로 배포하며, 파일 안에 저작권·라이선스 정보가 들어 있습니다.
앱은 `css/style.css` 의 `@font-face` 로 이 파일만 직접 불러옵니다(외부 CDN 없음).

## 라이선스

- 이 저장소의 **코드**: **GPL-3.0** (`LICENSE` 참고)
- **단어 데이터**(`data/words.txt`, `data/stats.json`): 위 두 원본의 파생물입니다.
  KKuTu 덤프에서 온 부분은 GPL-3.0, 끄코 유틸리티 오픈DB에서 온 부분은 CC BY-NC-SA 4.0 을 따릅니다.
  따라서 단어 데이터는 비영리 목적으로만 사용할 수 있고, 배포할 때는 출처 표시와
  동일조건변경허락(같은 라이선스) 조건이 함께 적용됩니다.
- **일상 어휘 목록**(`build/easy_words.txt`): 국립국어원·TOPIK 어휘 목록의 파생물입니다.
  출처는 위 3번과 같습니다.
