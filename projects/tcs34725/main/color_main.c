#include "telemetry.h"
#include <stdint.h>
#include <stdio.h>
#include "led_control.h"
#include "breathing_led.h"
#include "servo_control.h"
#include "cloud_network.h"
void dht_start(void);
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define COLOR_SDA GPIO_NUM_9
#define COLOR_SCL GPIO_NUM_8
#define COLOR_ADDRESS 0x29
#define ATIME_VALUE 0xd6 /* (256 - 214) * 2.4 = 100.8 ms */
static const char *TAG = "COLOR";
static i2c_master_dev_handle_t sensor;

static esp_err_t read_regs(uint8_t reg, uint8_t *data, size_t size)
{
    uint8_t cmd = 0x80 | (size > 1 ? 0x20 : 0) | reg;
    return i2c_master_transmit_receive(sensor, &cmd, 1, data, size, 100);
}

static esp_err_t write_reg(uint8_t reg, uint8_t value)
{
    uint8_t bytes[] = {0x80 | reg, value};
    return i2c_master_transmit(sensor, bytes, sizeof(bytes), 100);
}

static uint16_t le16(const uint8_t *p)
{
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

/* Slow, open-drain address-only diagnostic, independent of hardware I2C.
   Probe both orientations without writing any sensor register. */
static bool slow_ack(gpio_num_t sda, gpio_num_t scl)
{
    gpio_set_level(sda, 1);
    gpio_set_level(scl, 1);
    esp_rom_delay_us(100);
    if (!gpio_get_level(sda) || !gpio_get_level(scl)) return false;
    gpio_set_level(sda, 0);
    esp_rom_delay_us(50);
    gpio_set_level(scl, 0);
    for (int bit = 7; bit >= 0; --bit) {
        gpio_set_level(sda, ((COLOR_ADDRESS << 1) >> bit) & 1);
        esp_rom_delay_us(50);
        gpio_set_level(scl, 1);
        esp_rom_delay_us(50);
        gpio_set_level(scl, 0);
    }
    gpio_set_level(sda, 1);
    esp_rom_delay_us(50);
    gpio_set_level(scl, 1);
    esp_rom_delay_us(50);
    bool ack = gpio_get_level(scl) && !gpio_get_level(sda);
    gpio_set_level(scl, 0);
    gpio_set_level(sda, 0);
    esp_rom_delay_us(50);
    gpio_set_level(scl, 1);
    esp_rom_delay_us(50);
    gpio_set_level(sda, 1);
    esp_rom_delay_us(100);
    return ack;
}

static void diagnose_wires(void)
{
    const gpio_config_t config = {
        .pin_bit_mask = (1ULL << COLOR_SDA) | (1ULL << COLOR_SCL),
        .mode = GPIO_MODE_INPUT_OUTPUT_OD,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&config));
    gpio_set_level(COLOR_SDA, 1);
    gpio_set_level(COLOR_SCL, 1);
    vTaskDelay(pdMS_TO_TICKS(100));
    unsigned normal = 0, swapped = 0;
    for (int i = 0; i < 3; ++i) {
        normal += slow_ack(COLOR_SDA, COLOR_SCL);
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    for (int i = 0; i < 3; ++i) {
        swapped += slow_ack(COLOR_SCL, COLOR_SDA);
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    ESP_LOGI(TAG, "Slow probe 0x29: configured SDA=%d SCL=%d ACK=%u/3; reversed ACK=%u/3", COLOR_SDA, COLOR_SCL, normal, swapped);
    if (!normal && swapped) ESP_LOGW(TAG, "SDA/SCL appear reversed: power off and correct wiring");
    ESP_ERROR_CHECK(gpio_reset_pin(COLOR_SDA));
    ESP_ERROR_CHECK(gpio_reset_pin(COLOR_SCL));
}

void app_main(void)
{
    /* Keep the previously connected servo signal inactive. */
    ESP_ERROR_CHECK(gpio_reset_pin(GPIO_NUM_14));
    ESP_ERROR_CHECK(gpio_set_direction(GPIO_NUM_14, GPIO_MODE_OUTPUT));
    ESP_ERROR_CHECK(gpio_set_level(GPIO_NUM_14, 0));

    led_control_start();
    breathing_led_start();
    servo_control_start();
    diagnose_wires();
    dht_start();
    cloud_network_start();

    const i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = COLOR_SDA,
        .scl_io_num = COLOR_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_config, &bus));
    ESP_LOGI(TAG, "I2C SDA=GPIO9 (J1 pin15), SCL=GPIO8 (J1 pin12), 100kHz; servo PWM OFF");
    vTaskDelay(pdMS_TO_TICKS(200));
    unsigned found = 0;
    for (unsigned addr = 0x08; addr < 0x78; ++addr) {
        esp_err_t err = i2c_master_probe(bus, addr, 30);
        if (err == ESP_OK) {
            ++found;
            ESP_LOGI(TAG, "I2C scan found address 0x%02x", addr);
        } else if (err != ESP_ERR_NOT_FOUND) {
            ESP_LOGW(TAG, "Scan 0x%02x: %s (check SDA/SCL and pullups)", addr, esp_err_to_name(err));
            break;
        }
    }
    ESP_LOGI(TAG, "Scan complete: %u device(s)", found);
    while (i2c_master_probe(bus, COLOR_ADDRESS, 100) != ESP_OK) {
        telemetry_emit("SENSOR_JSON:{\"type\":\"color\",\"status\":\"error\",\"error\":\"not_found\"}\n");
        fflush(stdout);
        ESP_LOGW(TAG, "No device at 0x29. Check VIN/GND, SDA GPIO9, SCL GPIO8; idle SDA=%d SCL=%d",
                 gpio_get_level(COLOR_SDA), gpio_get_level(COLOR_SCL));
        vTaskDelay(pdMS_TO_TICKS(3000));
    }
    const i2c_device_config_t config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = COLOR_ADDRESS,
        .scl_speed_hz = 100000,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &config, &sensor));
    uint8_t id;
    ESP_ERROR_CHECK(read_regs(0x12, &id, 1));
    ESP_LOGI(TAG, "Sensor ID=0x%02x (%s)", id, id == 0x44 ? "TCS34725" : id == 0x4d ? "TCS34727" : "unknown");
    if (id != 0x44 && id != 0x4d) {
        ESP_LOGE(TAG, "Unexpected ID; stopping rather than configuring unknown hardware");
        return;
    }
    ESP_ERROR_CHECK(write_reg(0x00, 0x00));
    ESP_ERROR_CHECK(write_reg(0x01, ATIME_VALUE));
    ESP_ERROR_CHECK(write_reg(0x0f, 0x01)); /* 4x gain */
    ESP_ERROR_CHECK(write_reg(0x00, 0x01)); /* PON */
    vTaskDelay(pdMS_TO_TICKS(10)); /* > 2.4ms oscillator startup */
    ESP_ERROR_CHECK(write_reg(0x00, 0x03)); /* PON | AEN */
    vTaskDelay(pdMS_TO_TICKS(120));
    ESP_LOGI(TAG, "RGBC enabled: integration=100.8ms, gain=4x, report every 500ms");
    unsigned good = 0, failed = 0;
    for (;;) {
        uint8_t status = 0, bytes[8];
        esp_err_t err = read_regs(0x13, &status, 1);
        if (err == ESP_OK && (status & 0x01)) {
            err = read_regs(0x14, bytes, sizeof(bytes));
            if (err == ESP_OK) {
                ++good;
                uint16_t c = le16(bytes), r = le16(bytes + 2), g = le16(bytes + 4), b = le16(bytes + 6);
                telemetry_emit("SENSOR_JSON:{\"type\":\"color\",\"status\":\"ok\",\"id\":%u,\"c\":%u,\"r\":%u,\"g\":%u,\"b\":%u,\"saturated\":%s,\"ok\":%u,\"fail\":%u}\n",
                       id, c, r, g, b, (c >= 43008 || r >= 43008 || g >= 43008 || b >= 43008) ? "true" : "false", good, failed);
                fflush(stdout);
                /* Ratios are sensor channel ratios, not calibrated display RGB. */
                ESP_LOGI(TAG, "C=%u R=%u G=%u B=%u | R/C=%.3f G/C=%.3f B/C=%.3f | %s OK=%u FAIL=%u",
                         c, r, g, b, c ? (double)r/c : 0, c ? (double)g/c : 0, c ? (double)b/c : 0,
                         (c >= 43008 || r >= 43008 || g >= 43008 || b >= 43008) ? "SATURATED" : (c < 10 ? "DARK" : "VALID"), good, failed);
            }
        } else if (err == ESP_OK) {
            telemetry_emit("SENSOR_JSON:{\"type\":\"color\",\"status\":\"error\",\"error\":\"not_ready\"}\n");
            fflush(stdout);
            ESP_LOGW(TAG, "Waiting for valid conversion, status=0x%02x", status);
        }
        if (err != ESP_OK) {
            ++failed;
            telemetry_emit("SENSOR_JSON:{\"type\":\"color\",\"status\":\"error\",\"error\":\"%s\",\"ok\":%u,\"fail\":%u}\n", esp_err_to_name(err), good, failed);
            fflush(stdout);
            ESP_LOGW(TAG, "Read failed: %s OK=%u FAIL=%u", esp_err_to_name(err), good, failed);
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}
