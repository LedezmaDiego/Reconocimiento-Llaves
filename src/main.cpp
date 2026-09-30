#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "esp_camera.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// =========================================================
// CONFIGURACIÓN
// =========================================================
const char* ssid     = "Telecentro-cd93";
const char* password = "UHX63RCRHF3U";
// IP de la PC donde corre uvicorn (ver con ipconfig)
const char* SERVER_BASE  = "http://192.168.0.122:8000";
const char* CASILLERO_ID = "C01";

const unsigned long TIEMPO_ENTRE_FOTOS    = 1500;
const unsigned long PAUSA_TRAS_ACCESO_MS  = 5000;

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

unsigned long proximoEscaneo = 0;
unsigned long ultimoIntentoWiFi = 0;

// =========================================================
// CÁMARA
// =========================================================
bool setupCamera() {
  camera_config_t config = {};   // inicializa todos los campos en cero

  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
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
  config.frame_size   = FRAMESIZE_VGA;   // igual que el sketch de registro
  config.jpeg_quality = 10;
  config.fb_count     = 2;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Error al inicializar la cámara: 0x%x\n", err);
    return false;
  }
  Serial.println("Cámara inicializada correctamente.");
  return true;
}

camera_fb_t* capturar() {
  for (int i = 0; i < 3; i++) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) return fb;
    Serial.println("[CAM] captura fallida, reintentando...");
    delay(150);
  }
  return NULL;
}

// =========================================================
// RED
// =========================================================
void setupWiFi() {
  Serial.print("Conectando a WiFi: ");
  Serial.println(ssid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.print("\nWiFi OK. IP: ");
  Serial.println(WiFi.localIP());
}

void mantenerWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - ultimoIntentoWiFi < 5000) return;
  ultimoIntentoWiFi = millis();
  Serial.println("WiFi caído. Reconectando...");
  WiFi.disconnect();
  WiFi.begin(ssid, password);
}

// Extrae el valor de un campo string del JSON: "campo":"valor"
String extraerCampo(const String& json, const String& campo) {
  String clave = "\"" + campo + "\":\"";
  int i = json.indexOf(clave);
  if (i < 0) return "";
  i += clave.length();
  int f = json.indexOf("\"", i);
  if (f < 0) return "";
  return json.substring(i, f);
}

// =========================================================
// RECONOCIMIENTO
// =========================================================
// Devuelve true si el rostro fue autorizado
bool escanear() {
  camera_fb_t* fb = capturar();
  if (!fb) {
    Serial.println("Error al capturar.");
    return false;
  }

  Serial.printf("Enviando foto de %u bytes...\n", (unsigned)fb->len);

  HTTPClient http;
  String url = String(SERVER_BASE) + "/reconocimiento";
  http.begin(url);
  http.setTimeout(20000);   // el servidor puede tardar unos segundos
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-Casillero-Id", CASILLERO_ID);

  int code = http.POST(fb->buf, fb->len);
  bool autorizado = false;

  if (code > 0) {
    String resp = http.getString();
    autorizado = resp.indexOf("\"autorizado\":true") >= 0;

    if (autorizado) {
      Serial.println("==============================");
      Serial.println("ACCESO PERMITIDO: " + extraerCampo(resp, "persona"));
      Serial.println("==============================");
    } else {
      Serial.println("Acceso denegado: " + extraerCampo(resp, "mensaje"));
    }
  } else {
    Serial.printf("Error POST: %s\n", http.errorToString(code).c_str());
  }

  http.end();
  esp_camera_fb_return(fb);
  return autorizado;
}

// =========================================================
// SETUP / LOOP
// =========================================================
void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== BOOT ===");
  Serial.printf("PSRAM: %s\n", psramFound() ? "SI" : "NO");
  Serial.println("--- Llavero Inteligente ETEC: reconocimiento ---");

  if (!setupCamera()) {
    Serial.println("Cámara no disponible. Reinicia la placa.");
    return;
  }
  setupWiFi();
}

void loop() {
  mantenerWiFi();

  if (WiFi.status() != WL_CONNECTED) {
    delay(200);
    return;
  }

  if (millis() < proximoEscaneo) return;

  bool autorizado = escanear();
  proximoEscaneo = millis() + (autorizado ? PAUSA_TRAS_ACCESO_MS : TIEMPO_ENTRE_FOTOS);
}