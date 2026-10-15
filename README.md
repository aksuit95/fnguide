# FnGuide 리포트 수집 → Notion 요약 에이전트

FnGuide에서 지정한 종목의 신규 리포트를 매일 아침 수집하고, 요약해서 Notion 데이터베이스에 저장하는 개인용 자동화 도구입니다.

## 동작 방식

```
07:30  Windows 작업 스케줄러 "FnGuide Login"
         └─ fnguide_reports.py login --auto
            (Edge 자동 로그인 → auth_state.json 에 세션 저장)

08:01  Claude 예약 작업
         └─ 로그인된 브라우저 세션으로 신규 리포트 수집
         └─ 이미 저장된 리포트는 중복으로 건너뜀
         └─ 요약 후 Notion DB에 추가, 결과 알림
```

- 서버가 브라우저 밖 요청을 403으로 막기 때문에, 수집은 로그인된 브라우저 안에서 수행합니다.
- 자동 로그인은 다른 기기에 열려 있는 FnGuide 세션을 로그아웃시킵니다. 로그인 시 나오는 "이미 로그인된 다른 기기" 확인 창은 스크립트가 자동으로 승인합니다.

## 요구 사항

- Windows PC (실행 시간에 켜져 있어야 함)
- Python 3.10
- Microsoft Edge
- FnGuide 계정
- Notion Integration (대상 DB에 연결 필요)
- Claude 앱 (예약 작업 실행용, 실행 시간에 열려 있어야 함)

## 폴더 구조

```
C:\fnguide
├─ fnguide_reports.py      # 로그인 / 자격증명 저장 / 수집 메인 스크립트
├─ auth_state.json         # 로그인 세션 (민감, 커밋 금지)
├─ .browser_profile_cdp\   # 자동화용 Edge 프로필 (커밋 금지)
├─ out\
│  ├─ login.log            # 자동 로그인 로그
│  └─ login_fail.png       # 로그인 실패 스크린샷
├─ requirements.txt        # 의존 패키지
├─ agent_prompt.md         # 매일 작업(수집→전문 요약→Notion) 지침. 다른 AI에 그대로 줄 수 있음
├─ CLAUDE.md               # Claude Code 지침
├─ PLAN.md                 # 개발 계획과 진행 상황
└─ README.md
```

## 설치와 설정

1. 의존 패키지를 설치합니다.
   ```powershell
   pip install -r requirements.txt
   ```
2. 자격증명을 한 번 저장합니다.
   ```powershell
   python fnguide_reports.py setcred
   ```
3. 로그인을 테스트합니다.
   ```powershell
   python fnguide_reports.py login --auto
   ```
   성공하면 `navigator.webdriver: False`, `브라우저 내부 호출: 200` 등이 출력되고 `auth_state.json`이 저장됩니다.
4. 수집을 테스트합니다. `watchlist.json`의 종목별로 최근 N일 리포트를 받아 `out\new_reports.json`, `out\new_reports.md`로 저장합니다.
   ```powershell
   python fnguide_reports.py fetch --days 7        # 신규 리포트만
   python fnguide_reports.py fetch --days 7 --all  # 이미 본 리포트(state.json)도 포함
   ```
5. 작업 스케줄러에 매일 07:30 로그인을 등록합니다.
   ```powershell
   schtasks /Create /TN "FnGuide Login" /SC DAILY /ST 07:30 /TR "cmd /c cd /d C:\fnguide && C:\Users\CHECK\AppData\Local\Programs\Python\Python310\python.exe fnguide_reports.py login --auto >> C:\fnguide\out\login.log 2>&1" /F
   ```
6. Notion Integration을 만들고, 대상 데이터베이스에 연결합니다.

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 자동 로그인 실패 | `out\login.log`의 메시지, `out\login_fail.png` 스크린샷 확인 |
| 비밀번호 오류 | `setcred`를 다시 실행해 저장 |
| 이전 Edge가 남아 로그인이 꼬임 | 이 프로젝트 프로필의 Edge 프로세스만 종료 후 재실행 (CLAUDE.md의 명령 참고) |
| 수집 중 세션이 끊김 | 07:30~08:10에 다른 곳에서 FnGuide에 접속했는지 확인 |
| 리포트가 안 들어옴 | PC 전원/Claude 앱 실행 여부, `login.log` 확인 |

## 보안 주의

- 비밀번호, Notion 토큰, `auth_state.json`은 절대 커밋하거나 공유하지 마세요.
- Git을 쓴다면 `.gitignore`에 `auth_state.json`, 자격증명 파일, `.browser_profile_cdp/`, `out/`, `.env`를 반드시 넣으세요. 저장소는 private로 유지하세요.
- 리포트 원문 전체는 저장하지 않습니다. Notion에는 요약, 원문 링크, 리포트당 핵심 도표 이미지 최대 3개(출처 표기)만 둡니다. 리포트와 도표는 증권사의 저작물이므로 Notion을 개인용 비공개로 유지하고, 이 저장소에는 올리지 마세요.

## 이용 시 유의사항

FnGuide의 이용약관과 사내 규정상 자동 수집이 허용되는지는 별도 확인이 필요합니다. 공식 API나 데이터 피드가 있는지도 FnGuide 담당자에게 문의 중입니다. (PLAN.md 참고)
