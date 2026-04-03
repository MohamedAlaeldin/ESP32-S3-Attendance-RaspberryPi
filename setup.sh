#!/usr/bin/env bash
# =============================================================
# setup.sh — Automated setup script for Raspberry Pi 5 / Raspbian OS
# Installs system packages and Python dependencies required to
# run the ESP32-S3 Attendance System.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# NOTE: dlib compilation can take 15–30 minutes on Raspberry Pi!
# =============================================================

set -e  # Exit immediately on any error

echo "=============================================="
echo "  ESP32-S3 Attendance System — Setup Script"
echo "  Raspberry Pi 5 / Raspbian OS"
echo "=============================================="
echo ""

# Step 1: Update package list
echo "[1/5] Updating package list..."
sudo apt-get update -y

# Step 2: Install system-level dependencies for dlib / face_recognition
echo ""
echo "[2/5] Installing system dependencies (cmake, BLAS, LAPACK, JPEG)..."
sudo apt-get install -y \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libjpeg-dev \
    python3-pip \
    python3-venv

# Step 3: Create a virtual environment and install Python dependencies
# NOTE: dlib is compiled from source — this takes 15–30 minutes on Raspberry Pi 5.
echo ""
echo "[3/5] Creating Python virtual environment (venv/)..."
python3 -m venv venv
echo ""
echo "Installing Python packages into venv/ (this may take 15–30 min for dlib)..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# Step 4: Create known_faces directory if it doesn't already exist
echo ""
echo "[4/5] Ensuring known_faces/ directory exists..."
mkdir -p known_faces

# Step 5: Print success message and usage instructions
echo ""
echo "[5/5] Setup complete! ✅"
echo ""
echo "=============================================="
echo "  Next Steps:"
echo "=============================================="
echo ""
echo "1. Add student face photos to known_faces/"
echo "   Name each file: {student_id}.jpg  (e.g. 202010374.jpg)"
echo ""
echo "2. Verify student names in students.json"
echo ""
echo "3. Start the server:"
echo "   source venv/bin/activate"
echo "   python3 app.py"
echo ""
echo "4. Open the dashboard in your browser:"
echo "   http://<raspberry_pi_ip>:5000"
echo ""
echo "   Default login — username: admin   password: 00000"
echo ""
echo "   The ESP32-S3 sends images to:"
echo "   http://192.168.4.2:5000/upload"
echo "   Make sure the Pi's IP is 192.168.4.2 on the ESP32 AP network,"
echo "   or update PI_SERVER_URL in the ESP32 Arduino sketch (src/attendance_cam.ino)."
echo ""
