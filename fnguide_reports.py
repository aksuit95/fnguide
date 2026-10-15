"""FnGuide 관심종목 리포트 수집기.

사용법
  python fnguide_reports.py setcred # 자격 증명 저장(1회, 사용자가 직접)
  python fnguide_reports.py login --auto  # 저장된 자격 증명으로 자동 로그인
  python fnguide_reports.py login   # 최초 1회: 열린 브라우저에서 직접 로그인 후 Enter
  python fnguide_reports.py fetch   # 신규 리포트 수집 + PDF 본문 -> out/new_reports.json, out/text/<ID>.txt
  python fnguide_reports.py text 1137565 1137520   # 지정한 리포트의 PDF 본문만 추출
옵션: --days 30 (조회 기간), --all (이미 처리한 리포트도 포함), --no-text (본문 추출 생략)
"""
import argparse
import base64
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://www.fnguide.com"
ROOT = Path(__file__).parent
AUTH = ROOT / "auth_state.json"
KEYRING_SERVICE = "fnguide-reports"
UA_FILE = ROOT / "auth_ua.txt"
TEST_FORM = {"estTyp": "2", "action": "0", "period": "0", "fromDt": "2026.09.14", "toDt": "2026.10.14", "exclBlind": "true", "srchTyp": "1", "srchKeyword": "삼성전자", "srchCode": "005930", "menuCd": "1010", "curPage": "1", "perPage": "3", "ordCol": "ANL_DT", "ordDir": "D", "useDb": "false"}
WATCHLIST = ROOT / "watchlist.json"
STATE = ROOT / "state.json"
OUT = ROOT / "out"
TEXT_DIR = OUT / "text"
FIG_DIR = OUT / "figs"
REPORT_URL = BASE + "/Research/PdfViewer?rptId={}"
PER_PAGE = 50


def find_edge():
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(c).exists():
            return c
    sys.exit("msedge.exe 를 찾지 못했습니다.")


def set_credentials():
    import getpass, keyring
    keyring.set_password(KEYRING_SERVICE, "id", input("FnGuide 아이디: ").strip())
    keyring.set_password(KEYRING_SERVICE, "pw", getpass.getpass("FnGuide 비밀번호(입력은 보이지 않음): "))
    print("Windows 자격 증명 관리자에 저장했습니다.")


def auto_login(ctx):
    import keyring
    uid, pw = keyring.get_password(KEYRING_SERVICE, "id"), keyring.get_password(KEYRING_SERVICE, "pw")
    if not uid or not pw:
        sys.exit("저장된 자격 증명이 없습니다. 먼저 `python fnguide_reports.py setcred` 를 실행하세요.")
    ctx.clear_cookies()
    page = ctx.new_page()
    page.goto(BASE + "/Users/Login")
    try:
        page.wait_for_selector("#userId", timeout=15000)
    except Exception:
        sys.exit(f"로그인 입력칸을 찾지 못했습니다. 현재 주소: {page.url} / 제목: {page.title()}")
    page.fill("#userId", uid)
    page.fill("#userPw", pw)
    page.click("#loginBtn")
    try:
        page.get_by_role("button", name="확인", exact=True).click(timeout=4000)
    except Exception:
        pass
    try:
        page.wait_for_url(lambda u: "/Users/Login" not in u, timeout=20000)
    except Exception:
        OUT.mkdir(exist_ok=True)
        page.screenshot(path=str(OUT / "login_fail.png"))
        msgs = page.evaluate("""() => [...document.querySelectorAll('.modal, [role=dialog], .dialog, .error, .msg, .validation, .btn-validation, #dialogMessage, .toast')]
            .filter(e => e.offsetParent !== null).map(e => e.innerText.trim().slice(0, 200)).filter(Boolean)""")
        sys.exit(f"자동 로그인 실패: 주소 {page.url} / 화면 메시지: {msgs} / 스크린샷: {OUT / 'login_fail.png'}")
    page.close()


def login(auto=False):
    import subprocess, time
    edge = next((c for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(c).exists()), None)
    if not edge:
        sys.exit("msedge.exe 를 찾지 못했습니다.")
    args = ["--headless=new", "about:blank"] if auto else [BASE]
    proc = subprocess.Popen([edge, "--remote-debugging-port=9222", f"--user-data-dir={ROOT / '.browser_profile_cdp'}", *args],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not auto:
            input("열린 Edge 에서 직접 로그인한 뒤, 창을 닫지 말고 여기서 Enter 를 누르세요...")
        else:
            time.sleep(3)
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            ctx = browser.contexts[0]
            if auto:
                auto_login(ctx)
            page = ctx.new_page()
            page.goto(BASE + "/Research/SearchReport")
            ua = page.evaluate("navigator.userAgent")
            print("0) navigator.webdriver:", page.evaluate("navigator.webdriver"))
            print("1) 브라우저 내부 호출:", page.evaluate("""async(f)=>{const fd=new FormData();for(const k in f)fd.append(k,f[k]);const r=await fetch('/Research/GetReports',{method:'POST',body:fd,headers:{'X-Requested-With':'XMLHttpRequest'}});return r.status+' '+(await r.text()).slice(0,60)}""", TEST_FORM))
            ctx.storage_state(path=str(AUTH))
            UA_FILE.write_text(ua)
            req = p.request.new_context(storage_state=str(AUTH), user_agent=ua)
            res = req.post(BASE + "/Research/GetReports", multipart=TEST_FORM, headers={"X-Requested-With": "XMLHttpRequest"})
            print("2) 저장 세션(+같은 UA) 호출:", res.status, res.text()[:60])
            req.dispose()
            browser.close()
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    print("세션 저장 완료:", AUTH)


JS_POST = """async(f)=>{const fd=new FormData();for(const k in f)fd.append(k,f[k]);
const r=await fetch('/Research/GetReports',{method:'POST',body:fd,headers:{'X-Requested-With':'XMLHttpRequest'}});
return {status:r.status,text:await r.text()}}"""


def search(page, name, code, frm, to):
    reports, page_no = [], 1
    while True:
        form = {
            "estTyp": "2", "action": "0", "period": "0",
            "fromDt": frm, "toDt": to, "exclBlind": "true",
            "srchTyp": "1", "srchKeyword": name, "srchCode": code,
            "menuCd": "1010", "curPage": str(page_no), "perPage": str(PER_PAGE),
            "ordCol": "ANL_DT", "ordDir": "D", "useDb": "false",
        }
        res = page.evaluate(JS_POST, form)
        try:
            data = json.loads(res["text"])
        except ValueError:
            sys.exit("응답을 해석하지 못했습니다. 로그인 세션을 확인하세요: python fnguide_reports.py login")
        if data.get("returnCode") in (401, 403):
            sys.exit("로그인 세션이 만료되었습니다. `python fnguide_reports.py login` 을 다시 실행하세요.")
        if data.get("returnCode") != 0:
            sys.exit(f"API 오류: {data}")
        ds = data["dataSet"]
        batch = ds.get("reports") or []
        reports += batch
        total = ds["searchInfo"][-1]["TOTAL_CNT"]
        if not batch or len(reports) >= total:
            return reports
        page_no += 1


def normalize(r, stock):
    return {
        "id": r["RPT_ID"],
        "stock": stock["name"],
        "code": stock["code"],
        "date": "20" + r["ANL_DT"].replace(".", "-"),
        "broker": r["BROKERAGE"]["NAME"],
        "analysts": [a["NAME"] for a in r["ANALYSTS"]],
        "title": r["RPT_TITLE"],
        "rating": r["RECOMM"],
        "target_price": r["TARGET_PRICE"],
        "summary": r["COMMENT"] or [],
        "pages": r["PAGE_CNT"],
        "url": REPORT_URL.format(r["RPT_ID"]),
    }


def to_markdown(items):
    lines = []
    for stock in dict.fromkeys(i["stock"] for i in items):
        lines.append(f"## {stock}")
        for i in (x for x in items if x["stock"] == stock):
            lines.append(f"### {i['date']} {i['broker']} - {i['title']}")
            lines.append(f"- 투자의견: {i['rating'] or '-'} / 목표주가: {i['target_price'] or '-'} / 애널리스트: {', '.join(i['analysts'])}")
            lines += [f"- {s}" for s in i["summary"]]
            lines.append("")
    return "\n".join(lines)


@contextmanager
def edge_session():
    if not AUTH.exists():
        sys.exit("저장된 로그인 세션이 없습니다. `python fnguide_reports.py login` 을 먼저 실행하세요.")
    state = json.loads(AUTH.read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix="fng_"))
    proc = subprocess.Popen([find_edge(), "--headless=new", "--remote-debugging-port=9223", f"--user-data-dir={tmp}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with sync_playwright() as p:
            for _ in range(30):
                try:
                    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
                    break
                except Exception:
                    time.sleep(0.5)
            else:
                sys.exit("Edge 에 연결하지 못했습니다.")
            ctx = browser.contexts[0]
            ctx.add_cookies(state["cookies"])
            yield ctx
            browser.close()
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


SOURCE_RE = re.compile(r"^\s*(자료|출처|Source|Sources)\s*[:：]", re.I)
MAX_FIGS = 12


def _merge_rects(rects, gap):
    import pymupdf
    rects = [pymupdf.Rect(r.x0 - 0.5, r.y0 - 0.5, r.x1 + 0.5, r.y1 + 0.5) for r in rects]
    changed = True
    while changed:
        changed = False
        out = []
        for r in rects:
            for k, o in enumerate(out):
                if pymupdf.Rect(o.x0 - gap, o.y0 - gap, o.x1 + gap, o.y1 + gap).intersects(r):
                    out[k] = o | r
                    changed = True
                    break
            else:
                out.append(pymupdf.Rect(r))
        rects = out
    return rects


def _segments(page):
    """페이지의 텍스트를 같은 줄 안에서 가로 간격 12pt 이하로 이어진 조각 단위로 쪼갠다. (rect, text, font_size)"""
    import pymupdf
    segs = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            cur = None
            for sp in ln["spans"]:
                if not sp["text"].strip():
                    continue
                r = pymupdf.Rect(sp["bbox"])
                if cur and r.x0 - cur[0].x1 <= 12:
                    cur = (cur[0] | r, cur[1] + sp["text"], max(cur[2], sp["size"]))
                else:
                    if cur:
                        segs.append(cur)
                    cur = (r, sp["text"], sp["size"])
            if cur:
                segs.append(cur)
    return [(r, " ".join(t.split()), sz) for r, t, sz in segs]


def extract_figures(pdf, rpt_id):
    """PDF 에서 '그래픽 덩어리 + 아래 출처(자료:) 줄'이 있는 도표 후보를 PNG 로 잘라 저장한다.
    반환: [{file, page, caption, source, w, h}]. 어느 것이 핵심인지는 호출한 에이전트가 caption 으로 판단한다."""
    import pymupdf
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    outdir = FIG_DIR / str(rpt_id)
    figs = []
    for pno, page in enumerate(doc, 1):
        pr = page.rect
        rects = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
        rects += [pymupdf.Rect(d["rect"]) for d in page.get_drawings()]
        rects = [r for r in rects if r.y0 > pr.height * 0.06 and r.y1 < pr.height * 0.95 and r.get_area() < pr.get_area() * 0.8]
        segs = _segments(page)
        sources = [(r, t) for r, t, _ in segs if SOURCE_RE.match(t)]
        for cl in _merge_rects(rects, gap=8):
            if cl.width < 120 or cl.height < 70:
                continue
            below = [(r, t) for r, t in sources if -10 <= r.y0 - cl.y1 <= 36 and r.x0 < cl.x1 and r.x1 > cl.x0]
            if not below:
                continue
            src_r, src_t = min(below, key=lambda s: abs(s[0].y0 - cl.y1))
            above = [(r, t, sz) for r, t, sz in segs
                     if 0 <= cl.y0 - r.y1 <= 40 and len(t) <= 90 and not SOURCE_RE.match(t)
                     and min(r.x1, cl.x1) - max(r.x0, cl.x0) > 0.4 * r.width]
            title_r, title_t = (None, "")
            if above:
                best = max(above, key=lambda a: (round(a[2]), a[0].y1))
                title_r, title_t = best[0], best[1]
            top = min(cl.y0, title_r.y0) if title_r else cl.y0
            clip = pymupdf.Rect(min(cl.x0, src_r.x0) - 4, top - 4, max(cl.x1, src_r.x1) + 4, src_r.y1 + 4).intersect(pr)
            if clip.width < 140 or clip.height < 90:
                continue
            figs.append((pno, clip, title_t, src_t))
    figs.sort(key=lambda f: (f[0], f[1].y0, f[1].x0))
    result = []
    if figs:
        outdir.mkdir(parents=True, exist_ok=True)
    for n, (pno, clip, title, src) in enumerate(figs[:MAX_FIGS], 1):
        fp = outdir / f"{n:02d}_p{pno}.png"
        doc[pno - 1].get_pixmap(clip=clip, dpi=150).save(str(fp))
        result.append({"file": str(fp), "page": pno, "caption": title, "source": src,
                       "w": round(clip.width), "h": round(clip.height)})
    return result


def save_text(ctx, rpt_id, with_figs=True):
    from pypdf import PdfReader
    page = ctx.new_page()
    try:
        # 뷰어 페이지가 암호화 토큰으로 GetPdfFile 을 호출하므로, 직접 호출 대신 그 응답을 가로챈다
        with page.expect_response(lambda r: "/Research/GetPdfFile" in r.url, timeout=45000) as resp:
            page.goto(REPORT_URL.format(rpt_id))
        data = resp.value.json().get("dataSet") or ""
        pdf = base64.b64decode(data.split("base64,", 1)[-1])
        text = "\n".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(pdf)).pages)
    finally:
        page.close()
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    path = TEXT_DIR / f"{rpt_id}.txt"
    path.write_text(text, encoding="utf-8")
    figs = []
    if with_figs:
        try:
            figs = extract_figures(pdf, rpt_id)
        except Exception as e:
            print(f"[경고] 리포트 {rpt_id} 도표 추출 실패: {e}")
    return path, figs


def try_save_text(ctx, rpt_id, with_figs=True):
    try:
        path, figs = save_text(ctx, rpt_id, with_figs)
        time.sleep(2)
        return str(path), figs
    except Exception as e:
        print(f"[경고] 리포트 {rpt_id} 본문 추출 실패: {e}")
        return None, []


def extract_texts(ids, with_figs=True):
    with edge_session() as ctx:
        for rpt_id in ids:
            path, figs = try_save_text(ctx, rpt_id, with_figs)
            print(rpt_id, path, f"도표 {len(figs)}개")
            for f in figs:
                print("   ", f["page"], f["caption"][:50], "|", f["file"])


def fetch(days, include_seen, with_text=True, with_figs=True):
    watch = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    seen = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    to = date.today()
    frm = to - timedelta(days=days)
    fmt = lambda d: d.strftime("%Y.%m.%d")
    items = []
    with edge_session() as ctx:
        page = ctx.new_page()
        page.goto(BASE + "/Research/SearchReport")
        for stock in watch:
            for r in search(page, stock["name"], stock["code"], fmt(frm), fmt(to)):
                if include_seen or r["RPT_ID"] not in seen:
                    items.append(normalize(r, stock))
            time.sleep(2)
        if with_text:
            for i in items:
                i["text_file"], i["figures"] = try_save_text(ctx, i["id"], with_figs)
    items.sort(key=lambda x: (x["stock"], x["date"]), reverse=False)
    OUT.mkdir(exist_ok=True)
    (OUT / "new_reports.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "new_reports.md").write_text(to_markdown(items), encoding="utf-8")
    STATE.write_text(json.dumps(sorted(seen | {i["id"] for i in items})))
    print(f"신규 리포트 {len(items)}건 -> {OUT / 'new_reports.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["login", "fetch", "setcred", "text"])
    ap.add_argument("ids", nargs="*", type=int, help="text: 본문을 추출할 리포트 ID")
    ap.add_argument("--no-text", action="store_true", help="fetch: PDF 본문 추출 생략")
    ap.add_argument("--no-figs", action="store_true", help="fetch/text: 도표 이미지 추출 생략")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--auto", action="store_true", help="login: 저장된 자격 증명으로 자동 로그인")
    ap.add_argument("--log", help="출력을 이 파일에 덧붙임 (pythonw 등 콘솔 없는 실행용)")
    a = ap.parse_args()
    if a.log:
        from datetime import datetime
        sys.stdout = sys.stderr = open(a.log, "a", encoding="utf-8", buffering=1)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {a.cmd}")
    {"login": lambda: login(a.auto), "setcred": set_credentials, "fetch": lambda: fetch(a.days, a.all, not a.no_text, not a.no_figs),
     "text": lambda: extract_texts(a.ids, not a.no_figs)}[a.cmd]()
