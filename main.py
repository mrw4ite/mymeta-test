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

TEMPLATES = {
    "blank": {
        "badge": "OFFICIAL COMMUNITY",
        "headline": "Your Headline Here",
        "subtext": "Add a short description about your Telegram channel.",
        "bullets": "Benefit one\nBenefit two\nBenefit three",
        "btn_text": "Join free Telegram",
        "btn_color": "#F26522",
        "bg_color": "#F8F5F0",
    },
    "forex": {
        "badge": "CHARTS. CONTEXT. COMMUNITY.",
        "headline": "Understand the move. Learn the market.",
        "subtext": "Daily forex chart discussions, market structure lessons and risk awareness in one free community.",
        "bullets": "Daily chart breakdowns\nBeginner-friendly lessons\nRisk management first",
        "btn_text": "Join free Telegram",
        "btn_color": "#2E5A3E",
        "bg_color": "#EFEFE8",
    },
    "fitness": {
        "badge": "DAILY WORKOUTS · FREE GROUP",
        "headline": "Get stronger every week.",
        "subtext": "Simple home & gym routines, nutrition tips, and daily accountability.",
        "bullets": "Weekly workout plans\nHigh-protein meal ideas\nLive Q&A sessions",
        "btn_text": "Join Fitness Club",
        "btn_color": "#1D4ED8",
        "bg_color": "#EFF6FF",
    },
    "exam": {
        "badge": "EXAM PREP · STUDY NOTES",
        "headline": "Crack your exam with a plan.",
        "subtext": "Free daily mock tests, PDF notes, and topper strategies directly on Telegram.",
        "bullets": "Daily MCQs & quizzes\nFree PDF revision notes\nPrevious year papers",
        "btn_text": "Join Study Channel",
        "btn_color": "#EAB308",
        "bg_color": "#18181B",
    },
}

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
            whatsapp TEXT DEFAULT '',
            password_hash TEXT,
            plan TEXT DEFAULT 'free',
            page_limit INTEGER DEFAULT 2,
            is_admin INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            plan_expires_at INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            email TEXT,
            plan TEXT,
            amount INTEGER,
            utr TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            created_at INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('upi_id', 'yourupi@oksbi')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('merchant_name', 'MyMeta SaaS')")
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
            welcome_msg TEXT DEFAULT '',
            welcome_btn_text TEXT DEFAULT '',
            welcome_btn_url TEXT DEFAULT '',
            created_at INTEGER
        )
    """)
    for col in [
        "ALTER TABLE channels ADD COLUMN welcome_msg TEXT DEFAULT ''",
        "ALTER TABLE channels ADD COLUMN welcome_btn_text TEXT DEFAULT ''",
        "ALTER TABLE channels ADD COLUMN welcome_btn_url TEXT DEFAULT ''",
    ]:
        try:
            c.execute(col)
        except Exception:
            pass
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
            visual_bg_color TEXT DEFAULT '#F5F4EE',
            visual_bullets TEXT DEFAULT 'Daily chart breakdowns
Beginner-friendly lessons
Risk management first',
            visual_disclaimer TEXT DEFAULT 'Educational content only. No financial advice.',
            visual_font_size INTEGER DEFAULT 28,
            visual_delay INTEGER DEFAULT 0,
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
            utm_medium TEXT DEFAULT '',
            utm_content TEXT DEFAULT '',
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
    row = c.execute("SELECT id, email, plan, page_limit, is_admin, is_banned, plan_expires_at FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="User not found.")
    if row[5]:
        conn.close()
        raise HTTPException(status_code=403, detail="Your account has been suspended by Admin.")
    plan, page_limit, expires_at = row[2], row[3], row[6] or 0
    if not row[4] and plan != "free" and expires_at > 0 and expires_at < int(time.time()):
        plan = "free"
        page_limit = PLANS["free"]["limit"]
        expires_at = 0
        c.execute("UPDATE users SET plan=?, page_limit=?, plan_expires_at=0 WHERE id=?", (plan, page_limit, row[0]))
        conn.commit()
    conn.close()
    days_left = max(0, int((expires_at - time.time()) // 86400)) if expires_at > time.time() else 0
    return {"id": row[0], "email": row[1], "plan": plan, "page_limit": page_limit, "is_admin": bool(row[4]), "plan_expires_at": expires_at, "days_left": days_left}


# --- SCHEMAS ---
class AuthRequest(BaseModel):
    email: str
    password: str
    whatsapp: Optional[str] = ""


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
    welcome_msg: Optional[str] = ""
    welcome_btn_text: Optional[str] = ""
    welcome_btn_url: Optional[str] = ""


class ChannelUpdate(BaseModel):
    count_repeat: bool = True
    auto_approve: bool = False
    welcome_msg: Optional[str] = ""
    welcome_btn_text: Optional[str] = ""
    welcome_btn_url: Optional[str] = "" 


class PageCreate(BaseModel):
    title: str
    slug: str
    template: str = "forex"


class PageUpdate(BaseModel):
    mode: str
    visual_badge: Optional[str] = ""
    visual_image: Optional[str] = ""
    visual_headline: Optional[str] = ""
    visual_subtext: Optional[str] = ""
    visual_btn_text: Optional[str] = ""
    visual_btn_color: Optional[str] = "#F26522"
    visual_bg_color: Optional[str] = "#F5F4EE"
    visual_bullets: Optional[str] = ""
    visual_disclaimer: Optional[str] = ""
    visual_font_size: int = 28
    visual_delay: int = 0
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


def get_public_base_url(request: Request) -> str:
    host = request.headers.get("host", request.url.netloc)
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    if host and not host.startswith("localhost") and not host.startswith("127.0.0.1"):
        proto = "https"
    return f"{proto}://{host}".rstrip("/")


def get_page_live_url(slug: str, request: Request) -> str:
    if BASE_DOMAIN:
        return f"https://{slug}.{BASE_DOMAIN}"
    return f"{get_public_base_url(request)}/p/{slug}"


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


@app.get("/admin", response_class=HTMLResponse)
async def saas_admin_panel():
    with open(os.path.join(BASE_DIR, "admin.html"), "r", encoding="utf-8") as f:
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
            "INSERT INTO users (id, email, whatsapp, password_hash, plan, page_limit, is_admin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, email, data.whatsapp or "", hash_password(data.password), plan, limit, is_admin, int(time.time()))
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
    row = c.execute("SELECT id, password_hash, is_banned FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    if not row or not verify_password(data.password, row[1]):
        raise HTTPException(status_code=401, detail="Invalid email ya password.")
    if row[2]:
        raise HTTPException(status_code=403, detail="Account suspended. Contact @millrun.")
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


# --- CAMPAIGN / UTM REPORT & TELEGRAM BROADCAST ---
class BroadcastRequest(BaseModel):
    channel_conn_id: str
    message: str
    btn_text: Optional[str] = ""
    btn_url: Optional[str] = ""


@app.get("/api/stats/utm")
async def stats_utm(user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    pages_rows = c.execute("SELECT id, title FROM pages WHERE user_id=?", (user["id"],)).fetchall()
    if not pages_rows:
        conn.close()
        return []
    page_map = {r[0]: r[1] for r in pages_rows}
    page_ids = list(page_map.keys())
    q_marks = ",".join("?" * len(page_ids))

    click_rows = c.execute(f"""
        SELECT click_id, page_id, utm_source, utm_medium, utm_campaign, utm_content, invite_link, is_fake
        FROM clicks WHERE page_id IN ({q_marks})
    """, page_ids).fetchall()

    capi_links = set(
        r[0] for r in c.execute(f"SELECT invite_link FROM joins WHERE page_id IN ({q_marks}) AND capi_sent=1 AND invite_link != ''", page_ids).fetchall()
    )
    conn.close()

    agg = {}
    for cid, pid, src, med, camp, cont, inv, is_fake in click_rows:
        camp_key = camp.strip() if camp and camp.strip() else "(direct / no campaign)"
        src_key = src.strip() if src and src.strip() else "-"
        med_key = med.strip() if med and med.strip() else "-"
        cont_key = cont.strip() if cont and cont.strip() else "-"
        group_key = (pid, camp_key, src_key, med_key, cont_key)
        if group_key not in agg:
            agg[group_key] = {
                "page_title": page_map.get(pid, "-"),
                "campaign": camp_key,
                "source": src_key,
                "medium": med_key,
                "content": cont_key,
                "real_clicks": 0,
                "fake_clicks": 0,
                "joins": 0
            }
        if is_fake:
            agg[group_key]["fake_clicks"] += 1
        else:
            agg[group_key]["real_clicks"] += 1
            if inv and inv in capi_links:
                agg[group_key]["joins"] += 1

    out = []
    for item in agg.values():
        rc = item["real_clicks"]
        conv_rate = round((item["joins"] / rc) * 100, 1) if rc > 0 else 0.0
        out.append({**item, "conv_rate": conv_rate})
    out.sort(key=lambda x: (x["joins"], x["real_clicks"]), reverse=True)
    return out


@app.post("/api/broadcast/send")
async def send_broadcast(data: BroadcastRequest, user=Depends(get_current_user)):
    if not data.message or not data.message.strip():
        raise HTTPException(status_code=400, detail="Broadcast message khali nahi ho sakta.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    ch = c.execute("SELECT bot_token FROM channels WHERE id=? AND user_id=?", (data.channel_conn_id, user["id"])).fetchone()
    if not ch:
        conn.close()
        raise HTTPException(status_code=404, detail="Connected channel nahi mila.")
    bot_token = ch[0]
    tg_users = [
        r[0] for r in c.execute("SELECT DISTINCT tg_user_id FROM joins WHERE channel_conn_id=? AND tg_user_id IS NOT NULL", (data.channel_conn_id,)).fetchall()
    ]
    conn.close()

    if not tg_users:
        raise HTTPException(status_code=400, detail="Is channel ke liye abhi koi Telegram join-request user record nahi hai.")

    sent_ok = 0
    failed = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for uid in tg_users:
            payload = {"chat_id": uid, "text": data.message.strip(), "parse_mode": "HTML"}
            if data.btn_text and data.btn_url and data.btn_url.strip().startswith("http"):
                payload["reply_markup"] = {
                    "inline_keyboard": [[{"text": data.btn_text.strip(), "url": data.btn_url.strip()}]]
                }
            try:
                r = await client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload)
                if r.status_code == 200 and r.json().get("ok"):
                    sent_ok += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

    return {"status": "completed", "total_targets": len(tg_users), "sent": sent_ok, "failed": failed}


# --- PRO ADMIN ROUTES ---
class AdminBanUpdate(BaseModel):
    user_id: str
    is_banned: bool


@app.get("/api/admin/overview")
async def admin_overview(user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_pages = c.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    total_channels = c.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
    total_views = c.execute("SELECT COALESCE(SUM(views), 0) FROM pages").fetchone()[0]
    total_real = c.execute("SELECT COUNT(*) FROM clicks WHERE is_fake=0").fetchone()[0]
    total_fake = c.execute("SELECT COUNT(*) FROM clicks WHERE is_fake=1").fetchone()[0]
    total_joins = c.execute("SELECT COUNT(*) FROM joins WHERE capi_sent=1").fetchone()[0]

    # Estimate MRR from non-admin paid users
    paid_rows = c.execute("SELECT plan FROM users WHERE is_admin=0 AND plan != 'free'").fetchall()
    mrr = sum(PLANS.get(r[0], {}).get("price", 0) for r in paid_rows)

    labels, real_s, fake_s, join_s = [], [], [], []
    today = datetime.utcnow().date()
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        s_ts = int(datetime(day.year, day.month, day.day).timestamp())
        e_ts = s_ts + 86400
        labels.append(day.strftime("%d %b"))
        real_s.append(c.execute("SELECT COUNT(*) FROM clicks WHERE is_fake=0 AND created_at>=? AND created_at<?", (s_ts, e_ts)).fetchone()[0])
        fake_s.append(c.execute("SELECT COUNT(*) FROM clicks WHERE is_fake=1 AND created_at>=? AND created_at<?", (s_ts, e_ts)).fetchone()[0])
        join_s.append(c.execute("SELECT COUNT(*) FROM joins WHERE capi_sent=1 AND created_at>=? AND created_at<?", (s_ts, e_ts)).fetchone()[0])

    recent_joins = c.execute(
        "SELECT tg_user_id, capi_sent, capi_response, created_at FROM joins ORDER BY created_at DESC LIMIT 15"
    ).fetchall()
    recent_clicks = c.execute(
        "SELECT ip, utm_campaign, is_fake, created_at FROM clicks ORDER BY created_at DESC LIMIT 15"
    ).fetchall()
    conn.close()
    return {
        "total_users": total_users, "paid_users": len(paid_rows), "mrr": mrr,
        "total_pages": total_pages, "total_channels": total_channels, "total_views": total_views,
        "total_real": total_real, "total_fake": total_fake, "total_joins": total_joins,
        "labels": labels, "real_series": real_s, "fake_series": fake_s, "join_series": join_s,
        "recent_joins": [{"tg_user_id": x[0], "capi_sent": bool(x[1]), "capi_response": x[2] or "", "time": x[3]} for x in recent_joins],
        "recent_clicks": [{"ip": x[0], "campaign": x[1] or "-", "is_fake": bool(x[2]), "time": x[3]} for x in recent_clicks],
    }


@app.get("/api/admin/users")
async def admin_list_users(user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT id, email, whatsapp, plan, page_limit, is_admin, is_banned, created_at FROM users ORDER BY created_at DESC").fetchall()
    res = []
    for r in rows:
        p_count = c.execute("SELECT COUNT(*) FROM pages WHERE user_id=?", (r[0],)).fetchone()[0]
        ch_count = c.execute("SELECT COUNT(*) FROM channels WHERE user_id=?", (r[0],)).fetchone()[0]
        res.append({
            "id": r[0], "email": r[1], "whatsapp": r[2] or "", "plan": r[3], "page_limit": r[4],
            "used_pages": p_count, "channels": ch_count, "is_admin": bool(r[5]), "is_banned": bool(r[6]), "created_at": r[7]
        })
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


@app.post("/api/admin/toggle-ban")
async def admin_toggle_ban(data: AdminBanUpdate, user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    if data.user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot ban yourself.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=? WHERE id=?", (int(data.is_banned), data.user_id))
    conn.commit()
    conn.close()
    return {"status": "updated"}


@app.delete("/api/admin/users/{uid}")
async def admin_delete_user(uid: str, user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    if uid == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM pages WHERE user_id=?", (uid,))
    c.execute("DELETE FROM channels WHERE user_id=?", (uid,))
    c.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@app.get("/api/admin/pages")
async def admin_list_pages(request: Request, user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("""
        SELECT p.id, p.title, p.slug, p.mode, p.views, u.email
        FROM pages p LEFT JOIN users u ON p.user_id = u.id ORDER BY p.created_at DESC
    """).fetchall()
    out = []
    for r in rows:
        pid = r[0]
        rc = c.execute("SELECT COUNT(*) FROM clicks WHERE page_id=? AND is_fake=0", (pid,)).fetchone()[0]
        fc = c.execute("SELECT COUNT(*) FROM clicks WHERE page_id=? AND is_fake=1", (pid,)).fetchone()[0]
        jc = c.execute("SELECT COUNT(*) FROM joins WHERE page_id=? AND capi_sent=1", (pid,)).fetchone()[0]
        out.append({"id": pid, "title": r[1], "live_url": get_page_live_url(r[2], request), "mode": r[3], "views": r[4], "owner": r[5] or "-", "real_clicks": rc, "fake_clicks": fc, "joins": jc})
    conn.close()
    return out


@app.delete("/api/admin/pages/{pid}")
async def admin_delete_page(pid: str, user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM pages WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}


@app.get("/api/admin/channels")
async def admin_list_channels(user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("""
        SELECT ch.id, ch.name, ch.channel_id, ch.pixel_id, ch.conversion_event, u.email
        FROM channels ch LEFT JOIN users u ON ch.user_id = u.id ORDER BY ch.created_at DESC
    """).fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "channel_id": r[2], "pixel_id": r[3], "event": r[4], "owner": r[5] or "-"} for r in rows]


# --- AUTOMATED UPI / UTR BILLING ROUTES ---
class PaymentSubmit(BaseModel):
    plan: str
    utr: str


class PaymentAction(BaseModel):
    action: str  # approve or reject


class UpiSettingsUpdate(BaseModel):
    upi_id: str
    merchant_name: str


@app.get("/api/billing/info")
async def billing_info(user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    upi_id = (c.execute("SELECT value FROM settings WHERE key='upi_id'").fetchone() or ("yourupi@oksbi",))[0]
    merchant_name = (c.execute("SELECT value FROM settings WHERE key='merchant_name'").fetchone() or ("MyMeta SaaS",))[0]
    rows = c.execute(
        "SELECT id, plan, amount, utr, status, created_at FROM payments WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
        (user["id"],)
    ).fetchall()
    conn.close()
    return {
        "upi_id": upi_id,
        "merchant_name": merchant_name,
        "plans": PLANS,
        "history": [{"id": r[0], "plan": r[1], "amount": r[2], "utr": r[3], "status": r[4], "time": r[5]} for r in rows]
    }


@app.post("/api/billing/submit")
async def submit_payment(data: PaymentSubmit, user=Depends(get_current_user)):
    if data.plan not in ["starter", "agency", "enterprise"]:
        raise HTTPException(status_code=400, detail="Invalid plan selected.")
    utr = re.sub(r"[^a-zA-Z0-9]", "", data.utr.strip())
    if len(utr) < 8:
        raise HTTPException(status_code=400, detail="Valid 12-digit UTR / Reference Number daalein.")
    amount = PLANS[data.plan]["price"]
    pid = "PAY-" + str(uuid.uuid4())[:8].upper()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO payments (id, user_id, email, plan, amount, utr, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (pid, user["id"], user["email"], data.plan, amount, utr, int(time.time()))
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Ye UTR number pehle hi submit ho chuka hai.")
    conn.close()
    return {"status": "submitted", "payment_id": pid}


@app.get("/api/admin/payments")
async def admin_list_payments(user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute(
        "SELECT id, user_id, email, plan, amount, utr, status, created_at FROM payments ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END, created_at DESC LIMIT 50"
    ).fetchall()
    upi_id = (c.execute("SELECT value FROM settings WHERE key='upi_id'").fetchone() or ("yourupi@oksbi",))[0]
    merchant_name = (c.execute("SELECT value FROM settings WHERE key='merchant_name'").fetchone() or ("MyMeta SaaS",))[0]
    conn.close()
    return {
        "upi_id": upi_id,
        "merchant_name": merchant_name,
        "payments": [{"id": r[0], "user_id": r[1], "email": r[2], "plan": r[3], "amount": r[4], "utr": r[5], "status": r[6], "time": r[7]} for r in rows]
    }


@app.post("/api/admin/payments/{pid}/action")
async def admin_payment_action(pid: str, data: PaymentAction, user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    if data.action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="Invalid action.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    pay = c.execute("SELECT user_id, plan, status FROM payments WHERE id=?", (pid,)).fetchone()
    if not pay:
        conn.close()
        raise HTTPException(status_code=404, detail="Payment not found.")
    if data.action == "approve":
        expires_at = int(time.time()) + 30 * 86400
        c.execute("UPDATE payments SET status='approved' WHERE id=?", (pid,))
        c.execute("UPDATE users SET plan=?, page_limit=?, plan_expires_at=? WHERE id=?",
                  (pay[1], PLANS[pay[1]]["limit"], expires_at, pay[0]))
    else:
        c.execute("UPDATE payments SET status='rejected' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return {"status": data.action + "d"}


@app.post("/api/admin/settings/upi")
async def admin_update_upi(data: UpiSettingsUpdate, user=Depends(get_current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upi_id', ?)", (data.upi_id.strip(),))
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('merchant_name', ?)", (data.merchant_name.strip(),))
    conn.commit()
    conn.close()
    return {"status": "saved"}


# --- CHANNELS ---
@app.post("/api/channels")
async def connect_channel(data: ChannelCreate, request: Request, user=Depends(get_current_user)):
    base_url = get_public_base_url(request)
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
            wh_res = await client.post(
                f"{tg_api}/setWebhook",
                json={"url": f"{base_url}/webhook/{conn_id}", "allowed_updates": ["chat_join_request"], "drop_pending_updates": False}
            )
            if wh_res.status_code != 200 or not wh_res.json().get("ok"):
                raise HTTPException(status_code=400, detail=f"Webhook setup failed: {wh_res.text}")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """INSERT INTO channels (id, user_id, name, channel_id, bot_token, pixel_id, conversion_event,
           capi_token, test_event_code, count_repeat, auto_approve, welcome_msg, welcome_btn_text, welcome_btn_url, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (conn_id, user["id"], data.name, data.channel_id, data.bot_token, data.pixel_id,
         data.conversion_event, data.capi_token, data.test_event_code or "",
         int(data.count_repeat), int(data.auto_approve), data.welcome_msg or "",
         data.welcome_btn_text or "", data.welcome_btn_url or "", int(time.time()))
    )
    conn.commit()
    conn.close()
    return {"status": "connected", "id": conn_id}


@app.get("/api/channels")
async def get_channels(user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute(
        "SELECT id, name, channel_id, pixel_id, conversion_event, test_event_code, auto_approve, count_repeat, welcome_msg, welcome_btn_text, welcome_btn_url FROM channels WHERE user_id=? ORDER BY created_at DESC",
        (user["id"],)
    ).fetchall()
    conn.close()
    return [{
        "id": r[0], "name": r[1], "channel_id": r[2], "pixel_id": r[3],
        "event": r[4], "test_mode": bool(r[5]), "auto_approve": bool(r[6]), "count_repeat": bool(r[7]),
        "welcome_msg": r[8] or "", "welcome_btn_text": r[9] or "", "welcome_btn_url": r[10] or ""
    } for r in rows]


@app.put("/api/channels/{conn_id}")
async def update_channel(conn_id: str, data: ChannelUpdate, user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE channels SET count_repeat=?, auto_approve=?, welcome_msg=?, welcome_btn_text=?, welcome_btn_url=? WHERE id=? AND user_id=?",
        (int(data.count_repeat), int(data.auto_approve), data.welcome_msg or "", data.welcome_btn_text or "", data.welcome_btn_url or "", conn_id, user["id"])
    )
    conn.commit()
    conn.close()
    return {"status": "updated"}


@app.post("/api/channels/{conn_id}/resync")
async def resync_channel_webhook(conn_id: str, request: Request, user=Depends(get_current_user)):
    base_url = get_public_base_url(request)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT bot_token FROM channels WHERE id=? AND user_id=?", (conn_id, user["id"])).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Channel not found")
    webhook_url = f"{base_url}/webhook/{conn_id}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://api.telegram.org/bot{row[0]}/setWebhook",
            json={"url": webhook_url, "allowed_updates": ["chat_join_request"]}
        )
        if r.status_code != 200 or not r.json().get("ok"):
            raise HTTPException(status_code=400, detail=f"Telegram Webhook Error: {r.text}")
    return {"status": "synced", "webhook_url": webhook_url}


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
        tpl = TEMPLATES.get(data.template, TEMPLATES["forex"])
        c.execute(
            """INSERT INTO pages (id, user_id, title, slug, smart_key, visual_badge, visual_headline,
               visual_subtext, visual_bullets, visual_btn_text, visual_btn_color, visual_bg_color, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (page_id, user["id"], data.title, slug, smart_key, tpl["badge"], tpl["headline"],
             tpl["subtext"], tpl["bullets"], tpl["btn_text"], tpl["btn_color"], tpl["bg_color"], int(time.time()))
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Ye subdomain/slug already use ho chuka hai.")
    conn.close()
    return {"id": page_id, "slug": slug, "smart_key": smart_key}


@app.get("/api/pages")
async def list_pages(request: Request, user=Depends(get_current_user)):
    base_url = get_public_base_url(request)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("""
        SELECT id, title, slug, smart_key, mode, visual_badge, visual_image, visual_headline,
               visual_subtext, visual_btn_text, visual_btn_color, visual_bg_color, visual_bullets,
               visual_disclaimer, visual_font_size, visual_delay, custom_html,
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
        btn_matches = len(re.findall(re.escape(f"/t/{smart_key}"), r[16] or ""))

        output.append({
            "id": pid, "title": r[1], "slug": r[2], "smart_key": smart_key,
            "live_url": get_page_live_url(r[2], request), "smart_url": smart_url,
            "mode": r[4], "visual_badge": r[5], "visual_image": r[6], "visual_headline": r[7],
            "visual_subtext": r[8], "visual_btn_text": r[9], "visual_btn_color": r[10],
            "visual_bg_color": r[11], "visual_bullets": r[12], "visual_disclaimer": r[13],
            "visual_font_size": r[14], "visual_delay": r[15], "custom_html": r[16],
            "tracking_mode": r[17], "channel_conn_id": r[18], "normal_pixel_id": r[19],
            "instant_redirect": bool(r[20]), "views": r[21], "real_clicks": real_clicks,
            "fake_clicks": fake_clicks, "verified_joins": joins, "html_button_matches": btn_matches
        })
    conn.close()
    return output


@app.put("/api/pages/{page_id}")
async def update_page(page_id: str, data: PageUpdate, user=Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE pages SET mode=?, visual_badge=?, visual_image=?, visual_headline=?, visual_subtext=?,
        visual_btn_text=?, visual_btn_color=?, visual_bg_color=?, visual_bullets=?, visual_disclaimer=?,
        visual_font_size=?, visual_delay=?, custom_html=?, tracking_mode=?,
        channel_conn_id=?, normal_pixel_id=?, instant_redirect=? WHERE id=? AND user_id=?
    """, (
        data.mode, data.visual_badge, data.visual_image, data.visual_headline, data.visual_subtext,
        data.visual_btn_text, data.visual_btn_color, data.visual_bg_color, data.visual_bullets,
        data.visual_disclaimer, data.visual_font_size, data.visual_delay, data.custom_html,
        data.tracking_mode, data.channel_conn_id, data.normal_pixel_id, int(data.instant_redirect),
        page_id, user["id"]
    ))
    conn.commit()
    conn.close()
    return {"status": "updated"}


@app.post("/api/pages/{page_id}/regen-key")
async def regen_smart_key(page_id: str, request: Request, user=Depends(get_current_user)):
    new_key = str(uuid.uuid4()).replace("-", "")[:10]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE pages SET smart_key=? WHERE id=? AND user_id=?", (new_key, page_id, user["id"]))
    conn.commit()
    conn.close()
    return {"smart_key": new_key, "smart_url": f"{get_public_base_url(request)}/t/{new_key}"}


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
        "SELECT tg_user_id, capi_sent, capi_response, created_at FROM joins WHERE page_id=? ORDER BY created_at DESC LIMIT 30",
        (page_id,)
    ).fetchall()
    conn.close()
    return {
        "clicks": [{"ip": x[0], "fbclid": x[1][:14] + "..." if x[1] else "-", "campaign": x[2] or "-", "is_fake": bool(x[3]), "time": x[4]} for x in clicks],
        "joins": [{"tg_user_id": x[0], "capi_sent": bool(x[1]), "capi_response": x[2] or "", "time": x[3]} for x in joins]
    }


# --- LIVE HOSTED LANDING PAGE ---
@app.get("/p/{slug}", response_class=HTMLResponse)
async def render_landing_page(slug: str, request: Request):
    base_url = get_public_base_url(request)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    page = c.execute("""
        SELECT id, title, smart_key, mode, visual_badge, visual_image, visual_headline, visual_subtext,
               visual_btn_text, visual_btn_color, visual_bg_color, visual_bullets, visual_disclaimer,
               visual_font_size, visual_delay, custom_html, tracking_mode,
               channel_conn_id, normal_pixel_id, instant_redirect
        FROM pages WHERE slug=?
    """, (slug,)).fetchone()
    if not page:
        conn.close()
        raise HTTPException(status_code=404, detail="Landing page not found")

    pid, title, smart_key, mode, badge, img, headline, subtext, btn_text, btn_color, bg_color, bullets, disclaimer, font_size, delay_sec, custom_html, t_mode, ch_id, norm_px, instant_redir = page
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

    img_html = f'<img src="{img}" alt="Logo" class="w-20 h-20 rounded-2xl object-cover mx-auto mb-5 shadow-md" />' if img else ""
    bullets_html = "".join([f'<div class="text-sm text-gray-700">✓ {b.strip()}</div>' for b in (bullets or "").split("\n") if b.strip()])
    delay_script = f"<script>setTimeout(()=>document.getElementById('ctaBtn').classList.remove('hidden'), {int(delay_sec)*1000});</script>" if delay_sec and int(delay_sec) > 0 else ""
    btn_hidden = "hidden" if delay_sec and int(delay_sec) > 0 else ""
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  {pixel_code}
</head>
<body style="background-color:{bg_color};" class="min-h-screen flex items-center justify-center p-5 font-sans">
  <div class="bg-white/95 max-w-md w-full rounded-3xl shadow-xl p-8 text-center border border-black/5">
    <div class="text-[11px] font-bold tracking-[0.15em] text-gray-500 uppercase mb-5">{badge}</div>
    {img_html}
    <h1 style="font-size:{font_size}px;" class="font-extrabold text-gray-900 mb-3 leading-tight">{headline}</h1>
    <p class="text-gray-600 text-sm mb-6 leading-relaxed">{subtext}</p>
    <div class="space-y-2 mb-7">{bullets_html}</div>
    <a id="ctaBtn" href="{smart_url}" style="background-color:{btn_color};"
       class="{btn_hidden} block w-full text-white font-bold py-4 px-6 rounded-2xl shadow-lg hover:opacity-95 transition text-base">
      {btn_text} ➤
    </a>
    <p class="text-[11px] text-gray-400 mt-4">Request to join · Opens in Telegram</p>
    <p class="text-[10px] text-gray-400 mt-4 leading-relaxed">{disclaimer}</p>
  </div>
  {delay_script}
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
        "SELECT COUNT(*) FROM clicks WHERE page_id=? AND ip=? AND is_fake=0 AND created_at > ?",
        (page_id, ip, int(time.time()) - 300)
    ).fetchone()[0]

    is_fake = 1 if (q.get("wd") == "1" or any(b in ua.lower() for b in bot_sigs) or recent_ip_clicks >= 15) else 0
    click_id = str(uuid.uuid4())[:12]

    if is_fake:
        c.execute("""INSERT INTO clicks (click_id, page_id, channel_conn_id, ip, user_agent, fbclid, fbp, fbc,
           utm_source, utm_medium, utm_content, utm_campaign, invite_link, is_fake, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            click_id, page_id, ch_id, ip, ua, q.get("fbclid", ""), q.get("fbp", ""), q.get("fbc", ""),
            q.get("utm_source", ""), q.get("utm_medium", ""), q.get("utm_content", ""), q.get("utm_campaign", ""), "", 1, int(time.time())
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

    c.execute("""INSERT INTO clicks (click_id, page_id, channel_conn_id, ip, user_agent, fbclid, fbp, fbc,
       utm_source, utm_medium, utm_content, utm_campaign, invite_link, is_fake, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
        click_id, page_id, ch_id, ip, ua, q.get("fbclid", ""), q.get("fbp", ""), q.get("fbc", ""),
        q.get("utm_source", ""), q.get("utm_medium", ""), q.get("utm_content", ""), q.get("utm_campaign", ""), invite_link, 0, int(time.time())
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
    tg_first_name = req["from"].get("first_name", "Friend")
    inv_obj = req.get("invite_link", {})
    invite_link = inv_obj.get("invite_link", "")
    inv_name = inv_obj.get("name", "")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cfg = c.execute("""
        SELECT channel_id, bot_token, pixel_id, conversion_event, capi_token,
               test_event_code, count_repeat, auto_approve, welcome_msg, welcome_btn_text, welcome_btn_url
        FROM channels WHERE id=?
    """, (conn_id,)).fetchone()
    if not cfg:
        conn.close()
        return {"ok": True}

    channel_id, bot_token, pixel_id, event_name, capi_token, test_code, count_repeat, auto_approve, welcome_msg, w_btn_text, w_btn_url = cfg

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Auto-approve ONLY if client turned it ON; otherwise stays as join request on channel
        if auto_approve:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/approveChatJoinRequest",
                    json={"chat_id": channel_id, "user_id": tg_user_id}
                )
            except Exception:
                pass

        # 2. Send custom Welcome DM if configured by client
        if welcome_msg and welcome_msg.strip():
            try:
                msg_text = welcome_msg.replace("{name}", tg_first_name)
                dm_payload = {"chat_id": tg_user_id, "text": msg_text, "parse_mode": "HTML"}
                if w_btn_text and w_btn_url and w_btn_url.startswith("http"):
                    dm_payload["reply_markup"] = {
                        "inline_keyboard": [[{"text": w_btn_text.strip(), "url": w_btn_url.strip()}]]
                    }
                await client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=dm_payload)
            except Exception:
                pass

    prior = c.execute("SELECT COUNT(*) FROM joins WHERE channel_conn_id=? AND tg_user_id=?", (conn_id, tg_user_id)).fetchone()[0]
    if prior > 0 and not count_repeat:
        conn.close()
        return {"ok": True, "skipped": "repeat_blocked"}

    click = c.execute("SELECT page_id, ip, user_agent, fbclid, fbp, fbc FROM clicks WHERE invite_link=?", (invite_link,)).fetchone()
    if not click and inv_name.startswith("st_"):
        click_id_from_name = inv_name[3:]
        click = c.execute("SELECT page_id, ip, user_agent, fbclid, fbp, fbc FROM clicks WHERE click_id=?", (click_id_from_name,)).fetchone()

    capi_sent, capi_resp = 0, ""
    page_id = click[0] if click else ""
    base_url = get_public_base_url(request)

    if True:
        if click:
            _, ip, ua, fbclid, fbp, fbc = click
        else:
            ip, ua, fbclid, fbp, fbc = "", "", "", "", ""
        if not fbc and fbclid:
            fbc = f"fb.1.{int(time.time())}.{fbclid}"
        user_data = {
            "external_id": hashlib.sha256(str(tg_user_id).encode()).hexdigest()
        }
        if ip:
            user_data["client_ip_address"] = ip
        if ua:
            user_data["client_user_agent"] = ua
        if fbp:
            user_data["fbp"] = fbp
        if fbc:
            user_data["fbc"] = fbc

        payload = {
            "data": [{
                "event_name": event_name,
                "event_time": int(time.time()),
                "action_source": "website",
                "event_source_url": base_url,
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
