# 끝말잇기 한방봇 (Hanbang Bot)

한방 단어를 꽂는 4단계 봇과 붙는 1:1 끝말잇기. 366,094 단어 사전, 표준 두음법칙, 4단계 난이도.

- 라이브: **https://hanbang-bot.onrender.com**
- 저장소: https://github.com/Eomukim/hanbang-bot

## 무엇이 들어 있나

| 항목 | 내용 |
| --- | --- |
| 단어 사전 | 공개 사전 덤프에서 2글자 이상 순수 한글 366,094개 추출 |
| 두음법칙 | ㄹ+ㅑㅒㅕㅖㅛㅠㅣ → ㅇ, 그 밖의 ㄹ → ㄴ, ㄴ+ㅑㅒㅕㅖㅛㅠㅣ → ㅇ (표준 전체) |
| 한방 단어 | 끝 글자(와 두음 변환 글자)로 시작하는 후속 단어가 0개인 단어 762개 |
| 유도 단어 | 후속 단어가 1~5개뿐인 글자로 끝나는 단어 1,588개 |
| 내 단어장 | 사전에 없는 단어를 직접 등록·삭제, `localStorage`에 저장, 봇 판정에도 즉시 반영 |
| 봇 | 4단계. 4단계는 한방 단어가 있으면 100% 즉시 사용 |

## 규칙

- 2글자 이상 한글 단어만. 이미 나온 단어는 다시 쓸 수 없다.
- 앞 단어의 끝 글자로 시작해야 하며, 두음법칙 변환 글자도 인정된다(`력` → `역`).
- 자기 차례 제한 시간(10/15/20초)을 넘기면 패배. 이을 단어가 없으면 그 자리에서 패배.
- 점수 = (글자수² + 글자수×4) × 콤보 배수(최대 2.5) × 미션 글자 보너스(1.5).

## 난이도

| 단계 | 봇의 행동 |
| --- | --- |
| Lv.1 쉬움 | 한방 단어 금지, 후속 단어가 많은 2~3글자 위주, 1.5~2.5초 응답 |
| Lv.2 보통 | 가끔 긴 단어, 4턴 이후에만 낮은 확률로 한방 |
| Lv.3 어려움 | 후속 1~3개인 글자로 몰아넣고, 4턴 이후 85% 확률로 한방 |
| Lv.4 지옥 | 한방이 있으면 100% 즉시 사용. 없으면 최소 후속 글자·장문으로 0.2~0.5초 압박 |

봇 이름은 단계별로 한방봇 주니어 · 한방봇 · 한방봇 X · 한방봇 지옥이다.

## 구조

```
index.html          화면 뼈대
css/style.css       아케이드 UI (모바일 390px 우선, 키보드 높이 대응)
js/rules.js         한글 음절 분해 · 두음법칙
js/data.js          사전 로드(스트리밍) · 구간 색인 · 한방/유도 판정 · 내 단어장
js/engine.js        턴 진행 · 판정 · 점수 · 타이머
js/bot.js           4단계 봇 전략과 대사
js/audio.js         Web Audio 효과음(음원 파일 없음)
js/store.js         localStorage 설정 · 내 단어장 · 전적
js/ui.js            화면 조립, 입력, 결과
build/build_data.py db.sql → data/words.txt + data/stats.json
tools/verify.py     headless Chromium 검증(로컬/라이브)
```

사전은 시작 음절마다 연속 구간을 이루도록 정렬해 두어, 브라우저에서는 이진 탐색과 구간 조회만으로
판정·후속 단어 수·봇 후보를 계산한다. 별도 색인 파일 없이 366,094 단어가 즉시 조회된다.

## 데이터 다시 만들기

```bash
curl -L -o db.sql https://raw.githubusercontent.com/JJoriping/KKuTu/master/db.sql
python3 build/build_data.py db.sql
```

## 검증

```bash
python3 tools/verify.py --local
python3 tools/verify.py --url https://hanbang-bot.onrender.com
```

로컬/라이브 모두에서 콘솔·페이지 에러 0, 가로 오버플로 0, 두음법칙 입력, 중복 차단,
내 단어장 반영, 1단계 한방 금지, 4단계 한방 즉사, 모바일 키보드 높이 레이아웃을 확인하고
스크린샷을 `downloads/`에 남긴다.

## 출처와 라이선스

단어 데이터는 [JJoriping/KKuTu](https://github.com/JJoriping/KKuTu)의 `db.sql`(GPL-3.0)에서
파생했다. 자세한 표기는 [NOTICE.md](NOTICE.md) 참고.
