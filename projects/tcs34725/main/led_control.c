#include "telemetry.h"
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_control.h"
#include "breathing_led.h"
#include "servo_control.h"
#include "cloud_network.h"
#include "freertos/semphr.h"

#define LED_PIN GPIO_NUM_10
static bool led_on;
static SemaphoreHandle_t command_mutex;

static void report_state(void)
{
    telemetry_emit("SENSOR_JSON:{\"type\":\"led\",\"status\":\"ok\",\"on\":%s,\"gpio\":10}\n", led_on ? "true" : "false");
    fflush(stdout);
}

bool device_execute_command(const char *line, bool from_cloud)
{
    if(!command_mutex || xSemaphoreTake(command_mutex,pdMS_TO_TICKS(2000))!=pdTRUE)return false;
    bool handled=true;
    if(!from_cloud&&cloud_network_command(line)){}
    else if(strcmp(line,"LED ON")==0||strcmp(line,"LED OFF")==0){
        led_on=strcmp(line,"LED ON")==0;
        ESP_ERROR_CHECK(gpio_set_level(LED_PIN,led_on?1:0));report_state();
    }else if(servo_control_command_from(line,from_cloud)){}
    else if(breathing_led_command(line)){}
    else if(strcmp(line,"LED STATUS")==0)report_state();
    else handled=false;
    xSemaphoreGive(command_mutex);return handled;
}

static void command_task(void *arg)
{
    (void)arg;
    char line[512];
    size_t used = 0;
    bool overflow = false;
    unsigned idle_ticks = 0;
    for (;;) {
        uint8_t bytes[32];
        int n = uart_read_bytes(UART_NUM_0, bytes, sizeof(bytes), pdMS_TO_TICKS(100));
        for (int i = 0; i < n; ++i) {
            if (bytes[i] == '\r') continue;
            if (bytes[i] == '\n') {
                line[used] = '\0';
                if (!overflow) device_execute_command(line,false);
                used = 0;
                overflow = false;
            } else if (used < sizeof(line) - 1 && !overflow) {
                line[used++] = bytes[i];
            } else {
                overflow = true;
            }
        }
        if (++idle_ticks >= 20) {
            report_state();
            breathing_led_report();
            idle_ticks = 0;
        }
    }
}

void led_control_start(void)
{
    command_mutex=xSemaphoreCreateMutex();
    if(!command_mutex)ESP_ERROR_CHECK(ESP_ERR_NO_MEM);
    const gpio_config_t config = {
        .pin_bit_mask = 1ULL << LED_PIN,
        .mode = GPIO_MODE_INPUT_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&config));
    ESP_ERROR_CHECK(gpio_set_level(LED_PIN, 0));
    led_on = false;
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 1024, 0, 0, NULL, 0));
    report_state();
    if (xTaskCreate(command_task, "led_control", 8192, NULL, 2, NULL) != pdPASS) {
        ESP_ERROR_CHECK(ESP_ERR_NO_MEM);
    }
}
