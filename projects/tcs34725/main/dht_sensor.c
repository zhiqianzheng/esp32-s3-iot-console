#include "telemetry.h"
#include <stdint.h>
#include <stdio.h>
#include "driver/gpio.h"

#include "esp_err.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define DHT_PIN GPIO_NUM_4
#define EDGE_TIMEOUT_US 120

static const char *TAG = "DHT11";
static portMUX_TYPE timing_lock = portMUX_INITIALIZER_UNLOCKED;

/* Measure one pulse. The bound also detects an unplugged/stuck data line. */
static int pulse_us(int level)
{
    const int64_t start = esp_timer_get_time();
    while (gpio_get_level(DHT_PIN) == level) {
        if (esp_timer_get_time() - start >= EDGE_TIMEOUT_US) {
            return -1;
        }
    }
    return (int)(esp_timer_get_time() - start);
}

static esp_err_t read_dht11(uint8_t data[5], int *phase)
{
    for (int i = 0; i < 5; ++i) data[i] = 0;
    *phase = 0;
    gpio_set_level(DHT_PIN, 0);
    vTaskDelay(pdMS_TO_TICKS(20));

    esp_err_t result = ESP_ERR_TIMEOUT;
    /* Keep only the approximately 4 ms sensor response free of task switches.
       Open-drain level 1 releases DATA so the sensor can pull it low. */
    portENTER_CRITICAL(&timing_lock);
    gpio_set_level(DHT_PIN, 1);
    if (pulse_us(1) < 0) goto done;  /* sensor begins response */
    *phase = 1;
    if (pulse_us(0) < 0) goto done;  /* response low */
    *phase = 2;
    if (pulse_us(1) < 0) goto done;  /* response high */
    for (int bit = 0; bit < 40; ++bit) {
        *phase = 3 + bit * 2;
        if (pulse_us(0) < 0) goto done;
        *phase = 4 + bit * 2;
        int high = pulse_us(1);
        if (high < 0) goto done;
        data[bit / 8] = (uint8_t)((data[bit / 8] << 1) | (high > 50));
    }
    result = ESP_OK;
done:
    portEXIT_CRITICAL(&timing_lock);
    gpio_set_level(DHT_PIN, 1);
    if (result != ESP_OK) return result;
    if ((uint8_t)(data[0] + data[1] + data[2] + data[3]) != data[4]) {
        return ESP_ERR_INVALID_CRC;
    }
    /* DHT11 integer and decimal bytes; bit 7 of temperature decimal is sign. */
    if (data[0] > 100 || data[1] > 9 || data[2] > 80 || (data[3] & 0x7f) > 9) {
        return ESP_ERR_INVALID_RESPONSE;
    }
    return ESP_OK;
}

static void dht_task(void *arg)
{
    (void)arg;
    const gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << DHT_PIN,
        .mode = GPIO_MODE_INPUT_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));
    gpio_set_level(DHT_PIN, 1);
    ESP_LOGI(TAG, "DATA=GPIO%d, VCC=3V3, GND=GND; reading every 2.5 seconds", DHT_PIN);
    vTaskDelay(pdMS_TO_TICKS(2000));

    unsigned good = 0, failed = 0;
    for (;;) {
        uint8_t bytes[5];
        int phase;
        esp_err_t err = read_dht11(bytes, &phase);
        if (err == ESP_OK) {
            ++good;
            const float humidity = bytes[0] + bytes[1] / 10.0f;
            float temperature = bytes[2] + (bytes[3] & 0x7f) / 10.0f;
            if (bytes[3] & 0x80) temperature = -temperature;
            telemetry_emit("SENSOR_JSON:{\"type\":\"dht\",\"status\":\"ok\",\"temperature\":%.1f,\"humidity\":%.1f,\"ok\":%u,\"fail\":%u}\n", temperature, humidity, good, failed);
            fflush(stdout);
            ESP_LOGI(TAG, "Temperature: %.1f C | Humidity: %.1f %%RH | OK=%u FAIL=%u",
                     temperature, humidity, good, failed);
        } else {
            ++failed;
            telemetry_emit("SENSOR_JSON:{\"type\":\"dht\",\"status\":\"error\",\"error\":\"%s\",\"ok\":%u,\"fail\":%u}\n", esp_err_to_name(err), good, failed);
            fflush(stdout);
            ESP_LOGW(TAG, "%s phase=%d idle=%d raw=%02x %02x %02x %02x %02x OK=%u FAIL=%u",
                     esp_err_to_name(err), phase, gpio_get_level(DHT_PIN),
                     bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], good, failed);
        }
        vTaskDelay(pdMS_TO_TICKS(2500));
    }
}

void dht_start(void)
{
    if (xTaskCreate(dht_task, "dht11", 6144, NULL, 1, NULL) != pdPASS) {
        ESP_ERROR_CHECK(ESP_ERR_NO_MEM);
    }
}
