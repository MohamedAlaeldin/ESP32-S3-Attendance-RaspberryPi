# 📋 Session Log — 2026-05-16
> ESP32-S3 Attendance System — Troubleshooting & Feature Development

---

## 🛠️ Issues Fixed & Features Added

---

### 1. ✅ WiFi Connection Error (`nmcli key-mgmt`)
**Problem:**
```
Error: 802-11-wireless-security.key-mgmt: property is missing.
```
**Fix — tried in order:**
```bash
sudo nmcli dev wifi connect "ESP32-Camera" password "12345678" name "ESP32-Camera"
sudo nmcli dev wifi connect "ESP32-Camera" password "12345678" key-mgmt wpa-psk
sudo nmcli dev wifi connect "ESP32-Camera"   # if open network
```

---

### 2. ✅ Database Schema Error (`no such column: course_name`)
**Problem:**
```
sqlite3.OperationalError: no such column: course_name
```
**Fix — delete old DB and let it recreate:**
```bash
rm attendance.db
python3 app.py
```

---

### 3. ✅ Wrong `students.json` Data
**Problem:** Pi had old dummy student IDs.

**Fix:**
```bash
cat > students.json << 'EOF'
{
  "202210453": "Areej",
  "202410374": "Youssef"
}
EOF
```

---

### 4. ✅ Feature: Auto Session End + Shutdown
**Added to `app.py`:**
- At the **End Time** entered in the popup, the server logs the session end and shuts down cleanly (same as `Ctrl+C`).

**Log output:**
```
════════════════════════════════════════
[SESSION] ⏰ Session ended at 20:05:00
[SESSION] Course  : DIC
[SESSION] Section : 2B
[SESSION] Shutting down server...
════════════════════════════════════════
```

---

### 5. ✅ Feature: Unknown Face Message
**Added to `app.py`:**
- When an unrecognized face is scanned, the ESP32 browser and Pi logs both show a clear message.

**Pi logs:**
```
[WARN] ⚠ Unknown Face: This student is not registered in this course (distance: 0.71)
```
**ESP32 browser shows:**
```
⚠ Unknown Face: This student is not registered in this course
```

---

### 6. ✅ Feature: Auto-Send CSV Email at Session End
**Added to `app.py`:**
- At session end, the app automatically fetches today's attendance records, generates the CSV, and emails it.

**Log output:**
```
[EMAIL] Preparing attendance report...
[EMAIL] ✓ Report sent to areejshahwan2000@gmail.com
```

**Fix SMTP credentials permanently (run once):**
```bash
echo 'export SMTP_USER="nshahwan289@gmail.com"' >> ~/.bashrc
echo 'export SMTP_PASS="vsmesdrgquekzhpf"' >> ~/.bashrc
source ~/.bashrc
```

---

### 7. ✅ Feature: Auto-Exit at Class End Time
**Problem:** Students who only scanned **entry** had no exit time recorded.

**Fix added to `app.py`:**
- At session end, any student with only an entry scan gets their exit time automatically set to the class **End Time**.
- Status (Present/Absent) is then calculated using the 80% rule.

**Log output:**
```
[AUTO-EXIT] Areej  → exit set to 13:38:00 → Present
[AUTO-EXIT] Youssef → exit set to 13:38:00 → Absent
```

> Students who scanned both entry **and** exit during the session keep their recorded exit time. ✅

---

### 8. ✅ Feature: WiFi Name + Password in Popup
**Added two new fields to the Tkinter startup popup:**

```
── Home WiFi (for email after session) ──
WiFi Name:      [____________________]
WiFi Password:  [********************]
```

At session end:
1. Pi auto-exits open entries
2. Pi switches back to home WiFi using `nmcli`
3. Pi sends the CSV email
4. Pi shuts down

---

### 9. 🔴 WiFi Switch Failing (`No network with SSID found`)
**Problem:**
```
[WIFI] ✗ Failed: Error: No network with SSID 'Escape cafe' found.
```

**Root cause:** Pi was connected to ESP32 hotspot and hadn't scanned for other networks.

**Fix added to `app.py`:**
- Runs `nmcli dev wifi rescan` before connecting
- Waits 5 seconds for scan to complete
- Retries **3 times** with 5s between attempts

**Working log:**
```
[WIFI] Scanning for networks...
[WIFI] Switching to home WiFi: 'Escape cafe' ...
[WIFI] ✓ Connected to 'Escape cafe'
[EMAIL] ✓ Report sent to areejshahwan2000@gmail.com
```

> ⚠️ WiFi name must match **exactly** — check with:
> ```bash
> sudo nmcli dev wifi list
> ```

---

## 📦 Git Commands Used

```bash
# Pull latest app.py updates
git pull origin main

# Restart the app
python3 app.py
```

---

## 🔁 Full Session End Flow

```
Session End Time reached
  → [AUTO-EXIT] Set exit = End Time for entry-only students
  → [WIFI] rescan → connect to home WiFi (3 retries)
  → [EMAIL] Generate CSV → Send to professor's email
  → [SESSION] Shutdown Flask server
```

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `app.py` | Main Flask server — all logic |
| `students.json` | Student ID → Name mapping |
| `known_faces/` | Face images (named `<student_id>.jpg`) |
| `attendance.db` | SQLite database — attendance records |

---

## 🧪 Verified Working Sessions

| Course | Section | Time | Students | Email |
|--------|---------|------|----------|-------|
| Mathematics 1 | 2B | 13:11 - 13:22 | Areej ✅ Youssef ❌ | — (no WiFi) |
| DIC | 2B | 13:28 - 13:38 | Areej ✅ Youssef ❌ | — (WiFi failed) |

---

*Log generated: 2026-05-16*
