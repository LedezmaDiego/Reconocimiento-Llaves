        #include "esp_camera.h"
        #include <WiFi.h>
        #include <HTTPClient.h>

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


        const char* ssid = "Peine-2";
        const char* password = "etecPeine2";
        const char* serverUrl = "http://192.168.1.6:8000/reconocimiento";
        //const char* ssid = "PEINE-2";
        //const char* password = "etecPeine2";
        //const char* serverUrl = "http://10.56.2.32:8000/reconocimiento";

        void setupCamera() {
          camera_config_t config;
          config.ledc_channel = LEDC_CHANNEL_0;
          config.ledc_timer = LEDC_TIMER_0;
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
          config.pin_sscb_sda = SIOD_GPIO_NUM;
          config.pin_sscb_scl = SIOC_GPIO_NUM;
          config.pin_pwdn = PWDN_GPIO_NUM;
          config.pin_reset = RESET_GPIO_NUM;
          config.xclk_freq_hz = 20000000;
          config.pixel_format = PIXFORMAT_JPEG;
          config.frame_size = FRAMESIZE_VGA;
          config.jpeg_quality = 12;
         config.fb_count = 2;
         config.grab_mode = CAMERA_GRAB_LATEST;

          esp_err_t err = esp_camera_init(&config);
          if (err != ESP_OK) {
            Serial.printf("Error iniciando camara: 0x%x\n", err);
            ESP.restart();
          }
        }

        void setupWiFi() {
          WiFi.begin(ssid, password);
          Serial.println("Intentando conectar a la red WiFi");
          while (WiFi.status() != WL_CONNECTED) {
            delay(500);
            Serial.print(".");
          }
          Serial.println("WiFi conectado");
          Serial.println(WiFi.localIP());
        }

        void enviarFoto() {
          camera_fb_t *fb = esp_camera_fb_get();
          if (!fb) {
            Serial.println("Error al capturar foto");
            return;
          }

          HTTPClient http;
          http.begin(serverUrl);

          String boundary = "ESP32CAMBOUNDARY";
          String head = "--" + boundary + "\r\n";
          head += "Content-Disposition: form-data; name=\"file\"; filename=\"foto.jpg\"\r\n";
          head += "Content-Type: image/jpeg\r\n\r\n";
          String tail = "\r\n--" + boundary + "--\r\n";

          int totalLen = head.length() + fb->len + tail.length();

          uint8_t *body = (uint8_t *)malloc(totalLen);
          if (!body) {
            Serial.println("No hay memoria suficiente para armar el cuerpo");
            esp_camera_fb_return(fb);
            return;
          }

          int pos = 0;
          memcpy(body + pos, head.c_str(), head.length());
          pos += head.length();
          memcpy(body + pos, fb->buf, fb->len);
          pos += fb->len;
          memcpy(body + pos, tail.c_str(), tail.length());
          pos += tail.length();

          http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
          int httpCode = http.POST(body, pos);

          Serial.printf("POST enviado, codigo: %d\n", httpCode);
          if (httpCode > 0) {
            String respuesta = http.getString();
            Serial.println(respuesta);
          }

          http.end();
          free(body);
          esp_camera_fb_return(fb);
        }

        void setup() {
          Serial.begin(115200);
          setupWiFi();
          setupCamera();
        }

        void loop() {
          enviarFoto();
          delay(1000);
        }
