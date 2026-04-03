#!/usr/bin/env python3
"""
ESP32-S3 Attendance System — Flask Server
Runs on Raspberry Pi 5 / Raspbian OS

Routes:
  GET/POST /login    — admin login (user: admin, pass: 00000)
  GET      /logout   — clear session
  GET      /         — attendance dashboard (requires login)
  POST     /upload   — receive JPEG from ESP32 (no auth required)
"""

import os
import json
import sqlite3
from datetime import date, datetime
from io import BytesIO

import face_recognition
import numpy as np
from PIL import Image
from flask import (Flask, request, session, redirect, url_for,
                   render_template, jsonify)

# ──────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24)

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DB_PATH       = os.path.join(BASE_DIR, 'attendance.db')
STUDENTS_JSON = os.path.join(BASE_DIR, 'students.json')
KNOWN_DIR     = os.path.join(BASE_DIR, 'known_faces')

# Hardcoded admin credentials (override via environment variables for production)
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '00000')

# Face recognition tolerance (lower = stricter)
TOLERANCE = 0.5

# ──────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────

def get_db():
    """Open a database connection (creates file + table on first use)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the attendance table if it does not exist."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT    NOT NULL,
                full_name  TEXT    NOT NULL,
                date       TEXT    NOT NULL,
                time       TEXT    NOT NULL
            )
        """)
        conn.commit()


def already_recorded_today(student_id: str, today: str) -> bool:
    """Return True if student already has a record for today."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM attendance WHERE student_id = ? AND date = ?",
            (student_id, today)
        ).fetchone()
    return row is not None


def log_attendance(student_id: str, full_name: str, today: str, now: str):
    """Insert one attendance record."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO attendance (student_id, full_name, date, time) VALUES (?, ?, ?, ?)",
            (student_id, full_name, today, now)
        )
        conn.commit()

# ──────────────────────────────────────────────
# Load known faces on startup
# ──────────────────────────────────────────────

def load_known_faces():
    """
    Read every image in known_faces/, encode it, and pair it with the
    student ID (filename without extension) and full name from students.json.

    Returns:
        known_encodings  — list of 128-d face encodings
        known_ids        — list of student IDs (parallel to encodings)
        known_names      — list of full names   (parallel to encodings)
    """
    # Load name mapping
    with open(STUDENTS_JSON, 'r', encoding='utf-8') as f:
        students = json.load(f)

    known_encodings = []
    known_ids       = []
    known_names     = []

    if not os.path.isdir(KNOWN_DIR):
        print(f"[WARN] known_faces/ directory not found at {KNOWN_DIR}")
        return known_encodings, known_ids, known_names

    for filename in os.listdir(KNOWN_DIR):
        # Accept common image extensions
        if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
            continue

        student_id = os.path.splitext(filename)[0]
        img_path   = os.path.join(KNOWN_DIR, filename)

        try:
            image     = face_recognition.load_image_file(img_path)
            encodings = face_recognition.face_encodings(image)
        except Exception as e:
            print(f"[WARN] Could not encode {filename}: {e}")
            continue

        if not encodings:
            print(f"[WARN] No face found in {filename}, skipping.")
            continue

        full_name = students.get(student_id, f"Unknown ({student_id})")
        known_encodings.append(encodings[0])
        known_ids.append(student_id)
        known_names.append(full_name)
        print(f"[INFO] Loaded face: {student_id} — {full_name}")

    print(f"[INFO] Total known faces loaded: {len(known_encodings)}")
    return known_encodings, known_ids, known_names


# Load faces once at startup
known_encodings, known_ids, known_names = load_known_faces()

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
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

    today      = date.today().strftime('%Y-%m-%d')
    show_all   = request.args.get('all', '0') == '1'
    filter_str = "Today's" if not show_all else "All"

    with get_db() as conn:
        if show_all:
            records = conn.execute(
                "SELECT * FROM attendance ORDER BY date DESC, time DESC"
            ).fetchall()
        else:
            records = conn.execute(
                "SELECT * FROM attendance WHERE date = ? ORDER BY time DESC",
                (today,)
            ).fetchall()

    return render_template(
        'dashboard.html',
        records=records,
        today=today,
        show_all=show_all,
        filter_str=filter_str,
        total=len(records),
    )


@app.route('/upload', methods=['POST'])
def upload():
    """
    Receive raw JPEG bytes from ESP32-S3.
    Perform face recognition and log attendance.
    Returns a plain-text response string.
    """
    jpeg_bytes = request.data
    if not jpeg_bytes:
        return "No image data received", 400

    try:
        # Convert JPEG bytes → numpy array for face_recognition
        pil_image  = Image.open(BytesIO(jpeg_bytes)).convert('RGB')
        img_array  = np.array(pil_image)
    except Exception as e:
        app.logger.error("Image decode error: %s", e)
        return "Invalid image data", 400

    # Locate and encode faces in the received frame
    try:
        face_locations = face_recognition.face_locations(img_array)
        face_encs      = face_recognition.face_encodings(img_array, face_locations)
    except Exception as e:
        app.logger.error("Face recognition error: %s", e)
        return "Face recognition failed", 500

    if not face_encs:
        return "Face not recognized"

    today = date.today().strftime('%Y-%m-%d')
    now   = datetime.now().strftime('%H:%M:%S')

    # Check each detected face against known encodings
    for face_enc in face_encs:
        if not known_encodings:
            break

        matches   = face_recognition.compare_faces(known_encodings, face_enc, tolerance=TOLERANCE)
        distances = face_recognition.face_distance(known_encodings, face_enc)
        best_idx  = int(np.argmin(distances))

        if matches[best_idx]:
            student_id = known_ids[best_idx]
            full_name  = known_names[best_idx]

            if already_recorded_today(student_id, today):
                return f"Already recorded today: {full_name}"

            log_attendance(student_id, full_name, today, now)
            return f"Attendance recorded: {full_name}"

    return "Face not recognized"


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("[INFO] Starting Flask attendance server on 0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
