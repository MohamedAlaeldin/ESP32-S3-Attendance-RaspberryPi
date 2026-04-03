# ESP32-S3 Attendance System — Raspberry Pi 5

A lightweight Flask-based attendance system that runs on a **Raspberry Pi 5** (Raspbian OS).  
The system receives JPEG images from an **ESP32-S3** camera, performs face recognition, logs attendance to a SQLite database, and displays results on a web dashboard.

---

## System Overview

```
ESP32-S3 Camera
      │  (HTTP POST — raw JPEG)
      ▼
Raspberry Pi 5 — Flask Server (:5000)
      │
      ├─ Face Recognition  ←  known_faces/{student_id}.jpg
      │
      ├─ Attendance Log    →  attendance.db  (SQLite)
      │
      └─ Web Dashboard     →  http://<pi_ip>:5000
```

---

## Hardware Requirements

| Component | Details |
|-----------|---------|
| Raspberry Pi 5 | 4 GB RAM or more recommended |
| Storage | M.2 SSD (256 GB) or SD card ≥ 16 GB |
| OS | Raspbian OS (64-bit recommended) |
| Network | Same WiFi/AP network as the ESP32-S3 |
| ESP32-S3 | Freenove ESP32-S3-WROOM or compatible |

---

## Repository Structure

```
/
├── app.py                 # Main Flask application
├── students.json          # Student ID → Full Name mapping
├── requirements.txt       # Python dependencies
├── setup.sh               # Automated setup script for Raspbian
├── known_faces/           # Student face photos go here
│   └── README.md          # Instructions for adding photos
├── templates/
│   ├── login.html         # Admin login page
│   └── dashboard.html     # Attendance dashboard
├── static/
│   └── style.css          # Minimal CSS styling
└── README.md              # This file
```

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/MohamedAlaeldin/ESP32-S3-Attendance-RaspberryPi.git
cd ESP32-S3-Attendance-RaspberryPi
```

### 2. Run the setup script

```bash
chmod +x setup.sh
./setup.sh
```

> ⏳ **Note:** `dlib` (used by `face_recognition`) is compiled from source on ARM.  
> This typically takes **15–30 minutes** on a Raspberry Pi 5 — be patient!

The script will:
- Update the package list
- Install system dependencies (`cmake`, `libopenblas-dev`, `liblapack-dev`, `libjpeg-dev`, `python3-pip`)
- Install Python packages from `requirements.txt`
- Create the `known_faces/` directory

---

## Adding Students

### Step 1 — Add a face photo

Place a clear, front-facing JPEG photo named after the student's ID in `known_faces/`:

```
known_faces/202010374.jpg
known_faces/202010375.jpg
...
```

### Step 2 — Register in students.json

Add the student's entry to `students.json`:

```json
{
  "202010374": "Nour Saed Kamel Shahwan",
  "202010381": "New Student Full Name"
}
```

### Step 3 — Restart the server

```bash
python3 app.py
```

The server loads all face photos on startup.

---

## Running the App

```bash
source venv/bin/activate   # activate the virtual environment created by setup.sh
python3 app.py
```

You should see:

```
[INFO] Loaded face: 202010374 — Nour Saed Kamel Shahwan
[INFO] Total known faces loaded: 7
[INFO] Starting Flask attendance server on 0.0.0.0:5000
```

---

## Accessing the Dashboard

Open a browser and navigate to:

```
http://<raspberry_pi_ip>:5000
```

### Default Login

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `00000` |

### Dashboard Features

- **Today's view** — shows only today's attendance records by default
- **All Records** — click the button to see all historical records
- **Table columns**: #, Student ID, Full Name, Date, Time
- **Logout** button in the top-right corner

---

## Network Configuration

The ESP32-S3 sends captured images via HTTP POST to:

```
http://192.168.4.2:5000/upload
```

Make sure the Raspberry Pi's IP address is `192.168.4.2` on the ESP32's Access Point network.  
If the Pi has a different IP, update `PI_SERVER_URL` in the ESP32 Arduino sketch.

---

## API Endpoint

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| `POST` | `/upload` | None | Receive raw JPEG from ESP32 |
| `GET` | `/` | Session | Attendance dashboard |
| `GET/POST` | `/login` | — | Admin login |
| `GET` | `/logout` | — | Clear session |

### `/upload` Response Examples

```
Attendance recorded: Nour Saed Kamel Shahwan
Already recorded today: Nour Saed Kamel Shahwan
Face not recognized
```

---

## Notes

- **OS:** Built and tested for Raspbian OS on Raspberry Pi 5
- **Python:** Requires Python 3
- **Database:** SQLite (`attendance.db`) — created automatically on first run
- **Duplicate prevention:** Each student is logged at most once per day
- **Face tolerance:** Set to `0.5` (lower = stricter matching)
