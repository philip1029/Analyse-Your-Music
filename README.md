# Analyse Your Music

Last.fm 스크로블 기록을 분석하는 개인용 대시보드입니다. 청취 패턴, 장르 변화, 언어/지역권 트렌드, 급상승/급하락 아티스트 같은 걸 보여줍니다.

## 준비물

- macOS
- Python 3.10 이상 (`python3 --version`으로 확인)
- Node.js 18 이상 (`node --version`으로 확인)
- Last.fm 계정과 API 키

Python/Node가 없다면 [python.org](https://www.python.org/downloads/), [nodejs.org](https://nodejs.org/)에서 설치하세요.

## 1. Last.fm API 키 발급

1. [last.fm/api/account/create](https://www.last.fm/api/account/create)에서 API 계정을 만듭니다 (본인 Last.fm 계정으로 로그인 후 간단한 정보만 입력하면 바로 발급됨, 무료).
2. 발급받은 **API key**를 복사해둡니다.
3. 자신의 Last.fm 프로필 URL(`last.fm/user/내아이디`)에서 **유저네임**도 확인해둡니다.

> API 키는 계정마다 따로 발급받아야 합니다. 다른 사람의 키를 공유해서 쓰면 안 됩니다 (Last.fm 이용 약관 위반이자, 사용량 제한도 같이 씀).

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

`data/내유저네임_scrobbles.csv` 파일이 생성됩니다. 이후부터는 앱 안의 "🔄 최신 스크롭 불러오기" 버튼으로 갱신할 수 있습니다.

### Apple Music에서 과거 기록도 가져오고 싶다면

Last.fm을 쓰기 전부터의 재생 기록이 Apple Music에 남아있다면, Apple의 개인정보 데이터 내보내기([privacy.apple.com](https://privacy.apple.com) → 데이터 받기 → Apple Media Services 정보)로 받은 "Apple Music Activity" 데이터를 가져와 합치는 기능을 준비 중입니다. (`scripts/import_apple_music.py`, 아직 작업 중)

## 4. 서버 실행

리포 루트의 `start.command`를 더블클릭하면 백엔드(`:8000`)와 프론트엔드(`:5173`)가 같이 뜨고, 브라우저가 자동으로 열립니다. 창을 닫거나 `Ctrl+C`를 누르면 둘 다 종료됩니다.

처음 실행할 때 의존성을 자동으로 설치하므로 시간이 조금 걸릴 수 있습니다.

## 데이터는 어디 저장되나요

- `data/` — 스크로블 CSV (gitignore됨, 로컬에만 저장)
- `backend/cache/artists/` — Last.fm 아티스트 태그 캐시 (gitignore됨)
- `.env` — API 키 (gitignore됨)

전부 로컬 파일로만 저장되고, 외부 서버로 전송되지 않습니다 (Last.fm API 호출 제외).
