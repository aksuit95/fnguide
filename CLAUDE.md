# CLAUDE.md

이 파일은 Claude Code가 세션을 시작할 때마다 읽는 프로젝트 지침입니다.
작업 전에 이 파일과 PLAN.md를 먼저 확인하세요.

## 프로젝트 목적
FnGuide에서 내가 지정한 종목의 신규 리포트를 수집하고, 요약해서 Notion DB에 저장한다.
(자세한 구조와 실행법은 README.md, 진행 상황과 할 일은 PLAN.md 참고)

## 환경
- OS: Windows, 작업 폴더 `C:\fnguide`
- Python 3.10
- 브라우저: Edge를 CDP(원격 디버깅)로 제어. 전용 프로필 폴더 `.browser_profile_cdp` 사용
- 스케줄: Windows 작업 스케줄러(로그인) + Claude 예약 작업(수집/요약/Notion)

## 주요 파일
- `fnguide_reports.py`: 로그인, 자격증명 저장, 리포트 수집 메인 스크립트
- `auth_state.json`: 로그인 세션 저장 파일 (민감, 절대 공유/커밋 금지)
- `out/login.log`: 자동 로그인 로그
- `out/login_fail.png`: 로그인 실패 시 스크린샷 (비밀번호는 가려짐)

## 자주 쓰는 명령
```powershell
# 자격증명 저장 (처음 한 번, 비밀번호가 바뀌면 다시)
python fnguide_reports.py setcred

# 자동 로그인 + 세션 저장
python fnguide_reports.py login --auto

# 로그인 전에 남은 Edge 정리 (이 프로젝트 프로필만 종료)
Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object { $_.CommandLine -like '*fnguide\.browser_profile_cdp*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```
```powershell
# 수집: watchlist.json의 종목별 최근 N일 리포트 → out/new_reports.json, out/new_reports.md
python fnguide_reports.py fetch --days 7
# 이미 본 리포트(state.json)도 포함해서 다시 수집
python fnguide_reports.py fetch --days 7 --all
```
테스트/린트 설정은 없다. 수정 후에는 `python -m py_compile fnguide_reports.py`로 문법을 확인하고, `watchlist.json`을 종목 1개로 줄여 `fetch --days 1`을 돌려본다.

## 구조 (fnguide_reports.py 단일 파일)
- 서브커맨드는 `login` / `fetch` / `setcred` / `text` 네 개. `fetch`는 신규 리포트마다 뷰어(`/Research/PdfViewer?rptId=`)를 열어 `GetPdfFile` 응답(base64 PDF)을 가로채 `pypdf`로 텍스트를 뽑아 `out/text/<ID>.txt`에 저장하고(요약 입력용, 건 사이 2초 대기), `--no-text`로 끌 수 있다. `text <ID...>`는 지정한 리포트만 같은 방식으로 추출한다. 이 텍스트는 요약을 Notion에 올린 뒤 삭제한다(원문 로컬 보관 금지). 같은 PDF에서 `pymupdf`로 "그래픽 덩어리 + 아래 출처(`자료:`) 줄"이 있는 도표 후보를 찾아 `out/figs/<ID>/NN_pP.png`(150dpi)로 자르고, 항목의 `figures`(file/page/caption/source)에 담는다. 어느 도표가 핵심인지는 에이전트가 caption으로 고른다. `--no-figs`로 끌 수 있다. Notion 반영 절차는 `agent_prompt.md`에 있다.
- `login`과 `fetch`는 둘 다 `msedge.exe`를 직접 띄워 Playwright로 CDP(`connect_over_cdp`)에 붙는다. `login`은 포트 9222 + `.browser_profile_cdp`(`--auto`면 헤드리스), `fetch`는 포트 9223 + 임시 프로필(헤드리스, 종료 시 삭제)을 쓴다. 두 경로 모두 종료 시 `taskkill`로 Edge를 정리한다.- 아이디/비밀번호는 `keyring`(서비스명 `fnguide-reports`, Windows 자격 증명 관리자)에 저장된다. `login`은 성공 후 세션 쿠키를 `auth_state.json`에, UA를 `auth_ua.txt`에 저장하고, `fetch`는 이 쿠키를 새 브라우저 컨텍스트에 주입해서 쓴다.
- 수집은 `/Research/SearchReport` 페이지를 연 뒤 페이지 안에서 `fetch('/Research/GetReports', POST)`를 실행(`JS_POST`)한다. 브라우저 밖 요청은 403이므로 이 구조를 바꾸지 말 것. 페이지네이션(`PER_PAGE=50`)은 `search()`가 처리한다.
- 대상 종목은 `watchlist.json`(`[{"name","code","sector"}]`, `sector`는 참고용)에서 읽는다. 현재 75종목(반도체 2, 통신 3, 엔터·미디어 32, 게임 19, 인터넷 8, 레저 11)이며 업종은 FnGuide 업종 코드(통신서비스, 광고·방송과엔터테인먼트·출판, 게임엔터테인먼트, 양방향미디어와서비스, 호텔·레스토랑·레저) 기준이다. 종목 사이 조회는 2초 간격을 둔다. Notion "종목" 선택지는 종목명과 정확히 같아야 하고 쉼표를 쓸 수 없다. 코드에 하드코딩하지 않는다. (`TEST_FORM`은 응답 확인용 샘플 상수)
- 중복 방지는 두 겹이다. 로컬 `state.json`(본 `RPT_ID` 목록)으로 `fetch`가 신규만 거르고, Notion 쪽 중복 확인은 Claude 예약 작업이 담당한다. Notion 저장 코드는 이 저장소에 없다.
- 주의: `fetch`는 Notion 저장 성공 여부와 무관하게 결과를 쓰는 즉시 `state.json`에 ID를 기록한다. 저장이 실패했다면 해당 ID를 `state.json`에서 빼거나 `--all`로 다시 받아야 한다.
- 응답의 `COMMENT`가 리포트 요약 본문이고, `normalize()`가 Notion용 필드로 정리한다.

## 반드시 지킬 규칙
1. **비밀정보 보호**: 비밀번호, Notion 토큰, API 키, `auth_state.json`은 코드에 넣거나 커밋하거나 채팅/로그에 출력하지 않는다. 환경변수나 안전한 저장소를 쓴다.
2. **.gitignore 유지**: `auth_state.json`, 자격증명 파일, `.browser_profile_cdp/`, `out/`, `.env`는 항상 제외한다.
3. **원문 저장 제한**: 리포트 원문(전체 텍스트, PDF, 페이지 전체)은 저장·복제하지 않는다. Notion에는 요약, 메타데이터, 원문 링크, 그리고 리포트당 **핵심 도표 이미지 최대 3개**(출처 표기)만 올린다. 도표 이미지는 사용자가 2026-10-15에 허용했다. 로컬 임시 파일(`out/text`, `out/figs`)은 Notion 반영 후 삭제한다. 이 저장소(GitHub)에는 원문이나 도표를 올리지 않는다.
4. **요청 간격**: FnGuide 요청은 사이 간격을 충분히 두고(최소 2초), 불필요한 반복 호출을 하지 않는다.
5. **중복 방지**: 이미 Notion에 있는 리포트는 건너뛴다. 이 로직을 깨뜨리는 수정은 하지 않는다.
6. **수집은 브라우저 안에서**: 서버가 브라우저 밖 요청을 403으로 막는다. 수집 로직은 로그인된 브라우저 컨텍스트에서 실행한다.
7. **세션 충돌 주의**: 자동 로그인은 다른 기기의 FnGuide 세션을 끊는다. 07:30~08:10에는 다른 곳에서 FnGuide에 접속하지 않는다.
8. **사용자 확인 필요한 작업**: 작업 스케줄러 등록/삭제, 프로세스 강제 종료, 계정 정보 변경, 외부 서비스 설정 변경은 실행 전에 사용자에게 확인한다.

## 작업 방식
- 큰 변경은 PLAN.md의 단계 단위로 진행하고, 끝나면 PLAN.md 체크박스를 갱신한다.
- 수정 후에는 문법 검사와 소규모 실행 테스트(종목 1개 등)로 확인한다.
- 실패 시 원인을 알 수 있도록 화면 메시지와 스크린샷을 남기는 현재 방식을 유지한다.
- 코드를 바꾸면 README.md의 실행법과 이 파일의 명령어가 맞는지 확인한다.

## 알려진 이슈와 주의점
- 로그인 시 "이미 로그인된 다른 기기가 있습니다" 확인 창이 뜨며, 스크립트가 "확인"을 자동으로 누른다.
- 이용약관상 자동 수집이 허용되는지, 공식 API/데이터 피드가 있는지는 FnGuide 담당자에게 확인 예정이다 (PLAN.md 참고). 확인 전에는 접근 빈도와 범위를 늘리지 않는다.
- PC가 꺼져 있거나 Claude 앱이 닫혀 있으면 그날 수집은 실행되지 않는다.
