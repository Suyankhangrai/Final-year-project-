from dotenv import load_dotenv
load_dotenv()

import os
import threading
import time
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template_string, redirect,
    url_for, request, session, send_from_directory, flash, jsonify
)
import db


try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    BASE_DIR = os.getcwd()

def safe_makedirs(path):
   
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        print(f"Warning: Could not create directory {path}: {e}")
        return False

TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR   = os.path.join(BASE_DIR, "static")

safe_makedirs(TEMPLATE_DIR)
safe_makedirs(STATIC_DIR)

app = Flask(__name__,
            template_folder=TEMPLATE_DIR if os.path.exists(TEMPLATE_DIR) else None,
            static_folder=STATIC_DIR     if os.path.exists(STATIC_DIR)   else None)

# Secret key from environment variable — set FLASK_SECRET_KEY in your .env file
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

UPLOAD_FOLDER = os.path.join(STATIC_DIR, "pet_photos")
safe_makedirs(UPLOAD_FOLDER)

app.config["UPLOAD_FOLDER"]      = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

device_status   = {"online": False}
pending_command = {"command": "none", "pet_name": "", "grams": 0}


def schedule_checker():
    print("[SCHEDULER] thread started")
    while True:
        try:
            now          = datetime.now()
            current_time = now.strftime("%H:%M")
            current_day  = now.strftime("%a").lower()
            current_date = now.strftime("%Y-%m-%d")

            schedules = db.get_active_schedules()

            for s in schedules:
                if s["feed_time"] != current_time:
                    continue

                days_raw  = s.get("days")
                days      = days_raw.lower() if days_raw else "everyday"
                day_match = (days == "everyday") or (current_day in days)

                # Skip if already served today
                if str(s.get("last_served_date")) == current_date:
                    continue

                if day_match and pending_command["command"] == "none":
                    pending_command["command"]  = "feed"
                    pending_command["pet_name"] = s["pet_name"]
                    pending_command["grams"]    = float(s["grams"])
                    db.update_last_served(s["schedule_id"], current_date)
                    print(f"[SCHEDULER] Triggered: {s['pet_name']} at {current_time}")

        except Exception as e:
            print(f"[SCHEDULER ERROR]: {e}")

        time.sleep(30)

scheduler_thread = threading.Thread(target=schedule_checker, daemon=True)
scheduler_thread.start()


BASE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Smart Pet Feeder</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      --bg: #020617;
      --accent: #22c55e;
      --accent-soft: rgba(34,197,94,0.12);
      --accent-border: rgba(34,197,94,0.4);
      --accent-text: #bbf7d0;
      --text-main: #f9fafb;
      --text-muted: #9ca3af;
      --border-subtle: rgba(31,41,55,0.95);
      --border-strong: rgba(55,65,81,0.9);
      --danger: #ef4444;
      --danger-soft: rgba(239,68,68,0.12);
      --danger-border: rgba(239,68,68,0.4);
      --radius-lg: 18px;
      --radius-md: 12px;
      --radius-pill: 999px;
      --shadow-card: 0 14px 32px rgba(0,0,0,0.75);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; padding: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at top, #0f172a 0, #020617 45%);
      color: var(--text-main);
      min-height: 100vh;
    }
    .app-shell { min-height: 100vh; display: flex; flex-direction: column; }
    .topbar {
      position: sticky; top: 0; z-index: 20;
      padding: 12px 18px; display: flex; align-items: center; justify-content: space-between;
      background: rgba(15,23,42,0.97); backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border-subtle);
      box-shadow: 0 10px 30px rgba(0,0,0,0.8);
    }
    .topbar-left { display: flex; align-items: center; gap: 12px; }
    .topbar-icon {
      width: 36px; height: 36px; border-radius: 12px;
      display: inline-flex; align-items: center; justify-content: center;
      background: radial-gradient(circle at 30% 30%, #bbf7d0 0, #22c55e 60%, #14532d 100%);
      color: #022c22; font-size: 18px;
      box-shadow: 0 0 18px rgba(34,197,94,0.7);
    }
    .topbar-title-text { display: flex; flex-direction: column; }
    .topbar-title-main { font-weight: 650; font-size: 18px; }
    .topbar-title-sub  { font-size: 11px; color: var(--text-muted); }
    .topbar-user { display: flex; align-items: center; gap: 10px; font-size: 13px; }
    .topbar-user-name {
      padding: 6px 12px; border-radius: var(--radius-pill);
      background: rgba(15,23,42,0.8); border: 1px solid var(--border-strong);
    }
    .topbar-user a {
      padding: 6px 14px; border-radius: var(--radius-pill);
      border: 1px solid var(--border-strong); background: rgba(15,23,42,0.9);
      text-decoration: none; color: var(--text-main); font-weight: 500; font-size: 12px;
    }
    .screen { flex: 1; display: flex; justify-content: center; padding: 24px 16px 28px; }
    .screen-inner { width: 100%; max-width: 520px; }
    .section-heading {
      font-size: 13px; text-transform: uppercase; letter-spacing: 0.12em;
      color: var(--text-muted); margin-bottom: 12px;
      display: flex; align-items: center; gap: 10px;
    }
    .section-dot {
      width: 8px; height: 8px; border-radius: 999px;
      background: var(--accent); box-shadow: 0 0 12px rgba(34,197,94,0.8);
    }
    .card {
      background: radial-gradient(circle at top left, rgba(34,197,94,0.06), #020617 45%);
      border-radius: var(--radius-lg); padding: 20px;
      box-shadow: var(--shadow-card); border: 1px solid var(--border-subtle);
      margin-bottom: 20px;
    }
    .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
    .card-title    { font-size: 18px; font-weight: 600; }
    .card-subtitle { font-size: 13px; color: var(--text-muted); }
    .pill-status {
      font-size: 11px; padding: 6px 12px; border-radius: var(--radius-pill);
      border: 1px solid var(--border-strong); background: rgba(15,23,42,0.92);
      display: inline-flex; align-items: center; gap: 8px;
    }
    .pill-dot-online, .pill-dot-offline { width: 8px; height: 8px; border-radius: 999px; }
    .pill-dot-online  { background: #22c55e; box-shadow: 0 0 10px rgba(34,197,94,0.9); }
    .pill-dot-offline { background: #f97316; box-shadow: 0 0 10px rgba(249,115,22,0.9); }
    .field-label {
      font-size: 13px; font-weight: 600; margin: 14px 0 6px;
      color: var(--text-muted); display: block;
    }
    .field-input, select {
      width: 100%; padding: 11px 14px; border-radius: var(--radius-md);
      border: 1px solid var(--border-strong); font-size: 14px;
      background: rgba(15,23,42,0.95); color: var(--text-main); outline: none;
    }
    .field-input:focus, select:focus {
      border-color: var(--accent-border); box-shadow: 0 0 0 2px var(--accent-soft);
    }
    .btn, button {
      display: inline-flex; align-items: center; justify-content: center;
      padding: 10px 20px; border-radius: var(--radius-pill);
      border: 1px solid transparent;
      background: linear-gradient(135deg, #22c55e, #16a34a);
      color: #022c22; font-size: 14px; font-weight: 600;
      cursor: pointer; text-decoration: none;
      box-shadow: 0 10px 26px rgba(0,0,0,0.75);
    }
    .btn.secondary {
      background: rgba(15,23,42,0.96); color: var(--text-main);
      border-color: var(--border-strong);
    }
    .btn.small  { padding: 7px 14px; font-size: 12px; }
    .btn.danger {
      background: var(--danger-soft); color: #fecaca;
      border-color: var(--danger-border);
    }
    .feed-circle {
      width: 96px; height: 96px; border-radius: 50%;
      border: 1px solid var(--accent-border);
      background: radial-gradient(circle at 30% 30%, #bbf7d0 0, #22c55e 60%, #166534 100%);
      color: #022c22; font-size: 20px; font-weight: 750;
      display: inline-flex; align-items: center; justify-content: center;
      cursor: pointer; box-shadow: 0 18px 40px rgba(0,0,0,0.9);
    }
    .pet-list {
      list-style: none; padding: 0; margin: 0;
      display: flex; flex-direction: column; gap: 12px;
    }
    .pet-item {
      border-radius: var(--radius-md); background: rgba(15,23,42,0.98);
      border: 1px solid var(--border-subtle); padding: 12px;
      display: flex; flex-direction: column; gap: 8px;
    }
    .pet-main  { display: flex; gap: 12px; align-items: center; }
    .pet-thumb {
      width: 64px; height: 64px; border-radius: 16px; overflow: hidden;
      background: rgba(15,23,42,0.9); border: 1px solid var(--border-strong);
      display: flex; align-items: center; justify-content: center;
      font-size: 12px; color: var(--text-muted);
    }
    .pet-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .pet-text   { flex: 1; }
    .pet-name   { font-weight: 600; font-size: 16px; }
    .pet-meta   { font-size: 13px; color: var(--text-muted); margin-top: 4px; }
    .pet-footer { display: flex; justify-content: flex-end; }
    .add-circle {
      width: 38px; height: 38px; border-radius: 50%;
      border: 1px solid var(--accent-border);
      background: rgba(22,163,74,0.12); color: var(--accent-text);
      font-size: 22px; display: inline-flex;
      align-items: center; justify-content: center; cursor: pointer;
    }
    .login-hero        { margin-bottom: 20px; }
    .login-hero-title  { font-size: 24px; font-weight: 650; margin-bottom: 6px; }
    .login-hero-text   { font-size: 14px; color: var(--text-muted); }
    .muted-text        { font-size: 13px; color: var(--text-muted); }
    .log-list {
      list-style: none; padding: 0; margin: 0;
      max-height: 280px; overflow-y: auto;
    }
    .log-item {
      font-size: 13px; color: var(--text-muted); padding: 10px 0;
      border-bottom: 1px dashed rgba(55,65,81,0.8);
    }
    .schedule-list {
      list-style: none; padding: 0; margin: 0;
      display: flex; flex-direction: column; gap: 10px;
    }
    .schedule-item {
      border-radius: var(--radius-md); background: rgba(15,23,42,0.98);
      border: 1px solid var(--border-subtle); padding: 14px;
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
    }
    .schedule-info { display: flex; flex-direction: column; gap: 4px; }
    .schedule-time { font-size: 22px; font-weight: 700; color: var(--accent-text); }
    .schedule-meta { font-size: 13px; color: var(--text-muted); }
    .days-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
    .day-checkbox { display: flex; align-items: center; gap: 4px; font-size: 13px; color: var(--text-muted); cursor: pointer; }
    .bottom-nav {
      position: sticky; bottom: 0; padding: 12px 0;
      background: rgba(15,23,42,0.98); backdrop-filter: blur(14px);
      display: flex; justify-content: center; gap: 8px;
      border-top: 1px solid var(--border-subtle); margin-top: 24px;
    }
    .btn-nav { flex-direction: column; min-width: 70px; padding: 8px 12px; gap: 4px; }
    .btn-nav.active {
      background: rgba(34,197,94,0.15);
      border-color: var(--accent-border);
      color: var(--accent-text);
    }
    .flash-container {
      position: fixed; top: 80px; right: 20px;
      z-index: 100; max-width: 400px;
    }
    .flash {
      padding: 14px 18px; border-radius: var(--radius-md);
      margin-bottom: 10px; font-size: 14px;
    }
    .flash-success { background: var(--accent-soft); color: var(--accent-text); border: 1px solid var(--accent-border); }
    .flash-error   { background: var(--danger-soft); color: #fecaca; border: 1px solid var(--danger-border); }
    .layout-grid { display: grid; gap: 20px; }
    @media (min-width: 768px) {
      .screen-inner { max-width: 800px; }
      .layout-grid  { grid-template-columns: 2fr 1.4fr; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <div class="topbar">
      <div class="topbar-left">
        <div class="topbar-icon">🐾</div>
        <div class="topbar-title-text">
          <div class="topbar-title-main">Smart Pet Feeder</div>
          <div class="topbar-title-sub">Control & monitor feeding</div>
        </div>
      </div>
      {% if session.get('user') %}
        <div class="topbar-user">
          <div class="topbar-user-name">{{ session['user'] }}</div>
          <a href="{{ url_for('logout') }}">Logout</a>
        </div>
      {% endif %}
    </div>
    <div class="screen">
      <div class="screen-inner">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            <div class="flash-container">
              {% for category, message in messages %}
                <div class="flash flash-{{ category }}">{{ message }}</div>
              {% endfor %}
            </div>
          {% endif %}
        {% endwith %}
        {{ content|safe }}
        {% if session.get('user') %}
          <div class="bottom-nav">
            <a class="btn small secondary btn-nav {% if active == 'home' %}active{% endif %}"
               href="{{ url_for('home') }}">Feeder</a>
            <a class="btn small secondary btn-nav {% if active == 'profiles' %}active{% endif %}"
               href="{{ url_for('profiles') }}">Profiles</a>
            <a class="btn small secondary btn-nav {% if active == 'history' %}active{% endif %}"
               href="{{ url_for('history') }}">History</a>
            <a class="btn small secondary btn-nav {% if active == 'schedule' %}active{% endif %}"
               href="{{ url_for('schedule') }}">Auto</a>
            <a class="btn small secondary btn-nav {% if active == 'settings' %}active{% endif %}"
               href="{{ url_for('settings') }}">Settings</a>
          </div>
        {% endif %}
      </div>
    </div>
  </div>
</body>
</html>
"""

# ================================================================
# HELPERS
# ================================================================

def render_page(content, active=None, **context):
    return render_template_string(BASE_TEMPLATE, content=content,
                                  active=active, session=session, **context)

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            flash("Please log in to access this page.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()

        user_row = db.get_user_by_username_and_password(u, p)
        if user_row:
            session["user"]    = u
            session["user_id"] = user_row["user_id"]
            flash(f"Welcome back, {u}!", "success")
            return redirect(url_for("home"))

        flash("Invalid username or password.", "error")

    content = """
    <div class="section-heading">
      <span class="section-dot"></span>
      <span>Owner access</span>
    </div>
    <div class="card">
      <div class="login-hero">
        <div class="login-hero-title">Sign in to your feeder</div>
        <div class="login-hero-text">Use your owner account to manage pet profiles and trigger feedings.</div>
      </div>
      <form method="post">
        <label class="field-label">Email</label>
        <input class="field-input" type="text" name="username" placeholder="your@email.com" required>
        <label class="field-label">Password</label>
        <input class="field-input" type="password" name="password" required>
        <div style="margin-top:20px; display:flex; justify-content:flex-end;">
          <button type="submit" class="btn">Continue</button>
        </div>
      </form>
    </div>
    """
    return render_page(content)

@app.route("/logout")
def logout():
    user = session.get("user", "User")
    session.clear()
    flash(f"Goodbye, {user}!", "success")
    return redirect(url_for("login"))


@app.route("/", methods=["GET"])
@login_required
def home():
    pets_list = db.get_all_pets()
    pets_dict = {}
    for p in pets_list:
        pets_dict[str(p["pet_id"])] = {
            "name":          p["pet_name"],
            "rfid":          p.get("rfid_tag_uid"),
            "portion_grams": 50,
        }

    pet_options = ""
    for pid, p in pets_dict.items():
        pet_options += f'<option value="{pid}">{p["name"]} — {p["portion_grams"]} g</option>'

    no_pets_msg = "" if pets_dict else \
        '<p class="muted-text" style="margin-top:14px;">No profiles yet. Go to Profiles to add your first pet.</p>'

    is_online   = device_status["online"]
    dot_class   = "pill-dot-online"  if is_online else "pill-dot-offline"
    status_text = "Device online"    if is_online else "Device offline"

    content = f"""
    <div class="section-heading">
      <span class="section-dot"></span>
      <span>Feeder overview</span>
    </div>
    <div class="layout-grid">
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Quick feed</div>
            <div class="card-subtitle">Select a pet and start a portion</div>
          </div>
          <div class="pill-status">
            <span class="{dot_class}"></span>
            {status_text}
          </div>
        </div>
        <form method="post" action="{url_for('feed_from_home')}">
          <label class="field-label">Pet profile</label>
          <select name="pet_id" required>
            <option value="" disabled selected>Select a pet</option>
            {pet_options}
          </select>
          <div style="margin-top:20px; display:flex; align-items:center; justify-content:space-between;">
            <div class="muted-text">Portion size is defined in profile.</div>
            <button type="submit" class="feed-circle">Feed</button>
          </div>
        </form>
        {no_pets_msg}
      </div>
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Tips</div>
            <div class="card-subtitle">Best use of your feeder</div>
          </div>
        </div>
        <ul style="list-style:none; padding:0; margin:8px 0 0; font-size:13px; color:var(--text-muted); display:flex; flex-direction:column; gap:8px;">
          <li>• Create one profile per pet so history stays accurate.</li>
          <li>• Match portion size with your vet's recommendation.</li>
          <li>• Keep the device online to enable automatic schedules.</li>
        </ul>
      </div>
    </div>
    """
    return render_page(content, active='home')

@app.route("/feed", methods=["POST"])
@login_required
def feed_from_home():
    pet_id = request.form.get("pet_id")
    if not pet_id:
        flash("Please select a pet to feed.", "error")
        return redirect(url_for("home"))

    pet_row = db.get_pet_by_id(pet_id)
    if not pet_row:
        flash("Pet not found.", "error")
        return redirect(url_for("home"))

    portion = 50
    db.insert_feed_event(pet_row["pet_id"], "manual", portion, portion, "pending")

    pending_command["command"]  = "feed"
    pending_command["pet_name"] = pet_row["pet_name"]
    pending_command["grams"]    = portion

    flash(f"Feed command sent for {pet_row['pet_name']} ({portion}g) — waiting for device.", "success")
    return redirect(url_for("home"))


@app.route("/profiles", methods=["GET"])
@login_required
def profiles():
    pets_list = db.get_all_pets()
    pets_dict = {}
    for p in pets_list:
        pets_dict[str(p["pet_id"])] = {
            "name":          p["pet_name"],
            "species":       p.get("species"),
            "breed":         p.get("breed"),
            "birth_date":    p.get("birth_date"),
            "rfid":          p.get("rfid_tag_uid"),
            "photo_url":     p.get("photo_url"),
            "portion_grams": 50,
        }

    pet_list_html = ""
    if pets_dict:
        for pid, p in pets_dict.items():
            photo_html    = f'<img src="{p["photo_url"]}" alt="{p["name"]}">' if p.get("photo_url") else "<span>No photo</span>"
            breed_species = p.get("breed") or p.get("species") or "Pet"
            pet_list_html += f"""
            <li class="pet-item">
              <a href="{url_for('view_pet', pet_id=pid)}" style="text-decoration:none; color:inherit;">
                <div class="pet-main">
                  <div class="pet-thumb">{photo_html}</div>
                  <div class="pet-text">
                    <div class="pet-name">{p['name']}</div>
                    <div class="pet-meta">{breed_species}</div>
                    <div class="pet-meta">Portion: {p['portion_grams']} g</div>
                  </div>
                </div>
              </a>
              <div class="pet-footer">
                <form method="post" action="{url_for('delete_pet', pet_id=pid)}">
                  <button type="submit" class="btn danger">Delete</button>
                </form>
              </div>
            </li>
            """
        pet_list_html = f'<ul class="pet-list" style="margin-top:16px;">{pet_list_html}</ul>'
    else:
        pet_list_html = '<p class="muted-text" style="margin-top:12px;">No profiles yet. Click + to create one.</p>'

    content = f"""
    <div class="section-heading">
      <span class="section-dot"></span>
      <span>Pet profiles</span>
    </div>
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Manage pets</div>
          <div class="card-subtitle">Add or update your pet profiles</div>
        </div>
        <button type="button" onclick="document.getElementById('profile-form').style.display='block';" class="add-circle">+</button>
      </div>
      <form id="profile-form" style="display:none; margin-top:10px;" method="post" action="{url_for('add_pet')}" enctype="multipart/form-data">
        <label class="field-label">Pet name *</label>
        <input class="field-input" type="text" name="name" required>
        <label class="field-label">Species</label>
        <input class="field-input" type="text" name="species" placeholder="Dog, Cat, etc.">
        <label class="field-label">Breed</label>
        <input class="field-input" type="text" name="breed" placeholder="Labrador, Persian, etc.">
        <label class="field-label">Date of birth</label>
        <input class="field-input" type="date" name="birth_date">
        <label class="field-label">RFID UID (optional)</label>
        <input class="field-input" type="text" name="rfid" placeholder="e.g. 04A1B2C3">
        <label class="field-label">Pet photo (optional)</label>
        <input class="field-input" type="file" name="photo_file" accept="image/*">
        <div style="margin-top:16px; display:flex; justify-content:flex-end; gap:10px;">
          <button type="button" class="btn secondary small" onclick="document.getElementById('profile-form').style.display='none';">Cancel</button>
          <button type="submit" class="btn small">Save profile</button>
        </div>
      </form>
      {pet_list_html}
    </div>
    """
    return render_page(content, active='profiles')

@app.route("/pet", methods=["POST"])
@login_required
def add_pet():
    name       = request.form.get("name",       "").strip()
    species    = request.form.get("species",    "").strip()
    breed      = request.form.get("breed",      "").strip()
    birth_date = request.form.get("birth_date") or None
    rfid       = request.form.get("rfid",       "").strip()

    if not name:
        flash("Pet name is required.", "error")
        return redirect(url_for("profiles"))

    photo_file = request.files.get("photo_file")
    photo_url  = None

    if photo_file and photo_file.filename:
        try:
            safe_name = f"{name}_{photo_file.filename}".replace(" ", "_")
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
            photo_file.save(save_path)
            photo_url = url_for("pet_photo", filename=safe_name)
        except Exception as e:
            print(f"Error saving file: {e}")
            flash("Failed to upload photo, but profile was created.", "error")

    user_id = session.get("user_id", 1)
    db.insert_pet(name, species, breed, birth_date, rfid, photo_url, user_id)
    flash(f"Pet profile for {name} created successfully!", "success")
    return redirect(url_for("profiles"))

@app.route("/pet/<pet_id>", methods=["GET"])
@login_required
def view_pet(pet_id):
    pet = db.get_pet_by_id(pet_id)
    if not pet:
        flash("Pet not found.", "error")
        return redirect(url_for("profiles"))

    photo_html = (
        f'<img src="{pet.get("photo_url")}" alt="{pet["pet_name"]}" '
        f'style="width:100%; max-height:320px; border-radius:16px; object-fit:cover; '
        f'margin:12px 0 16px; border:1px solid var(--border-subtle);">'
        if pet.get("photo_url") else ""
    )

    content = f"""
    <div class="section-heading">
      <span class="section-dot"></span>
      <span>Pet details</span>
    </div>
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">{pet['pet_name']}</div>
          <div class="card-subtitle">{pet.get('species') or 'Pet profile'}</div>
        </div>
      </div>
      {photo_html}
      <div style="display:flex; flex-direction:column; gap:10px;">
        <div class="pet-meta"><strong style="color:var(--text-main);">Species:</strong> {pet.get('species') or 'Not specified'}</div>
        <div class="pet-meta"><strong style="color:var(--text-main);">Breed:</strong> {pet.get('breed') or 'Not specified'}</div>
        <div class="pet-meta"><strong style="color:var(--text-main);">Date of birth:</strong> {pet.get('birth_date') or 'Not specified'}</div>
        <div class="pet-meta"><strong style="color:var(--text-main);">RFID:</strong> {pet.get('rfid_tag_uid') or 'No RFID assigned'}</div>
        <div class="pet-meta"><strong style="color:var(--text-main);">Portion:</strong> 50 grams</div>
      </div>
      <div style="margin-top:20px; display:flex; justify-content:space-between; gap:10px;">
        <a class="btn small secondary" href="{url_for('profiles')}">Back</a>
        <form method="post" action="{url_for('delete_pet', pet_id=pet['pet_id'])}">
          <button type="submit" class="btn danger">Delete</button>
        </form>
      </div>
    </div>
    """
    return render_page(content, active='profiles')

@app.route("/pet/<int:pet_id>/delete", methods=["POST"])
@login_required
def delete_pet(pet_id):
    pet_row = db.get_pet_by_id(pet_id)
    if pet_row:
        if pet_row.get("photo_url"):
            filename  = pet_row["photo_url"].split("/")[-1]
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        db.delete_pet(pet_id)
        flash(f"Pet profile for {pet_row['pet_name']} deleted.", "success")
    else:
        flash("Pet not found.", "error")
    return redirect(url_for("profiles"))

@app.route("/pet_photos/<path:filename>")
def pet_photo(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/device/identify_tag/<rfid_uid>", methods=["GET"])
def identify_tag(rfid_uid):
    pet = db.get_pet_by_rfid(rfid_uid.upper())
    if pet:
        return jsonify({
            "status":   "authorized",
            "pet_name": pet["pet_name"],
            "grams":    50,
        }), 200
    return jsonify({"status": "unknown"}), 404

@app.route("/pet/update_rfid/<int:pet_id>", methods=["POST"])
@login_required
def update_rfid(pet_id):
    rfid_uid = request.form.get("rfid_uid", "").upper().strip()
    if rfid_uid:
        db.update_pet_rfid(pet_id, rfid_uid)
        flash("RFID tag assigned successfully!", "success")
    else:
        flash("No RFID value provided.", "error")
    return redirect(url_for("profiles"))


@app.route("/history")
@login_required
def history():
    mode    = request.args.get("mode", "all")
    entries = db.get_feed_history()

    if mode != "all":
        entries = [e for e in entries if e.get("source") == mode]

    log_items = ""
    if entries:
        for e in entries:
            log_items += f"""
            <li class="log-item">
              <span style="display:inline-block; padding:2px 8px; background:rgba(34,197,94,0.15); border-radius:4px; font-size:11px; color:var(--accent-text); margin-right:6px;">
                {e.get('source', 'unknown')}
              </span>
              <strong style="color:var(--text-main);">{e['pet_name']}</strong>
              received <strong>{e['grams']}g</strong> — {e['event_time']}
            </li>
            """
    else:
        log_items = '<li class="log-item" style="text-align:center; padding:20px;">No feeding events found.</li>'

    count_html = f'<div style="margin-top:14px; text-align:center;"><p class="muted-text">Showing {len(entries)} event(s)</p></div>' if entries else ""

    content = f"""
    <div class="section-heading">
      <span class="section-dot"></span>
      <span>Feed history</span>
    </div>
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Events log</div>
          <div class="card-subtitle">All feeding actions</div>
        </div>
      </div>
      <div style="margin-bottom:14px; display:flex; flex-wrap:wrap; gap:8px;">
        <a class="btn small secondary" href="{url_for('history', mode='all')}">All</a>
        <a class="btn small secondary" href="{url_for('history', mode='manual')}">Manual</a>
        <a class="btn small secondary" href="{url_for('history', mode='schedule')}">Scheduled</a>
        <a class="btn small secondary" href="{url_for('history', mode='rfid')}">RFID</a>
      </div>
      <ul class="log-list">{log_items}</ul>
      {count_html}
    </div>
    """
    return render_page(content, active='history')


@app.route("/schedule", methods=["GET"])
@login_required
def schedule():
    pets      = db.get_all_pets()
    schedules = db.get_all_schedules()

    pet_options = ""
    for p in pets:
        pet_options += f'<option value="{p["pet_id"]}">{p["pet_name"]}</option>'

    schedule_list_html = ""
    if schedules:
        for s in schedules:
            days_display = (s["days"] or "everyday").replace(",", "  ·  ").upper()
            active_label = "Active" if s["is_active"] else "Paused"
            active_color = "var(--accent-text)" if s["is_active"] else "var(--text-muted)"
            schedule_list_html += f"""
            <li class="schedule-item">
              <div class="schedule-info">
                <div class="schedule-time">{s['feed_time']}</div>
                <div class="schedule-meta">{s['pet_name']} — {s['grams']}g</div>
                <div class="schedule-meta">{days_display}</div>
                <div class="schedule-meta" style="color:{active_color};">{active_label}</div>
              </div>
              <div style="display:flex; flex-direction:column; gap:8px; align-items:flex-end;">
                <form method="post" action="{url_for('toggle_schedule', schedule_id=s['schedule_id'])}">
                  <button type="submit" class="btn secondary small">
                    {'Pause' if s['is_active'] else 'Activate'}
                  </button>
                </form>
                <form method="post" action="{url_for('delete_schedule', schedule_id=s['schedule_id'])}">
                  <button type="submit" class="btn danger small">Delete</button>
                </form>
              </div>
            </li>
            """
        schedule_list_html = f'<ul class="schedule-list" style="margin-top:16px;">{schedule_list_html}</ul>'
    else:
        schedule_list_html = '<p class="muted-text" style="margin-top:12px;">No schedules yet. Add one below.</p>'

    content = f"""
    <div class="section-heading">
      <span class="section-dot"></span>
      <span>Automatic feeding</span>
    </div>
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Add schedule</div>
          <div class="card-subtitle">Pick a pet, time and days</div>
        </div>
      </div>
      <form method="post" action="{url_for('add_schedule')}">
        <label class="field-label">Pet</label>
        <select name="pet_id" required>
          <option value="" disabled selected>Select a pet</option>
          {pet_options}
        </select>
        <label class="field-label">Feed time</label>
        <input class="field-input" type="time" name="feed_time" required>
        <label class="field-label">Portion (grams)</label>
        <input class="field-input" type="number" name="grams" value="50" min="1" max="500" required>
        <label class="field-label">Days</label>
        <div class="days-row">
          <label class="day-checkbox"><input type="checkbox" name="days" value="everyday" checked> Every day</label>
          <label class="day-checkbox"><input type="checkbox" name="days" value="mon"> Mon</label>
          <label class="day-checkbox"><input type="checkbox" name="days" value="tue"> Tue</label>
          <label class="day-checkbox"><input type="checkbox" name="days" value="wed"> Wed</label>
          <label class="day-checkbox"><input type="checkbox" name="days" value="thu"> Thu</label>
          <label class="day-checkbox"><input type="checkbox" name="days" value="fri"> Fri</label>
          <label class="day-checkbox"><input type="checkbox" name="days" value="sat"> Sat</label>
          <label class="day-checkbox"><input type="checkbox" name="days" value="sun"> Sun</label>
        </div>
        <div style="margin-top:16px; display:flex; justify-content:flex-end;">
          <button type="submit" class="btn small">Save schedule</button>
        </div>
      </form>
    </div>
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Active schedules</div>
          <div class="card-subtitle">Feeding happens automatically at these times</div>
        </div>
      </div>
      {schedule_list_html}
    </div>
    """
    return render_page(content, active='schedule')

@app.route("/schedule/add", methods=["POST"])
@login_required
def add_schedule():
    pet_id    = request.form.get("pet_id")
    feed_time = request.form.get("feed_time")
    grams     = int(request.form.get("grams", 50))
    days_list = request.form.getlist("days")
    days_str  = "everyday" if "everyday" in days_list else ",".join(days_list)

    if not pet_id or not feed_time:
        flash("Please select a pet and time.", "error")
        return redirect(url_for("schedule"))

    db.create_schedule(pet_id, "Daily Feed", feed_time, grams, days_str)
    flash("Schedule added successfully!", "success")
    return redirect(url_for("schedule"))

@app.route("/schedule/toggle/<int:schedule_id>", methods=["POST"])
@login_required
def toggle_schedule(schedule_id):
    schedules = db.get_all_schedules()
    matched   = next((s for s in schedules if s["schedule_id"] == schedule_id), None)
    if matched:
        db.toggle_schedule(schedule_id, not matched["is_active"])
        flash("Schedule status updated.", "success")
    return redirect(url_for("schedule"))

@app.route("/schedule/delete/<int:schedule_id>", methods=["POST"])
@login_required
def delete_schedule(schedule_id):
    db.delete_schedule(schedule_id)
    flash("Schedule deleted.", "success")
    return redirect(url_for("schedule"))

@app.route("/settings")
@login_required
def settings():
    content = f"""
    <div class="section-heading">
      <span class="section-dot"></span>
      <span>Settings</span>
    </div>
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Account</div>
          <div class="card-subtitle">Manage your user account</div>
        </div>
      </div>
      <div style="margin-top:12px;">
        <div class="pet-meta" style="margin-bottom:12px;"><strong style="color:var(--text-main);">Email:</strong> {session.get('user', 'Unknown')}</div>
        <div class="pet-meta" style="margin-bottom:12px;"><strong style="color:var(--text-main);">User ID:</strong> {session.get('user_id', 'N/A')}</div>
        <div style="margin-top:18px;">
          <a class="btn secondary small" href="{url_for('logout')}">Logout</a>
        </div>
      </div>
    </div>
    """
    return render_page(content, active='settings')


@app.route("/device/online", methods=["GET"])
def device_online():

    device_status["online"] = True
    return "OK", 200

@app.route("/device/offline", methods=["GET"])
def device_offline():
    device_status["online"] = False
    return "OK", 200

@app.route("/api/device/status", methods=["GET"])
def api_device_status():
    return jsonify({"online": device_status["online"]})

@app.route("/api/command", methods=["GET"])
def api_command():
    
    cmd = dict(pending_command)
    if cmd["command"] == "feed":
        pending_command["command"]  = "none"
        pending_command["pet_name"] = ""
        pending_command["grams"]    = 0
    return jsonify(cmd)

@app.route("/api/pets", methods=["GET"])
def api_pets():
   
    return jsonify(db.get_all_pets_api())

@app.route("/api/feed", methods=["POST"])
def api_feed():
    
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"status": "bad_request", "detail": "No JSON body"}), 400

        pet_name = data.get("pet_name")
        grams    = float(data.get("grams", 0))
        source   = data.get("source", "esp32")

        if not pet_name:
            return jsonify({"status": "bad_request", "detail": "pet_name required"}), 400

        db.log_feeding_event(pet_name, grams, source)
        device_status["online"] = True
        return jsonify({"status": "success"}), 201

    except Exception as e:
        print(f"[/api/feed] error: {e}")
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.errorhandler(404)
def not_found(error):
    flash("Page not found.", "error")
    return redirect(url_for("home"))

@app.errorhandler(413)
def too_large(error):
    flash("Uploaded file is too large (max 16 MB).", "error")
    return redirect(url_for("profiles"))

if __name__ == "__main__":
    print("=" * 50)
    print("Smart Pet Feeder — Starting")
    print("URL : http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)