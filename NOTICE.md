# 출처 (NOTICE)

## 단어 데이터

`data/words.txt`, `data/stats.json` 은 아래 공개 오픈DB 단어 목록에서 파생했습니다.
2026-11 사용자 지시로 예전에 병합하던 KKuTu `db.sql` 덤프(GPL-3.0)는 원천에서 완전히 뺐습니다.

### 끄코 유틸리티 오픈DB (CC BY-NC-SA 4.0)

- 원본: 끄코 유틸리티 — https://kkuko-utils.vercel.app/word (오픈DB)
- 수집 경로: 공개 오픈API `GET /api/words/search` (https://kkuko-utils.vercel.app/openapi/word)
  — 로그인 없이 공개된 API이며, `build/collect_kkuko.py` 로 시작 음절별 전체 목록을 받았습니다.
- 라이선스: **CC BY-NC-SA 4.0** (저작자표시-비영리-동일조건변경허락 4.0)
  https://creativecommons.org/licenses/by-nc-sa/4.0/deed.ko
- 쓴 범위: 오픈DB가 "끝말잇기 사용가능"으로 표시한 단어 중 2글자 이상 순수 한글 (732,372개).
  오픈DB의 뜻·주제(어인정)·flag 정보는 API가 제공하지 않아 가져오지 않았습니다.
- 변경 내용: 실제 끄투코리아 일반·어인정 방의 기본 룰과 같게, **단어 목록은 가공하지 않습니다**.
  2글자 미만·한글이 아닌 표제어만 빼고 그대로 씁니다(동사·형용사 사전형, 작품명·어인정 표제어 포함).
- 다시 계산한 것: 시작 음절별 후속 단어 수, 한방·유도 단어, 음절 대전 그래프. 원본 데이터 자체를
  수정하지는 않았고, 앱이 읽는 목록만 722,109개로 다시 만들었습니다.

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
  `build_data.py` 는 이 중 722,109단어 사전에 실제로 남은 단어만 싣습니다(원천에 flag 비트가 없어
  일상 어휘는 목록 자체로만 구분합니다).

## 폰트

`fonts/` 에 함께 넣은 두 폰트는 화면을 시안과 같은 모양으로 그리기 위한 것입니다.

- **나눔스퀘어라운드(NanumSquareRound)** — 제목·버튼·난이도 이름·점수 같은 디스플레이 요소.
  Copyright (c) 2010, NHN Corporation (http://www.nhncorp.com) — NAVER 배포.
  SIL Open Font License 1.1 (`fonts/Nanum-OFL.txt`).
  배포처: https://hangeul.naver.com/font (공식 배포 묶음 `nanum-all_new.zip`)
  `fonts/NanumSquareRound-400.woff2` · `-700.woff2` · `-800.woff2` 는 위 배포본의
  TTF(Regular/Bold/ExtraBold)를 글자 모양 그대로 웹 전송용 WOFF2 로 변환한 것입니다.
  https://github.com/google/fonts/blob/main/ofl/nanumgothic/OFL.txt
- **Pretendard** — Copyright (c) 2021, Kil Hyung-jin. SIL Open Font License 1.1.
  단어 타일·본문·사전·입력창에 씁니다.
  https://github.com/orioncactus/pretendard

두 폰트 모두 OFL 1.1 에 따라 배포하며, 파일 안에 저작권·라이선스 정보가 들어 있습니다.
앱은 `css/style.css` 의 `@font-face` 로 이 파일만 직접 불러옵니다(외부 CDN 없음).
이전 화면에 쓰던 Jua(주아체)는 읽기 편한 서체로 바꾸면서 저장소에서 함께 지웠습니다.

## 라이선스

- 이 저장소의 **코드**: **GPL-3.0** (`LICENSE` 참고)
- **단어 데이터**(`data/words.txt`, `data/stats.json`): 끄코 유틸리티 오픈DB(CC BY-NC-SA 4.0)의
  파생물입니다. 따라서 단어 데이터는 비영리 목적으로만 사용할 수 있고, 배포할 때는 출처 표시와
  동일조건변경허락(같은 라이선스) 조건이 함께 적용됩니다.
- **일상 어휘 목록**(`build/easy_words.txt`): 국립국어원·TOPIK 어휘 목록의 파생물입니다.
  출처는 위 '일상 어휘 목록' 절과 같습니다.
