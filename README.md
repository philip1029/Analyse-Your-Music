# Analyse-Your-Music
Last.fm API를 이용한 개인 프로그램

## AI 분석용 프롬프트 (Data 탭)

복사해서 ChatGPT/Claude에 붙여넣을 분석용 프롬프트를 만든다. 세 가지 형태가 있다.

- **전체 기간**: 위쪽에서 고른 날짜 범위 기준 (`/api/ai-prompt`).
- **월간 / 주간**: 고른 달(또는 월~일 한 주)을 직전 기간과 비교한다 (`/api/ai-prompt/period?period=month|week&anchor=...`,
  기간 목록은 `/api/ai-prompt/periods`). 날짜 범위와 상관없이 전체 기록에서 계산하고, 기본값은 가장 최근에 끝난 기간이다.
  기록이 기간 끝까지 닿지 않으면 "일부 기간"으로 표시하고 일평균 위주로 비교하라고 안내한다.
  구성: 기간 요약 / 청취량 흐름 / 순위(직전 기간 대비 신규·복귀) / 신규 발견 / 시간 패턴·연속 청취 세션 /
  장르·언어권·집중도 / 분석 요청.

## 스크로블 전처리 (`scripts/preprocess.py`)

애플 뮤직 연동이 만든 가짜/중복 스크로블을 걸러낸다. `source` 열(A=애플 로그 유래, L=last.fm 유래)은
바꾸지 않고, 판정과 제거는 L 행에만 적용한다. 기본은 dry-run이고, 반영하면 백업과 제거 기록이 남는다.

```bash
python3 scripts/preprocess.py --init-state    # 최초 1회 (상태 파일 생성)
python3 scripts/preprocess.py                 # dry-run: 새 행만 판정해서 보고
python3 scripts/preprocess.py --apply         # 실제 반영 (data/*.bak_preprocess_* 백업 + 제거 기록)
python3 scripts/preprocess.py --apply --apple-dir "<Apple Music Activity 폴더>"   # 애플 데이터를 새로 받았을 때
```

"🔄 최신 스크롭 불러오기" 버튼은 새 기록을 받은 직후 `--apply`를 자동으로 실행한다.

| 규칙 | 적용 구간 | 근거 |
|---|---|---|
| `log:no_play` / `log:excess` | 애플 로그가 있는 구간 | 그날 애플 로그 재생이 0회이거나 로그의 실제 재생 수를 넘는 초과분 |
| `provisional:pair_both_clash` | 애플 로그 이후 구간 | 길이 일치 2회 묶음 + 양쪽 기록이 모두 다른 곡과 같은 초에 겹침. 과거 통계상 85%가 가짜, 첫 행이 실제 시작일 확률 98.6% (약 15%는 실제 청취일 수 있음) |
| `exact_dup` | 전체 | `uts+artist+track` 완전 중복 |

- 지우지 않고 보고만 하는 것(보류): 그 밖의 2회 묶음, 3회 이상 묶음, 곡 길이 불명, 같은 초 충돌.
- 곡 길이 조회 순서: 애플 로그 / 라이브러리 XML → last.fm `track.getInfo`(곡당 1회, `data/preprocess_durations.json`에 캐시). 허용 오차 ±2초.
- 새 애플 데이터를 받아 `--apple-dir`로 다시 돌리면 `provisional:*`로 지운 행을 되살려 로그로 재판정한다.
- 지운 행은 `data/preprocess_removed.csv`에 이유/근거와 함께 남는다. 처리 위치는 `data/preprocess_state.json`.
- 빈 artist 채우기(`scripts/fill_missing_artists.py`): 스트리밍으로만 들어 라이브러리에 없는 A 소스 곡의 아티스트를 애플 `Play History Daily Tracks.csv`의 "아티스트 - 곡명"으로 채운다(곡명이 한 아티스트에만 대응할 때만). dry-run 기본, `--apply` 시 백업과 `data/artist_fill_log.csv` 기록. 수동 지정은 `--set "곡명=아티스트"`, `--set-album "곡명=앨범"`. `--album-unique`를 주면 그래도 빈 행을 같은 앨범의 다른 행에 아티스트가 정확히 한 명뿐일 때 그 아티스트로 채운다(규칙 이름 `album_unique`; 컴필레이션이면 틀릴 수 있다).
- 한계: 이미 확정된 구간을 다시 훑으면 1차 판정이 놓친 잔여분이 소수(8행 수준) 더 걸릴 수 있다. 확정 구간은 다시 훑지 않는 것이 정상 흐름이다.
