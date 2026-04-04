# ESP32-S3 Face Recognition Attendance System — Full Project Documentation

> **Last Updated:** 2026-04-04 15:12:15  
> **Author:** Mohamed Alaeldin  
> **Status:** ✅ Working & Tested

---

## 📋 Table of Contents

1. [System Overview](#system-overview)
2. [Hardware Requirements](#hardware-requirements)
3. [Repository Structure](#repository-structure)
4. [ESP32-S3 Firmware](#esp32-s3-firmware)
   - [platformio.ini Configuration](#platformioini-configuration)
   - [PSRAM Setup & Known Issues](#psram-setup--known-issues)
   - [Camera Configuration](#camera-configuration)
   - [WiFi Access Point](#wifi-access-point)
   - [Web Interface & Routes](#web-interface--routes)
5. [Raspberry Pi Flask Server](#raspberry-pi-flask-server)
   - [Installation on Windows WSL](#installation-on-windows-wsl)
   - [Installation on Raspberry Pi 5](#installation-on-raspberry-pi-5)
   - [Running the Server](#running-the-server)
   - [Face Recognition Pipeline](#face-recognition-pipeline)
   - [Database Schema](#database-schema)
   - [API Endpoints](#api-endpoints)
   - [Web Dashboard](#web-dashboard)
6. [Managing Students](#managing-students)
7. [Managing Attendance Records](#managing-attendance-records)
8. [Troubleshooting](#troubleshooting)
9. [Known Issues & Fixes Applied](#known-issues--fixes-applied)
10. [Pending Improvements](#pending-improvements)

---

## System Overview

```
┌─────────────────────┐        HTTP POST (raw JPEG)        ┌──────────────────────────────┐
│   ESP32-S3 Camera   │ ─────────────────────────────────► │  Raspberry Pi 5 Flask Server │
│  (Freenove WROOM)   │                                     │       Port 5000              │
│                     │                                     │                              │
│  • Captures JPEG    │                                     │  • Face Recognition          │
│  • WiFi Access Point│                                     │  • Attendance Logging        │
│  • Live Stream      │                                     │  • SQLite Database           │
│  • Web UI (port 80) │                                     │  • Web Dashboard             │
└─────────────────────┘                                     └──────────────────────────────┘
         │                                                             │
         │ Connect phone/laptop to:                                    │ Open browser:
         │ WiFi: "ESP32-Camera"                                        │ http://<pi_ip>:5000
         │ Pass: "12345678"                                            │
         │ Then open: http://192.168.4.1                               │
         └─────────────────────────────────────────────────────────────┘
```

**How it works:**
1. The ESP32-S3 creates a WiFi Access Point named `ESP32-Camera`
2. The Raspberry Pi connects to that AP and gets IP `192.168.4.2`
3. A user connects their phone/laptop to the same AP and opens `http://192.168.4.1`
4. The user sees a live camera stream and presses **CAPTURE**
5. The ESP32 takes a JPEG photo and sends it via HTTP POST to `http://192.168.4.2:5000/upload`
6. The Flask server runs face recognition and logs attendance to SQLite
7. The result (`Attendance recorded: Name` / `Already recorded today` / `Face not recognized`) is shown on the ESP32 web page

---

## Hardware Requirements

| Component | Details |
|-----------|---------|
| **ESP32-S3** | Freenove ESP32-S3-WROOM (with OV2640 camera, 8MB Flash, 8MB OPI PSRAM) |
| **Raspberry Pi 5** | 4 GB RAM or more recommended |
| **Storage (Pi)** | M.2 SSD (256 GB) or SD card ≥ 16 GB |
| **OS (Pi)** | Raspbian OS 64-bit |
| **Network** | Both devices on same WiFi / ESP32 AP network |
| **Camera** | OV2640 (built into Freenove board) |

---

## Repository Structure

### ESP32 Firmware Repo — `ESP32-S3-Attendance-`
```
/
├── src/
│   ├── attendance_cam.ino   # Main Arduino sketch
│   ├── config_base.h        # Shared pin & WiFi definitions
│   ├── config_in.h          # Role: IN device config
│   └── config_out.h         # Role: OUT device config
├── platformio.ini           # PlatformIO build configuration
└── .vscode/                 # VS Code settings
```

### Raspberry Pi Server Repo — `ESP32-S3-Attendance-RaspberryPi`
```
/
├── app.py                   # Main Flask application
├── students.json            # Student ID → Full Name mapping
├── requirements.txt         # Python dependencies
├── setup.sh                 # Automated setup script for Raspbian
├── known_faces/             # Student face photos (named by student ID)
│   └── README.md
├── templates/
│   ├── login.html           # Admin login page
│   └── dashboard.html       # Attendance dashboard
├── static/
│   └── style.css            # CSS styling
└── attendance.db            # SQLite database (auto-created on first run)
```

---

## ESP32-S3 Firmware

### platformio.ini Configuration

```ini
[env:freenove_esp32_s3_wroom]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino

board_build.arduino.memory_type = qio_qspi
board_build.flash_mode = qio
board_build.psram = opi                    ← OPI PSRAM for Freenove board
board_build.flash_size = 8MB
board_build.partitions = default_8MB.csv

upload_speed = 921600
monitor_speed = 115200

build_flags =
  -DCORE_DEBUG_LEVEL=0
  -DARDUINO_USB_MODE=1
  -DARDUINO_USB_CDC_ON_BOOT=1
  -DBOARD_HAS_PSRAM                        ← Enables PSRAM in firmware

lib_deps =
  esp32-camera
```

### PSRAM Setup & Known Issues

The Freenove ESP32-S3-WROOM has **8MB OPI PSRAM**. PSRAM is critical for camera operation at VGA resolution.

**PSRAM is correctly enabled in `platformio.ini`:**
- `board_build.psram = opi` ✅
- `-DBOARD_HAS_PSRAM` build flag ✅

**⚠️ Known Issue in current sketch (line 245):**  
The sketch currently uses `CAMERA_FB_IN_DRAM` which ignores PSRAM. This is a safe fallback but not optimal.

**Recommended fix (pending PR):**
```cpp
// Current (conservative)
config.fb_location = CAMERA_FB_IN_DRAM;
config.fb_count    = 1;

// Recommended (uses PSRAM properly)
if (psramFound()) {
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.fb_count    = 2;
} else {
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.fb_count    = 1;
}
```

**To verify PSRAM works at runtime, add to `setup()`:**
```cpp
if (psramFound()) {
    Serial.printf("✅ PSRAM: %d bytes free\n", ESP.getFreePsram());
} else {
    Serial.println("❌ PSRAM NOT found!");
}
```

### Camera Configuration

| Setting | Current Value | Notes |
|---------|--------------|-------|
| `xclk_freq_hz` | `12000000` | ⚠️ Should be `20000000` — see Known Issues |
| `frame_size` | `FRAMESIZE_VGA` (640×480) | ✅ Good for face recognition |
| `pixel_format` | `PIXFORMAT_JPEG` | ✅ |
| `jpeg_quality` | `12` | ✅ Good balance (0=best, 63=worst) |
| `grab_mode` | `CAMERA_GRAB_WHEN_EMPTY` | ✅ |
| `fb_location` | `CAMERA_FB_IN_DRAM` | ⚠️ Should use PSRAM |
| `fb_count` | `1` | ⚠️ Should be `2` with PSRAM |

**Camera Pin Mapping (Freenove ESP32-S3-WROOM):**

| Signal | GPIO |
|--------|------|
| XCLK | 15 |
| SIOD (SDA) | 4 |
| SIOC (SCL) | 5 |
| Y9–Y2 (data) | 16, 17, 18, 12, 10, 8, 9, 11 |
| VSYNC | 6 |
| HREF | 7 |
| PCLK | 13 |
| PWDN | -1 (not used) |
| RESET | -1 (not used) |
|
> **Fix applied:** Deprecated `pin_sscb_sda` / `pin_sscb_scl` renamed to `pin_sccb_sda` / `pin_sccb_scl` ✅

### WiFi Access Point

The ESP32 creates its own WiFi network:

| Setting | Value |
|---------|-------|
| SSID | `ESP32-Camera` |
| Password | `12345678` |
| ESP32 IP | `192.168.4.1` |
| Raspberry Pi IP | `192.168.4.2` (must be set on Pi) |

### Web Interface & Routes

The ESP32 runs an HTTP server on **port 80** with 3 routes:

| Route | Description |
|-------|-------------|
| `GET /` | Web page with live stream + CAPTURE button |
| `GET /stream` | MJPEG live video stream |
| `GET /capture` | Takes a photo and POSTs it to the Pi server |

**Capture flow:**
1. Browser calls `GET /capture` on ESP32
2. ESP32 calls `esp_camera_fb_get()` to take photo
3. ESP32 sends JPEG via `HTTP POST` to `http://192.168.4.2:5000/upload`
4. Pi server responds with plain text result
5. ESP32 forwards that text back to the browser
6. `esp_camera_fb_return(fb)` frees the frame buffer ✅

---

## Raspberry Pi Flask Server

### Installation on Windows WSL

> Use this if you are running the server on a Windows machine using WSL (Ubuntu).

**Step 1 — Open WSL terminal (Ubuntu)**

**Step 2 — Clone the repository**
```bash
git clone https://github.com/MohamedAlaeldin/ESP32-S3-Attendance-RaspberryPi.git
cd ESP32-S3-Attendance-RaspberryPi
```

**Step 3 — Create virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Step 4 — Fix setuptools (required for Python 3.12 + WSL)**
```bash
pip install "setuptools<67"
```
> ⚠️ `setuptools>=67` removed `pkg_resources` which `face_recognition_models` depends on. Using `<67` fixes this.

**Step 5 — Install dependencies**
```bash
pip install dlib face_recognition flask pillow numpy
```

**Step 6 — Run the server**
```bash
python3 app.py
```

**Step 7 — Access the dashboard**

Open your browser and go to: `http://localhost:5000`

**To access known_faces/ folder from Windows File Explorer:**
```
\wsl$\Ubuntu\home\<your_username>\ESP32-S3-Attendance-RaspberryPi\known_faces
```

---

### Installation on Raspberry Pi 5

> Send this section to your friend running the Pi.

**Step 1 — Open terminal on the Pi (or SSH in)**
```bash
ssh pi@<raspberry_pi_ip>
```

**Step 2 — Install Git**
```bash
sudo apt update
sudo apt install git -y
```

**Step 3 — Clone the repository**
```bash
git clone https://github.com/MohamedAlaeldin/ESP32-S3-Attendance-RaspberryPi.git
cd ESP32-S3-Attendance-RaspberryPi
```

**Step 4 — Run the setup script**
```bash
chmod +x setup.sh
./setup.sh
```
> ⏳ **This takes 15–30 minutes** — `dlib` is compiled from source on ARM. Do NOT close the terminal!

**Step 5 — Fix setuptools**
```bash
source venv/bin/activate
pip install "setuptools<67"
```

**Step 6 — Run the server**
```bash
python3 app.py
```

**Step 7 — (Optional) Auto-start on boot**
```bash
crontab -e
```
Add at the bottom:
```
@reboot cd /home/pi/ESP32-S3-Attendance-RaspberryPi && source venv/bin/activate && python3 app.py >> server.log 2>&1
```

---

### Running the Server

```bash
cd ~/ESP32-S3-Attendance-RaspberryPi
source venv/bin/activate
python3 app.py
```

Expected output:
```
[INFO] Loaded face: 201912664 — Yassmin Tarek Abdallah
[INFO] Total known faces loaded: 1
[INFO] Starting Flask attendance server on 0.0.0.0:5000
 * Running on http://127.0.0.1:5000
 * Running on http://172.29.81.141:5000
```

To stop: press `Ctrl+C`

---

### Face Recognition Pipeline

1. ESP32 sends raw JPEG bytes via `HTTP POST` to `/upload`
2. Flask receives bytes with `request.data`
3. PIL decodes JPEG → RGB image → numpy array
4. `face_recognition.face_locations()` finds all faces in the frame
5. `face_recognition.face_encodings()` generates 128-D vectors for each face
6. Each encoding is compared to all known face encodings:
   - `face_recognition.compare_faces()` with `tolerance=0.5`
   - `face_recognition.face_distance()` to find the best match
7. If a match is found → check if already recorded today → log to SQLite
8. Plain text response sent back to ESP32

**Tolerance setting:**

| Value | Behaviour |
|-------|-----------|
| `0.4` | Very strict — may miss matches |
| `0.5` | ✅ Default — good balance |
| `0.6` | More lenient — may cause false matches |

---

### Database Schema

**File:** `attendance.db` (SQLite, auto-created on first run)

```sql
CREATE TABLE attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT    NOT NULL,
    full_name  TEXT    NOT NULL,
    date       TEXT    NOT NULL,   -- format: YYYY-MM-DD
    time       TEXT    NOT NULL    -- format: HH:MM:SS
);
```

**Duplicate prevention:** Each student can only be logged once per calendar day.

---

### API Endpoints

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| `POST` | `/upload` | None | Receive JPEG from ESP32, run face recognition |
| `GET` | `/` | Session | Attendance dashboard |
| `GET/POST` | `/login` | — | Admin login form |
| `GET` | `/logout` | — | Clear session and redirect to login |

**`/upload` Response Examples:**
```
Attendance recorded: Yassmin Tarek Abdallah
Already recorded today: Yassmin Tarek Abdallah
Face not recognized
No image data received       (HTTP 400)
Invalid image data           (HTTP 400)
Face recognition failed      (HTTP 500)
```

---

### Web Dashboard

**Login credentials:**

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `00000` |

> Can be overridden with environment variables `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

**Dashboard features:**
- **Today's view** (default) — shows only today's records
- **All Records** — toggle to see full historical records
- **Table columns:** #, Student ID, Full Name, Date, Time
- **Logout** button

---

## Managing Students

### Add a New Student

**Step 1 — Add photo to `known_faces/`**

Name the photo file exactly as the student's ID:
```
known_faces/201912664.jpg
known_faces/202010374.jpg
```

Photo requirements:
- One clear, front-facing face
- Good lighting
- No sunglasses or heavy filters
- JPG, JPEG, or PNG format

**From Windows File Explorer (WSL):**
```
\wsl$\Ubuntu\home\<username>\ESP32-S3-Attendance-RaspberryPi\known_faces
```

**From another computer to Raspberry Pi (SCP):**
```bash
scp photo.jpg pi@<pi_ip>:~/ESP32-S3-Attendance-RaspberryPi/known_faces/201912664.jpg
```

**Step 2 — Register the student in `students.json`**

```bash
python3 -c ":
import json
with open('students.json', 'r') as f:
    data = json.load(f)
data['201912664'] = 'Yassmin Tarek Abdallah'
with open('students.json', 'w') as f:
    json.dump(data, f, indent=2)
print('Done!')
"
```

Or edit `students.json` directly:
```json
{
  "201912664": "Yassmin Tarek Abdallah",
  "202010374": "Nour Saed Kamel Shahwan",
  "202010375": "Ahmed Mohamed Ali",
  "202010376": "Sara Hassan Ibrahim",
  "202010377": "Omar Khaled Youssef",
  "202010378": "Lina Mahmoud Fathy",
  "202010379": "Yousef Tarek Saleh",
  "202010380": "Rania Adel Mansour"
}
```

**Step 3 — Restart the server**
```bash
python3 app.py
```

You should see:
```
[INFO] Loaded face: 201912664 — Yassmin Tarek Abdallah
```

---

## Managing Attendance Records

### Insert a Record Manually
```bash
python3 -c ":
import sqlite3
conn = sqlite3.connect('attendance.db')
conn.execute("INSERT INTO attendance (student_id, full_name, date, time) VALUES ('201912664', 'Yassmin Tarek Abdallah', '2026-04-04', '09:00:00')")
conn.commit()
print('Done!')
"
```

### Delete a Specific Record
```bash
python3 -c ":
import sqlite3
conn = sqlite3.connect('attendance.db')
conn.execute("DELETE FROM attendance WHERE student_id = '201912664' AND date = '2026-04-04'")
conn.commit()
print('Done!')
"
```

### Delete All Records
```bash
python3 -c ":
import sqlite3
conn = sqlite3.connect('attendance.db')
conn.execute('DELETE FROM attendance')
conn.commit()
print('All records deleted!')
"
```

### View All Records in Terminal
```bash
python3 -c ":
import sqlite3
conn = sqlite3.connect('attendance.db')
rows = conn.execute('SELECT * FROM attendance ORDER BY date DESC, time DESC').fetchall()
for row in rows:
    print(dict(row))
"
```

---

## Troubleshooting

### `Please install face_recognition_models` error
**Cause:** `pkg_resources` not available (broken in `setuptools>=67`)  
**Fix:**
```bash
pip install "setuptools<67"
```

### `No module named 'pkg_resources'`
**Same fix as above:**
```bash
pip install "setuptools<67"
```

### Camera init failed on ESP32
**Causes & fixes:**
- Wrong board selected in Arduino IDE → set to `ESP32S3 Dev Module`
- PSRAM not enabled → set `Tools → PSRAM → OPI PSRAM`
- Bad USB cable → use a data cable, not charge-only
- Hold **BOOT** button while uploading

### `Face not recognized` even for known students
- Ensure photo is clear and front-facing
- Try lowering tolerance in `app.py`: `TOLERANCE = 0.6`
- Make sure `students.json` has the correct student ID matching the filename

### Dashboard shows no records
- The database might be empty — use the manual insert command above to test
- Make sure you're looking at the correct date (default is today only — click "All Records")

### ESP32 cannot reach Raspberry Pi
- Confirm Pi is connected to the `ESP32-Camera` WiFi AP
- Run `hostname -I` on Pi to confirm IP is `192.168.4.2`
- If different IP, update `PI_SERVER_URL` in `attendance_cam.ino`

---

## Known Issues & Fixes Applied

| # | Issue | Status | Fix Applied |
|---|-------|--------|-------------|
| 1 | `pin_sscb_sda` deprecated API | ✅ Fixed | Renamed to `pin_sccb_sda` / `pin_sccb_scl` |
| 2 | `pkg_resources` missing (setuptools 67+) | ✅ Fixed | Install `setuptools<67` |
| 3 | `face_recognition_models` install error | ✅ Fixed | Caused by missing `pkg_resources` |
| 4 | `fb_location = CAMERA_FB_IN_DRAM` ignores PSRAM | ⚠️ Pending | Switch to `CAMERA_FB_IN_PSRAM` + `fb_count=2` |
| 5 | `xclk_freq_hz = 12000000` (too low) | ⚠️ Pending | Change to `20000000` |
| 6 | `config_base.h` / `config_in.h` / `config_out.h` unused | ⚠️ Pending | Clean up or integrate into sketch |

---

## Pending Improvements

- [ ] Switch `fb_location` to `CAMERA_FB_IN_PSRAM` in `attendance_cam.ino`
- [ ] Fix `xclk_freq_hz` to `20000000`
- [ ] Add `psramFound()` check with Serial warning in `setup()`
- [ ] Add export attendance to CSV feature on dashboard
- [ ] Add delete record button directly from dashboard UI
- [ ] Add student management page to dashboard (add/remove without terminal)
- [ ] Auto-start server on Raspberry Pi boot via systemd service
- [ ] Secure the `/upload` endpoint with a device key

---

*Documentation generated: 2026-04-04 15:12:15*  
*Project: ESP32-S3 Face Recognition Attendance System*  
*Repos: [ESP32 Firmware](https://github.com/MohamedAlaeldin/ESP32-S3-Attendance-) | [Raspberry Pi Server](https://github.com/MohamedAlaeldin/ESP32-S3-Attendance-RaspberryPi)*