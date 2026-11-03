/*
 * ============================================================
 *  DISPENSADOR DE LLAVES - ESP32 (Arduino IDE)
 * ============================================================
 *  MOTOR (L298N puente B):   IN3 -> GPIO25   IN4 -> GPIO26
 *  ENCODER:                  GPIO34
 *  RFID RC522 (3.3V):        SS=5 SCK=18 MOSI=23 MISO=19 RST=27
 *  LCD I2C:                  SCL=22 SDA=21
 *  TECLADO 4x4:              R=4,13,14,16  C=17,32,33,2
 *  LED:                      R=12 G=15
 *
 *  Novedades:
 *   - Acepta varios tags por llave (campo "rfids" del servidor).
 *   - Modo escaneo: el admin pide escanear desde la web y el UID
 *     se envía al backend (MAYÚSCULAS, sin separadores).
 *   - Flujo por rostro: la ESP32-CAM reconoce a la persona, el LCD
 *     muestra "Bienvenido <persona>" y luego se escribe el número de
 *     aula. El servidor confirma si la llave está disponible antes de
 *     girar el carrusel.
 * ============================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <LiquidCrystal_I2C.h>
#include <Keypad.h>
#include <SPI.h>
#include <MFRC522.h>
#include <ArduinoJson.h>

// ===== RED =====
const char* WIFI_SSID      = "PEINE-3";
const char* WIFI_PASSWORD  = "etecPeine3";
const char* SERVER_URL     = "http://10.56.16.12:8000";   // IP de la PC del backend
const char* DISPENSADOR_ID = "D01";

// ===== PINES =====
#define PIN_IN3      25
#define PIN_IN4      26
#define VEL_MOTOR   200
#define PIN_ENCODER  34
#define PIN_RFID_SS   5
#define PIN_RFID_RST 27
#define LCD_ADDR    0x27
#define LCD_COLS    16
#define LCD_ROWS     2
const byte FILAS[4]    = { 4, 13, 14, 16};
const byte COLUMNAS[4] = {17, 32, 33,  2};
#define PIN_LED_R    12
#define PIN_LED_G    15

char teclas[4][4] = {
  {'1','2','3','A'},
  {'4','5','6','B'},
  {'7','8','9','C'},
  {'*','0','#','D'}
};

// ===== PARÁMETROS =====
const unsigned long TIMEOUT_PETICION_MS   = 15000;
const unsigned long TIMEOUT_SESION_MS     = 60000;
const unsigned long TIMEOUT_GIRO_MS       = 10000;
const unsigned long TIEMPO_RETIRO_MS      = 8000;
const int           MAX_INTENTOS_PIN      = 3;
const int           PULSOS_POR_VUELTA     = 20;   // CALIBRAR
const unsigned long CONSULTA_SOLICITUD_MS = 3000;
const unsigned long CONSULTA_ESCANEO_MS   = 1000;
const int           MAX_TAGS              = 8;
// Flujo por rostro: el ESP32-CAM reconoce y el dispensador saluda y pide el aula.
const unsigned long CONSULTA_ROSTRO_MS    = 1500;
const unsigned long SALUDO_MS             = 2500;
const unsigned long AVISO_MS              = 2500;
const int           LONGITUD_LCD          = 16;

// ===== ESTRUCTURAS =====
struct SolicitudLlave {
  bool   activa      = false;
  int    aulaId      = 0;
  String aulaNombre  = "";
  String persona     = "";
  String rfids[MAX_TAGS];
  int    nRfids      = 0;
  bool   requierePin = false;
};

struct EstadoDispensador {
  bool motorGirando = false;
  volatile long pulsosEncoder = 0;
  int  intentosPin  = 0;
};

LiquidCrystal_I2C lcd(LCD_ADDR, LCD_COLS, LCD_ROWS);
Keypad teclado = Keypad(makeKeymap(teclas), FILAS, COLUMNAS, 4, 4);
MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);

SolicitudLlave    solicitud;
EstadoDispensador estado;

unsigned long ultimaPeticionMs         = 0;
unsigned long ultimaConsultaEscaneoMs  = 0;
unsigned long ultimaConsultaRostroMs   = 0;
unsigned long ultimaAccionMs           = 0;
bool modoEscaneo = false;

// Rostro que avisó el ESP32-CAM. "ultimoSeqSaludado" evita repetir el saludo.
String personaReconocida = "";
long   ultimoSeqSaludado = -1;

String bufferAula, bufferPin;
int pantalla = 0;   // 0 inicio, 1 aula, 2 PIN, 3 girando, 4 entregado, 5 error

// ===== PROTOTIPOS =====
void setupWiFi();
void mantenerWiFi();
void mostrarEnLCD(const String& l1, const String& l2 = "");
void ledRojo(); void ledVerde(); void ledAzul(); void ledAmbar(); void ledApagado();
void IRAM_ATTR encoderISR();
void girarMotor(int velocidad);
void detenerMotor();
String leerRFID();
bool buscarYLlevarLlave();
bool peticionSolicitud();
bool validarPinEnServidor(const String& pin);
bool notificarEvento(const String& evento, const String& detalle = "");
String peticionHTTP(const String& endpoint, const String& metodo,
                    const String& cuerpo, const String& tipoContenido);
bool esTagObjetivo(const String& uid);
void gestionarEscaneo();
void dibujarInicio(); void dibujarAula(); void dibujarPin(); void dibujarGirando();
void dibujarEntregado(const String& aula); void dibujarError(const String& mensaje);
void procesarTecla(char tecla);
void resetSesion();
// Flujo por rostro
String recortarLCD(const String& texto);
void avisar(const String& l1, const String& l2);
void saludar(const String& persona);
bool consultarRostro();
bool solicitarLlave(const String& numero);

// ===== SETUP =====
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n\n=== DISPENSADOR DE LLAVES ===");

  pinMode(PIN_IN3, OUTPUT);
  pinMode(PIN_IN4, OUTPUT);
  detenerMotor();

  pinMode(PIN_ENCODER, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_ENCODER), encoderISR, RISING);

  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  ledApagado();

  lcd.init();
  lcd.backlight();
  mostrarEnLCD("Iniciando...", "Dispensador ETEC");

  SPI.begin();
  rfid.PCD_Init();
  Serial.println("RC522 listo");

  setupWiFi();
  pantalla = 0;
  dibujarInicio();
  Serial.println("Sistema listo.");
}

// ===== LOOP =====
void loop() {
  mantenerWiFi();

  // En reposo se consulta la web (solicitud) y la cámara (rostro reconocido).
  if (WiFi.status() == WL_CONNECTED && pantalla == 0) {
    if (millis() - ultimaPeticionMs > CONSULTA_SOLICITUD_MS) {
      ultimaPeticionMs = millis();
      peticionSolicitud();
    }
    // Si hay un pedido hecho desde la web, ese tiene prioridad sobre el rostro.
    if (!solicitud.activa && !modoEscaneo &&
        millis() - ultimaConsultaRostroMs > CONSULTA_ROSTRO_MS) {
      ultimaConsultaRostroMs = millis();
      consultarRostro();
    }
    gestionarEscaneo();
  }

  char tecla = teclado.getKey();
  if (tecla) {
    procesarTecla(tecla);
    ultimaAccionMs = millis();
  }

  if (pantalla != 0 && millis() - ultimaAccionMs > TIMEOUT_SESION_MS) {
    resetSesion();
  }

  delay(50);
}

// ===== WIFI =====
void setupWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  mostrarEnLCD("Conectando WiFi", WIFI_SSID);

  int intentos = 0;
  while (WiFi.status() != WL_CONNECTED && intentos < 40) {
    delay(500);
    Serial.print(".");
    intentos++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi OK: " + WiFi.localIP().toString());
    mostrarEnLCD("WiFi OK", WiFi.localIP().toString());
  } else {
    Serial.println("\nWiFi FALLO - reiniciando");
    mostrarEnLCD("WiFi ERROR", "Reiniciando...");
    delay(2000);
    ESP.restart();
  }
  delay(1000);
}

void mantenerWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  static unsigned long ultimoIntento = 0;
  if (millis() - ultimoIntento < 5000) return;
  ultimoIntento = millis();
  Serial.println("WiFi caido. Reconectando...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// ===== LCD =====
void mostrarEnLCD(const String& l1, const String& l2) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(l1);
  if (l2.length() > 0) {
    lcd.setCursor(0, 1);
    lcd.print(l2);
  }
}

// ===== LED (ánodo común: HIGH apaga, LOW enciende) =====
void ledRojo()   { digitalWrite(PIN_LED_R, HIGH); digitalWrite(PIN_LED_G, LOW);  }
void ledVerde()  { digitalWrite(PIN_LED_R, LOW);  digitalWrite(PIN_LED_G, HIGH); }
void ledAmbar()  { digitalWrite(PIN_LED_R, HIGH); digitalWrite(PIN_LED_G, HIGH); }
void ledAzul()   { digitalWrite(PIN_LED_R, LOW);  digitalWrite(PIN_LED_G, LOW);  }
void ledApagado(){ digitalWrite(PIN_LED_R, LOW);  digitalWrite(PIN_LED_G, LOW);  }

// ===== ENCODER + MOTOR =====
void IRAM_ATTR encoderISR() {
  estado.pulsosEncoder++;
}

void girarMotor(int velocidad) {
  analogWrite(PIN_IN3, velocidad);
  digitalWrite(PIN_IN4, LOW);
  estado.motorGirando = true;
}

void detenerMotor() {
  analogWrite(PIN_IN3, 0);
  digitalWrite(PIN_IN4, LOW);
  estado.motorGirando = false;
}

// ===== RFID: UID en MAYÚSCULAS, sin separadores (ej. 04A32B1F) =====
String leerRFID() {
  if (!rfid.PICC_IsNewCardPresent()) return "";
  if (!rfid.PICC_ReadCardSerial())   return "";

  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  rfid.PICC_HaltA();
  return uid;
}

bool esTagObjetivo(const String& uid) {
  for (int i = 0; i < solicitud.nRfids; i++) {
    if (uid.equalsIgnoreCase(solicitud.rfids[i])) return true;
  }
  return false;
}

// ===== HTTP =====
String peticionHTTP(const String& endpoint, const String& metodo,
                    const String& cuerpo, const String& tipoContenido) {
  if (WiFi.status() != WL_CONNECTED) return "";

  HTTPClient http;
  http.begin(String(SERVER_URL) + endpoint);
  http.setTimeout(TIMEOUT_PETICION_MS);
  if (cuerpo.length() > 0) http.addHeader("Content-Type", tipoContenido);
  http.addHeader("X-Dispensador-Id", DISPENSADOR_ID);

  int codigo = (metodo == "GET") ? http.GET() : http.POST(cuerpo);

  String respuesta = "";
  if (codigo > 0) {
    respuesta = http.getString();
  } else {
    Serial.printf("HTTP %d: %s\n", codigo, http.errorToString(codigo).c_str());
  }
  http.end();
  return respuesta;
}

bool peticionSolicitud() {
  String json = peticionHTTP("/dispensador/solicitud", "GET", "", "");
  if (json.isEmpty()) return false;

  StaticJsonDocument<768> doc;
  if (deserializeJson(doc, json)) {
    Serial.println("JSON inválido del servidor");
    return false;
  }

  if (!(doc["activa"] | false)) {
    if (solicitud.activa && pantalla == 0) resetSesion();
    solicitud.activa = false;
    return false;
  }

  solicitud.activa      = true;
  solicitud.aulaId      = doc["aula_id"] | 0;
  solicitud.aulaNombre  = doc["aula_nombre"].as<String>();
  solicitud.persona     = doc["persona"].as<String>();
  solicitud.requierePin = doc["requiere_pin"] | false;

  // Lista de tags válidos; si el servidor viejo no la manda, usa "rfid".
  solicitud.nRfids = 0;
  JsonArray lista = doc["rfids"].as<JsonArray>();
  if (!lista.isNull()) {
    for (JsonVariant v : lista) {
      if (solicitud.nRfids >= MAX_TAGS) break;
      solicitud.rfids[solicitud.nRfids++] = v.as<String>();
    }
  }
  if (solicitud.nRfids == 0) {
    String unico = doc["rfid"].as<String>();
    if (unico.length() > 0) solicitud.rfids[solicitud.nRfids++] = unico;
  }

  Serial.printf("Solicitud: aula=%d (%s) tags=%d pin=%s\n",
                solicitud.aulaId, solicitud.aulaNombre.c_str(),
                solicitud.nRfids, solicitud.requierePin ? "SI" : "NO");
  return true;
}

bool validarPinEnServidor(const String& pin) {
  if (solicitud.persona.isEmpty()) {
    Serial.println("PIN: no hay persona en la solicitud");
    return false;
  }
  StaticJsonDocument<160> doc;
  doc["aula_id"] = solicitud.aulaId;
  doc["pin"]     = pin;
  doc["persona"] = solicitud.persona;
  String cuerpo;
  serializeJson(doc, cuerpo);

  String resp = peticionHTTP("/dispensador/pin", "POST", cuerpo, "application/json");
  return resp.indexOf("\"ok\":true") >= 0;
}

bool notificarEvento(const String& evento, const String& detalle) {
  StaticJsonDocument<256> doc;
  doc["evento"]  = evento;
  doc["aula_id"] = solicitud.aulaId;
  doc["persona"] = solicitud.persona;
  doc["rfid"]    = solicitud.nRfids > 0 ? solicitud.rfids[0] : "";
  doc["detalle"] = detalle;
  String cuerpo;
  serializeJson(doc, cuerpo);
  return peticionHTTP("/dispensador/confirmar", "POST", cuerpo,
                      "application/json").length() > 0;
}

// ===== MODO ESCANEO (alta de tags desde la web) =====
void gestionarEscaneo() {
  if (WiFi.status() != WL_CONNECTED) return;

  if (millis() - ultimaConsultaEscaneoMs > CONSULTA_ESCANEO_MS) {
    ultimaConsultaEscaneoMs = millis();
    String r = peticionHTTP("/dispensador/modo-escaneo", "GET", "", "");
    bool activo = r.indexOf("\"activo\":true") >= 0;
    if (activo && !modoEscaneo) {
      mostrarEnLCD("Escaneo de tag", "Apoye la tarjeta");
      ledAmbar();
    } else if (!activo && modoEscaneo) {
      dibujarInicio();
    }
    modoEscaneo = activo;
  }

  if (!modoEscaneo) return;

  String uid = leerRFID();
  if (uid.isEmpty()) return;

  Serial.println("UID escaneado: " + uid);
  StaticJsonDocument<96> doc;
  doc["uid"] = uid;
  String cuerpo;
  serializeJson(doc, cuerpo);
  String resp = peticionHTTP("/dispensador/escaneo", "POST", cuerpo, "application/json");

  if (resp.indexOf("\"ok\":true") >= 0) {
    mostrarEnLCD("Tag leido", uid);
    ledVerde();
  } else {
    mostrarEnLCD("Escaneo fallido", "Reintente");
    ledRojo();
  }
  modoEscaneo = false;
  delay(2000);
  dibujarInicio();
}

// ===== FLUJO POR ROSTRO =====
// El ESP32-CAM manda cada rostro autorizado al servidor; acá se consulta cuál
// fue el último y se saluda. Después la persona escribe el número de aula.
String recortarLCD(const String& texto) {
  return texto.length() <= LONGITUD_LCD ? texto : texto.substring(0, LONGITUD_LCD);
}

void avisar(const String& l1, const String& l2) {
  mostrarEnLCD(recortarLCD(l1), recortarLCD(l2));
  ledRojo();
  delay(AVISO_MS);
  if (personaReconocida.length() > 0) {
    bufferAula = "";
    pantalla = 1;
    dibujarAula();
  } else {
    resetSesion();
  }
  ultimaAccionMs = millis();
}

void saludar(const String& persona) {
  Serial.println("Rostro reconocido: " + persona);
  personaReconocida = persona;
  mostrarEnLCD("Bienvenido", recortarLCD(persona));
  ledVerde();
  delay(SALUDO_MS);
  bufferAula = "";
  bufferPin = "";
  estado.intentosPin = 0;
  pantalla = 1;
  dibujarAula();
  ultimaAccionMs = millis();
}

bool consultarRostro() {
  String json = peticionHTTP("/dispensador/reconocido", "GET", "", "");
  if (json.isEmpty()) return false;

  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, json)) return false;
  if (!(doc["reconocido"] | false)) return false;

  String persona = doc["persona"].as<String>();
  long seq = doc["seq"] | 0;
  if (persona.isEmpty()) return false;
  // Misma persona y mismo aviso: no repetir el saludo.
  if (seq == ultimoSeqSaludado && persona.equalsIgnoreCase(personaReconocida)) return false;

  ultimoSeqSaludado = seq;
  saludar(persona);
  return true;
}

bool solicitarLlave(const String& numero) {
  String json = peticionHTTP("/dispensador/llave/" + numero, "GET", "", "");
  if (json.isEmpty()) {
    avisar("Sin conexion", "Reintente");
    return false;
  }

  DynamicJsonDocument doc(1024);
  if (deserializeJson(doc, json)) {
    avisar("Error", "Respuesta invalida");
    return false;
  }

  // El servidor consulta la base: aula existente, activa y llave no prestada.
  if (!(doc["ok"] | false)) {
    avisar("No disponible", doc["error"] | "Aula invalida");
    return false;
  }
  if (!(doc["disponible"] | false)) {
    avisar("Llave no", "disponible");
    return false;
  }

  JsonArray lista = doc["uids"].as<JsonArray>();
  if (lista.isNull() || lista.size() == 0) {
    avisar("Llave sin tag", "Avisa al admin");
    return false;
  }

  solicitud = SolicitudLlave();
  solicitud.activa      = true;
  solicitud.aulaId      = doc["aula_id"] | numero.toInt();
  solicitud.aulaNombre  = doc["aula_nombre"].as<String>();
  solicitud.persona     = personaReconocida;
  solicitud.requierePin = false;
  for (JsonVariant v : lista) {
    if (solicitud.nRfids >= MAX_TAGS) break;
    solicitud.rfids[solicitud.nRfids++] = v.as<String>();
  }

  Serial.printf("Llave pedida: aula=%d (%s) tags=%d persona=%s\n",
                solicitud.aulaId, solicitud.aulaNombre.c_str(),
                solicitud.nRfids, solicitud.persona.c_str());
  pantalla = 3;
  dibujarGirando();
  buscarYLlevarLlave();
  return true;
}

// ===== PANTALLAS =====
void dibujarInicio() {
  mostrarEnLCD("Llavero ETEC", "Mire la camara");
  ledAzul();
}
void dibujarAula() { mostrarEnLCD("Nro de aula", "Aula:" + bufferAula + "  #"); }
void dibujarPin() {
  String oculto(bufferPin.length(), '*');
  mostrarEnLCD("Ingrese PIN:", oculto + " #");
}
void dibujarGirando() {
  mostrarEnLCD("Buscando llave", recortarLCD(solicitud.aulaNombre));
  ledAmbar();
}
void dibujarEntregado(const String& aula) {
  mostrarEnLCD("Retire su llave", aula);
  ledVerde();
}
void dibujarError(const String& mensaje) {
  mostrarEnLCD("ERROR", mensaje);
  ledRojo();
}

// ===== TECLADO =====
void procesarTecla(char tecla) {
  Serial.printf("Tecla '%c' (pantalla %d)\n", tecla, pantalla);

  switch (pantalla) {
    case 0:
      if (peticionSolicitud() && solicitud.activa) {
        bufferAula = ""; bufferPin = "";
        estado.intentosPin = 0;
        pantalla = solicitud.requierePin ? 2 : 1;
        (solicitud.requierePin ? dibujarPin() : dibujarAula());
      } else {
        mostrarEnLCD("Sin solicitudes", "Espere...");
        delay(1000);
        dibujarInicio();
      }
      break;

    case 1:
      if (tecla >= '0' && tecla <= '9') {
        if (bufferAula.length() < 3) {
          bufferAula += tecla;
          dibujarAula();
        }
      } else if (tecla == '#') {
        if (bufferAula.length() == 0) break;
        if (solicitud.activa && solicitud.nRfids > 0) {
          // Pedido hecho desde la web: ya está validado y el préstamo registrado.
          if (bufferAula.toInt() == solicitud.aulaId) {
            if (solicitud.requierePin) {
              pantalla = 2;
              bufferPin = "";
              dibujarPin();
            } else {
              pantalla = 3;
              dibujarGirando();
              buscarYLlevarLlave();
            }
          } else {
            dibujarError("Aula invalida");
            delay(1500);
            bufferAula = "";
            dibujarAula();
          }
        } else {
          // Flujo por rostro: se consulta disponibilidad y se dispensa.
          solicitarLlave(bufferAula);
        }
      } else if (tecla == '*') {
        bufferAula = "";
        dibujarAula();
      } else if (tecla == 'D') {
        resetSesion();
      }
      break;

    case 2: {
      if (tecla >= '0' && tecla <= '9') {
        if (bufferPin.length() < 6) {
          bufferPin += tecla;
          dibujarPin();
        }
      } else if (tecla == '#') {
        if (bufferPin.length() == 0) break;
        if (validarPinEnServidor(bufferPin)) {
          pantalla = 3;
          dibujarGirando();
          buscarYLlevarLlave();
        } else {
          estado.intentosPin++;
          dibujarError("PIN incorrecto " + String(MAX_INTENTOS_PIN - estado.intentosPin));
          delay(2000);
          bufferPin = "";
          if (estado.intentosPin >= MAX_INTENTOS_PIN) {
            notificarEvento("bloqueado", "max intentos PIN en teclado");
            resetSesion();
          } else {
            dibujarPin();
          }
        }
      } else if (tecla == '*') {
        bufferPin = "";
        dibujarPin();
      }
      break;
    }

    case 3:
      if (tecla == 'D') {
        detenerMotor();
        notificarEvento("error", "cancelado por el usuario");
        resetSesion();
      }
      break;

    case 4:
    case 5:
      resetSesion();
      break;
  }
}

// ===== RESET =====
void resetSesion() {
  detenerMotor();
  solicitud = SolicitudLlave();
  personaReconocida = "";
  estado.intentosPin = 0;
  bufferAula = "";
  bufferPin  = "";
  pantalla   = 0;
  dibujarInicio();
}

// ===== BÚSQUEDA DE LA LLAVE (gira + lee RFID) =====
bool buscarYLlevarLlave() {
  pantalla = 3;
  dibujarGirando();

  if (solicitud.nRfids == 0) {
    notificarEvento("error", "el aula no tiene tag RFID");
    dibujarError("Llave sin tag");
    pantalla = 5;
    return false;
  }

  long pulsosInicio     = estado.pulsosEncoder;
  unsigned long tInicio = millis();
  bool encontrada       = false;

  mostrarEnLCD("Girando...", "buscando tag");

  while (millis() - tInicio < TIMEOUT_GIRO_MS) {
    girarMotor(VEL_MOTOR);

    String uid = leerRFID();
    if (!uid.isEmpty()) {
      Serial.printf("RFID: %s\n", uid.c_str());
      if (esTagObjetivo(uid)) {
        detenerMotor();
        delay(150);
        digitalWrite(PIN_IN3, LOW);
        analogWrite(PIN_IN4, VEL_MOTOR);
        delay(120);
        analogWrite(PIN_IN4, 0);
        detenerMotor();
        encontrada = true;
        break;
      }
    }

    if (estado.pulsosEncoder - pulsosInicio > PULSOS_POR_VUELTA) break;
    delay(30);
  }

  detenerMotor();

  if (!encontrada) {
    Serial.println("Llave no encontrada");
    notificarEvento("error", "no encontrada tras una vuelta");
    dibujarError("Llave no hallada");
    pantalla = 5;
    return false;
  }

  Serial.println("Llave posicionada");
  notificarEvento("encontrada", "posicionada");

  pantalla = 4;
  dibujarEntregado(solicitud.aulaNombre);
  unsigned long tRetiro = millis();
  while (millis() - tRetiro < TIEMPO_RETIRO_MS) {
    if (teclado.getKey()) break;
    delay(100);
  }
  notificarEvento("entregada", "llave retirada");
  resetSesion();
  return true;
}