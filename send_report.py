#!/usr/bin/env python3
import csv
import getpass
import os
import re
import sqlite3
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import StringIO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'attendance.db')

SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))

RESET = '\033[0m'
BOLD = '\033[1m'
RED = '\033[91m'
GREEN = '\033[92m'
CYAN = '\033[96m'
YELLOW = '\033[93m'


def color(text, code):
    return f'{code}{text}{RESET}'


def sanitize_filename(part):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', part.strip())


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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


def pick_session():
    with get_db() as conn:
        sessions = conn.execute(
            """
            SELECT course_name, section, date, COUNT(*) AS records_count
            FROM attendance
            GROUP BY course_name, section, date
            ORDER BY date DESC, MAX(id) DESC
            """
        ).fetchall()

    if not sessions:
        print(color('[INFO] No attendance sessions found in attendance.db', YELLOW))
        return None

    print(color('Available sessions:', CYAN))
    for i, row in enumerate(sessions, 1):
        print(
            f"  [{i}] {row['course_name']} | Section {row['section']} | "
            f"{row['date']}  ({row['records_count']} records)"
        )

    while True:
        choice = input(f"\nSelect session [1-{len(sessions)}] (or q to quit): ").strip()
        if choice.lower() in {'q', 'quit'}:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(sessions):
            return sessions[int(choice) - 1]
        print(color('[ERROR] Invalid selection. Try again.', RED))


def fetch_session_records(course_name, section, session_date):
    with get_db() as conn:
        return conn.execute(
            """
            SELECT * FROM attendance
            WHERE course_name=? AND section=? AND date=?
            ORDER BY entry_time ASC, id ASC
            """,
            (course_name, section, session_date)
        ).fetchall()


def save_csv_file(course_name, section, session_date, csv_content):
    filename = (
        f"attendance_{sanitize_filename(course_name)}_"
        f"{sanitize_filename(section)}_{sanitize_filename(session_date)}.csv"
    )
    path = os.path.join(BASE_DIR, filename)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(csv_content)
    return path, filename


def send_email_report(to_email, smtp_user, smtp_pass, csv_content, filename,
                      course_name, section, session_date):
    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg['Subject'] = (
        f"Attendance Report — {course_name} | Section {section} | {session_date}"
    )
    msg.attach(MIMEText(
        f"Attendance report attached.\n\nCourse: {course_name}\n"
        f"Section: {section}\nDate: {session_date}",
        'plain'
    ))

    att = MIMEBase('application', 'octet-stream')
    att.set_payload(csv_content.encode('utf-8'))
    encoders.encode_base64(att)
    att.add_header('Content-Disposition', f'attachment; filename="{filename}"')
    msg.attach(att)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as srv:
        srv.starttls()
        srv.login(smtp_user, smtp_pass)
        srv.sendmail(smtp_user, to_email, msg.as_string())


def main():
    print(color('══════════════════════════════════════', CYAN))
    print(color('  ESP32-S3 Attendance — Send Report', BOLD))
    print(color('══════════════════════════════════════', CYAN))
    print()

    if not os.path.exists(DB_PATH):
        print(color(f'[ERROR] Database not found: {DB_PATH}', RED))
        return 1

    session_row = pick_session()
    if session_row is None:
        print(color('[INFO] Exiting without sending report.', YELLOW))
        return 0

    course_name = session_row['course_name']
    section = session_row['section']
    session_date = session_row['date']

    records = fetch_session_records(course_name, section, session_date)
    if not records:
        print(color('[ERROR] No records found for selected session.', RED))
        return 1

    recipient = input('\nRecipient email: ').strip()
    if not recipient:
        print(color('[ERROR] Recipient email is required.', RED))
        return 1

    smtp_user = os.environ.get('SMTP_USER', '').strip()
    smtp_pass = os.environ.get('SMTP_PASS', '').strip()

    if not smtp_user:
        smtp_user = input('SMTP user (Gmail): ').strip()
    if not smtp_pass:
        smtp_pass = getpass.getpass('SMTP password (app password): ').strip()

    if not smtp_user or not smtp_pass:
        print(color('[ERROR] SMTP user and password are required.', RED))
        return 1

    csv_content = generate_csv(records)
    csv_path, csv_filename = save_csv_file(course_name, section, session_date, csv_content)
    print(color(f'[CSV] Saved: {csv_path}', GREEN))

    print(color(f'[EMAIL] Sending to {recipient} ...', CYAN))
    try:
        send_email_report(
            recipient, smtp_user, smtp_pass, csv_content, csv_filename,
            course_name, section, session_date
        )
        print(color('[EMAIL] ✓ Report sent successfully!', GREEN))
        return 0
    except Exception as e:
        print(color(f'[EMAIL] ✗ Failed to send: {e}', RED))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
