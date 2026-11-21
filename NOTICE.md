# 출처 (NOTICE)

## 단어 데이터

`data/words.txt`, `data/stats.json` 은 **끄투 온라인(KKuTu)** 의 데이터베이스 덤프에서
파생했습니다.

- 원본: https://github.com/JJoriping/KKuTu — `db.sql`, `kkutu_ko` 테이블
- 원본 저작권: Copyright (C) 2017 JJoriping(op@jjo.kr) 및 KKuTu 기여자
- 원본 라이선스: GNU General Public License v3.0 (이 저장소의 `LICENSE` 와 같음)

이 저장소가 만든 파생물은 `db.sql` 에서 다음만 남겨 다시 만든 것입니다.

1. `kkutu_ko` 의 표제어 중 2글자 이상, 순수 한글, 띄어쓰기가 필요 없는(flag 4 제외) 단어
2. 각 단어의 flag 비트(외래어 1, 어인정 2, 방언 8, 옛말 16, 문화어 32)
3. 시작 음절별 단어 수와 한방·유도 단어 목록(`stats.json`)

원본의 뜻풀이(`mean`) 열은 공개 덤프에서 자리표시자(`＂1＂［1］（1）`)로만 제공되어
가져오지 않았습니다. 앱의 단어 카드에 뜨는 것은 뜻이 아니라 사전 표제어 정보(글자 수, 분류)와
앱의 내 단어장에 사용자가 직접 적은 뜻입니다.

## 라이선스

이 저장소의 코드와 위 파생 데이터는 **GPL-3.0** 을 따릅니다(`LICENSE` 참고).
