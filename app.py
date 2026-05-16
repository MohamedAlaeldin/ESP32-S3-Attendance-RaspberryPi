#!/usr/bin/env python3
"""
ESP32-S3 Attendance System — Flask Server
Runs on Raspberry Pi 5 / Raspbian OS

Features:
  - Tkinter popup at startup to configure course session
  - WiFi SSID + Password entered in popup → Pi switches to home WiFi at session end
  - First scan  = entry time
  - Second scan = exit time (optional — if missing, auto-set to class end_time)
  - 80% attendance rule
  - CSV export + email report (auto-sent at session end)
  - Dashboard with color-coded status
  - Unknown face → clear message sent back to ESP32 HTML + Pi logs

Routes:
  GET/POST /login        — admin login
  GET      /logout       — clear session
  GET      /             — attendance dashboard
  POST     /upload       — receive JPEG from ESP32
  GET      /download_csv — download attendance CSV
  GET      /send_report  — email the CSV report
"""

import os
import json
import csv
import signal
import socket
import sqlite3
import smtplib
import subprocess
import threading
import time
from datetime import date, datetime
from io import BytesIO, StringIO
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import tkinter as tk

import face_recognition
import numpy as np
from PIL import Image
from flask import (Flask, request, session, redirect, url_for,
                   render_template, jsonify, make_response)

# ──────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DB_PATH       = os.path.join(BASE_DIR, 'attendance.db')
STUDENTS_JSON = os.path.join(BASE_DIR, 'students.json')
KNOWN_DIR     = os.path.join(BASE_DIR, 'known_faces')

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '00000')

TOLERANCE = 0.65

# ──────────────────────────────────────────────
# Course Session  (filled by popup)
# ──────────────────────────────────────────────
course_session = {
    'course_name': '',
    'start_time':  '',   # 24-h "HH:MM"
    'end_time':    '',   # 24-h "HH:MM"
    'section':     '',
    'email':       '',
    'date':        '',
    'wifi_ssid':   '',
    'wifi_pass':   '',
}

# Per-student scan tracking: {student_id: {'entry': 'HH:MM:SS', 'exit': None}}
scan_records = {}

known_encodings, known_ids, known_names = [], [], []

# ──────────────────────────────────────────────
# WiFi switch helpers
# ──────────────────────────────────────────────
def run_cmd(cmd, timeout=20):
    """Run a shell command and return (ok, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, '', str(e)


def detect_wifi_interface():
    """Try to detect the active WiFi interface name."""
    candidates = ['wlan0', 'wlp2s0', 'wlp1s0']
    for iface in candidates:
        ok, out, _ = run_cmd(['ip', 'link', 'show', iface], timeout=8)
        if ok and out:
            return iface

    ok, out, _ = run_cmd(['iw', 'dev'], timeout=8)
    if ok:
        lines = [line.strip() for line in out.splitlines()]
        for line in lines:
            if line.startswith('Interface '):
                return line.split('Interface ', 1)[1].strip()

    return 'wlan0'


WIFI_IFACE = detect_wifi_interface()


def disconnect_current_wifi():
    """Disconnect from current WiFi/AP before scanning for home WiFi."""
    print(f"[WIFI] Disconnecting current WiFi on interface '{WIFI_IFACE}'...")

    commands = [
        ['sudo', 'nmcli', 'device', 'disconnect', WIFI_IFACE],
        ['sudo', 'nmcli', 'connection', 'down', 'Hotspot'],
        ['sudo', 'wpa_cli', '-i', WIFI_IFACE, 'disconnect'],
        ['sudo', 'ip', 'link', 'set', WIFI_IFACE, 'down'],
        ['sudo', 'ip', 'link', 'set', WIFI_IFACE, 'up'],
    ]

    for cmd in commands:
        ok, out, err = run_cmd(cmd, timeout=12)
        msg = out or err or 'done'
        print(f"[WIFI] {'✓' if ok else '•'} {' '.join(cmd)} -> {msg}")
        time.sleep(1)

    time.sleep(3)


def verify_internet(host='8.8.8.8', port=53, timeout=5):
    """Check raw connectivity and DNS resolution before sending email."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            print(f"[NET] ✓ Internet reachable via {host}:{port}")
            return True
    except Exception as e:
        print(f"[NET] Raw connectivity failed: {e}")

    try:
        socket.gethostbyname('smtp.gmail.com')
        print("[NET] ✓ DNS resolution works")
        return True
    except Exception as e:
        print(f"[NET] DNS resolution failed: {e}")

    ok, out, err = run_cmd(['ping', '-c', '1', '-W', '3', '8.8.8.8'], timeout=6)
    if ok:
        print("[NET] ✓ Ping check passed")
        return True

    print(f"[NET] Ping check failed: {err or out or 'no response'}")
    return False


def connect_using_nmcli(ssid, pwd):
    """Connect using direct nmcli connect command."""
    cmd = ['sudo', 'nmcli', 'dev', 'wifi', 'connect', ssid]
    if pwd:
        cmd += ['password', pwd]
    return run_cmd(cmd, timeout=30)


def connect_using_saved_profile(ssid):
    """Connect using a pre-saved NetworkManager profile if it exists."""
    return run_cmd(['sudo', 'nmcli', 'connection', 'up', ssid], timeout=25)


def connect_using_wpa_cli(ssid, pwd):
    """Fallback connection using wpa_cli."""
    print(f"[WIFI] Trying wpa_cli fallback on '{WIFI_IFACE}'...")

    steps = [
        ['sudo', 'wpa_cli', '-i', WIFI_IFACE, 'reconfigure'],
        ['sudo', 'wpa_cli', '-i', WIFI_IFACE, 'add_network'],
    ]

    run_cmd(steps[0], timeout=10)
    ok, net_id_out, err = run_cmd(steps[1], timeout=10)
    if not ok:
        return False, '', err or 'Failed to add network'

    net_id = net_id_out.splitlines()[-1].strip()
    if not net_id.isdigit():
        return False, '', f'Unexpected network id: {net_id_out}'

    cmds = [
        ['sudo', 'wpa_cli', '-i', WIFI_IFACE, 'set_network', net_id, 'ssid', f'"{ssid}"'],
        ['sudo', 'wpa_cli', '-i', WIFI_IFACE, 'set_network', net_id, 'psk', f'"{pwd}"'] if pwd else None,
        ['sudo', 'wpa_cli', '-i', WIFI_IFACE, 'enable_network', net_id],
        ['sudo', 'wpa_cli', '-i', WIFI_IFACE, 'select_network', net_id],
        ['sudo', 'dhclient', WIFI_IFACE],
    ]

    for cmd in cmds:
        if not cmd:
            continue
        ok, out, err = run_cmd(cmd, timeout=20)
        if not ok:
            return False, out, err
        time.sleep(2)

    return True, 'wpa_cli connection attempted', ''


def connect_using_iwconfig(ssid, pwd):
    """Last-resort fallback using iwconfig + dhclient."""
    print(f"[WIFI] Trying iwconfig fallback on '{WIFI_IFACE}'...")

    cmds = [
        ['sudo', 'ip', 'link', 'set', WIFI_IFACE, 'up'],
        ['sudo', 'iwconfig', WIFI_IFACE, 'essid', ssid],
        ['sudo', 'dhclient', WIFI_IFACE],
    ]

    for cmd in cmds:
        ok, out, err = run_cmd(cmd, timeout=20)
        if not ok:
            return False, out, err
        time.sleep(2)

    return True, 'iwconfig connection attempted', ''


def switch_to_home_wifi(retries=3):
    """Disconnect from ESP32 hotspot first, then reconnect Pi to home WiFi.
    Uses multiple fallback methods and verifies internet access before success."""
    ssid = course_session.get('wifi_ssid', '').strip()
    pwd  = course_session.get('wifi_pass', '').strip()

    if not ssid:
        print("[WIFI] No home WiFi SSID provided — skipping switch.")
        return False

    disconnect_current_wifi()

    print(f"[WIFI] Scanning for networks on '{WIFI_IFACE}'...")
    ok, out, err = run_cmd(['sudo', 'nmcli', 'dev', 'wifi', 'rescan'], timeout=15)
    print(f"[WIFI] Rescan: {out or err or 'done'}")
    time.sleep(5)

    ok, out, err = run_cmd(['sudo', 'nmcli', '-f', 'SSID,SIGNAL', 'dev', 'wifi', 'list'], timeout=15)
    if out:
        print("[WIFI] Visible networks:")
        for line in out.splitlines():
            print(f"[WIFI]   {line}")
    elif err:
        print(f"[WIFI] Could not list visible networks: {err}")

    print(f"[WIFI] Switching to home WiFi: '{ssid}' ...")
    for attempt in range(1, retries + 1):
        print(f"[WIFI] Attempt {attempt}/{retries} using nmcli direct connect...")
        ok, out, err = connect_using_nmcli(ssid, pwd)
        if ok:
            time.sleep(5)
            if verify_internet():
                print(f"[WIFI] ✓ Connected to '{ssid}' via nmcli direct connect")
                return True
            print("[WIFI] Connected but internet not ready yet.")
        print(f"[WIFI] nmcli direct failed: {err or out or 'unknown error'}")

        print(f"[WIFI] Attempt {attempt}/{retries} using saved profile...")
        ok, out, err = connect_using_saved_profile(ssid)
        if ok:
            time.sleep(5)
            if verify_internet():
                print(f"[WIFI] ✓ Connected to '{ssid}' via saved profile")
                return True
            print("[WIFI] Saved profile connected but internet not ready yet.")
        print(f"[WIFI] Saved profile failed: {err or out or 'unknown error'}")

        print(f"[WIFI] Attempt {attempt}/{retries} using wpa_cli fallback...")
        ok, out, err = connect_using_wpa_cli(ssid, pwd)
        if ok:
            time.sleep(6)
            if verify_internet():
                print(f"[WIFI] ✓ Connected to '{ssid}' via wpa_cli")
                return True
            print("[WIFI] wpa_cli connected but internet not ready yet.")
        print(f"[WIFI] wpa_cli failed: {err or out or 'unknown error'}")

        print(f"[WIFI] Attempt {attempt}/{retries} using iwconfig fallback...")
        ok, out, err = connect_using_iwconfig(ssid, pwd)
        if ok:
            time.sleep(6)
            if verify_internet():
                print(f"[WIFI] ✓ Connected to '{ssid}' via iwconfig")
                return True
            print("[WIFI] iwconfig connected but internet not ready yet.")
        print(f"[WIFI] iwconfig failed: {err or out or 'unknown error'}")

        if attempt < retries:
            print("[WIFI] Retrying in 5s...")
            time.sleep(5)

    print(f"[WIFI] ✗ Could not connect to '{ssid}' after {retries} attempts.")
    return False

# ──────────────────────────────────────────────
# Auto-exit students who only scanned entry
# ──────────────────────────────────────────────
def auto_exit_missing():
    """Set exit_time = class end_time for students who only scanned entry."""
    end_time_str = course_session['end_time'] + ':00'   # "HH:MM:SS"

    for sid, rec in scan_records.items():
        if rec['exit'] is None:
            name = known_names[known_ids.index(sid)] if sid in known_ids else sid
            status = calculate_status(rec['entry'], end_time_str)
            update_exit_and_status(sid, end_time_str, status)
            scan_records[sid]['exit'] = end_time_str
            print(f"[AUTO-EXIT] {name} → exit set to {end_time_str} → {status}")

# ──────────────────────────────────────────────
# Session end timer
# ──────────────────────────────────────────────
def schedule_session_end():
    """Background thread: waits until end_time, auto-exits students,
    switches to home WiFi, sends CSV email, then shuts down."""
    try:
        end_dt = datetime.strptime(course_session['end_time'], '%H:%M').replace(
            year=datetime.now().year,
            month=datetime.now().month,
            day=datetime.now().day
        )

        if end_dt <= datetime.now():
            print("[SESSION] End time is in the past — auto-shutdown not scheduled.")
            return

        delay = (end_dt - datetime.now()).total_seconds()
        print(f"[SESSION] Auto-shutdown scheduled in {delay/60:.1f} min "
              f"at {course_session['end_time']}")

        def _shutdown():
            end_str = datetime.now().strftime('%H:%M:%S')
            print("\n" + "═" * 40)
            print(f"[SESSION] ⏰ Session ended at {end_str}")
            print(f"[SESSION] Course  : {course_session['course_name']}")
            print(f"[SESSION] Section : {course_session['section']}")

            # 1. Auto-exit students who only scanned entry
            print("[SESSION] Auto-closing open entries...")
            auto_exit_missing()

            # 2. Switch Pi back to home WiFi
            wifi_ok = switch_to_home_wifi()
            if not wifi_ok:
                print("[EMAIL] Skipping report send because WiFi/internet is unavailable")
            else:
                print("[EMAIL] WiFi restored successfully. Internet looks ready.")

            # 3. Send email report
            if wifi_ok:
                print("[EMAIL] Preparing attendance report...")
                try:
                    today = date.today().strftime('%Y-%m-%d')
                    with get_db() as conn:
                        records = conn.execute(
                            "SELECT * FROM attendance "
                            "WHERE date=? AND course_name=? AND section=?",
                            (today, course_session['course_name'],
                             course_session['section'])
                        ).fetchall()
                    csv_content = generate_csv(records)
                    ok = send_email_report(course_session['email'], csv_content)
                    if ok:
                        print(f"[EMAIL] ✓ Report sent to {course_session['email']}")
                    else:
                        print("[EMAIL] ✗ Failed to send — check SMTP credentials / network")
                except Exception as e:
                    print(f"[EMAIL] ✗ Error: {e}")

            print("[SESSION] Shutting down server...")
            print("═" * 40)
            os.kill(os.getpid(), signal.SIGINT)

        t = threading.Timer(delay, _shutdown)
        t.daemon = True
        t.start()

    except Exception as e:
        print(f"[WARN] Could not schedule session end: {e}")

# ──────────────────────────────────────────────
# Tkinter popup
# ──────────────────────────────────────────────
def show_course_popup():
    """Blocking tkinter window — fills course_session before Flask starts."""
    root = tk.Tk()
    root.title("Attendance System — Course Setup")
    root.geometry("500x530")
    root.resizable(False, False)
    root.configure(bg='#1a1a2e')

    def lbl(parent, text, **kw):
        return tk.Label(parent, text=text, bg='#1a1a2e', fg='white',
                        font=('Helvetica', 11), **kw)

    def entry_field(parent, default='', show=None):
        kw = dict(font=('Helvetica', 11), width=26,
                  bg='#16213e', fg='white', insertbackground='white',
                  relief='flat', bd=5)
        if show:
            kw['show'] = show
        e = tk.Entry(parent, **kw)
        e.insert(0, default)
        return e

    tk.Label(root, text="ESP32-S3 Attendance System", bg='#1a1a2e',
             fg='#00d4ff', font=('Helvetica', 14, 'bold')).pack(pady=(15, 3))
    tk.Label(root, text="Enter Course Session Details", bg='#1a1a2e',
             fg='#aaa', font=('Helvetica', 10)).pack(pady=(0, 8))

    frame = tk.Frame(root, bg='#1a1a2e')
    frame.pack(padx=35, fill='x')

    def divider(row, text):
        tk.Label(frame, text=text, bg='#1a1a2e', fg='#00d4ff',
                 font=('Helvetica', 10, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', pady=(10, 2))

    course_fields = [
        ("Course Name:",   "Mathematics", None),
        ("Start Time:",    "10:00 AM",    None),
        ("End Time:",      "11:30 AM",    None),
        ("Section:",       "2B",          None),
        ("Send Email to:", "example@gmail.com", None),
    ]

    entries = []
    for i, (label, default, show) in enumerate(course_fields):
        lbl(frame, label).grid(row=i, column=0, sticky='w', pady=6)
        e = entry_field(frame, default, show=show)
        e.grid(row=i, column=1, pady=6, padx=(12, 0))
        entries.append(e)

    course_e, start_e, end_e, section_e, email_e = entries

    wifi_row = len(course_fields)
    divider(wifi_row, "── Home WiFi (for email after session) ──")

    wifi_fields = [
        ("WiFi Name:",     "",  None),
        ("WiFi Password:", "",  '*'),
    ]
    wifi_entries = []
    for j, (label, default, show) in enumerate(wifi_fields):
        r = wifi_row + 1 + j
        lbl(frame, label).grid(row=r, column=0, sticky='w', pady=6)
        e = entry_field(frame, default, show=show)
        e.grid(row=r, column=1, pady=6, padx=(12, 0))
        wifi_entries.append(e)

    wifi_e, wpass_e = wifi_entries

    err_lbl = tk.Label(root, text='', bg='#1a1a2e', fg='red',
                       font=('Helvetica', 10))
    err_lbl.pack(pady=(4, 0))

    def parse_time(t):
        t = t.strip()
        for fmt in ('%I:%M %p', '%H:%M', '%I:%M%p', '%I %p'):
            try:
                return datetime.strptime(t, fmt).strftime('%H:%M')
            except ValueError:
                continue
        return None

    def on_start():
        course  = course_e.get().strip()
        start   = start_e.get().strip()
        end     = end_e.get().strip()
        section = section_e.get().strip()
        email   = email_e.get().strip()
        wifi    = wifi_e.get().strip()
        wpass   = wpass_e.get().strip()

        if not all([course, start, end, section, email]):
            err_lbl.config(text='All course fields are required!')
            return

        s24 = parse_time(start)
        e24 = parse_time(end)
        if not s24 or not e24:
            err_lbl.config(text='Invalid time! Use format: 10:00 AM or 10:00')
            return

        course_session.update({
            'course_name': course,
            'start_time':  s24,
            'end_time':    e24,
            'section':     section,
            'email':       email,
            'date':        date.today().strftime('%Y-%m-%d'),
            'wifi_ssid':   wifi,
            'wifi_pass':   wpass,
        })

        print(f"\n[SESSION] Course  : {course}")
        print(f"[SESSION] Section : {section}")
        print(f"[SESSION] Time    : {s24} - {e24}")
        print(f"[SESSION] Email   : {email}")
        print(f"[SESSION] Date    : {course_session['date']}")
        if wifi:
            print(f"[SESSION] Home WiFi: {wifi}")
        print()
        root.destroy()

    tk.Button(root, text="START SESSION", command=on_start,
              bg='#007bff', fg='white', font=('Helvetica', 13, 'bold'),
              relief='flat', padx=20, pady=9, cursor='hand2').pack(pady=12)

    root.mainloop()

# ──────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                course_name TEXT    NOT NULL,
                section     TEXT    NOT NULL,
                student_id  TEXT    NOT NULL,
                full_name   TEXT    NOT NULL,
                date        TEXT    NOT NULL,
                entry_time  TEXT,
                exit_time   TEXT,
                status      TEXT    NOT NULL DEFAULT 'Absent'
            )
        """)
        conn.commit()

def get_or_create_record(student_id, full_name):
    today = date.today().strftime('%Y-%m-%d')
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM attendance WHERE student_id=? AND date=? AND course_name=? AND section=?",
            (student_id, today, course_session['course_name'], course_session['section'])
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO attendance (course_name,section,student_id,full_name,date,status) "
                "VALUES (?,?,?,?,?,'Absent')",
                (course_session['course_name'], course_session['section'],
                 student_id, full_name, today)
            )
            conn.commit()

def update_entry_time(student_id, entry_time):
    today = date.today().strftime('%Y-%m-%d')
    with get_db() as conn:
        conn.execute(
            "UPDATE attendance SET entry_time=? "
            "WHERE student_id=? AND date=? AND course_name=? AND section=?",
            (entry_time, student_id, today,
             course_session['course_name'], course_session['section'])
        )
        conn.commit()

def update_exit_and_status(student_id, exit_time, status):
    today = date.today().strftime('%Y-%m-%d')
    with get_db() as conn:
        conn.execute(
            "UPDATE attendance SET exit_time=?, status=? "
            "WHERE student_id=? AND date=? AND course_name=? AND section=?",
            (exit_time, status, student_id, today,
             course_session['course_name'], course_session['section'])
        )
        conn.commit()

# ──────────────────────────────────────────────
# Attendance calculation (80% rule)
# ──────────────────────────────────────────────
def calculate_status(entry_str, exit_str):
    try:
        fmt   = '%H:%M:%S'
        entry = datetime.strptime(entry_str, fmt)
        exit_ = datetime.strptime(exit_str,  fmt)
        start = datetime.strptime(course_session['start_time'], '%H:%M')
        end   = datetime.strptime(course_session['end_time'],   '%H:%M')

        total_class = (end   - start).total_seconds()
        attended    = (exit_ - entry).total_seconds()

        if total_class <= 0:
            return 'Absent'

        pct = attended / total_class
        print(f"[ATTEND] {attended/60:.1f} min / {total_class/60:.1f} min = {pct*100:.1f}%")
        return 'Present' if pct >= 0.80 else 'Absent'
    except Exception as e:
        print(f"[ERROR] Attendance calc: {e}")
        return 'Absent'

# ──────────────────────────────────────────────
# CSV + Email
# ──────────────────────────────────────────────
def generate_csv(records):
    output = StringIO()
    w = csv.writer(output)
    w.writerow(['Course Name', 'Section', 'Student Name', 'Student ID',
                'Entry Time', 'Exit Time', 'Status'])
    for r in records:
        w.writerow([r['course_name'], r['section'], r['full_name'],
                    r['student_id'], r['entry_time'] or '-',
                    r['exit_time'] or '-', r['status']])
    return output.getvalue()

def send_email_report(to_email, csv_content):
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASS', '')

    if not smtp_user or not smtp_pass:
        print("[EMAIL] SMTP_USER / SMTP_PASS not set in environment — skipping email")
        return False

    course  = course_session['course_name']
    section = course_session['section']
    today   = date.today().strftime('%Y-%m-%d')
    fname   = f"attendance_{course}_{section}_{today}.csv"

    try:
        msg = MIMEMultipart()
        msg['From']    = smtp_user
        msg['To']      = to_email
        msg['Subject'] = f"Attendance Report — {course} | Section {section} | {today}"
        msg.attach(MIMEText(
            f"Attendance report attached.\n\nCourse: {course}\n"
            f"Section: {section}\nDate: {today}", 'plain'))

        att = MIMEBase('application', 'octet-stream')
        att.set_payload(csv_content.encode('utf-8'))
        encoders.encode_base64(att)
        att.add_header('Content-Disposition', f'attachment; filename="{fname}"')
        msg.attach(att)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as srv:
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_user, to_email, msg.as_string())

        print(f"[EMAIL] Sent to {to_email}")
        return True
    except Exception as e:
        print(f"[EMAIL] Failed: {e}")
        return False

# ──────────────────────────────────────────────
# Load known faces
# ──────────────────────────────────────────────
def load_known_faces():
    with open(STUDENTS_JSON, 'r', encoding='utf-8') as f:
        students = json.load(f)

    encs, ids, names = [], [], []

    if not os.path.isdir(KNOWN_DIR):
        print(f"[WARN] known_faces/ not found at {KNOWN_DIR}")
        return encs, ids, names

    for filename in os.listdir(KNOWN_DIR):
        if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
            continue
        sid      = os.path.splitext(filename)[0]
        img_path = os.path.join(KNOWN_DIR, filename)
        try:
            image     = face_recognition.load_image_file(img_path)
            encodings = face_recognition.face_encodings(image)
        except Exception as e:
            print(f"[WARN] Could not encode {filename}: {e}")
            continue
        if not encodings:
            print(f"[WARN] No face in {filename}, skipping.")
            continue
        full_name = students.get(sid, f"Unknown ({sid})")
        encs.append(encodings[0])
        ids.append(sid)
        names.append(full_name)
        print(f"[INFO]   Loaded: {sid} — {full_name}")

    print(f"[INFO] Total known faces: {len(encs)}")
    return encs, ids, names

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if (request.form.get('username', '').strip() == ADMIN_USERNAME and
                request.form.get('password', '').strip() == ADMIN_PASSWORD):
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        error = 'Invalid username or password.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    today    = date.today().strftime('%Y-%m-%d')
    show_all = request.args.get('all', '0') == '1'

    with get_db() as conn:
        if show_all:
            records = conn.execute(
                "SELECT * FROM attendance ORDER BY date DESC, entry_time DESC"
            ).fetchall()
        else:
            records = conn.execute(
                "SELECT * FROM attendance WHERE date=? AND course_name=? AND section=? "
                "ORDER BY entry_time DESC",
                (today, course_session['course_name'], course_session['section'])
            ).fetchall()

    return render_template('dashboard.html',
        records=records,
        today=today,
        show_all=show_all,
        course=course_session,
        total=len(records),
    )

@app.route('/download_csv')
def download_csv():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    today = date.today().strftime('%Y-%m-%d')
    with get_db() as conn:
        records = conn.execute(
            "SELECT * FROM attendance WHERE date=? AND course_name=? AND section=?",
            (today, course_session['course_name'], course_session['section'])
        ).fetchall()
    csv_content = generate_csv(records)
    fname = (f"attendance_{course_session['course_name']}_"
             f"{course_session['section']}_{today}.csv")
    resp = make_response(csv_content)
    resp.headers['Content-Disposition'] = f'attachment; filename="{fname}"'
    resp.headers['Content-Type'] = 'text/csv'
    return resp

@app.route('/send_report')
def send_report():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    today = date.today().strftime('%Y-%m-%d')
    with get_db() as conn:
        records = conn.execute(
            "SELECT * FROM attendance WHERE date=? AND course_name=? AND section=?",
            (today, course_session['course_name'], course_session['section'])
        ).fetchall()
    csv_content = generate_csv(records)
    ok = send_email_report(course_session['email'], csv_content)
    return jsonify({'success': ok,
                    'message': f"Report sent to {course_session['email']}" if ok
                               else 'Email failed — check SMTP env vars'})

@app.route('/upload', methods=['POST'])
def upload():
    SEP = "═" * 40
    print(SEP)

    jpeg_bytes = request.data
    sender_ip  = request.remote_addr or 'unknown'

    if not jpeg_bytes:
        print(f"[CAPTURE] No image data from {sender_ip}")
        print(SEP)
        return "No image data received", 400

    size_kb = len(jpeg_bytes) / 1024
    print(f"[CAPTURE] New image from {sender_ip}")
    print(f"[STEP 1] Image size: {size_kb:.1f} KB")

    try:
        pil_image = Image.open(BytesIO(jpeg_bytes)).convert('RGB')
        pil_image = pil_image.rotate(180)
        img_array = np.array(pil_image)
        w, h = pil_image.size
        print(f"[STEP 2] Decoded: {w}x{h} px")
    except Exception as e:
        print(f"[ERROR] Decode failed: {e}")
        print(SEP)
        return "Invalid image data", 400

    print("[STEP 3] Detecting faces...")
    try:
        face_locations = face_recognition.face_locations(
            img_array, number_of_times_to_upsample=2)
        face_encs = face_recognition.face_encodings(img_array, face_locations)
    except Exception as e:
        print(f"[ERROR] Face recognition: {e}")
        print(SEP)
        return "Face recognition failed", 500

    if not face_encs:
        print("[STEP 4] ⚠ No face detected")
        print(SEP)
        return "No face detected"

    print(f"[STEP 4] Faces detected: {len(face_encs)}")
    now = datetime.now().strftime('%H:%M:%S')

    for i, face_enc in enumerate(face_encs, 1):
        print(f"[STEP 5] Matching face {i} against {len(known_encodings)} known faces...")

        if not known_encodings:
            print("[WARN] No known faces loaded")
            break

        distances = face_recognition.face_distance(known_encodings, face_enc)
        best_idx  = int(np.argmin(distances))
        best_dist = float(distances[best_idx])
        matches   = face_recognition.compare_faces(
            known_encodings, face_enc, tolerance=TOLERANCE)

        print(f"[STEP 6] Best match: {known_ids[best_idx]} — {known_names[best_idx]} "
              f"(distance: {best_dist:.2f})")

        if not matches[best_idx]:
            msg = "⚠ Unknown Face: This student is not registered in this course"
            print(f"[WARN] {msg} (distance: {best_dist:.2f})")
            print(SEP)
            return msg, 200

        sid  = known_ids[best_idx]
        name = known_names[best_idx]

        # ── First scan = entry ──────────────────────────────────────
        if sid not in scan_records:
            scan_records[sid] = {'entry': now, 'exit': None}
            get_or_create_record(sid, name)
            update_entry_time(sid, now)
            print(f"[STEP 7] ✓ ENTRY: {name} at {now}")
            print(SEP)
            return f"✓ Entry recorded: {name} at {now}"

        # ── Second scan = exit ──────────────────────────────────────
        if scan_records[sid]['exit'] is None:
            scan_records[sid]['exit'] = now
            status = calculate_status(scan_records[sid]['entry'], now)
            update_exit_and_status(sid, now, status)
            print(f"[STEP 7] ✓ EXIT: {name} at {now} → {status}")
            print(SEP)
            return f"✓ Exit recorded: {name} — {status}"

        # ── Already complete ────────────────────────────────────────
        print(f"[INFO] {name} already fully recorded")
        print(SEP)
        return f"Already recorded today: {name}"

    print(SEP)
    return "⚠ Unknown Face: This student is not registered in this course", 200

# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == '__main__':
    # 1. Popup — blocks until user clicks START SESSION
    show_course_popup()

    if not course_session['course_name']:
        print("[ERROR] No course configured. Exiting.")
        exit(1)

    # 2. Init DB
    init_db()

    # 3. Load known faces
    known_encodings, known_ids, known_names = load_known_faces()

    # 4. Schedule auto session-end + auto email
    schedule_session_end()

    print(f"[INFO] WiFi IF   : {WIFI_IFACE}")
    print(f"[INFO] DB        : {DB_PATH}")
    print(f"[INFO] Starting Flask on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
