# Analyse Your Music

Last.fm 스크로블 기록을 분석하는 개인용 대시보드입니다. 청취 패턴, 장르 변화, 언어/지역권 트렌드, 급상승/급하락 아티스트 같은 걸 보여줍니다.

<p align="center">
  <a href="https://github.com/philip1029/Analyse-Your-Music/archive/refs/heads/main.zip">
    <img alt="ZIP 다운로드" src="https://img.shields.io/badge/%E2%AC%87%EF%B8%8E%20%EB%8B%A4%EC%9A%B4%EB%A1%9C%EB%93%9C-ZIP-2563eb?style=for-the-badge">
  </a>
</p>

<p align="center">
  <sub>버튼을 누르면 최신 버전이 ZIP으로 받아집니다. 압축을 풀고 아래 <b>준비물</b>부터 따라 하세요.<br>
  특정 버전이 필요하면 <a href="https://github.com/philip1029/Analyse-Your-Music/tags">Tags</a>에서 고를 수 있습니다 (현재 v0.2.0-beta).</sub>
</p>

## 준비물

- macOS
- Python 3.10 이상 (`python3 --version`으로 확인)
- Node.js 18 이상 (`node --version`으로 확인)
- Last.fm 계정과 API 키

Python/Node가 없다면 [python.org](https://www.python.org/downloads/), [nodejs.org](https://nodejs.org/)에서 설치하세요.

## 1. Last.fm API 키 발급

1. [last.fm/api/account/create](https://www.last.fm/api/account/create)에서 API 계정을 만듭니다 (본인 Last.fm 계정으로 로그인 후 간단한 정보만 입력하면 바로 발급되며 무료입니다).
2. 발급받은 **API key**를 복사해둡니다.
3. 자신의 Last.fm 프로필 URL(`last.fm/user/내아이디`)에서 **유저네임**도 확인해둡니다.

> API 키는 계정마다 따로 발급받아야 합니다. 다른 사람의 키를 공유해서 쓰면 안 됩니다 (Last.fm 이용 약관 위반이며, 사용량 제한도 함께 쓰게 됩니다).

## 2. 환경 설정

리포 루트에 `.env.example`을 복사해서 `.env` 파일을 만들고, 위에서 받은 값을 채워 넣습니다.

```bash
cp .env.example .env
```

```
LASTFM_API_KEY=발급받은_API_키
USERNAME=본인_last.fm_유저네임
```

## 3. 스크로블 데이터 가져오기

처음 실행하기 전에 자신의 Last.fm 청취 기록을 한 번 받아와야 합니다 (의존성은 아래 4번에서 `start.command`가 처음 실행할 때 자동으로 설치하므로, 먼저 한 번 실행해두면 편합니다).

```bash
cd scripts
python3 callData.py
```

`data/내유저네임_scrobbles.csv` 파일이 생성됩니다. 이후부터는 앱 안의 "🔄 최신 스크롭 불러오기" 버튼으로 갱신할 수 있습니다 (새 기록을 받은 직후 아래 전처리의 `--apply`도 자동으로 같이 실행됩니다).

### Apple Music 재생 기록도 같이 쓰고 싶다면

Last.fm을 쓰기 전부터의 재생 기록이 Apple Music에 남아있다면, Apple의 개인정보 데이터 내보내기([privacy.apple.com](https://privacy.apple.com) → 데이터 받기 → Apple Media Services 정보)로 받은 "Apple Music Activity" 데이터를 아래 전처리 파이프라인이 참고 자료로 사용합니다. 자세한 건 "스크로블 전처리" 섹션을 참고하세요.

## 4. 서버 실행

리포 루트의 `start.command`를 더블클릭하면 백엔드(`:8000`)와 프론트엔드(`:5173`)가 같이 뜨고, 브라우저가 자동으로 열립니다. 창을 닫거나 `Ctrl+C`를 누르면 둘 다 종료됩니다.

처음 실행할 때 의존성을 자동으로 설치하므로 시간이 조금 걸릴 수 있습니다.

## 데이터는 어디 저장되나요

- `data/` — 스크로블 CSV (gitignore 대상, 로컬에만 저장)
- `backend/cache/artists/` — Last.fm 아티스트 태그 캐시 (gitignore 대상)
- `.env` — API 키 (gitignore 대상)

전부 로컬 파일로만 저장되고, 외부 서버로 전송되지 않습니다 (Last.fm API 호출 제외).

## 백업과 복원

스크로블 CSV를 고치는 작업(전처리, 아티스트/곡명 정리, 빈 아티스트 채우기, 병합 되돌리기 등)은 실행 전에 항상 백업을 만듭니다.

- 백업은 `data/<CSV 이름>.bak_<종류>_<날짜>_<시각>.gz` 로 저장되고, 압축되어 CSV 한 개의 4분의 1 정도 크기입니다.
- 같은 종류의 백업은 최근 5개만 남기고 오래된 것부터 지웁니다. 개수는 환경변수 `BACKUP_KEEP` 으로 바꿀 수 있습니다 (최소 1). 앱은 `.env` 에 적은 값을 읽지만, 터미널에서 스크립트를 직접 실행할 때는 `BACKUP_KEEP=3 python3 scripts/preprocess.py --apply` 처럼 앞에 붙여야 합니다.
- 백업 관리는 아래 명령으로 합니다. `clean` 과 `restore` 는 기본이 dry-run이라, `--apply` 를 붙여야 실제로 반영됩니다.

```bash
python3 scripts/csv_backup.py list                          # 백업 목록과 크기
python3 scripts/csv_backup.py clean [--apply]               # 압축 안 된 옛 백업을 종류별 최근 N개만 압축해 남기고 정리
python3 scripts/csv_backup.py restore 파일이름 [--apply]     # 그 백업으로 CSV 를 되돌림 (되돌리기 전 현재 CSV 도 백업)
```

- 아티스트/곡명 병합을 되돌리는 기능은 백업이 아니라 `data/*_log.csv` 의 변경 기록을 사용합니다.

## 폰에서 보기

같은 Wi-Fi에 연결된 폰 브라우저에서 앱을 열 수 있습니다.

```bash
./start_phone.command    # (= ./start.command --lan) 서버를 0.0.0.0 으로 열고 폰 접속 주소(http://<맥 IP>:5173)를 출력합니다
```

- 프런트엔드는 접속한 주소의 호스트에 맞춰 `:8000` 백엔드를 자동으로 찾습니다. 다른 주소를 쓰려면 `frontend/.env` 에 `VITE_API_URL` 을 지정하세요.
- 인증이 없습니다. 같은 Wi-Fi의 모든 기기가 "최신 스크롭 불러오기" 같은 기능을 쓸 수 있으니 공용 Wi-Fi에서는 켜지 마세요. 기본(`./start.command`)은 이 맥에서만 접속됩니다.
- 폰 Safari에서 "홈 화면에 추가"를 누르면 앱처럼 전체 화면으로 열립니다 (PWA 매니페스트 포함).

## Apple Music 데이터 (선택)

Last.fm 스크로블만으로도 앱은 동작합니다. Apple Music 개인정보 내보내기를 함께 쓰면 가짜/중복 스크로블 판정, 곡 길이 조회, 빈 아티스트 채우기가 Apple 재생 기록을 근거로 정확해집니다 (Last.fm 이 기준이고 Apple 은 보조 근거입니다).

1. privacy.apple.com → "데이터 사본 요청"에서 **Apple Music 활동**을 요청해 받습니다 (며칠 걸릴 수 있습니다).
2. 압축을 풀어 아무 곳에나 둡니다 (프로젝트 안이면 `data/apple/` 를 권합니다. `.xml` 은 gitignore 되지 않으니 올리지 않게 주의하세요).
3. 폴더 경로를 알려 줍니다. 둘 중 하나입니다:
   - **Data 탭 → 설정 → "Apple Music 내보내기 폴더"** 에 경로를 넣고 저장합니다 (맨 위 폴더를 줘도 안에서 찾아 주고, 찾은 파일을 ✅ 로 보여 줍니다)
   - `.env` 에 `APPLE_ACTIVITY_DIR=/폴더/경로`

앱이 읽는 파일 (이름이 같아야 합니다; 없으면 그 기능만 건너뜁니다):

| 파일 | 쓰임 |
|---|---|
| `Apple Music Play Activity.csv` | 가짜/중복 스크로블 판정 (`scripts/preprocess.py`) |
| `Apple Music Library Tracks.json.zip` (보관함 곡 목록, 같은 내보내기에 들어 있음) | 정확한 곡 길이 (청취 시간 계산에 쓰는 곡 길이의 1순위) |
| `Apple Music - Play History Daily Tracks.csv` | 빈 아티스트 채우기 (`scripts/fill_missing_artists.py`) |
| `전체.xml` · `플레이리스트.xml` (음악 앱의 파일 → 라이브러리 → 라이브러리 내보내기로 직접 만든 보관함, 선택) | 곡 길이·아티스트 보강. 같은 폴더에 이 이름으로 넣습니다 |

폴더를 저장하면 Data 탭의 **“Apple 파일 안내”** 가 파일마다 용도·받는 곳·있는지를 보여 줍니다. 보관함 곡 목록이나 `전체.xml` 처럼 다른 곳에 받아 둔 파일은 그 경로(파일이나 폴더)를 적고 “이 폴더로 가져오기”를 누르면 Apple 폴더로 복사해 줍니다 (원본은 그대로, 이미 있으면 덮어쓰기 확인).

경로는 스크립트의 `--apple-dir` 옵션으로 직접 줄 수도 있습니다.

## AI 분석용 프롬프트 (Data 탭)

복사해서 ChatGPT/Claude에 붙여넣을 분석용 프롬프트를 만듭니다. 네 가지 형태가 있습니다.

- **전체 기간**: 위쪽에서 고른 날짜 범위 기준 (`/api/ai-prompt`).
- **연간 / 월간 / 주간**: 고른 해(또는 달, 월~일 한 주)를 직전 기간(전년/직전 달/직전 주)과 비교합니다
  (`/api/ai-prompt/period?period=year|month|week&anchor=YYYY|YYYY-MM|YYYY-MM-DD`, 기간 목록은 `/api/ai-prompt/periods`).
  날짜 범위와 상관없이 전체 기록에서 계산하고, 기본값은 가장 최근에 끝난 기간입니다.
  기록이 기간 전체를 덮지 못하면(진행 중이거나 데이터 시작 직후) "일부 기간"으로 표시하고 일평균 위주로 비교하라고 안내합니다.
  구성: 기간 요약 / 청취량 흐름 / 순위(직전 기간 대비 신규·복귀) / 신규 발견 / 시간 패턴·연속 청취 세션 /
  장르·언어권·집중도 / 분석 요청. 연간은 월별 표(월별 Top 아티스트·신규 아티스트 수), 연도별 추이, 연간 하이라이트
  (가장 많이 들은 날, 최장 연속 청취일)가 추가됩니다.

## 스크로블 전처리 (`scripts/preprocess.py`)

애플 뮤직 연동이 만든 가짜/중복 스크로블을 걸러냅니다. `source` 열(A=애플 로그 유래, L=last.fm 유래)은
바꾸지 않고, 판정과 제거는 L 행에만 적용합니다. 기본은 dry-run이고, 반영하면 백업과 제거 기록이 남습니다.

```bash
python3 scripts/preprocess.py --init-state    # 최초 1회 (상태 파일 생성)
python3 scripts/preprocess.py                 # dry-run: 새 행만 판정해서 보고
python3 scripts/preprocess.py --apply         # 실제 반영 (data/*.bak_preprocess_*.gz 백업 + 제거 기록)
python3 scripts/preprocess.py --apply --apple-dir "<Apple Music Activity 폴더>"   # 애플 데이터를 새로 받았을 때
```

"🔄 최신 스크롭 불러오기" 버튼은 새 기록을 받은 직후 `--apply`를 자동으로 실행합니다.

| 규칙 | 적용 구간 | 근거 |
|---|---|---|
| `log:no_play` / `log:excess` | 애플 로그가 있는 구간 | 그날 애플 로그 재생이 0회이거나 로그의 실제 재생 수를 넘는 초과분 |
| `provisional:pair_both_clash` | 애플 로그 이후 구간 | 길이 일치 2회 묶음 + 양쪽 기록이 모두 다른 곡과 같은 초에 겹침. 과거 통계상 85%가 가짜, 첫 행이 실제 시작일 확률 98.6% (약 15%는 실제 청취일 수 있음) |
| `exact_dup` | 전체 | `uts+artist+track` 완전 중복 |

- 지우지 않고 보고만 하는 것(보류): 그 밖의 2회 묶음, 3회 이상 묶음, 곡 길이 불명, 같은 초 충돌.
- 곡 길이 조회 순서: 애플 로그 / 라이브러리 XML → last.fm `track.getInfo`(곡당 1회, `data/preprocess_durations.json`에 캐시). 허용 오차 ±2초.
- 새 애플 데이터를 받아 `--apple-dir`로 다시 돌리면 `provisional:*`로 지운 행을 되살려 로그로 재판정합니다.
- 지운 행은 `data/preprocess_removed.csv`에 이유/근거와 함께 남습니다. 처리 위치는 `data/preprocess_state.json`에 저장됩니다.
- 빈 artist 채우기(`scripts/fill_missing_artists.py`): 스트리밍으로만 들어 라이브러리에 없는 A 소스 곡의 아티스트를 애플 `Play History Daily Tracks.csv`의 "아티스트 - 곡명"으로 채웁니다(곡명이 한 아티스트에만 대응할 때만). dry-run 기본, `--apply` 시 백업과 `data/artist_fill_log.csv` 기록. 수동 지정은 `--set "곡명=아티스트"`, `--set-album "곡명=앨범"`. `--album-unique`를 주면 그래도 빈 행을 같은 앨범의 다른 행에 아티스트가 정확히 한 명뿐일 때 그 아티스트로 채웁니다(규칙 이름 `album_unique`; 컴필레이션이면 틀릴 수 있습니다).
- 한계: 이미 확정된 구간을 다시 훑으면 1차 판정이 놓친 잔여분이 소수(8행 수준) 더 걸릴 수 있습니다. 확정 구간은 다시 훑지 않는 것이 정상 흐름입니다.
