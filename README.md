# 청소업체 올인원 포스팅 자동화

구글 드라이브에 현장 사진만 올리면 **구글 블로그 · 네이버 블로그 · 틱톡**에 자동으로 글/영상을 올리고, 결과를 **슬랙**으로 보고합니다.
GitHub Actions(무료)에서 동작하며, 최초 1회 실행 시 드라이브 폴더·기본 템플릿을 **코드가 스스로 만듭니다 (Zero-Touch Setup)**.

```
 [슬랙 /posting] ─▶ Cloudflare Worker ─▶ GitHub Actions ◀─ [매일 스케줄]
                    (서명 검증·중계)          │
                                             ▼
  구글 드라이브 ─▶ ① 셀프 세팅 점검 ─▶ ② 사진 선택 ─▶ ③ EXIF 제거·세탁 ─▶ ④ Gemini 원고
                                                                          │
         ⑦ 사용 사진 99_사용완료 이동 ◀─ ⑥ 구글블로그 / 네이버 / 틱톡 발행 ◀─ ⑤ 9:16 영상
                     │
                     ▼
               ⑧ 슬랙 결과 카드 (+ 실패 시 수동 발행용 초안·영상)
```

슬랙에는 실행마다 **진행 메시지 1개**가 올라오고, 단계가 끝날 때마다 그 메시지가 갱신됩니다.
결과물(선택된 사진·전후 비교·원고·영상·발행 결과)은 그 메시지의 **스레드**에 모입니다.

```
🧹 정기청소 포스팅 진행 중                     → 끝나면 ✅ 정기청소 포스팅 완료
카테고리 정기청소 · 지역 안산 상록구 본오동 (서비스 지역) · 슬랙 명령 · 요청 hong · 09/28 10:17
✅ 사진 선택 — 5장 (작업 전 2 · 작업 중 1 · 작업 후 2)
✅ 사진 정리·전후 비교 — 전후 비교 O · 고객후기 1장
⏳ AI 원고 작성 진행 중…
⬜ 틱톡 영상 제작
⬜ 블로그·틱톡 발행
⬜ 사용 사진 보관
결과물은 이 메시지의 스레드에 올라갑니다 | 실행 로그 보기
  └ 스레드: 📸 선택된 사진 · 🖼️ 전후 비교 · 📝 원고(post.txt) · 🎬 영상 · 결과 카드
```
- 도중에 오류가 나면 그 단계가 ❌ 로 바뀌고 오류 내용이 스레드에 남습니다 (중복 알림 없음).
- GitHub `Actions` 목록에는 `💬 슬랙 포스팅 · 로프청소 [테스트]` 처럼 무엇을 실행했는지 표시되고,
  실행 페이지의 **Summary** 에 제목·지역·플랫폼별 결과표가 정리됩니다.
- 패키지 설치 등 파이썬 실행 전 단계에서 실패해도 웹훅으로 실패 알림 + 로그 링크를 보냅니다.

---

## 명세서 대비 달라진 점 (중요)

| 명세서 | 실제 구현 | 이유 |
|---|---|---|
| 구글 서비스 계정 | **내 구글 계정 OAuth refresh token** | 서비스 계정은 내 드라이브에 파일 업로드(저장 용량 0)와 Blogger 글 작성이 불가능 |
| 슬랙 `/포스팅` → GitHub Actions | **Cloudflare Worker 중계** (`slack_relay/`) | GitHub Actions 는 슬랙 요청을 직접 받을 수 없음. Worker 가 슬랙 서명 검증 후 실행 (무료) |
| 슬랙 명령어 `/포스팅`, `/초기세팅` | 기본 `/posting`, `/posting-setup` | 슬랙이 한글 명령어를 허용하는지 불확실. Worker 는 한글 이름도 인식하므로 등록되면 그대로 사용 가능 |
| 네이버 블로그 자동 발행 | Playwright 로 에디터 조작 **+ 실패 시 슬랙으로 수동 발행용 초안** | 네이버는 글쓰기 API 가 없음. 화면 구조가 바뀌면 깨질 수 있어 안전장치 추가 |
| 틱톡 업로드 | 공식 Content Posting API | 틱톡 앱 **심사(audit) 전에는 '나만 보기'로만 게시** 가능. 심사 통과 후 전체 공개 |
| 기본 BGM | 코드로 직접 합성한 음원 | 저작권 걱정 없는 확실한 무료 음원. 드라이브에서 파일만 교체하면 됨 |
| (추가) | `98_블로그_게시이미지` 폴더 | Blogger 는 이미지를 직접 호스팅하지 않아 드라이브 공개 링크로 게시 |
| (추가) | dry-run(테스트) 모드 | 발행 없이 원고·영상을 슬랙으로 미리보기 |

---

## 폴더 구조

```
├─ main.py                  포스팅 실행 (python main.py)
├─ setup.py                 초기 세팅 실행 (python setup.py) ※ 패키징용 setup.py 아님
├─ autopost/
│  ├─ setup_engine.py       Zero-Touch 드라이브 폴더/템플릿 자동 생성 (멱등)
│  ├─ templates.py          기본 헤더·푸터 이미지, BGM 합성
│  ├─ drive_helper.py       Google Drive API
│  ├─ photo_selector.py     카테고리·사진 선택
│  ├─ image_wash.py         EXIF(GPS) 제거, 1~2% 크롭, 미세 색감 조정, HEIC 지원
│  ├─ ai_helper.py          Gemini Vision 원고·해시태그 15개·틱톡 캡션
│  ├─ video_maker.py        MoviePy 9:16 슬라이드쇼 (페이드 + BGM + 단계 라벨)
│  ├─ blog_publisher.py     구글 블로그 (Blogger API v3)
│  ├─ naver_publisher.py    네이버 블로그 (Playwright)
│  ├─ tiktok_publisher.py   틱톡 (Content Posting API)
│  ├─ slack_helper.py       슬랙 알림·리포트 카드 (메시지 수정·스레드·파일 업로드)
│  ├─ progress.py           슬랙 진행 상황 체크리스트 (단계별 갱신)
│  ├─ step_summary.py       GitHub Actions 실행 요약(Summary) 작성
│  ├─ pipeline.py           전체 흐름
│  └─ cli.py / config.py    실행 인자·환경변수 검증
├─ slack_relay/             슬랙 → GitHub 중계 Cloudflare Worker
├─ scripts/                 1회용 토큰/세션 발급 스크립트
├─ slack_app_manifest.yml   슬랙 앱 한 번에 만들기
├─ .github/workflows/
│  ├─ auto_post.yml         자동 포스팅 (스케줄 / 수동 / 슬랙)
│  └─ ci.yml                테스트
└─ tests/                   pytest (234개) — 외부 서비스 없이 실행 (네이버 흐름은 로컬 가짜 에디터로 검증)
```

드라이브에는 아래 구조가 **자동 생성**됩니다 (`DRIVE_ROOT_FOLDER_NAME` 폴더 안).

```
청소업체_포스팅자동화/
├─ 00_공통_헤더이미지/header_로고.png   (기본 로고 자동 생성 → 교체 가능)
├─ 00_공통_푸터이미지/footer_안내.png   (연락처 안내 자동 생성 → 교체 가능)
├─ 00_공통_BGM/bgm.mp3                 (합성 BGM 자동 생성 → 교체 가능)
├─ 01_정기청소/ 작업전 · 작업중 · 작업후
├─ 02_로프청소/ 작업전 · 작업중 · 작업후
├─ 03_방역소독/ 작업전 · 작업중 · 작업후
├─ 98_블로그_게시이미지/                (구글 블로그 이미지 호스팅용, 삭제 금지)
├─ 99_사용완료_사진/날짜_카테고리/       (사용한 원본 + 영상 + 원고 보관)
└─ 00_사용안내.txt
```

---

## 1회 준비 (약 1시간)

> 준비물: 구글 계정(블로그 운영 계정), 슬랙 워크스페이스 관리자 권한, GitHub 계정, Cloudflare 계정(무료)
> 네이버·틱톡은 나중에 추가해도 됩니다. **시크릿을 비워두면 그 플랫폼은 자동으로 건너뜁니다.**

### 0) GitHub 비공개 리포지토리
1. GitHub 에서 **Private** 리포지토리를 만들고 이 폴더를 push 합니다.
   (공개 리포지토리면 실행 결과물(사진·영상·오류 스크린샷)이 노출될 수 있습니다)
2. 이후 나오는 값은 `Settings → Secrets and variables → Actions` 에 등록합니다.
   - **Secrets**: 토큰·비밀번호류 / **Variables**: `COMPANY_NAME`, `COMPANY_PHONE` 등 일반 설정

### 1) 구글 (드라이브 + 블로그)
1. https://console.cloud.google.com → 새 프로젝트
2. `API 및 서비스 → 라이브러리` 에서 **Google Drive API**, **Blogger API v3** 사용 설정
3. `OAuth 동의 화면` → 외부(External) → 앱 이름 등 입력 → **앱 게시(프로덕션으로 푸시)**
   - ⚠️ '테스트' 상태로 두면 refresh token 이 **7일 후 만료**됩니다. ('확인되지 않은 앱' 경고는 본인 사용이므로 '고급 → 이동' 으로 진행)
4. `사용자 인증 정보 → OAuth 클라이언트 ID → 데스크톱 앱` → JSON 다운로드 → 프로젝트 폴더에 `client_secret.json` 으로 저장
5. 내 PC 에서 실행:
   ```bash
   pip install -r requirements.txt
   python scripts/get_google_token.py client_secret.json
   ```
6. 출력된 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `BLOGGER_BLOG_ID` 를 Secrets 에 등록

### 2) Gemini
https://aistudio.google.com/apikey 에서 키 발급 → Secret `GEMINI_API_KEY`
> 무료 등급은 입력 데이터가 구글 서비스 개선에 쓰일 수 있습니다. 고객 현장 사진이 민감하면 유료(결제 연결) 등급을 권장합니다.

### 3) 슬랙 앱
1. https://api.slack.com/apps → **Create New App → From an app manifest** → `slack_app_manifest.yml` 내용 붙여넣기
   (url 두 곳은 4단계 후 Worker 주소로 수정 — 먼저 임시값으로 만들어도 됩니다)
2. `Install to Workspace` → **Bot User OAuth Token(xoxb-...)** → Secret `SLACK_BOT_TOKEN`
3. 알림 받을 채널의 ID(채널 이름 클릭 → 맨 아래 `C0...`) → Secret `SLACK_CHANNEL_ID`
   비공개 채널이면 채널에서 `/invite @cleanbot`
4. `Basic Information → Signing Secret` 은 4단계에서 사용
5. (선택, 예비 경로) `Incoming Webhooks` 켜기 → `Add New Webhook` → 알림 채널 선택 → URL 을 Secret `SLACK_WEBHOOK_URL` 에 등록.
   봇 전송이 실패하면 자동으로 웹훅으로 다시 보냅니다 (파일 업로드는 봇만 가능).
6. 연결 확인: `python scripts/slack_test.py` (봇·웹훅 각각 테스트 메시지 전송)

### 4) Cloudflare Worker (슬랙 명령 중계)
1. GitHub `Settings → Developer settings → Fine-grained tokens` → **이 리포지토리만** 선택 → **Actions: Read and write** 권한 하나만으로 토큰 생성
   (Worker 는 `auto_post.yml` 워크플로 실행 API 만 호출합니다. 코드 수정 권한은 필요 없습니다. 만료일을 정하고, 의심되면 즉시 폐기·재발급하세요)
2. `slack_relay/wrangler.toml` 의 `GITHUB_REPO` 확인 (`내아이디/리포지토리`)
3. 배포:
   ```bash
   cd slack_relay
   npx wrangler login
   npx wrangler secret put SLACK_SIGNING_SECRET
   npx wrangler secret put GITHUB_TOKEN
   npx wrangler deploy
   ```
4. 출력된 `https://....workers.dev` 주소를 슬랙 앱 `Slash Commands` 두 개의 Request URL 에 입력
5. (선택) `ALLOWED_USER_IDS` 에 실행 허용할 슬랙 사용자 ID 를 넣으면 그 사람만 실행 가능

### 5) 초기 세팅 실행
슬랙에서 `/posting-setup` (또는 GitHub `Actions → 청소 자동 포스팅 → Run workflow → mode: setup`)
→ 드라이브 폴더·템플릿이 자동 생성되고 슬랙에 **"✅ 초기 세팅 완료" + 연동 점검표**가 옵니다.

### 6) (선택) 네이버 블로그
```bash
python -m playwright install chromium
python scripts/export_naver_cookies.py
```
열린 창에서 **직접** 로그인 → Enter → 생성된 `naver_state.b64` 내용을 Secret `NAVER_STORAGE_STATE_B64` 에 등록 후 파일 삭제.
Secret `NAVER_BLOG_ID` 에는 블로그 주소 `blog.naver.com/아이디` 의 아이디를 넣습니다.
- 네이버 `내정보 → 보안설정 → 해외 로그인 차단`이 켜져 있으면 GitHub(해외 서버)에서 막힐 수 있습니다.
- 처음에는 Variable `NAVER_PUBLISH_MODE=draft` 로 **임시저장**만 해서 결과를 확인한 뒤 `publish` 로 바꾸는 것을 권장합니다.

### 7) (선택) 틱톡
1. https://developers.tiktok.com → 앱 생성 → **Login Kit**, **Content Posting API** 추가 → 스코프 `user.info.basic`, `video.publish`, `video.upload`
2. Redirect URI 에 https 주소 등록 (예: 내 구글 블로그 주소 `https://xxxx.blogspot.com/`)
3. 실행:
   ```bash
   python scripts/get_tiktok_token.py --client-key 키 --client-secret 시크릿 --redirect-uri https://xxxx.blogspot.com/
   ```
4. 출력된 3개 값을 Secrets 에 등록
- 앱 심사 전에는 **나만 보기(SELF_ONLY)** 로만 게시됩니다. 심사 통과 후 Variable `TIKTOK_PRIVACY_LEVEL=PUBLIC_TO_EVERYONE`.
- 또는 `TIKTOK_MODE=inbox` 로 두면 틱톡 앱 **받은편지함**으로 영상이 가고, 앱에서 음악·문구를 다듬어 직접 게시할 수 있습니다.

### 8) (선택) 토큰 자동 갱신 저장
네이버 세션·틱톡 refresh token 은 사용 중 갱신될 수 있습니다. Fine-grained PAT(이 리포지토리, **Secrets: Read and write**)를
Secret `GH_SECRETS_TOKEN` 으로 등록하면 갱신값을 자동으로 시크릿에 다시 저장합니다.

---

## 운영 방법

1. 작업 후 드라이브 `0X_카테고리/작업전·작업중·작업후` 폴더에 사진을 올립니다. (아이폰 HEIC 가능)
2. 평일 10:17(KST)에 자동 실행되거나, 슬랙에서 직접 실행합니다.

| 슬랙 명령 | 동작 |
|---|---|
| `/posting` | 사진이 가장 많은 카테고리로 포스팅 |
| `/posting 로프청소` | 카테고리 지정 (`정기`, `로프`, `방역` 처럼 줄여도 됨) |
| `/posting 정기청소 고잔동` | 실제 현장 위치까지 지정 → 제목·본문에 현장 위치로 사용 |
| `/posting 테스트` | 발행 없이 원고·영상만 만들어 슬랙으로 미리보기 |
| `/posting 도움말` | 사용법 안내 (실행하지 않음) |
| `/posting-setup` | 드라이브 폴더·템플릿 점검 및 연동 상태 보고 |

- 한 번에 단계별 최대 3장(`PHOTOS_PER_STAGE`), 최소 3장(`MIN_PHOTOS`)이 있어야 실행됩니다.
- **한 곳이라도 발행에 성공하면** 사용한 사진이 `99_사용완료_사진/날짜_카테고리/` 로 이동합니다. 모두 실패하면 사진은 그대로 두어 다음 실행에 재시도합니다.
- 네이버/틱톡이 실패하면 진행 메시지 스레드에 **수동 발행용 원고와 영상**이 올라옵니다.
- 실행 결과물(영상·원고·오류 스크린샷)은 Actions 실행 페이지의 Artifacts 에 7일간 보관됩니다.
- 스케줄 변경: `.github/workflows/auto_post.yml` 의 `cron` (UTC 기준, KST-9시간)

## 포스팅 양식

네이버 청소업체 '현장 기록' 글의 공통 구조를 따릅니다 (업체가 직접 쓰는 1인칭, 고객 후기 형식은 쓰지 않음).

1. 제목: `[지역 카테고리] 현장 내용` — 검색 키워드를 앞에
2. 인사 + 오늘 현장 소개 → 단계별 인용구 소제목
3. **사진마다 2~4줄 설명** (글·사진 교차, 모바일용 짧은 줄 자동 줄바꿈)
4. 작업 전/후 사진이 있으면 **전후 비교 이미지 자동 생성** → 글 끝·영상에 삽입
5. **고객후기** (`04_고객후기` 폴더의 실제 후기 캡처, 글마다 `REVIEWS_PER_POST`장, 사용 후 보관 폴더로 이동)
6. **관리 TIP** 문단 → 맺음말 + 상담 안내 + 전화번호 → 연락처 이미지 → 해시태그 15개

- **분량**: 사진 수에 비례한 최소 분량(공백 제외 400 + 사진당 60자)에 못 미치면 AI에 1회 자동 재요청
- **지역 검색(SEO) — 동 단위**: `SERVICE_AREA=서울,경기,인천,안산`
  - 서울·경기·인천의 행정동 약 800개(`autopost/data/regions.json`)를 글마다 순환합니다.
    항목끼리 번갈아(서울→경기→인천→안산), 한 항목 안에서는 시군구를 번갈아 선택합니다.
  - **실제 현장 위치를 모를 때(기본)**: 동은 '서비스 지역' 키워드로만 사용 —
    제목 `… | 안산 상록구 정기청소 본연클린`, 맺음말 "본오동 등 안산 상록구 전 지역 출장·상담 가능",
    해시태그 `#본오동정기청소 #상록구청소업체 #안산정기청소 …`. 현장이 그 동이라고는 쓰지 않습니다.
  - **실제 현장 위치를 알려주면**: 슬랙 `/posting 정기청소 고잔동` (또는 Actions 의 location 입력)
    → 제목 `[고잔동 정기청소] …` 처럼 실제 위치로 작성합니다. 동명이 여러 곳이면 `안산 중앙동` 처럼 시를 함께.
  - 행정구역 개편 시 `python scripts/build_region_data.py` 로 목록 갱신.
  - 없는 동을 현장처럼 쓰면 허위 표시 + 네이버 '지역 키워드 도배' 저품질 위험이 있어 위 방식으로 구분합니다.
- **고객후기는 반드시 실제 후기만** 사용하세요 (AI 생성·지어낸 후기는 표시광고법 위반 소지). 이름·연락처는 가린 뒤 업로드.

### 내 PC에서 미리보기 (드라이브·블로그에 아무것도 올리지 않음)
```bash
python scripts/preview_post.py <사진폴더> --category 로프청소
```
`<사진폴더>/작업전`, `작업중`, `작업후` 에 사진을 넣고 실행하면 `output/preview_…/preview.html`(블로그 모습), `tiktok.mp4`, `post.txt` 가 만들어집니다.

## 로컬 실행 / 테스트

```bash
python -m venv .venv && .venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt
copy .env.example .env                                   # 값 채우기
python setup.py                                          # 초기 세팅
python main.py --dry-run                                 # 발행 없이 미리보기
python main.py --category 로프청소                        # 실제 포스팅

pytest --cov=autopost                                    # 파이썬 테스트 (외부 서비스 불필요)
cd slack_relay && node --test                            # Worker 테스트
```
> 로컬 Python 3.10 은 2026-10 이후 구글 라이브러리 지원이 종료됩니다. 3.12 이상을 권장합니다 (Actions 는 3.12 사용).

## 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| `refresh token 이 만료` 슬랙 오류 | OAuth 동의화면이 '테스트' 상태 → 프로덕션으로 게시 후 `get_google_token.py` 재실행 |
| 네이버 `세션이 만료` | `export_naver_cookies.py` 재실행 후 시크릿 교체. 해외 로그인 차단 해제 확인 |
| 네이버 `이미지 업로드가 완료되지 않았습니다` / 셀렉터 오류 | 네이버 에디터 구조 변경. Artifacts 의 `naver_error_*.png` 확인 후 `autopost/naver_publisher.py` 의 `NaverSelectors` 수정 |
| 네이버가 계속 막힘 | 한국 PC 에 [self-hosted runner](https://docs.github.com/actions/hosting-your-own-runners) 를 설치해 `runs-on: self-hosted` 로 변경 (국내 IP로 실행) |
| 틱톡 `unaudited_client_can_only_post_to_private_accounts` 등 | 앱 심사 전 제한. `TIKTOK_PRIVACY_LEVEL=SELF_ONLY` 유지 또는 `TIKTOK_MODE=inbox` |
| 슬랙 명령 후 "dispatch_failed" | Worker URL 오타, Worker 시크릿 누락 확인 |
| 슬랙 명령 후 `GitHub API HTTP 403/404` | PAT 권한(Actions: Read and write)·대상 리포지토리·만료일 확인 |
| `GitHub API HTTP 422` | `auto_post.yml` 이 `main` 브랜치에 있는지, 워크플로 입력 이름이 Worker 와 같은지 확인 |
| 진행 메시지가 갱신되지 않고 줄마다 새로 올라옴 | 봇 토큰(`SLACK_BOT_TOKEN`) 없이 웹훅만 설정된 상태. 봇 토큰을 등록하면 한 메시지로 갱신·스레드 사용 |
| 블로그 이미지가 안 보임 | `98_블로그_게시이미지` 폴더/파일 삭제 여부 확인 (공개 링크로 게시됨) |
| 영상 글자가 네모(□)로 나옴 | 한글 폰트 없음. 로컬은 `FONT_PATH` 지정, Actions 는 `fonts-nanum` 자동 설치 |

## 참고 / 주의

- 생성된 원고는 사진에 보이는 사실만 쓰도록 지시되어 있지만, **AI 원고는 게시 전 가끔 직접 확인**하세요 (가격·지역·효과 과장 여부).
- 이미지 세탁은 촬영 위치(GPS)·기기 정보 제거가 주목적입니다. 같은 사진을 여러 번 재사용하는 용도로는 쓰지 마세요 — 사용한 사진은 자동으로 보관 폴더로 빠집니다.
- 네이버·틱톡 자동화는 각 플랫폼 정책 변경에 영향을 받을 수 있습니다. 과도한 빈도(하루 여러 건)는 스팸 판정 위험이 있으니 하루 1회 정도를 권장합니다.
