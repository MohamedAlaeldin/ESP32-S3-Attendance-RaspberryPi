#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"
#include <HTTPClient.h>

// =================== CONFIGURATION ===================
const char* PI_SERVER_URL = "http://192.168.4.2:5000/upload";

// =================== CAMERA PINS (Freenove ESP32-S3-WROOM) ===================
#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  15
#define SIOD_GPIO_NUM  4
#define SIOC_GPIO_NUM  5
#define Y9_GPIO_NUM    16
#define Y8_GPIO_NUM    17
#define Y7_GPIO_NUM    18
#define Y6_GPIO_NUM    12
#define Y5_GPIO_NUM    10
#define Y4_GPIO_NUM    8
#define Y3_GPIO_NUM    9
#define Y2_GPIO_NUM    11
#define VSYNC_GPIO_NUM 6
#define HREF_GPIO_NUM  7
#define PCLK_GPIO_NUM  13

httpd_handle_t camera_httpd = NULL;

// =================== WEB PAGE HTML ===================
const char index_html[] PROGMEM = R"rawliteral(
<!DOCTYPE HTML>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: #1a1a1a;
      text-align: center;
      color: white;
      font-family: Helvetica, Arial, sans-serif;
      padding: 20px;
    }
    h2 { margin-bottom: 10px; font-size: 26px; letter-spacing: 1px; }
    .subtitle { color: #aaa; font-size: 13px; margin-bottom: 15px; }
    img {
      width: 100%;
      max-width: 420px;
      transform: rotate(180deg);
      border: 2px solid #444;
      border-radius: 10px;
      display: block;
      margin: 0 auto;
    }
    .btn {
      background-color: #007bff;
      border: none;
      color: white;
      padding: 18px 40px;
      font-size: 22px;
      font-weight: bold;
      margin: 25px auto 10px auto;
      cursor: pointer;
      border-radius: 50px;
      width: 80%;
      max-width: 300px;
      display: block;
      box-shadow: 0 5px #0056b3;
      transition: all 0.1s;
    }
    .btn:active {
      background-color: #0056b3;
      box-shadow: 0 0 #0056b3;
      transform: translateY(4px);
    }
    .btn:disabled {
      background-color: #555;
      box-shadow: 0 5px #333;
      cursor: not-allowed;
    }
    #status {
      font-size: 22px;
      font-weight: bold;
      margin-top: 15px;
      min-height: 35px;
      color: #00ff00;
      padding: 5px;
    }
    #log {
      margin: 15px auto;
      max-width: 420px;
      background: #111;
      border: 1px solid #333;
      border-radius: 8px;
      padding: 10px;
      font-size: 13px;
      color: #aaa;
      text-align: left;
      min-height: 60px;
      max-height: 150px;
      overflow-y: auto;
    }
  </style>
</head>
<body>
  <h2>Attendance Cam</h2>
  <p class="subtitle">Freenove ESP32-S3-WROOM</p>

  <img src="/stream" id="video">

  <p id="status">Ready</p>

  <button class="btn" id="captureBtn" onclick="capture()">CAPTURE</button>

  <div id="log">Waiting for capture...</div>

  <script>
    function addLog(msg) {
      var log = document.getElementById("log");
      var line = document.createElement("div");
      line.textContent = new Date().toLocaleTimeString() + " -> " + msg;
      log.appendChild(line);
      log.scrollTop = log.scrollHeight;
    }

    function capture() {
      var statusEl = document.getElementById("status");
      var btn = document.getElementById("captureBtn");

      statusEl.innerHTML = "Capturing...";
      statusEl.style.color = "yellow";
      btn.disabled = true;

      addLog("Capturing photo...");

      var xhttp = new XMLHttpRequest();

      xhttp.onreadystatechange = function() {
        if (this.readyState == 4) {
          btn.disabled = false;
          if (this.status == 200) {
            var resp = this.responseText.trim();
            statusEl.innerHTML = resp;
            statusEl.style.color = "#00ff00";
            addLog("Server: " + resp);
          } else {
            statusEl.innerHTML = "Error: " + this.responseText;
            statusEl.style.color = "red";
            addLog("Error: " + this.responseText);
          }
          setTimeout(function() {
            statusEl.innerHTML = "Ready";
            statusEl.style.color = "#00ff00";
          }, 3000);
        }
      };

      xhttp.timeout = 30000;
      xhttp.ontimeout = function() {
        statusEl.innerHTML = "Timeout - Pi took too long";
        statusEl.style.color = "red";
        btn.disabled = false;
        addLog("Timeout after 30 seconds");
      };

      xhttp.onerror = function() {
        statusEl.innerHTML = "Connection Error";
        statusEl.style.color = "red";
        btn.disabled = false;
        addLog("Connection error");
      };

      xhttp.open("GET", "/capture", true);
      xhttp.send();
      addLog("Sending to Pi server...");
    }
  </script>
</body>
</html>
)rawliteral";

// =================== HANDLERS ===================

static esp_err_t index_handler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, index_html, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t capture_handler(httpd_req_t *req) {
  Serial.println("-----------------------------");
  Serial.println("[ESP32] Capture triggered by browser");

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[ESP32] ERROR: Camera capture failed!");
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }

  Serial.printf("[ESP32] Photo captured: %u bytes (%.1f KB)\n", fb->len, fb->len / 1024.0);
  Serial.printf("[ESP32] Sending to: %s\n", PI_SERVER_URL);

  HTTPClient http;
  http.begin(PI_SERVER_URL);
  http.addHeader("Content-Type", "image/jpeg");
  http.setTimeout(30000);

  int httpCode = http.POST(fb->buf, fb->len);
  esp_camera_fb_return(fb);

  String responseMsg;
  if (httpCode > 0) {
    responseMsg = http.getString();
    Serial.printf("[ESP32] Pi responded (%d): %s\n", httpCode, responseMsg.c_str());
    httpd_resp_send(req, responseMsg.c_str(), HTTPD_RESP_USE_STRLEN);
  } else {
    responseMsg = "Send Failed: " + String(httpCode);
    Serial.printf("[ESP32] ERROR: %s\n", responseMsg.c_str());
    httpd_resp_set_status(req, "500 Internal Server Error");
    httpd_resp_send(req, responseMsg.c_str(), HTTPD_RESP_USE_STRLEN);
  }

  http.end();
  Serial.println("-----------------------------");
  return ESP_OK;
}

static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t *fb = NULL;
  esp_err_t res = ESP_OK;
  char part_buf[64];

  res = httpd_resp_set_type(req, "multipart/x-mixed-replace;boundary=frame");
  if (res != ESP_OK) return res;

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
    } else {
      size_t hlen = snprintf(part_buf, 64,
        "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", fb->len);
      res = httpd_resp_send_chunk(req, part_buf, hlen);
      if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
      if (res == ESP_OK) res = httpd_resp_send_chunk(req, "\r\n--frame\r\n", 12);
      esp_camera_fb_return(fb);
    }
    if (res != ESP_OK) break;
    delay(20);
  }
  return res;
}

void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;

  httpd_uri_t index_uri   = { .uri = "/",       .method = HTTP_GET, .handler = index_handler,   .user_ctx = NULL };
  httpd_uri_t stream_uri  = { .uri = "/stream",  .method = HTTP_GET, .handler = stream_handler,  .user_ctx = NULL };
  httpd_uri_t capture_uri = { .uri = "/capture", .method = HTTP_GET, .handler = capture_handler, .user_ctx = NULL };

  if (httpd_start(&camera_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(camera_httpd, &index_uri);
    httpd_register_uri_handler(camera_httpd, &stream_uri);
    httpd_register_uri_handler(camera_httpd, &capture_uri);
    Serial.println("[ESP32] Web server started on port 80");
  }
}

// =================== SETUP ===================
void setup() {
  delay(3000);
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=============================");
  Serial.println("  ESP32-S3 Attendance Cam");
  Serial.println("  Freenove ESP32-S3-WROOM");
  Serial.println("=============================");

  // --- Camera Config ---
  camera_config_t config;
  config.ledc_channel  = LEDC_CHANNEL_0;
  config.ledc_timer    = LEDC_TIMER_0;
  config.pin_d0        = Y2_GPIO_NUM;
  config.pin_d1        = Y3_GPIO_NUM;
  config.pin_d2        = Y4_GPIO_NUM;
  config.pin_d3        = Y5_GPIO_NUM;
  config.pin_d4        = Y6_GPIO_NUM;
  config.pin_d5        = Y7_GPIO_NUM;
  config.pin_d6        = Y8_GPIO_NUM;
  config.pin_d7        = Y9_GPIO_NUM;
  config.pin_xclk      = XCLK_GPIO_NUM;
  config.pin_pclk      = PCLK_GPIO_NUM;
  config.pin_vsync     = VSYNC_GPIO_NUM;
  config.pin_href      = HREF_GPIO_NUM;
  config.pin_sccb_sda  = SIOD_GPIO_NUM;
  config.pin_sccb_scl  = SIOC_GPIO_NUM;
  config.pin_pwdn      = PWDN_GPIO_NUM;
  config.pin_reset     = RESET_GPIO_NUM;
  config.xclk_freq_hz  = 20000000;
  config.pixel_format  = PIXFORMAT_JPEG;
  config.grab_mode     = CAMERA_GRAB_WHEN_EMPTY;

  // Use PSRAM for maximum quality (Freenove ESP32-S3-WROOM has 8MB PSRAM)
  if (psramFound()) {
    Serial.println("[ESP32] PSRAM found - using maximum quality");
    config.frame_size   = FRAMESIZE_UXGA;
    config.jpeg_quality = 4;
    config.fb_count     = 2;
    config.fb_location  = CAMERA_FB_IN_PSRAM;
  } else {
    Serial.println("[ESP32] No PSRAM - falling back to QVGA");
    config.frame_size   = FRAMESIZE_QVGA;
    config.jpeg_quality = 10;
    config.fb_count     = 1;
    config.fb_location  = CAMERA_FB_IN_DRAM;
  }

  // --- Init Camera ---
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[ESP32] ERROR: Camera init failed (0x%x)\n", err);
    return;
  }
  Serial.println("[ESP32] Camera initialized successfully!");

  // --- Maximum Quality Sensor Settings ---
  sensor_t *s = esp_camera_sensor_get();
  s->set_framesize(s, FRAMESIZE_UXGA);
  s->set_quality(s, 4);
  s->set_brightness(s, 1);
  s->set_contrast(s, 1);
  s->set_saturation(s, 0);
  s->set_whitebal(s, 1);
  s->set_awb_gain(s, 1);
  s->set_exposure_ctrl(s, 1);
  s->set_aec2(s, 1);
  Serial.println("[ESP32] Camera quality set to MAXIMUM (UXGA, quality=4)");

  // --- WiFi Access Point ---
  WiFi.softAP("ESP32-Camera", "12345678", 6);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  Serial.print("[ESP32] WiFi AP started - IP: ");
  Serial.println(WiFi.softAPIP());

  // --- Start Web Server ---
  startCameraServer();

  Serial.println("[ESP32] System ready!");
  Serial.printf("[ESP32] Pi server URL: %s\n", PI_SERVER_URL);
  Serial.println("=============================");
}

// =================== LOOP ===================
void loop() {
  delay(1);
}
