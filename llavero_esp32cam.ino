#include <WiFi.h>
#include <HTTPClient.h>
#include "esp_camera.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// ===== CONFIGURACIÓN =====
const char* ssid         = "PEINE-2";
const char* password     = "etecPeine2";
const char* serverUrl    = "http://10.56.2.9:8000/reconocimiento";
const char* CASILLERO_ID = "C01";

const unsigned long TIEMPO_ENTRE_FOTOS   = 1000;
const unsigned long TIEMPO_REGISTRO      = 500;
const unsigned long PAUSA_TRAS_ACCESO_MS = 5000;
const unsigned long WIFI_TIMEOUT_MS      = 15000;

// Pines AI Thinker ESP32-CAM
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

bool enRegistro = false;
unsigned long proximoEscaneo = 0;
unsigned long ultimoIntentoWiFi = 0;

// ===== CÁMARA =====
void setupCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 10000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_VGA;
  config.jpeg_quality = 12;
  config.fb_count     = 3;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Error camara: 0x%x\n", err);
    delay(2000);
    ESP.restart();
  }
  Serial.println("Camara OK");
}

camera_fb_t* capturar() {
  for (int i = 0; i < 3; i++) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) return fb;
    Serial.println("[CAM] reintento...");
    delay(150);
  }
  return NULL;
}

// ===== WIFI =====
void setupWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.print("WiFi");
  unsigned long ini = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - ini < WIFI_TIMEOUT_MS) {
    delay(500); Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nConectado: " + WiFi.localIP().toString());
    Serial.println("Server: " + String(serverUrl));
  } else {
    Serial.println("\nTimeout - reintentara en loop");
  }
}

void mantenerWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - ultimoIntentoWiFi < 5000) return;
  ultimoIntentoWiFi = millis();
  Serial.println("WiFi caido -> reconectando");
  WiFi.disconnect();
  WiFi.begin(ssid, password);
}

// ===== JSON HELPER =====
String extraerCampo(const String& json, const String& campo) {
  String clave = "\"" + campo + "\":\"";
  int i = json.indexOf(clave);
  if (i < 0) return "";
  i += clave.length();
  int f = json.indexOf("\"", i);
  return (f < 0) ? "" : json.substring(i, f);
}

// ===== ENVÍO =====
void enviarFoto() {
  sensor_t* s = esp_camera_sensor_get();
  s->set_framesize(s, enRegistro ? FRAMESIZE_QVGA : FRAMESIZE_VGA);

  camera_fb_t* fb = capturar();
  if (!fb) { proximoEscaneo = millis() + 1000; return; }

  HTTPClient http;
  http.begin(serverUrl);
  http.setTimeout(20000);
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-Casillero-Id", CASILLERO_ID);

  int code = http.POST(fb->buf, fb->len);

  if (code > 0) {
    String r = http.getString();
    bool reg = r.indexOf("\"modo\":\"registro\"") >= 0;

    if (reg != enRegistro) {
      enRegistro = reg;
      Serial.println(reg ? "[MODO] Registro" : "[MODO] Reconocimiento");
    }

    if (reg) {
      proximoEscaneo = millis() + TIEMPO_REGISTRO;
    } else {
      bool ok = r.indexOf("\"autorizado\":true") >= 0;
      if (ok) {
        Serial.println("=== ACCESO: " + extraerCampo(r, "persona") + " ===");
        proximoEscaneo = millis() + PAUSA_TRAS_ACCESO_MS;
      } else {
        Serial.println("Denegado: " + extraerCampo(r, "mensaje"));
        proximoEscaneo = millis() + TIEMPO_ENTRE_FOTOS;
      }
    }
  } else {
    Serial.printf("HTTP %d: %s\n", code, http.errorToString(code).c_str());
    proximoEscaneo = millis() + 2000;
  }
  http.end();
  esp_camera_fb_return(fb);
  delay(10);
}

// ===== SETUP / LOOP =====
void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== BOOT ===");
  Serial.printf("PSRAM: %s\n", psramFound() ? "SI" : "NO");
  setupCamera();
  setupWiFi();
}

void loop() {
  mantenerWiFi();
  if (WiFi.status() != WL_CONNECTED) { delay(200); return; }
  if (millis() >= proximoEscaneo) enviarFoto();
  delay(10);
}