# -*- coding: utf-8 -*-
"""
Sky Group Tasks - Team Task Tracker
متابعة تاسكات التيم
"""

import os
import uuid
import json
import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, jsonify, flash
)

logger = logging.getLogger(__name__)

tasks_bp = Blueprint("tasks", __name__, url_prefix="/tasks",
                     template_folder="templates")

# ── Storage ──────────────────────────────────────────────────────────────────
DATA_DIR = os.getenv(
    "DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
)
os.makedirs(DATA_DIR, exist_ok=True)

TASKS_FILE   = os.path.join(DATA_DIR, "tasks.json")
MEMBERS_FILE = os.path.join(DATA_DIR, "team_members.json")

_lock = threading.Lock()

ADMIN_USERNAME = os.getenv("TASKS_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("TASKS_ADMIN_PASS", "skylines2026")

DEPARTMENTS = {
    "sales":      "المبيعات",
    "marketing":  "التسويق",
    "admin":      "الإداري",
    "operations": "العمليات",
    "design":     "التصميم",
    "cs":         "خدمة العملاء",
    "management": "الإدارة العليا",
}


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def _load(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Load {path}: {e}")
    return default


def _save(path, data):
    with _lock:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Save {path}: {e}")


def load_tasks():
    return _load(TASKS_FILE, [])


def save_tasks(tasks):
    _save(TASKS_FILE, tasks)


def load_members():
    members = _load(MEMBERS_FILE, {})
    # Ensure built-in admin always exists
    if ADMIN_USERNAME not in members:
        members[ADMIN_USERNAME] = {
            "name": "المدير العام",
            "role": "admin",
            "department": "management",
            "password": _hash(ADMIN_PASSWORD),
            "created_at": datetime.now().isoformat(),
        }
        _save(MEMBERS_FILE, members)
    return members


def save_members(members):
    _save(MEMBERS_FILE, members)


# ── Auth helpers ─────────────────────────────────────────────────────────────
def current_user():
    username = session.get("tasks_user")
    if not username:
        return None
    members = load_members()
    m = members.get(username)
    if not m:
        return None
    return {"username": username, **m}


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("tasks.login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u or u.get("role") != "admin":
            flash("هذه الصفحة للمدير فقط", "danger")
            return redirect(url_for("tasks.dashboard"))
        return f(*args, **kwargs)
    return wrapper


# ── Telegram helper (re-uses bot's send_telegram if available) ───────────────
def _send_telegram(text):
    try:
        import requests as _req
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat  = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat:
            return
        _req.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception as e:
        logger.error(f"Telegram: {e}")


# ── Status display map ───────────────────────────────────────────────────────
STATUS_AR = {
    "pending":     ("في انتظار الموافقة", "warning"),
    "approved":    ("معتمدة",             "info"),
    "in_progress": ("جاري التنفيذ",       "primary"),
    "done":        ("مكتملة",             "success"),
    "rejected":    ("مرفوضة",             "secondary"),
    "overdue":     ("متأخرة",             "danger"),
}

PRIORITY_AR = {
    "high":   ("عالية",   "danger"),
    "medium": ("متوسطة",  "warning"),
    "low":    ("منخفضة",  "success"),
}


def _mark_overdue(tasks):
    now = datetime.now()
    changed = False
    for t in tasks:
        if t.get("status") in ("approved", "in_progress", "pending"):
            dl = t.get("deadline")
            if dl:
                try:
                    if datetime.fromisoformat(dl) < now:
                        t["status"] = "overdue"
                        changed = True
                except Exception:
                    pass
    return changed


# ── Background overdue checker ───────────────────────────────────────────────
def _overdue_loop():
    while True:
        time.sleep(3600)  # every hour
        try:
            tasks = load_tasks()
            changed = _mark_overdue(tasks)
            if changed:
                save_tasks(tasks)
                overdue = [t for t in tasks if t["status"] == "overdue"]
                if overdue:
                    lines = "\n".join(
                        f"• {t['title']} — {t.get('created_by','?')} (موعد: {t.get('deadline','?')[:10]})"
                        for t in overdue
                    )
                    _send_telegram(
                        f"⏰ <b>تنبيه: تاسكات متأخرة!</b>\n\n{lines}\n\n"
                        f"🔗 لمتابعة: /tasks/"
                    )
        except Exception as e:
            logger.error(f"Overdue loop: {e}")


def start_overdue_checker():
    t = threading.Thread(target=_overdue_loop, daemon=True)
    t.start()


# ── Routes ────────────────────────────────────────────────────────────────────

@tasks_bp.route("/")
@login_required
def dashboard():
    tasks = load_tasks()
    _mark_overdue(tasks)
    u = current_user()
    if u["role"] == "admin":
        visible = tasks
    else:
        visible = [t for t in tasks if t["created_by"] == u["username"]]

    # counts for admin stats bar
    counts = {
        "total":       len(visible),
        "pending":     sum(1 for t in visible if t["status"] == "pending"),
        "in_progress": sum(1 for t in visible if t["status"] == "in_progress"),
        "done":        sum(1 for t in visible if t["status"] == "done"),
        "overdue":     sum(1 for t in visible if t["status"] == "overdue"),
    }

    status_filter   = request.args.get("status", "")
    member_filter   = request.args.get("member", "")
    priority_filter = request.args.get("priority", "")

    if status_filter:
        visible = [t for t in visible if t["status"] == status_filter]
    if member_filter and u["role"] == "admin":
        visible = [t for t in visible if t.get("created_by") == member_filter]
    if priority_filter:
        visible = [t for t in visible if t.get("priority") == priority_filter]

    # sort: overdue first, then by deadline
    visible.sort(key=lambda t: (
        0 if t["status"] == "overdue" else
        1 if t["status"] == "pending" else
        2 if t["status"] == "in_progress" else 3,
        t.get("deadline") or "9999"
    ))

    dept_filter = request.args.get("dept", "")
    if dept_filter and u["role"] == "admin":
        dept_members = [uname for uname, m in load_members().items()
                        if m.get("department") == dept_filter]
        visible = [t for t in visible if t.get("created_by") in dept_members]

    members = load_members()
    return render_template(
        "tasks/dashboard.html",
        tasks=visible, counts=counts,
        user=u, members=members,
        STATUS_AR=STATUS_AR, PRIORITY_AR=PRIORITY_AR,
        DEPARTMENTS=DEPARTMENTS,
        status_filter=status_filter,
        member_filter=member_filter,
        priority_filter=priority_filter,
        dept_filter=dept_filter,
    )


@tasks_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("tasks.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        members  = load_members()
        m = members.get(username)
        if m and m.get("password") == _hash(password):
            session["tasks_user"] = username
            return redirect(url_for("tasks.dashboard"))
        flash("اسم المستخدم أو كلمة السر غلط", "danger")
    return render_template("tasks/login.html")


@tasks_bp.route("/logout")
def logout():
    session.pop("tasks_user", None)
    return redirect(url_for("tasks.login"))


@tasks_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_task():
    u = current_user()
    if request.method == "POST":
        steps_raw = request.form.getlist("steps[]")
        steps = [
            {"id": i + 1, "title": s.strip(), "done": False}
            for i, s in enumerate(steps_raw) if s.strip()
        ]
        deadline_str = request.form.get("deadline", "")
        task = {
            "id":          str(uuid.uuid4())[:8],
            "title":       request.form.get("title", "").strip(),
            "description": request.form.get("description", "").strip(),
            "category":    request.form.get("category", "عام").strip(),
            "priority":    request.form.get("priority", "medium"),
            "deadline":    deadline_str,
            "estimated_hours": request.form.get("estimated_hours", ""),
            "steps":       steps,
            "status":      "pending",
            "notes":       request.form.get("notes", "").strip(),
            "admin_notes": "",
            "created_by":  u["username"],
            "created_at":  datetime.now().isoformat(),
            "approved_by": None,
            "approved_at": None,
            "completed_at": None,
            "updates":     [],
        }
        if not task["title"]:
            flash("عنوان التاسك مطلوب", "danger")
            return render_template("tasks/new_task.html", user=u)

        tasks = load_tasks()
        tasks.append(task)
        save_tasks(tasks)

        # Notify admin
        dl_display = deadline_str[:10] if deadline_str else "—"
        _send_telegram(
            f"📋 <b>تاسك جديدة تنتظر موافقتك</b>\n\n"
            f"👤 من: {u.get('name', u['username'])}\n"
            f"📌 العنوان: {task['title']}\n"
            f"⭐ الأولوية: {PRIORITY_AR.get(task['priority'], ('',''))[0]}\n"
            f"📅 الموعد النهائي: {dl_display}\n"
            f"🔢 الخطوات: {len(steps)}\n\n"
            f"✅ وافق عليها من: /tasks/{task['id']}"
        )
        flash("تم إرسال التاسك للمدير للموافقة ✅", "success")
        return redirect(url_for("tasks.dashboard"))

    return render_template("tasks/new_task.html", user=u)


@tasks_bp.route("/<task_id>")
@login_required
def task_detail(task_id):
    tasks = load_tasks()
    task  = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        flash("التاسك مش موجودة", "danger")
        return redirect(url_for("tasks.dashboard"))
    u = current_user()
    if u["role"] != "admin" and task["created_by"] != u["username"]:
        flash("مش مسموح لك تشوف التاسك دي", "danger")
        return redirect(url_for("tasks.dashboard"))
    members = load_members()
    return render_template(
        "tasks/task_detail.html",
        task=task, user=u, members=members,
        STATUS_AR=STATUS_AR, PRIORITY_AR=PRIORITY_AR,
    )


@tasks_bp.route("/<task_id>/approve", methods=["POST"])
@admin_required
def approve_task(task_id):
    tasks = load_tasks()
    task  = next((t for t in tasks if t["id"] == task_id), None)
    if task:
        task["status"]      = "approved"
        task["approved_by"] = session["tasks_user"]
        task["approved_at"] = datetime.now().isoformat()
        task["admin_notes"] = request.form.get("admin_notes", "")
        save_tasks(tasks)

        members = load_members()
        owner   = members.get(task["created_by"], {})
        _send_telegram(
            f"✅ <b>تمت الموافقة على تاسكتك</b>\n\n"
            f"📌 {task['title']}\n"
            f"👤 لـ: {owner.get('name', task['created_by'])}\n"
            f"📅 الموعد النهائي: {task.get('deadline','')[:10]}\n"
            + (f"💬 ملاحظة المدير: {task['admin_notes']}" if task['admin_notes'] else "")
        )
        flash("تمت الموافقة على التاسك ✅", "success")
    return redirect(url_for("tasks.task_detail", task_id=task_id))


@tasks_bp.route("/<task_id>/reject", methods=["POST"])
@admin_required
def reject_task(task_id):
    tasks = load_tasks()
    task  = next((t for t in tasks if t["id"] == task_id), None)
    if task:
        task["status"]      = "rejected"
        task["admin_notes"] = request.form.get("admin_notes", "")
        save_tasks(tasks)

        members = load_members()
        owner   = members.get(task["created_by"], {})
        _send_telegram(
            f"❌ <b>تم رفض التاسك</b>\n\n"
            f"📌 {task['title']}\n"
            f"👤 لـ: {owner.get('name', task['created_by'])}\n"
            + (f"💬 سبب الرفض: {task['admin_notes']}" if task['admin_notes'] else "")
        )
        flash("تم رفض التاسك", "secondary")
    return redirect(url_for("tasks.task_detail", task_id=task_id))


@tasks_bp.route("/<task_id>/start", methods=["POST"])
@login_required
def start_task(task_id):
    u     = current_user()
    tasks = load_tasks()
    task  = next((t for t in tasks if t["id"] == task_id), None)
    if task and task["created_by"] == u["username"] and task["status"] == "approved":
        task["status"] = "in_progress"
        _add_update(task, u, "بدأ تنفيذ التاسك")
        save_tasks(tasks)
        flash("تم تغيير الحالة إلى جاري التنفيذ", "primary")
    return redirect(url_for("tasks.task_detail", task_id=task_id))


@tasks_bp.route("/<task_id>/done", methods=["POST"])
@login_required
def complete_task(task_id):
    u     = current_user()
    tasks = load_tasks()
    task  = next((t for t in tasks if t["id"] == task_id), None)
    if task and (task["created_by"] == u["username"] or u["role"] == "admin"):
        task["status"]       = "done"
        task["completed_at"] = datetime.now().isoformat()
        note = request.form.get("completion_note", "")
        _add_update(task, u, f"تم إنهاء التاسك. {note}".strip())
        save_tasks(tasks)

        members = load_members()
        owner   = members.get(task["created_by"], {})
        _send_telegram(
            f"🏁 <b>تاسك اتعملت!</b>\n\n"
            f"📌 {task['title']}\n"
            f"👤 {owner.get('name', task['created_by'])}\n"
            + (f"💬 {note}" if note else "")
        )
        flash("تم إنهاء التاسك ✅", "success")
    return redirect(url_for("tasks.task_detail", task_id=task_id))


@tasks_bp.route("/<task_id>/step/<int:step_id>/toggle", methods=["POST"])
@login_required
def toggle_step(task_id, step_id):
    u     = current_user()
    tasks = load_tasks()
    task  = next((t for t in tasks if t["id"] == task_id), None)
    if task and (task["created_by"] == u["username"] or u["role"] == "admin"):
        for s in task.get("steps", []):
            if s["id"] == step_id:
                s["done"] = not s["done"]
                break
        save_tasks(tasks)
    return redirect(url_for("tasks.task_detail", task_id=task_id))


@tasks_bp.route("/<task_id>/update", methods=["POST"])
@login_required
def add_update(task_id):
    u     = current_user()
    tasks = load_tasks()
    task  = next((t for t in tasks if t["id"] == task_id), None)
    note  = request.form.get("update_text", "").strip()
    if task and note and (task["created_by"] == u["username"] or u["role"] == "admin"):
        _add_update(task, u, note)
        save_tasks(tasks)

        if u["role"] != "admin":
            _send_telegram(
                f"💬 <b>تحديث على تاسك</b>\n\n"
                f"📌 {task['title']}\n"
                f"👤 {u.get('name', u['username'])}: {note}"
            )
        flash("تم إضافة التحديث", "success")
    return redirect(url_for("tasks.task_detail", task_id=task_id))


def _add_update(task, u, text):
    task.setdefault("updates", []).append({
        "by":   u["username"],
        "name": u.get("name", u["username"]),
        "text": text,
        "at":   datetime.now().isoformat(),
    })


# ── Team management (admin only) ──────────────────────────────────────────────

@tasks_bp.route("/team")
@admin_required
def team():
    members = load_members()
    tasks   = load_tasks()
    stats   = {}
    for uname in members:
        utasks  = [t for t in tasks if t["created_by"] == uname]
        stats[uname] = {
            "total":   len(utasks),
            "done":    sum(1 for t in utasks if t["status"] == "done"),
            "overdue": sum(1 for t in utasks if t["status"] == "overdue"),
            "pending": sum(1 for t in utasks if t["status"] == "pending"),
        }
    u = current_user()
    return render_template(
        "tasks/team.html",
        members=members, stats=stats,
        user=u, DEPARTMENTS=DEPARTMENTS,
    )


@tasks_bp.route("/team/add", methods=["POST"])
@admin_required
def add_member():
    username   = request.form.get("username", "").strip().lower()
    name       = request.form.get("name", "").strip()
    password   = request.form.get("password", "").strip()
    department = request.form.get("department", "admin").strip()
    if not username or not name or not password:
        flash("كل الحقول مطلوبة", "danger")
        return redirect(url_for("tasks.team"))
    members = load_members()
    if username in members:
        flash("المستخدم موجود بالفعل", "danger")
        return redirect(url_for("tasks.team"))
    members[username] = {
        "name":       name,
        "role":       "member",
        "department": department,
        "password":   _hash(password),
        "created_at": datetime.now().isoformat(),
    }
    save_members(members)
    dept_name = DEPARTMENTS.get(department, department)
    _send_telegram(
        f"👋 <b>عضو جديد انضم للتيم</b>\n\n"
        f"👤 {name} (@{username})\n🏢 القسم: {dept_name}"
    )
    flash(f"تم إضافة {name} لقسم {dept_name} ✅", "success")
    return redirect(url_for("tasks.team"))


@tasks_bp.route("/team/<username>/delete", methods=["POST"])
@admin_required
def delete_member(username):
    if username == ADMIN_USERNAME:
        flash("ممنوع حذف الأدمين", "danger")
        return redirect(url_for("tasks.team"))
    members = load_members()
    members.pop(username, None)
    save_members(members)
    flash("تم حذف العضو", "secondary")
    return redirect(url_for("tasks.team"))


@tasks_bp.route("/team/<username>/reset-password", methods=["POST"])
@admin_required
def reset_password(username):
    new_pw  = request.form.get("new_password", "").strip()
    if not new_pw:
        flash("كلمة السر مطلوبة", "danger")
        return redirect(url_for("tasks.team"))
    members = load_members()
    if username in members:
        members[username]["password"] = _hash(new_pw)
        save_members(members)
        flash("تم تغيير كلمة السر ✅", "success")
    return redirect(url_for("tasks.team"))


# ── API ───────────────────────────────────────────────────────────────────────

@tasks_bp.route("/api/stats")
@login_required
def api_stats():
    tasks   = load_tasks()
    u       = current_user()
    visible = tasks if u["role"] == "admin" else [t for t in tasks if t["created_by"] == u["username"]]
    return jsonify({
        "total":       len(visible),
        "pending":     sum(1 for t in visible if t["status"] == "pending"),
        "approved":    sum(1 for t in visible if t["status"] == "approved"),
        "in_progress": sum(1 for t in visible if t["status"] == "in_progress"),
        "done":        sum(1 for t in visible if t["status"] == "done"),
        "overdue":     sum(1 for t in visible if t["status"] == "overdue"),
    })
