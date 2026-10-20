/*
 * ============================================================
 *  DISPENSADOR DE LLAVES - ESP32 (para Arduino IDE)
 * ============================================================
 *  Componentes y conexiones (según tabla del proyecto):
 *
 *  MOTOR (L298N puente B, con jumpers puestos en ENA/ENB)
 *    IN3  -> GPIO25      IN4 -> GPIO26
 *    OUT3 -> Motor +     OUT4 -> Motor -
 *    La velocidad se controla por PWM sobre IN3 (el jumper de
 *    ENB queda puesto: la habilitación es permanente).
 *
 *  ENCODER del motor (1 señal)
 *    Señal -> GPIO34 (entrada only, OK para interrupción)
 *
 *  RFID RC522 (¡ALIMENTAR A 3.3V, con 5V se quema!)
 *    SS/SDA -> GPIO5     SCK  -> GPIO18
 *    MOSI   -> GPIO23    MISO -> GPIO19
 *    RST    -> GPIO27    IRQ  -> desconectado
 *
 *  LCD I2C
 *    SCL -> GPIO22       SDA -> GPIO21
 *
 *  TECLADO 4x4 (filas / columnas)
 *    R1..R4 -> GPIO4, 13, 14, 16
 *    C1..C4 -> GPIO17, 32, 33, 2
 *
 *  LED HW-480 (con resistencia 220 en serie en cada color)
 *    R -> GPIO12         G -> GPIO15
 *
 *  NOTA: los pines coinciden 1:1 con la tabla; NO cambiar sin
 *  revisar conflictos. Pines de entrada only del ESP32: 34-39.
 * ============================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <LiquidCrystal_I2C.h>
#include <Keypad.h>
#include <SPI.h>
#include <MFRC522.h>
#include <ArduinoJson.h>

// ============================================================
//  CONFIGURACIÓN DE RED
// ============================================================
const char* WIFI_SSID      = "PEINE-3";
const char* WIFI_PASSWORD  = "etecPeine3";
const char* SERVER_URL     = "http://10.56.13.16:8000";   // PC que corre FastAPI
const char* DISPENSADOR_ID = "D01";                       // identificador de este equipo

// ============================================================
//  PINES
// ============================================================
// Motor (puente B del L298N; ENB con jumper = siempre habilitado)
#define PIN_IN3      25
#define PIN_IN4      26
#define VEL_MOTOR   200      // PWM 0-255 para IN3

// Encoder (1 canal)
#define PIN_ENCODER  34      // GPIO34: entrada only, válida para interrupción

// RC522
#define PIN_RFID_SS   5
#define PIN_RFID_RST 27

// LCD I2C
#define LCD_ADDR    0x27
#define LCD_COLS    16
#define LCD_ROWS     2

// Teclado 4x4
const byte FILAS[4]    = { 4, 13, 14, 16};
const byte COLUMNAS[4] = {17, 32, 33,  2};

// LED HW-480
#define PIN_LED_R    12
#define PIN_LED_G    15

// ============================================================
//  MAPA DEL TECLADO
// ============================================================
char teclas[4][4] = {
  {'1','2','3','A'},
  {'4','5','6','B'},
  {'7','8','9','C'},
  {'*','0','#','D'}
};

// ============================================================
//  PARÁMETROS DEL SISTEMA
// ============================================================
const unsigned long TIMEOUT_PETICION_MS = 15000;   // espera respuesta del servidor
const unsigned long TIMEOUT_SESION_MS   = 60000;   // inactividad -> pantalla inicio
const unsigned long TIMEOUT_GIRO_MS     = 10000;   // tope de girando buscando llave
const unsigned long TIEMPO_RETIRO_MS    = 8000;    // ventana para retirar la llave
const int           MAX_INTENTOS_PIN    = 3;       // intentos de PIN en el teclado
const int           PULSOS_POR_VUELTA   = 20;      // CALIBRAR: pulsos del encoder por vuelta
const unsigned long REINTENTO_GIRO_MS   = 60000;   // tras no encontrar, espera antes de reintentar

// ============================================================
//  ESTRUCTURAS
// ============================================================
struct SolicitudLlave {
  bool     activa        = false;
  int      aulaId        = 0;
  String   aulaNombre    = "";
  String   persona       = "";
  String   rfidObjetivo  = "";
  bool     requierePin   = false;
};

struct EstadoDispensador {
  bool   motorGirando    = false;
  long   pulsosEncoder   = 0;
  int    intentosPin     = 0;
  String ultimaAccion    = "";
};

// ============================================================
//  OBJETOS GLOBALES
// ============================================================
LiquidCrystal_I2C lcd(LCD_ADDR, LCD_COLS, LCD_ROWS);
Keypad teclado = Keypad(makeKeymap(teclas), FILAS, COLUMNAS, 4, 4);
MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);

SolicitudLlave   solicitud;
EstadoDispensador estado;

unsigned long ultimaPeticionMs = 0;   // última consulta de /solicitud
unsigned long ultimaAccionMs   = 0;   // última tecla (para el timeout de sesión)

String  bufferAula, bufferPin;
int     pantalla = 0;   // 0 inicio, 1 aula, 2 PIN, 3 girando, 4 entregado, 5 error

// ============================================================
//  PROTOTIPOS
// ============================================================
void setupWiFi();
void mantenerWiFi();
void mostrarEnLCD(const String& l1, const String& l2 = "");

void ledRojo();
void ledVerde();
void ledAzul();
void ledAmbar();
void ledApagado();

void IRAM_ATTR encoderISR();
void girarMotor(int velocidad);
void detenerMotor();

String leerRFID();
bool   buscarYLlevarLlave();

bool   peticionSolicitud();
bool   validarPinEnServidor(const String& pin);
bool   notificarEvento(const String& evento, const String& detalle = "");
String peticionHTTP(const String& endpoint, const String& metodo,
                    const String& cuerpo, const String& tipoContenido);

void dibujarInicio();
void dibujarAula();
void dibujarPin();
void dibujarGirando();
void dibujarEntregado(const String& aula);
void dibujarError(const String& mensaje);
void procesarTecla(char tecla);
void resetSesion();

// ============================================================
//  SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n\n=== DISPENSADOR DE LLAVES ===");

  // Motor
  pinMode(PIN_IN3, OUTPUT);
  pinMode(PIN_IN4, OUTPUT);
  detenerMotor();

  // Encoder (GPIO34 no tiene pull-up interna: se usa resistencia externa)
  pinMode(PIN_ENCODER, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_ENCODER), encoderISR, RISING);

  // LED
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  ledApagado();

  // LCD
  lcd.init();
  lcd.backlight();
  mostrarEnLCD("Iniciando...", "Dispensador ETEC");

  // RFID
  SPI.begin();
  rfid.PCD_Init();
  Serial.println("RC522 listo");

  // WiFi
  setupWiFi();

  pantalla = 0;
  dibujarInicio();
  Serial.println("Sistema listo.");
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
  mantenerWiFi();

  // Consultar si el servidor tiene una llave para entregar (cada 3s).
  if (WiFi.status() == WL_CONNECTED && millis() - ultimaPeticionMs > 3000) {
    ultimaPeticionMs = millis();
    peticionSolicitud();
  }

  // Teclado
  char tecla = teclado.getKey();
  if (tecla) {
    procesarTecla(tecla);
    ultimaAccionMs = millis();
  }

  // Timeout de sesión: vuelve al inicio si no hay actividad.
  if (pantalla != 0 && millis() - ultimaAccionMs > TIMEOUT_SESION_MS) {
    resetSesion();
  }

  delay(50);
}

// ============================================================
//  WIFI
// ============================================================
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

// ============================================================
//  LCD
// ============================================================
void mostrarEnLCD(const String& l1, const String& l2) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(l1);
  if (l2.length() > 0) {
    lcd.setCursor(0, 1);
    lcd.print(l2);
  }
}

// ============================================================
//  LED HW-480 (ánodo común: HIGH apaga, LOW enciende el color)
//  Con resistencias de 220 en serie por color.
// ============================================================
void ledRojo()  { digitalWrite(PIN_LED_R, HIGH); digitalWrite(PIN_LED_G, LOW);  }
void ledVerde() { digitalWrite(PIN_LED_R, LOW);  digitalWrite(PIN_LED_G, HIGH); }
void ledAmbar() { digitalWrite(PIN_LED_R, HIGH); digitalWrite(PIN_LED_G, HIGH); }
void ledAzul()  { digitalWrite(PIN_LED_R, LOW);  digitalWrite(PIN_LED_G, LOW);  }
void ledApagado(){ digitalWrite(PIN_LED_R, LOW); digitalWrite(PIN_LED_G, LOW);  }

// ============================================================
//  ENCODER + MOTOR
// ============================================================
void IRAM_ATTR encoderISR() {
  estado.pulsosEncoder++;
}

// Giro en un sentido: IN3 con PWM (velocidad), IN4 en LOW.
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

// ============================================================
//  RFID
// ============================================================
String leerRFID() {
  if (!rfid.PICC_IsNewCardPresent()) return "";
  if (!rfid.PICC_ReadCardSerial())   return "";

  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  rfid.PICC_HaltA();
  return uid;
}

// ============================================================
//  HTTP
// ============================================================
String peticionHTTP(const String& endpoint, const String& metodo,
                    const String& cuerpo, const String& tipoContenido) {
  if (WiFi.status() != WL_CONNECTED) return "";

  HTTPClient http;
  String url = String(SERVER_URL) + endpoint;
  http.begin(url);
  http.setTimeout(TIMEOUT_PETICION_MS);
  if (cuerpo.length() > 0) {
    http.addHeader("Content-Type", tipoContenido);
  }
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

// ¿El servidor tiene una llave para entregar?
bool peticionSolicitud() {
  String json = peticionHTTP("/dispensador/solicitud", "GET", "", "");
  if (json.isEmpty()) return false;

  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, json)) {
    Serial.println("JSON inválido del servidor");
    return false;
  }

  if (!(doc["activa"] | false)) {
    if (solicitud.activa && pantalla == 0) resetSesion();
    solicitud.activa = false;
    return false;
  }

  solicitud.activa       = true;
  solicitud.aulaId       = doc["aula_id"]       | 0;
  solicitud.aulaNombre   = doc["aula_nombre"].as<String>();
  solicitud.persona      = doc["persona"].as<String>();
  solicitud.rfidObjetivo = doc["rfid"].as<String>();
  solicitud.requierePin  = doc["requiere_pin"]  | false;

  Serial.printf("Solicitud: aula=%d (%s) rfid=%s pin=%s\n",
                solicitud.aulaId, solicitud.aulaNombre.c_str(),
                solicitud.rfidObjetivo.c_str(),
                solicitud.requierePin ? "SI" : "NO");
  return true;
}

// Valida el PIN en el servidor (el hash y el bloqueo viven allá).
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

// Informa un evento al servidor.
bool notificarEvento(const String& evento, const String& detalle) {
  StaticJsonDocument<256> doc;
  doc["evento"]    = evento;
  doc["aula_id"]   = solicitud.aulaId;
  doc["persona"]   = solicitud.persona;
  doc["rfid"]      = solicitud.rfidObjetivo;
  doc["detalle"]   = detalle;
  String cuerpo;
  serializeJson(doc, cuerpo);
  return peticionHTTP("/dispensador/confirmar", "POST", cuerpo,
                      "application/json").length() > 0;
}

// ============================================================
//  PANTALLAS
// ============================================================
void dibujarInicio() {
  mostrarEnLCD("Dispensador", "Listo");
  ledAzul();
}

void dibujarAula() {
  mostrarEnLCD("Ingrese nro aula", "Aula:" + bufferAula + "  #");
}

void dibujarPin() {
  String oculto(bufferPin.length(), '*');
  mostrarEnLCD("Ingrese PIN:", oculto + " #");
}

void dibujarGirando() {
  mostrarEnLCD("Buscando llave", "Aula " + String(solicitud.aulaId));
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

// ============================================================
//  TECLADO
// ============================================================
void procesarTecla(char tecla) {
  Serial.printf("Tecla '%c' (pantalla %d)\n", tecla, pantalla);

  switch (pantalla) {
    case 0:  // inicio: fuerza consulta y pasa a la pantalla que corresponda
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

    case 1:  // número de aula
      if (tecla >= '0' && tecla <= '9') {
        if (bufferAula.length() < 3) {
          bufferAula += tecla;
          dibujarAula();
        }
      } else if (tecla == '#') {
        if (bufferAula.length() == 0) break;
        if (bufferAula.toInt() == solicitud.aulaId) {
          pantalla = 2;
          bufferPin = "";
          dibujarPin();
        } else {
          dibujarError("Aula invalida");
          delay(1500);
          bufferAula = "";
          dibujarAula();
        }
      } else if (tecla == '*') {
        bufferAula = "";
        dibujarAula();
      }
      break;

    case 2: {  // PIN
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

    case 3:  // girando: 'D' cancela
      if (tecla == 'D') {
        detenerMotor();
        notificarEvento("error", "cancelado por el usuario");
        resetSesion();
      }
      break;

    case 4:
    case 5:  // tras entregar o error, cualquier tecla vuelve al inicio
      resetSesion();
      break;
  }
}

// ============================================================
//  RESET
// ============================================================
void resetSesion() {
  detenerMotor();
  solicitud      = SolicitudLlave();
  estado.intentosPin = 0;
  bufferAula     = "";
  bufferPin      = "";
  pantalla       = 0;
  dibujarInicio();
}

// ============================================================
//  BÚSQUEDA DE LA LLAVE (gira + lee RFID)
// ============================================================
bool buscarYLlevarLlave() {
  pantalla = 3;
  dibujarGirando();

  if (solicitud.rfidObjetivo.isEmpty()) {
    notificarEvento("error", "el aula no tiene tag RFID");
    dibujarError("Llave sin tag");
    pantalla = 5;
    return false;
  }

  long pulsosInicio    = estado.pulsosEncoder;
  unsigned long tInicio = millis();
  bool encontrada       = false;

  mostrarEnLCD("Girando...", "buscando tag");

  while (millis() - tInicio < TIMEOUT_GIRO_MS) {
    girarMotor(VEL_MOTOR);

    String uid = leerRFID();
    if (!uid.isEmpty()) {
      Serial.printf("RFID: %s (busco %s)\n", uid.c_str(), solicitud.rfidObjetivo.c_str());
      if (uid.equalsIgnoreCase(solicitud.rfidObjetivo)) {
        // Frenar y retroceder un poco para centrar la llave.
        // El giro inverso se hace con IN4 en PWM (IN3 en LOW).
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

    // Vuelta completa sin encontrarla: avisa y sale.
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

  // Espera a que retiren la llave.
  pantalla = 4;
  dibujarEntregado("Aula " + String(solicitud.aulaId));
  unsigned long tRetiro = millis();
  while (millis() - tRetiro < TIEMPO_RETIRO_MS) {
    if (teclado.getKey()) break;           // cualquier tecla confirma el retiro
    delay(100);
  }
  notificarEvento("entregada", "llave retirada");
  resetSesion();
  return true;
}