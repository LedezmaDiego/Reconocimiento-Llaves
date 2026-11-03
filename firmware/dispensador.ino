#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <Keypad.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>


// ===== RED (SERVER_URL = IP de la PC del backend: hostname -I) =====
const char* WIFI_SSID      = "PEINE-3";
const char* WIFI_PASSWORD  = "etecPeine3";
const char* SERVER_URL     = "http://10.56.16.134:8000";
const char* DISPENSADOR_ID = "D01";

// true  = hay que mirar la cámara (rostro reconocido) antes de pedir el aula
// false = se puede tipear el aula directo en el teclado
const bool EXIGIR_ROSTRO = true;


#define RFID_SS   5
#define RFID_RST  27

#define MOTOR_IN3 25
#define MOTOR_IN4 26

#define LED_VERDE 12
#define LED_ROJO  15


LiquidCrystal_I2C lcd(0x27, 16, 2);
MFRC522 rfid(RFID_SS, RFID_RST);


const byte FILAS = 4;
const byte COLUMNAS = 4;
char teclas[FILAS][COLUMNAS] = {
 {'1','2','3','A'},
 {'4','5','6','B'},
 {'7','8','9','C'},
 {'*','0','#','D'}
};
byte pinesFilas[FILAS]       = {4, 13, 14, 16};
byte pinesColumnas[COLUMNAS] = {17, 32, 33, 2};
Keypad teclado = Keypad(makeKeymap(teclas), pinesFilas, pinesColumnas, FILAS, COLUMNAS);


// ===== LLAVE PEDIDA (viene del servidor, no hay tabla fija) =====
const int MAX_UIDS = 8;
String uidsObjetivo[MAX_UIDS];
int nUidsObjetivo = 0;
String aulaPedida = "";        // nombre o número que se muestra en la LCD
String personaActual = "";     // quien pidió la llave (rostro o web)
bool origenWeb = false;        // true = pedido hecho desde la web
int  aulaIdWeb = 0;
bool requierePin = false;
int  intentosPin = 0;
const int MAX_INTENTOS_PIN = 3;

// Llaves que salieron de la rueda (por UID) para el LED rojo
const int MAX_FALTANTES = 30;
String faltantes[MAX_FALTANTES];
int nFaltantes = 0;


enum EstadoSistema {
 REPOSO,
 ESPERANDO_AULA,
 ESPERANDO_PIN,
 BUSCANDO_LLAVE,
 BUSCANDO_VACIO,        // vuelta completa sin encontrar: avanza hasta un hueco sin llavero
 LLAVE_NO_ENCONTRADA,
 LLAVE_ENCONTRADA,
 DEVOLUCION_DETECTADA,
 LIMPIANDO_POSICION
};
EstadoSistema estado = REPOSO;


String bufferAula = "";
String bufferPin  = "";
bool motorPulsando = false;
unsigned long inicioPulso = 0;
const unsigned long DURACION_PASO_MS  = 500;   // AJUSTAR porque no usamos el encoder
const unsigned long TIEMPO_GRACIA_MS  = 5000;  // motor quieto para agarrar la llave
const unsigned long TIEMPO_MENSAJE_MS = 3000;
const unsigned long TIMEOUT_SESION_MS = 60000;
const unsigned long SALUDO_MS         = 2500;
const unsigned long AVISO_MS          = 2500;
unsigned long inicioGracia = 0;
unsigned long inicioSesionMs = 0;
bool lcdSucio = true;

const int LONGITUD_LCD = 16;


// ===== Consultas periódicas al servidor =====
const unsigned long CONSULTA_SOLICITUD_MS = 3000;
const unsigned long CONSULTA_ROSTRO_MS    = 1500;
const unsigned long CONSULTA_ESCANEO_MS   = 1000;
unsigned long ultimaPeticionMs         = 0;
unsigned long ultimaConsultaRostroMs   = 0;
unsigned long ultimaConsultaEscaneoMs  = 0;
bool modoEscaneo = false;
long ultimoSeqSaludado = -1;


// UID del último llavero leído (copia propia, porque rfid.uid se pisa al hacer Halt)
byte uidActual[4] = {0, 0, 0, 0};


// ---- Referencia para detectar vuelta completa ----
byte uidReferencia[4] = {0, 0, 0, 0};
bool tieneReferencia = false;
bool referenciaAbandonada = false;   // la referencia ya salió del lector al menos una vez
int  pulsosBusqueda = 0;
const int MAX_PULSOS_BUSQUEDA = 80;  // seguridad: si no hay ningún llavero, no gira para siempre
const int MAX_PULSOS_VACIO    = 40;  // seguridad: si no hay ningún hueco, se detiene igual


// ===== PROTOTIPOS =====
String recortarLCD(const String& texto);
void mostrarLCD(String l1, String l2 = "");
void iniciarPulsoMotor();
void detenerMotor();
bool pulsoTerminado();
void actualizarLed();
void marcarFaltante(const String& uid);
void quitarFaltante(const String& uid);
bool hayTarjetaPresente();
bool uidCoincide(byte* a, byte* b);
String uidAString(byte* u);
bool esLlaveObjetivo();
void reiniciarBusqueda();
void iniciarBusqueda();
void volverAInicio();
void cancelarPorUsuario();
void setupWiFi();
void mantenerWiFi();
String peticionHTTP(const String& endpoint, const String& cuerpo, int timeoutMs);
void notificarEvento(const String& evento, const String& detalle = "", const String& uid = "");
bool peticionSolicitud();
void iniciarSolicitudWeb();
bool validarPinEnServidor(const String& pin);
void consultarRostro();
void saludar(const String& persona);
void avisar(const String& l1, const String& l2);
void solicitarLlave(const String& numero);
void procesarTeclaAula(char tecla);
void consultarRed();
void procesarEscaneo();
void dibujarReposo();


// ============================================================
//  LCD
// ============================================================
String recortarLCD(const String& texto) {
 return texto.length() <= LONGITUD_LCD ? texto : texto.substring(0, LONGITUD_LCD);
}

void mostrarLCD(String l1, String l2) {
 lcd.clear();
 lcd.setCursor(0, 0);
 lcd.print(recortarLCD(l1));
 lcd.setCursor(0, 1);
 lcd.print(recortarLCD(l2));
}

void dibujarReposo() {
 if (modoEscaneo)         mostrarLCD("Escaneo de tag", "Apoye el llavero");
 else if (EXIGIR_ROSTRO)  mostrarLCD("Llavero ETEC", "Mire la camara");
 else                     mostrarLCD("Ingrese aula:", "");
}


// ============================================================
//  MOTOR (por pulsos, sin encoder)
// ============================================================
void iniciarPulsoMotor() {
 digitalWrite(MOTOR_IN3, HIGH);
 digitalWrite(MOTOR_IN4, LOW);
 motorPulsando = true;
 inicioPulso = millis();
}

void detenerMotor() {
 digitalWrite(MOTOR_IN3, LOW);
 digitalWrite(MOTOR_IN4, LOW);
 motorPulsando = false;
}

bool pulsoTerminado() {
 return motorPulsando && (millis() - inicioPulso >= DURACION_PASO_MS);
}


// ============================================================
//  LED
// ============================================================
void actualizarLed() {
 digitalWrite(LED_VERDE, HIGH);
 digitalWrite(LED_ROJO, nFaltantes > 0 ? HIGH : LOW);
}

void marcarFaltante(const String& uid) {
 for (int i = 0; i < nFaltantes; i++) if (faltantes[i] == uid) return;
 if (nFaltantes < MAX_FALTANTES) faltantes[nFaltantes++] = uid;
 actualizarLed();
}

void quitarFaltante(const String& uid) {
 for (int i = 0; i < nFaltantes; i++) {
   if (faltantes[i] == uid) {
     faltantes[i] = faltantes[nFaltantes - 1];
     nFaltantes--;
     break;
   }
 }
 actualizarLed();
}


// ============================================================
//  RFID
// ============================================================
// Lee un llavero y guarda su UID en uidActual. Lo "duerme" (Halt) para que
// al volver a pasar por el lector se detecte como tarjeta nueva.
bool hayTarjetaPresente() {
 if (!rfid.PICC_IsNewCardPresent()) return false;
 if (!rfid.PICC_ReadCardSerial())   return false;
 for (int i = 0; i < 4; i++) uidActual[i] = rfid.uid.uidByte[i];
 rfid.PICC_HaltA();
 rfid.PCD_StopCrypto1();
 return true;
}

bool uidCoincide(byte* uidLeido, byte* uidObjetivo) {
 for (int i = 0; i < 4; i++) {
   if (uidLeido[i] != uidObjetivo[i]) return false;
 }
 return true;
}

// UID en MAYÚSCULAS sin separadores (ej. CAA8EA81), igual que el servidor
String uidAString(byte* u) {
 String s = "";
 for (int i = 0; i < 4; i++) {
   if (u[i] < 0x10) s += "0";
   s += String(u[i], HEX);
 }
 s.toUpperCase();
 return s;
}

// ¿El llavero leído es uno de los que devolvió el servidor?
bool esLlaveObjetivo() {
 String uid = uidAString(uidActual);
 for (int i = 0; i < nUidsObjetivo; i++) {
   if (uid.equalsIgnoreCase(uidsObjetivo[i])) return true;
 }
 return false;
}


// ============================================================
//  BÚSQUEDA / SESIÓN
// ============================================================
void reiniciarBusqueda() {
 tieneReferencia = false;
 referenciaAbandonada = false;
 pulsosBusqueda = 0;
}

void iniciarBusqueda() {
 reiniciarBusqueda();
 estado = BUSCANDO_LLAVE;
 lcdSucio = true;
 iniciarPulsoMotor();
}

void volverAInicio() {
 detenerMotor();
 reiniciarBusqueda();
 bufferAula = "";
 bufferPin = "";
 origenWeb = false;
 personaActual = "";
 aulaIdWeb = 0;
 requierePin = false;
 intentosPin = 0;
 estado = REPOSO;
 lcdSucio = true;
 ultimaPeticionMs = millis();
 ultimaConsultaRostroMs = millis();
}

// Tecla D: frena el motor y cancela lo que se esté haciendo
void cancelarPorUsuario() {
 detenerMotor();
 notificarEvento("error", "cancelado por el usuario");
 mostrarLCD("Cancelado", "");
 delay(1000);
 volverAInicio();
}


// ============================================================
//  WIFI Y HTTP
// ============================================================
void setupWiFi() {
 WiFi.mode(WIFI_STA);
 WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
 mostrarLCD("Conectando WiFi", WIFI_SSID);

 int intentos = 0;
 while (WiFi.status() != WL_CONNECTED && intentos < 40) {
   delay(500);
   Serial.print(".");
   intentos++;
 }

 if (WiFi.status() == WL_CONNECTED) {
   Serial.println("\nWiFi OK: " + WiFi.localIP().toString());
   mostrarLCD("WiFi OK", WiFi.localIP().toString());
 } else {
   Serial.println("\nWiFi FALLO");
   mostrarLCD("Sin WiFi", "Reintentando...");
 }
 delay(1500);
}

void mantenerWiFi() {
 if (WiFi.status() == WL_CONNECTED) return;
 static unsigned long ultimoIntento = 0;
 if (millis() - ultimoIntento < 10000) return;
 ultimoIntento = millis();
 WiFi.disconnect();
 WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// Petición HTTP simple: GET si no hay cuerpo, POST si lo hay. Devuelve el cuerpo, o "" si falla.
String peticionHTTP(const String& endpoint, const String& cuerpo, int timeoutMs) {
 if (WiFi.status() != WL_CONNECTED) return "";

 HTTPClient http;
 http.begin(String(SERVER_URL) + endpoint);
 http.setConnectTimeout(timeoutMs);
 http.setTimeout(timeoutMs);
 http.addHeader("X-Dispensador-Id", DISPENSADOR_ID);

 int codigo;
 if (cuerpo.length() > 0) {
   http.addHeader("Content-Type", "application/json");
   codigo = http.POST(cuerpo);
 } else {
   codigo = http.GET();
 }

 String respuesta = "";
 if (codigo > 0) {
   respuesta = http.getString();
 } else {
   Serial.printf("HTTP %d: %s\n", codigo, http.errorToString(codigo).c_str());
 }
 http.end();
 return respuesta;
}

// Avisa un evento al servidor. Pedidos de la web -> /dispensador/confirmar,
// pedidos por rostro/teclado -> /dispensador/llave/evento. No frena nada si falla.
void notificarEvento(const String& evento, const String& detalle, const String& uid) {
 StaticJsonDocument<320> doc;
 String cuerpo;
 String ruta;

 if (origenWeb) {
   doc["evento"]  = evento;
   doc["aula_id"] = aulaIdWeb;
   doc["persona"] = personaActual;
   doc["rfid"]    = nUidsObjetivo > 0 ? uidsObjetivo[0] : "";
   doc["detalle"] = detalle;
   ruta = "/dispensador/confirmar";
 } else {
   doc["numero_aula"] = aulaPedida;
   doc["evento"]      = evento;
   doc["persona"]     = personaActual;
   doc["uid"]         = uid;
   doc["detalle"]     = detalle;
   ruta = "/dispensador/llave/evento";
 }
 serializeJson(doc, cuerpo);
 peticionHTTP(ruta, cuerpo, 1500);
}


// ============================================================
//  PEDIDO DESDE LA WEB (solicitud activa en el servidor)
// ============================================================
bool peticionSolicitud() {
 String json = peticionHTTP("/dispensador/solicitud", "", 2000);
 if (json.isEmpty()) return false;

 StaticJsonDocument<768> doc;
 if (deserializeJson(doc, json)) return false;
 if (!(doc["activa"] | false)) return false;

 aulaIdWeb     = doc["aula_id"] | 0;
 aulaPedida    = doc["aula_nombre"].as<String>();
 personaActual = doc["persona"].as<String>();
 requierePin   = doc["requiere_pin"] | false;

 nUidsObjetivo = 0;
 JsonArray lista = doc["rfids"].as<JsonArray>();
 if (!lista.isNull()) {
   for (JsonVariant v : lista) {
     if (nUidsObjetivo >= MAX_UIDS) break;
     uidsObjetivo[nUidsObjetivo++] = v.as<String>();
   }
 }
 if (nUidsObjetivo == 0) {
   String unico = doc["rfid"].as<String>();
   if (unico.length() > 0) uidsObjetivo[nUidsObjetivo++] = unico;
 }

 Serial.printf("Solicitud web: aula=%d (%s) tags=%d pin=%s\n",
               aulaIdWeb, aulaPedida.c_str(), nUidsObjetivo, requierePin ? "SI" : "NO");
 return true;
}

void iniciarSolicitudWeb() {
 origenWeb = true;
 intentosPin = 0;
 bufferPin = "";

 if (nUidsObjetivo == 0) {
   notificarEvento("error", "el aula no tiene tag RFID");
   mostrarLCD("Llave sin tag", aulaPedida);
   delay(2000);
   volverAInicio();
   return;
 }

 if (requierePin) {
   inicioSesionMs = millis();
   estado = ESPERANDO_PIN;
   lcdSucio = true;
 } else {
   iniciarBusqueda();
 }
}

bool validarPinEnServidor(const String& pin) {
 if (personaActual.isEmpty()) return false;
 StaticJsonDocument<160> doc;
 doc["aula_id"] = aulaIdWeb;
 doc["pin"]     = pin;
 doc["persona"] = personaActual;
 String cuerpo;
 serializeJson(doc, cuerpo);

 String resp = peticionHTTP("/dispensador/pin", cuerpo, 4000);
 return resp.indexOf("\"ok\":true") >= 0;
}


// ============================================================
//  FLUJO POR ROSTRO + PEDIDO POR TECLADO
// ============================================================
// El ESP32-CAM manda cada rostro autorizado al servidor; acá se consulta cuál
// fue el último y se saluda. Después la persona escribe el número de aula.
void consultarRostro() {
 String json = peticionHTTP("/dispensador/reconocido", "", 1500);
 if (json.isEmpty()) return;

 StaticJsonDocument<256> doc;
 if (deserializeJson(doc, json)) return;
 if (!(doc["reconocido"] | false)) return;

 String persona = doc["persona"].as<String>();
 long seq = doc["seq"] | 0;
 if (persona.isEmpty()) return;
 if (seq == ultimoSeqSaludado) return;     // ya se saludó por este aviso

 ultimoSeqSaludado = seq;
 saludar(persona);
}

void saludar(const String& persona) {
 Serial.println("Rostro reconocido: " + persona);
 personaActual = persona;
 origenWeb = false;
 mostrarLCD("Bienvenido", persona);
 delay(SALUDO_MS);
 bufferAula = "";
 estado = ESPERANDO_AULA;
 inicioSesionMs = millis();
 lcdSucio = true;
}

// Muestra un mensaje y vuelve a pedir el aula (si hay persona) o al reposo.
void avisar(const String& l1, const String& l2) {
 mostrarLCD(l1, l2);
 delay(AVISO_MS);
 bufferAula = "";
 if (personaActual.length() > 0) {
   estado = ESPERANDO_AULA;
   inicioSesionMs = millis();
   lcdSucio = true;
 } else {
   volverAInicio();
 }
}

// Le pregunta al servidor qué UID(s) tiene el aula y si la llave está disponible.
void solicitarLlave(const String& numero) {
 mostrarLCD("Consultando...", "Aula " + numero);

 String json = peticionHTTP("/dispensador/llave/" + numero, "", 4000);
 if (json.isEmpty()) {
   avisar("Sin conexion", "con el servidor");
   return;
 }

 StaticJsonDocument<768> doc;
 if (deserializeJson(doc, json)) {
   avisar("Error servidor", "Respuesta invalida");
   return;
 }

 if (!(doc["ok"] | false)) {
   String error = doc["error"].as<String>();
   if (error.indexOf("no tiene") >= 0) avisar("Aula sin llavero", "Aula " + numero);
   else avisar("No disponible", error.length() > 0 ? error : String("Aula invalida"));
   return;
 }

 // Si el servidor manda "disponible" en false, la llave ya está prestada.
 if (!(doc["disponible"] | true)) {
   avisar("Llave no", "disponible");
   return;
 }

 nUidsObjetivo = 0;
 JsonArray lista = doc["uids"].as<JsonArray>();
 if (!lista.isNull()) {
   for (JsonVariant v : lista) {
     if (nUidsObjetivo >= MAX_UIDS) break;
     uidsObjetivo[nUidsObjetivo++] = v.as<String>();
   }
 }
 if (nUidsObjetivo == 0) {
   avisar("Llave sin tag", "Avisa al admin");
   return;
 }

 String nombre = doc["aula_nombre"].as<String>();
 aulaPedida = (nombre.length() > 0 && nombre != "null") ? nombre : numero;
 origenWeb = false;
 aulaIdWeb = 0;
 bufferAula = "";

 Serial.printf("Llave pedida: aula=%s tags=%d persona=%s\n",
               aulaPedida.c_str(), nUidsObjetivo, personaActual.c_str());
 iniciarBusqueda();
}

void procesarTeclaAula(char tecla) {
 if (tecla >= '0' && tecla <= '9') {
   if (bufferAula.length() < 3) bufferAula += tecla;
   lcdSucio = true;
   if (bufferAula.length() == 3) {
     String numero = bufferAula;
     solicitarLlave(numero);
   }
 } else if (tecla == '#') {
   if (bufferAula.length() > 0) {
     String numero = bufferAula;
     solicitarLlave(numero);
   }
 } else if (tecla == '*') {
   bufferAula = "";
   lcdSucio = true;
 } else if (tecla == 'D') {
   volverAInicio();
 }
}


// ============================================================
//  MODO ESCANEO (alta de llaveros desde la web)
// ============================================================
void consultarRed() {
 if (WiFi.status() != WL_CONNECTED) return;
 unsigned long ahora = millis();

 // 1) ¿El admin pidió escanear un llavero nuevo?
 if (ahora - ultimaConsultaEscaneoMs > CONSULTA_ESCANEO_MS) {
   ultimaConsultaEscaneoMs = ahora;
   String r = peticionHTTP("/dispensador/modo-escaneo", "", 1500);
   bool activo = r.indexOf("\"activo\":true") >= 0;
   if (activo != modoEscaneo) {
     modoEscaneo = activo;
     lcdSucio = true;
   }
 }
 if (modoEscaneo) return;

 // 2) ¿Hay un pedido hecho desde la web? Tiene prioridad sobre el rostro.
 if (ahora - ultimaPeticionMs > CONSULTA_SOLICITUD_MS) {
   ultimaPeticionMs = ahora;
   if (peticionSolicitud()) {
     iniciarSolicitudWeb();
     return;
   }
 }

 // 3) ¿La cámara reconoció a alguien?
 if (ahora - ultimaConsultaRostroMs > CONSULTA_ROSTRO_MS) {
   ultimaConsultaRostroMs = ahora;
   consultarRostro();
 }
}

void procesarEscaneo() {
 if (!hayTarjetaPresente()) return;

 String uid = uidAString(uidActual);
 Serial.println("UID escaneado: " + uid);

 StaticJsonDocument<96> doc;
 doc["uid"] = uid;
 String cuerpo;
 serializeJson(doc, cuerpo);
 String resp = peticionHTTP("/dispensador/escaneo", cuerpo, 3000);

 if (resp.indexOf("\"ok\":true") >= 0) mostrarLCD("Tag leido", uid);
 else                                  mostrarLCD("Escaneo fallido", "Reintente");

 modoEscaneo = false;
 delay(2000);
 lcdSucio = true;
}


// ============================================================
//  SETUP / LOOP
// ============================================================
void setup() {
 Serial.begin(115200);
 SPI.begin();
 rfid.PCD_Init();

 pinMode(MOTOR_IN3, OUTPUT);
 pinMode(MOTOR_IN4, OUTPUT);
 pinMode(LED_VERDE, OUTPUT);
 pinMode(LED_ROJO, OUTPUT);
 detenerMotor();

 lcd.init();
 lcd.backlight();

 actualizarLed();
 setupWiFi();
 volverAInicio();
}

void loop() {

 mantenerWiFi();

 // La tecla D frena el motor en cualquier momento mientras se mueve
 if (estado == BUSCANDO_LLAVE || estado == BUSCANDO_VACIO || estado == LIMPIANDO_POSICION) {
   char t = teclado.getKey();
   if (t == 'D') {
     cancelarPorUsuario();
     return;
   }
 }


 switch (estado) {


   case REPOSO: {
     if (lcdSucio) {
       dibujarReposo();
       lcdSucio = false;
     }

     char tecla = teclado.getKey();

     // Sin rostro obligatorio, se puede tipear el aula directo
     if (!EXIGIR_ROSTRO && !modoEscaneo && tecla >= '0' && tecla <= '9') {
       bufferAula = "";
       estado = ESPERANDO_AULA;
       inicioSesionMs = millis();
       lcdSucio = true;
       procesarTeclaAula(tecla);
       return;
     }

     consultarRed();
     if (estado != REPOSO) break;

     if (modoEscaneo) {
       procesarEscaneo();
       break;
     }

     // Un llavero apoyado en reposo es una devolución
     if (hayTarjetaPresente()) {
       estado = DEVOLUCION_DETECTADA;
       lcdSucio = true;
     }
     break;
   }




   case ESPERANDO_AULA: {
     if (lcdSucio) {
       mostrarLCD("Nro de aula:", "Aula:" + bufferAula + "  #");
       lcdSucio = false;
     }

     if (millis() - inicioSesionMs > TIMEOUT_SESION_MS) {
       volverAInicio();
       break;
     }

     char tecla = teclado.getKey();
     if (tecla) {
       inicioSesionMs = millis();
       procesarTeclaAula(tecla);
     }
     break;
   }




   case ESPERANDO_PIN: {
     if (lcdSucio) {
       String oculto = "";
       for (unsigned int i = 0; i < bufferPin.length(); i++) oculto += "*";
       mostrarLCD("Ingrese PIN:", oculto + " #");
       lcdSucio = false;
     }

     if (millis() - inicioSesionMs > TIMEOUT_SESION_MS) {
       notificarEvento("error", "tiempo agotado en PIN");
       volverAInicio();
       break;
     }

     char tecla = teclado.getKey();
     if (!tecla) break;
     inicioSesionMs = millis();

     if (tecla >= '0' && tecla <= '9') {
       if (bufferPin.length() < 6) { bufferPin += tecla; lcdSucio = true; }
     } else if (tecla == '*') {
       bufferPin = "";
       lcdSucio = true;
     } else if (tecla == 'D') {
       cancelarPorUsuario();
     } else if (tecla == '#' && bufferPin.length() > 0) {
       if (validarPinEnServidor(bufferPin)) {
         bufferPin = "";
         iniciarBusqueda();
       } else {
         intentosPin++;
         mostrarLCD("PIN incorrecto", "Quedan " + String(MAX_INTENTOS_PIN - intentosPin));
         delay(2000);
         bufferPin = "";
         if (intentosPin >= MAX_INTENTOS_PIN) {
           notificarEvento("bloqueado", "max intentos PIN en teclado");
           volverAInicio();
         } else {
           lcdSucio = true;
         }
       }
     }
     break;
   }




   case BUSCANDO_LLAVE: {
     if (lcdSucio) {
       mostrarLCD("Buscando llave...", "D = cancelar");
       lcdSucio = false;
     }


     // Mientras el motor está en pulso no se lee nada (no bloquea: el teclado sigue activo)
     if (motorPulsando) {
       if (pulsoTerminado()) detenerMotor();
       break;
     }


     // Motor quieto: se lee lo que quedó frente al lector
     pulsosBusqueda++;


     if (hayTarjetaPresente()) {


       // 1) ¿Es la llave buscada?
       if (esLlaveObjetivo()) {
         detenerMotor();
         reiniciarBusqueda();
         String uid = uidAString(uidActual);
         marcarFaltante(uid);
         notificarEvento("encontrada", "posicionada", uid);
         inicioGracia = millis();
         estado = LLAVE_ENCONTRADA;
         lcdSucio = true;
         break;
       }


       // 2) El primer llavero que pasa queda como referencia
       if (!tieneReferencia) {
         for (int i = 0; i < 4; i++) uidReferencia[i] = uidActual[i];
         tieneReferencia = true;
         referenciaAbandonada = false;
       }
       // 3) Volvió a pasar la referencia: dio la vuelta completa
       else if (uidCoincide(uidActual, uidReferencia)) {
         if (referenciaAbandonada) {
           estado = BUSCANDO_VACIO;   // sigue hasta el próximo hueco sin llavero
           pulsosBusqueda = 0;
           lcdSucio = true;
           iniciarPulsoMotor();
           break;
         }
         // si no se abandonó, sigue siendo la misma lectura de antes: no cuenta
       }
       // 4) Otro llavero distinto: la referencia ya se fue del lector
       else {
         referenciaAbandonada = true;
       }


     } else {
       // Hueco sin llavero: si ya hay referencia, significa que se alejó de ella
       if (tieneReferencia) referenciaAbandonada = true;
     }


     // Seguridad: demasiados pasos sin completar vuelta (rueda vacía o llavero atascado)
     if (pulsosBusqueda >= MAX_PULSOS_BUSQUEDA) {
       detenerMotor();
       reiniciarBusqueda();
       notificarEvento("error", "no encontrada (limite de pasos)");
       estado = LLAVE_NO_ENCONTRADA;
       lcdSucio = true;
       inicioGracia = millis();
       break;
     }


     iniciarPulsoMotor();
     break;
   }




   // Vuelta completa sin encontrar la llave: avanza hasta el siguiente espacio vacío y se detiene
   case BUSCANDO_VACIO: {
     if (lcdSucio) {
       mostrarLCD("No esta en la", "rueda, ajustando");
       lcdSucio = false;
     }


     if (motorPulsando) {
       if (pulsoTerminado()) detenerMotor();
       break;
     }


     pulsosBusqueda++;


     if (!hayTarjetaPresente() || pulsosBusqueda >= MAX_PULSOS_VACIO) {
       detenerMotor();
       reiniciarBusqueda();
       notificarEvento("error", "no encontrada tras una vuelta");
       estado = LLAVE_NO_ENCONTRADA;
       lcdSucio = true;
       inicioGracia = millis();
     } else {
       iniciarPulsoMotor();
     }
     break;
   }




   case LLAVE_NO_ENCONTRADA: {
     if (lcdSucio) {
       mostrarLCD("Llave no hallada", "Aula " + aulaPedida);
       digitalWrite(LED_ROJO, HIGH);
       lcdSucio = false;
     }


     if (millis() - inicioGracia >= TIEMPO_MENSAJE_MS) {
       actualizarLed();
       volverAInicio();
     }
     break;
   }




   case LLAVE_ENCONTRADA: {
     if (lcdSucio) {
       mostrarLCD("Listo! Aula " + aulaPedida, "Llave encontrada");
       lcdSucio = false;
     }


     if (millis() - inicioGracia >= TIEMPO_GRACIA_MS) {
       notificarEvento("entregada", "llave retirada");
       volverAInicio();
     }
     break;
   }




   case DEVOLUCION_DETECTADA: {
     String uid = uidAString(uidActual);
     quitarFaltante(uid);

     // Le pregunta al servidor de qué aula es y lo deja registrado
     String resp = peticionHTTP("/dispensador/llave-por-uid/" + uid, "", 2000);
     if (resp.length() > 0) {
       StaticJsonDocument<192> doc;
       if (!deserializeJson(doc, resp) && (doc["ok"] | false)) {
         aulaPedida = doc["aula"].as<String>();
         mostrarLCD("Llave devuelta", "Aula " + aulaPedida);
         notificarEvento("devuelta", "", uid);
         delay(1500);
       }
     }

     estado = LIMPIANDO_POSICION;
     iniciarPulsoMotor();
     lcdSucio = true;
     break;
   }  




   case LIMPIANDO_POSICION: {
     if (motorPulsando) {
       if (pulsoTerminado()) detenerMotor();
       break;
     }


     if (hayTarjetaPresente()) {
       iniciarPulsoMotor();
     } else {
       volverAInicio();
     }
     break;
   }
 }
}