#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include "esp_camera.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// =========================================================
// CONFIGURACIÓN
// =========================================================

const char* ssid     = "Telecentro-cd93";
const char* password = "UHX63RCRHF3U";
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

WebServer server(80);

// =========================================================
// PÁGINA WEB
// =========================================================
const char PAGINA[] PROGMEM = R"rawliteral(
<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Registro de rostros</title>
<style>
  body{font-family:sans-serif;text-align:center;background:#111;color:#eee;margin:0;padding:12px}
  img{max-width:100%;border-radius:8px;background:#000;min-height:200px}
  input,button{font-size:1.1em;padding:10px;margin:6px;border-radius:6px;border:0}
  button{background:#2e7d32;color:#fff}
</style></head><body>
<h2>Registro de rostros - ESP32-CAM</h2>
<img id="v" src="/capture">
<div>
  <input id="n" placeholder="nombre (ej: dylan)">
  <button onclick="guardar()">Guardar foto</button>
</div>
<p id="m"></p>
<script>
let guardando = false;
const v = document.getElementById('v');
const m = document.getElementById('m');

function refrescar(){
  if (guardando) return;
  v.src = '/capture?t=' + Date.now();
}
v.onload  = () => setTimeout(refrescar, 500);
v.onerror = () => setTimeout(refrescar, 1000);

async function guardar(){
  const nombre = document.getElementById('n').value.trim().toLowerCase().replace(/[^a-z]/g,'');
  if (!nombre){ m.textContent = 'Escribe un nombre (solo letras).'; return; }
  guardando = true;
  try {
    const r = await fetch('/capture?t=' + Date.now());
    if (!r.ok) throw new Error('la placa no pudo capturar (HTTP ' + r.status + ')');
    const b = await r.blob();
    if (b.size < 5000) throw new Error('imagen demasiado pequeña (' + b.size + ' bytes)');
    const c = parseInt(localStorage.getItem('c_' + nombre) || '0') + 1;
    localStorage.setItem('c_' + nombre, c);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = nombre + c + '.jpg';
    a.click();
    m.textContent = 'Guardada: ' + nombre + c + '.jpg (' + Math.round(b.size / 1024) + ' KB)';
  } catch (e) {
    m.textContent = 'Error: ' + e.message + '. Vuelve a intentar.';
  }
  guardando = false;
  refrescar();
}
</script>
</body></html>
)rawliteral";

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
  config.frame_size   = FRAMESIZE_VGA;   // 640x480, igual que el sistema final
  config.jpeg_quality = 10;              // menor número = mejor calidad
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
// HANDLERS
// =========================================================
void handleRoot() {
  server.send_P(200, "text/html", PAGINA);
}

void handleCapture() {
  camera_fb_t* fb = capturar();
  if (!fb) {
    Serial.println("[CAPTURE] esp_camera_fb_get devolvió NULL");
    server.send(500, "text/plain", "Error de captura");
    return;
  }
  Serial.printf("[CAPTURE] Foto de %u bytes\n", (unsigned)fb->len);

  WiFiClient client = server.client();
  client.print("HTTP/1.1 200 OK\r\n");
  client.print("Content-Type: image/jpeg\r\n");
  client.printf("Content-Length: %u\r\n", (unsigned)fb->len);
  client.print("Cache-Control: no-store\r\n");
  client.print("Connection: close\r\n\r\n");

  size_t enviados = 0;
  while (enviados < fb->len) {
    size_t resto = fb->len - enviados;
    size_t n = client.write(fb->buf + enviados, resto > 1024 ? 1024 : resto);
    if (n == 0) break;
    enviados += n;
  }
  esp_camera_fb_return(fb);
}

// =========================================================
// SETUP / LOOP
// =========================================================
void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== BOOT ===");
  Serial.printf("PSRAM: %s, tamaño: %u bytes\n", psramFound() ? "SI" : "NO", (unsigned)ESP.getPsramSize());
  Serial.println("--- Registro de rostros ETEC ---");

  if (!setupCamera()) {
    Serial.println("Cámara no disponible. Reinicia la placa.");
    return;
  }

  WiFi.begin(ssid, password);
  Serial.print("Conectando a WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Abre en el navegador: http://");
  Serial.println(WiFi.localIP());

  server.on("/", handleRoot);
  server.on("/capture", handleCapture);
  server.begin();
}

void loop() {
  server.handleClient();
}