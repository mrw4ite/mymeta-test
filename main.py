import os
import time
import uuid
import re
import hmac
import json
import base64
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Response, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import httpx

app = FastAPI(title="MyMeta Pro SaaS")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "mymeta_pro.db"))
SECRET_KEY = os.getenv("SECRET_KEY", "mymeta-pro-secret-key-change-me-2026")
BASE_DOMAIN = os.getenv("BASE_DOMAIN", "").lower().strip()

PLANS = {
    "free": {"name": "Free Offer", "price": 0, "limit": 2},
    "starter": {"name": "Starter", "price": 1999, "limit": 2},
    "agency": {"name": "Agency", "price": 4999, "limit": 8},
    "enterprise": {"name": "Enterprise", "price": 14999, "limit": 50},
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            password_hash TEXT,
            plan TEXT DEFAULT 'free',
            page_limit INTEGER DEFAULT 2,
            is_admin INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            name TEXT,
            channel_id TEXT,
            bot_token TEXT,
            pixel_id TEXT,
            conversion_event TEXT,
            capi_token TEXT,
            test_event_code TEXT,
            count_repeat INTEGER,
            auto_approve INTEGER,
            created_at INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            title TEXT,
            slug TEXT UNIQUE,
            smart_key TEXT UNIQUE,
            mode TEXT DEFAULT 'visual',
            visual_badge TEXT DEFAULT 'OFFICIAL TELEGRAM COMMUNITY',
            visual_image TEXT DEFAULT '',
            visual_headline TEXT DEFAULT 'Understand the move. Learn the market.',
            visual_subtext TEXT DEFAULT 'Daily analysis, live updates & risk management in one free community.',
            visual_btn_text TEXT DEFAULT 'Join Free Telegram',
            visual_btn_color TEXT DEFAULT '#F26522',
            visual_bg_color TEXT DEFAULT '#F8F5F0',
            custom_html TEXT DEFAULT '',
            tracking_mode TEXT DEFAULT 'smart',
            channel_conn_id TEXT DEFAULT '',
            normal_pixel_id TEXT DEFAULT '',
            instant_redirect INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS clicks (
            click_id TEXT PRIMARY KEY,
            page_id TEXT,
            channel_conn_id TEXT,
            ip TEXT,
            user_agent TEXT,
            fbclid TEXT,
            fbp TEXT,
            fbc TEXT,
            utm_source TEXT,
            utm_campaign TEXT,
            invite_link TEXT,
            is_fake INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS joins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id TEXT,
            channel_conn_id TEXT,
            tg_user_id INTEGER,
            invite_link TEXT,
            capi_sent INTEGER DEFAULT 0,
            capi_response TEXT,
            created_at INTEGER
        )
    """)
    conn.commit()
    conn.close()


init_db()


# --- AUTH ---
def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or uuid.uuid4().hex
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
    return f"{salt}${dk}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$")
        return hmac.compare_digest(hash_password(password, salt), stored)
    except Exception:
        return False


def create_session_token(user_id: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"uid": user_id, "exp": int(time.time()) + 86400 * 7}).encode()).decode()
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token: str) -> Optional[str]:
    try:
        payload, sig = token.split(".")
        expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
        if data.get("exp", 0) < time.time():
            return None
        return data.get("uid")
    except Exception:
        return None


def get_current_user(request: Request):
    token = request.cookies.get("mymeta_session")
    if not token:
        raise HTTPException(status_code=401, detail="Please login first.")
    uid = verify_session_token(token)
    if not uid:
        raise HTTPException(status_code=401, detail="Session expired.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT id, email, plan, page_limit, is_admin FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="User not found.")
    return {"id": row[0], "email": row[1], "plan": row[2], "page_limit": row[3], "is_admin": bool(row[4])}


# --- SCHEMAS ---
class AuthRequest(BaseModel):
    email: str
    password: str


class AdminPlanUpdate(BaseModel):
    user_id: str
    plan: str


class ChannelCreate(BaseModel):
    name: str
    channel_id: str
    bot_token: str
    pixel_id: str
    conversion_event: str = "Subscribe"
    capi_token: str
    test_event_code: Optional[str] = ""
    count_repeat: bool = True
    auto_approve: bool = False
    replace_webhook: bool = True


class PageCreate(BaseModel):
    title: str
    slug: str


class PageUpdate(BaseModel):
    mode: str
    visual_badge: Optional[str] = ""
    visual_image: Optional[str] = ""
    visual_headline: Optional[str] = ""
    visual_subtext: Optional[str] = ""
    visual_btn_text: Optional[str] = ""
    visual_btn_color: Optional[str] = "#F26522"
    visual_bg_color: Optional[str] = "#F8F5F0"
    custom_html: Optional[str] = ""
    tracking_mode: str = "smart"
    channel_conn_id: Optional[str] = ""
    normal_pixel_id: Optional[str] = ""
    instant_redirect: bool = False


# --- HELPERS ---
def build_pixel_snippet(pixel_id: str) -> str:
    if not pixel_id:
        return ""
    return f"""
<script>
!function(f,b,e,v,n,t,s){{if(f.fbq)return;n=f.fbq=function(){{n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)}};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}}(window,
document,'script','https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '{pixel_id}');
fbq('track', 'PageView');
</script>
"""


def build_param_passer_script(smart_key: str) -> str:
    return f"""
<script>
(function(){{
  const urlParams = new URLSearchParams(window.location.search);
  const getCookie = (n) => (document.cookie.match('(^|;)\\\\s*' + n + '\\\\s*=\\\\s*([^;]+)')?.pop() || '');
  document.addEventListener('click', function(e) {{
    const a = e.target.closest('a[href*="/t/{smart_key}"]');
    if (!a) return;
    const u = new URL(a.href, window.location.origin);
    ['fbclid','utm_source','utm_campaign','utm_medium','utm_content'].forEach(k => {{
      if (urlParams.get(k)) u.searchParams.set(k, urlParams.get(k));
    }});
    const fbp = getCookie('_fbp');
    const fbc = getCookie('_fbc');
    if (fbp) u.searchParams.set('fbp', fbp);
    if (fbc) u.searchParams.set('fbc', fbc);
    if (navigator.webdriver) u.searchParams.set('wd', '1');
    a.href = u.toString();
  }});
}})();
</script>
"""


def get_subdomain_slug(request: Request) -> Optional[str]:
    if not BASE_DOMAIN:
        return None
    host = request.headers.get("host", "").split(":")[0].lower()
    if host.endswith(f".{BASE_DOMAIN}"):
        sub = host[: -(len(BASE_DOMAIN) + 1)]
        if sub and sub not in ["www", "app", "api"]:
            return sub
    return None


def get_page_live_url(slug: str, request: Request) -> str:
    if BASE_DOMAIN:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        return f"{scheme}://{slug}.{BASE_DOMAIN}"
    return f"{str(request.base_url).rstrip('/')}/p/{slug}"


# --- FRONTEND ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def home_or_subdomain(request: Request):
    sub_slug = get_subdomain_slug(request)
    if sub_slug:
        return await render_landing_page(sub_slug, request)
    with open(os.path.join(BASE_DIR, "landing.html"), "r", encoding="utf-8") as f:
        return f.read()


@app.get("/app", response_class=HTMLResponse)
async def saas_dashboard():
    with open(os.path.join(BASE_DIR, "dashboard.html"), "r", encoding="utf-8") as f:
        return f.read()


# --- AUTH ROUTES ---
@app.post("/api/auth/register")
async def register(data: AuthRequest, response: Response):
    email = data.email.strip().lower()
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password kam se kam 6 characters ka hona chahiye.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    is_admin = 1 if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 else 0
    plan = "enterprise" if is_admin else "free"
    limit = PLANS[plan]["limit"]
    uid = str(uuid.uuid4())[:10]
    try:
        c.execute(
            "INSERT INTO users (id, email, password_hash, plan, page_limit, is_admin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, email, hash_password(data.password), plan, limit, is_admin, int(time.time()))
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Ye email already registered hai.")
    conn.close()
    response.set_cookie("mymeta_session", create_session_token(uid), httponly=True, samesite="lax", max_age=86400 * 7)
    return {"status": "registered", "is_admin": bool(is_admin)}


@app.post("/api/auth/login")
async def login(data: AuthRequest, response: Response):
    email = data.email.strip().lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT id, password_hash FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    if not row or not verify_password(data.password, row[1]):
        raise HTTPException(status_code=401, detail="Invalid email ya password.")
    response.set_cookie("mymeta_session", create_session_token(row[0]), httponly=True, samesite="lax", max_age=86400 * 7)
    return {"status": "logged_in"}


@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie("mymeta_session")
    return {"status": "logged_out"}


@app.get("/api/auth/me")
async def me(user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    used_pages = c.execute("SELECT COUNT(*) FROM pages WHERE user_id=?", (user["id"],)).fetchone()[0]
    conn.close()
    return {**user, "used_pages": used_pages, "plans": PLANS, "base_domain": BASE_DOMAIN}


# --- OVERVIEW ANALYTICS (REAL 7-DAY DB STATS FOR CHARTS) ---
@app.get("/api/stats/overview")
async def stats_overview(user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    page_ids = [r[0] for r in c.execute("SELECT id FROM pages WHERE user_id=?", (user["id"],)).fetchall()]
    total_views = c.execute("SELECT COALESCE(SUM(views), 0) FROM pages WHERE user_id=?", (user["id"],)).fetchone()[0]

    labels, real_series, fake_series, join_series = [], [], [], []
    today = datetime.utcnow().date()

    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        start_ts = int(datetime(day.year, day.month, day.day).timestamp())
        end_ts = start_ts + 86400
        labels.append(day.strftime("%d %b"))
        if page_ids:
            q_marks = ",".join("?" * len(page_ids))
            rc = c.execute(f"SELECT COUNT(*) FROM clicks WHERE page_id IN ({q_marks}) AND is_fake=0 AND created_at>=? AND created_at<?", (*page_ids, start_ts, end_ts)).fetchone()[0]
            fc = c.execute(f"SELECT COUNT(*) FROM clicks WHERE page_id IN ({q_marks}) AND is_fake=1 AND created_at>=? AND created_at<?", (*page_ids, start_ts, end_ts)).fetchone()[0]
            jc = c.execute(f"SELECT COUNT(*) FROM joins WHERE page_id IN ({q_marks}) AND capi_sent=1 AND created_at>=? AND created_at<?", (*page_ids, start_ts, end_ts)).fetchone()[0]
        else:
            rc, fc, jc = 0, 0, 0
        real_series.append(rc)
        fake_series.append(fc)
        join_series.append(jc)

    conn.close()
    return {
        "total_views": total_views,
        "total_real_clicks": sum(real_series),
        "total_fake_blocked": sum(fake_series),
        "total_joins": sum(join_series),
        "labels": labels,
        "real_series": real_series,
        "fake_series": fake_series,
        "join_series": join_series
    }


# --- ADMIN ROUTES ---
@app.get("/api/admin/users")
async def admin_list_users(user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT id, email, plan, page_limit, is_admin FROM users ORDER BY created_at DESC").fetchall()
    res = []
    for r in rows:
        p_count = c.execute("SELECT COUNT(*) FROM pages WHERE user_id=?", (r[0],)).fetchone()[0]
        res.append({"id": r[0], "email": r[1], "plan": r[2], "page_limit": r[3], "used_pages": p_count, "is_admin": bool(r[4])})
    conn.close()
    return res


@app.post("/api/admin/set-plan")
async def admin_set_plan(data: AdminPlanUpdate, user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    if data.plan not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET plan=?, page_limit=? WHERE id=?", (data.plan, PLANS[data.plan]["limit"], data.user_id))
    conn.commit()
    conn.close()
    return {"status": "plan_updated"}


# --- CHANNELS ---
@app.post("/api/channels")
async def connect_channel(data: ChannelCreate, request: Request, user=Depends(get_current_user)):
    base_url = str(request.base_url).rstrip("/")
    tg_api = f"https://api.telegram.org/bot{data.bot_token}"
    async with httpx.AsyncClient(timeout=15) as client:
        me = await client.get(f"{tg_api}/getMe")
        if me.status_code != 200 or not me.json().get("ok"):
            raise HTTPException(status_code=400, detail="Invalid Telegram Bot Token.")
        bot_id = me.json()["result"]["id"]

        member = await client.get(f"{tg_api}/getChatMember", params={"chat_id": data.channel_id, "user_id": bot_id})
        if member.status_code != 200 or not member.json().get("ok"):
            raise HTTPException(status_code=400, detail="Channel ID galat hai ya Bot channel mein add nahi hai.")
        if member.json()["result"].get("status") not in ["administrator", "creator"]:
            raise HTTPException(status_code=400, detail="Bot ko Channel mein Admin banayein (Invite Users permission ke saath).")

        conn_id = str(uuid.uuid4())[:8]
        if data.replace_webhook and base_url.startswith("https://"):
            await client.post(
                f"{tg_api}/setWebhook",
                json={"url": f"{base_url}/webhook/{conn_id}", "allowed_updates": ["chat_join_request"]}
            )

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO channels VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        conn_id, user["id"], data.name, data.channel_id, data.bot_token, data.pixel_id,
        data.conversion_event, data.capi_token, data.test_event_code or "",
        int(data.count_repeat), int(data.auto_approve), int(time.time())
    ))
    conn.commit()
    conn.close()
    return {"status": "connected", "id": conn_id}


@app.get("/api/channels")
async def get_channels(user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute(
        "SELECT id, name, channel_id, pixel_id, conversion_event, test_event_code, auto_approve, count_repeat FROM channels WHERE user_id=? ORDER BY created_at DESC",
        (user["id"],)
    ).fetchall()
    conn.close()
    return [{
        "id": r[0], "name": r[1], "channel_id": r[2], "pixel_id": r[3],
        "event": r[4], "test_mode": bool(r[5]), "auto_approve": bool(r[6]), "count_repeat": bool(r[7])
    } for r in rows]


@app.delete("/api/channels/{conn_id}")
async def delete_channel(conn_id: str, user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM channels WHERE id=? AND user_id=?", (conn_id, user["id"]))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


# --- PAGES CRUD & LOGS ---
@app.post("/api/pages")
async def create_page(data: PageCreate, user=Depends(get_current_user)):
    slug = re.sub(r"[^a-zA-Z0-9-]", "", data.slug.lower().strip())
    if not slug or slug in ["www", "app", "api", "admin"]:
        raise HTTPException(status_code=400, detail="Valid subdomain/slug daalein (e.g. forextrading)")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    used = c.execute("SELECT COUNT(*) FROM pages WHERE user_id=?", (user["id"],)).fetchone()[0]
    if used >= user["page_limit"]:
        conn.close()
        raise HTTPException(status_code=403, detail=f"Plan limit ({user['page_limit']} pages) full ho gayi hai. Plan upgrade karein!")

    page_id = str(uuid.uuid4())[:8]
    smart_key = str(uuid.uuid4()).replace("-", "")[:10]
    try:
        c.execute(
            "INSERT INTO pages (id, user_id, title, slug, smart_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (page_id, user["id"], data.title, slug, smart_key, int(time.time()))
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Ye subdomain/slug already use ho chuka hai.")
    conn.close()
    return {"id": page_id, "slug": slug, "smart_key": smart_key}


@app.get("/api/pages")
async def list_pages(request: Request, user=Depends(get_current_user)):
    base_url = str(request.base_url).rstrip("/")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("""
        SELECT id, title, slug, smart_key, mode, visual_badge, visual_image, visual_headline,
               visual_subtext, visual_btn_text, visual_btn_color, visual_bg_color, custom_html,
               tracking_mode, channel_conn_id, normal_pixel_id, instant_redirect, views
        FROM pages WHERE user_id=? ORDER BY created_at DESC
    """, (user["id"],)).fetchall()

    output = []
    for r in rows:
        pid, smart_key = r[0], r[3]
        smart_url = f"{base_url}/t/{smart_key}"
        real_clicks = c.execute("SELECT COUNT(*) FROM clicks WHERE page_id=? AND is_fake=0", (pid,)).fetchone()[0]
        fake_clicks = c.execute("SELECT COUNT(*) FROM clicks WHERE page_id=? AND is_fake=1", (pid,)).fetchone()[0]
        joins = c.execute("SELECT COUNT(*) FROM joins WHERE page_id=? AND capi_sent=1", (pid,)).fetchone()[0]
        btn_matches = len(re.findall(re.escape(f"/t/{smart_key}"), r[12] or ""))

        output.append({
            "id": pid, "title": r[1], "slug": r[2], "smart_key": smart_key,
            "live_url": get_page_live_url(r[2], request), "smart_url": smart_url,
            "mode": r[4], "visual_badge": r[5], "visual_image": r[6], "visual_headline": r[7],
            "visual_subtext": r[8], "visual_btn_text": r[9], "visual_btn_color": r[10],
            "visual_bg_color": r[11], "custom_html": r[12], "tracking_mode": r[13],
            "channel_conn_id": r[14], "normal_pixel_id": r[15], "instant_redirect": bool(r[16]),
            "views": r[17], "real_clicks": real_clicks, "fake_clicks": fake_clicks,
            "verified_joins": joins, "html_button_matches": btn_matches
        })
    conn.close()
    return output


@app.put("/api/pages/{page_id}")
async def update_page(page_id: str, data: PageUpdate, user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE pages SET mode=?, visual_badge=?, visual_image=?, visual_headline=?, visual_subtext=?,
        visual_btn_text=?, visual_btn_color=?, visual_bg_color=?, custom_html=?, tracking_mode=?,
        channel_conn_id=?, normal_pixel_id=?, instant_redirect=? WHERE id=? AND user_id=?
    """, (
        data.mode, data.visual_badge, data.visual_image, data.visual_headline, data.visual_subtext,
        data.visual_btn_text, data.visual_btn_color, data.visual_bg_color, data.custom_html,
        data.tracking_mode, data.channel_conn_id, data.normal_pixel_id, int(data.instant_redirect),
        page_id, user["id"]
    ))
    conn.commit()
    conn.close()
    return {"status": "updated"}


@app.delete("/api/pages/{page_id}")
async def delete_page(page_id: str, user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM pages WHERE id=? AND user_id=?", (page_id, user["id"]))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@app.get("/api/pages/{page_id}/logs")
async def page_logs(page_id: str, user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    owner = c.execute("SELECT user_id FROM pages WHERE id=?", (page_id,)).fetchone()
    if not owner or owner[0] != user["id"]:
        conn.close()
        raise HTTPException(status_code=404, detail="Page not found.")
    clicks = c.execute(
        "SELECT ip, fbclid, utm_campaign, is_fake, created_at FROM clicks WHERE page_id=? ORDER BY created_at DESC LIMIT 30",
        (page_id,)
    ).fetchall()
    joins = c.execute(
        "SELECT tg_user_id, capi_sent, created_at FROM joins WHERE page_id=? ORDER BY created_at DESC LIMIT 30",
        (page_id,)
    ).fetchall()
    conn.close()
    return {
        "clicks": [{"ip": x[0], "fbclid": x[1][:14] + "..." if x[1] else "-", "campaign": x[2] or "-", "is_fake": bool(x[3]), "time": x[4]} for x in clicks],
        "joins": [{"tg_user_id": x[0], "capi_sent": bool(x[1]), "time": x[2]} for x in joins]
    }


# --- LIVE HOSTED LANDING PAGE ---
@app.get("/p/{slug}", response_class=HTMLResponse)
async def render_landing_page(slug: str, request: Request):
    base_url = str(request.base_url).rstrip("/")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    page = c.execute("""
        SELECT id, title, smart_key, mode, visual_badge, visual_image, visual_headline, visual_subtext,
               visual_btn_text, visual_btn_color, visual_bg_color, custom_html, tracking_mode,
               channel_conn_id, normal_pixel_id, instant_redirect
        FROM pages WHERE slug=?
    """, (slug,)).fetchone()
    if not page:
        conn.close()
        raise HTTPException(status_code=404, detail="Landing page not found")

    pid, title, smart_key, mode, badge, img, headline, subtext, btn_text, btn_color, bg_color, custom_html, t_mode, ch_id, norm_px, instant_redir = page
    c.execute("UPDATE pages SET views = views + 1 WHERE id=?", (pid,))
    conn.commit()

    if instant_redir and t_mode == "smart":
        qs = str(request.url.query)
        conn.close()
        return RedirectResponse(url=f"{base_url}/t/{smart_key}" + (f"?{qs}" if qs else ""))

    pixel_id = ""
    if t_mode == "smart" and ch_id:
        ch = c.execute("SELECT pixel_id FROM channels WHERE id=?", (ch_id,)).fetchone()
        pixel_id = ch[0] if ch else ""
    elif t_mode == "pixel":
        pixel_id = norm_px
    conn.close()

    pixel_code = build_pixel_snippet(pixel_id)
    param_script = build_param_passer_script(smart_key)
    smart_url = f"{base_url}/t/{smart_key}"

    if mode == "html" and custom_html.strip():
        html = custom_html
        html = html.replace("</head>", f"{pixel_code}</head>", 1) if "</head>" in html else pixel_code + html
        html = html.replace("</body>", f"{param_script}</body>", 1) if "</body>" in html else html + param_script
        return HTMLResponse(content=html)

    img_html = f'<img src="{img}" alt="Banner" class="w-24 h-24 rounded-2xl object-cover mx-auto mb-5 shadow-md" />' if img else ""
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  {pixel_code}
</head>
<body style="background-color:{bg_color};" class="min-h-screen flex items-center justify-center p-5 font-sans">
  <div class="bg-white max-w-md w-full rounded-3xl shadow-2xl p-8 text-center border border-gray-100">
    {img_html}
    <span class="inline-block bg-orange-50 text-[#F26522] text-[11px] font-bold px-3.5 py-1 rounded-full mb-4 tracking-wider">{badge}</span>
    <h1 class="text-3xl font-extrabold text-gray-900 mb-3 leading-tight">{headline}</h1>
    <p class="text-gray-500 text-sm mb-8 leading-relaxed">{subtext}</p>
    <a href="{smart_url}" style="background-color:{btn_color};"
       class="block w-full text-white font-bold py-4 px-6 rounded-2xl shadow-lg hover:opacity-95 transition text-base">
      {btn_text} →
    </a>
    <p class="text-[11px] text-gray-400 mt-6">Verified Telegram Community · Instant Access</p>
  </div>
  {param_script}
</body>
</html>""")


# --- SMART TRACKING ROUTER ---
@app.get("/t/{smart_key}")
async def smart_tracking_redirect(smart_key: str, request: Request):
    ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
    ua = request.headers.get("user-agent", "")
    q = request.query_params

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    page = c.execute("SELECT id, channel_conn_id FROM pages WHERE smart_key=?", (smart_key,)).fetchone()
    if not page or not page[1]:
        conn.close()
        raise HTTPException(status_code=404, detail="Smart Tracking Channel not connected.")
    page_id, ch_id = page

    ch = c.execute("SELECT channel_id, bot_token FROM channels WHERE id=?", (ch_id,)).fetchone()
    if not ch:
        conn.close()
        raise HTTPException(status_code=404, detail="Channel not found.")
    channel_id, bot_token = ch

    bot_sigs = ["bot", "crawler", "spider", "facebookexternalhit", "facebot", "headless", "curl", "python", "wget", "preview"]
    recent_ip_clicks = c.execute(
        "SELECT COUNT(*) FROM clicks WHERE page_id=? AND ip=? AND created_at > ?",
        (page_id, ip, int(time.time()) - 600)
    ).fetchone()[0]

    is_fake = 1 if (q.get("wd") == "1" or any(b in ua.lower() for b in bot_sigs) or recent_ip_clicks >= 3) else 0
    click_id = str(uuid.uuid4())[:12]

    if is_fake:
        c.execute("INSERT INTO clicks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            click_id, page_id, ch_id, ip, ua, q.get("fbclid", ""), q.get("fbp", ""), q.get("fbc", ""),
            q.get("utm_source", ""), q.get("utm_campaign", ""), "", 1, int(time.time())
        ))
        conn.commit()
        conn.close()
        return HTMLResponse("<h3>Traffic verification failed. Open directly in mobile browser.</h3>", status_code=403)

    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(
            f"https://api.telegram.org/bot{bot_token}/createChatInviteLink",
            json={"chat_id": channel_id, "name": f"st_{click_id}", "creates_join_request": True}
        )
        if res.status_code != 200 or not res.json().get("ok"):
            conn.close()
            raise HTTPException(status_code=500, detail="Telegram invite link failed.")
        invite_link = res.json()["result"]["invite_link"]

    c.execute("INSERT INTO clicks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        click_id, page_id, ch_id, ip, ua, q.get("fbclid", ""), q.get("fbp", ""), q.get("fbc", ""),
        q.get("utm_source", ""), q.get("utm_campaign", ""), invite_link, 0, int(time.time())
    ))
    conn.commit()
    conn.close()
    return RedirectResponse(url=invite_link, status_code=302)


# --- TELEGRAM WEBHOOK ---
@app.post("/webhook/{conn_id}")
async def telegram_webhook(conn_id: str, request: Request):
    update = await request.json()
    req = update.get("chat_join_request")
    if not req:
        return {"ok": True}

    tg_user_id = req["from"]["id"]
    invite_link = req.get("invite_link", {}).get("invite_link", "")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cfg = c.execute("""
        SELECT channel_id, bot_token, pixel_id, conversion_event, capi_token,
               test_event_code, count_repeat, auto_approve
        FROM channels WHERE id=?
    """, (conn_id,)).fetchone()
    if not cfg:
        conn.close()
        return {"ok": True}

    channel_id, bot_token, pixel_id, event_name, capi_token, test_code, count_repeat, auto_approve = cfg

    if auto_approve:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/approveChatJoinRequest",
                json={"chat_id": channel_id, "user_id": tg_user_id}
            )

    prior = c.execute("SELECT COUNT(*) FROM joins WHERE channel_conn_id=? AND tg_user_id=?", (conn_id, tg_user_id)).fetchone()[0]
    if prior > 0 and not count_repeat:
        conn.close()
        return {"ok": True, "skipped": "repeat_blocked"}

    click = c.execute("SELECT page_id, ip, user_agent, fbclid, fbp, fbc FROM clicks WHERE invite_link=?", (invite_link,)).fetchone()
    capi_sent, capi_resp = 0, ""
    page_id = click[0] if click else ""

    if click:
        _, ip, ua, fbclid, fbp, fbc = click
        if not fbc and fbclid:
            fbc = f"fb.1.{int(time.time())}.{fbclid}"
        user_data = {
            "client_ip_address": ip,
            "client_user_agent": ua,
            "external_id": hashlib.sha256(str(tg_user_id).encode()).hexdigest()
        }
        if fbp:
            user_data["fbp"] = fbp
        if fbc:
            user_data["fbc"] = fbc

        payload = {
            "data": [{
                "event_name": event_name,
                "event_time": int(time.time()),
                "action_source": "website",
                "event_id": f"tg_{conn_id}_{tg_user_id}_{int(time.time())}",
                "user_data": user_data
            }]
        }
        if test_code:
            payload["test_event_code"] = test_code

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://graph.facebook.com/v19.0/{pixel_id}/events",
                params={"access_token": capi_token},
                json=payload
            )
            capi_resp = r.text[:250]
            if r.status_code == 200:
                capi_sent = 1

    c.execute("INSERT INTO joins (page_id, channel_conn_id, tg_user_id, invite_link, capi_sent, capi_response, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (page_id, conn_id, tg_user_id, invite_link, capi_sent, capi_resp, int(time.time())))
    conn.commit()
    conn.close()
    return {"ok": True, "capi_sent": capi_sent}
