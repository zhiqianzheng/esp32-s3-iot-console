#include "telemetry.h"
#include <math.h>
#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"
#include "driver/rmt_tx.h"
#include "driver/rmt_encoder.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "breathing_led.h"

#define MAX_COLORS 8
static const char *mode_names[] = {"single", "multi", "rainbow", "off"};
typedef struct {
    int mode, brightness, count, request;
    float frequency;
    uint8_t colors[MAX_COLORS][3];
    unsigned revision;
} settings_t;
static settings_t settings = {
    .mode = 1, .brightness = 35, .frequency = 0.25f, .count = 6,
    .colors = {{255,30,60},{255,140,0},{255,220,0},{0,230,130},{30,120,255},{180,40,255}},
    .revision = 1,
};
static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
static uint8_t current_pixel[3];
static float current_phase;
static rmt_channel_handle_t channel;
static rmt_encoder_handle_t encoder;

static void report_error(const char *error, int request)
{
    telemetry_emit("SENSOR_JSON:{\"type\":\"rgb\",\"status\":\"error\",\"error\":\"%s\",\"request\":%d}\n", error, request);
    fflush(stdout);
}

void breathing_led_report(void)
{
    settings_t s;
    uint8_t pixel[3];
    float phase;
    portENTER_CRITICAL(&lock);
    s = settings; memcpy(pixel, current_pixel, sizeof(pixel)); phase = current_phase;
    portEXIT_CRITICAL(&lock);
    char out[512];
    int used = snprintf(out, sizeof(out), "SENSOR_JSON:{\"type\":\"rgb\",\"status\":\"ok\",\"mode\":\"%s\",\"frequency\":%.3f,\"brightness\":%d,\"request\":%d,\"revision\":%u,\"colors\":[",
                        mode_names[s.mode], s.frequency, s.brightness, s.request, s.revision);
    for (int i = 0; i < s.count; ++i) {
        used += snprintf(out + used, sizeof(out) - used, "%s\"#%02X%02X%02X\"", i ? "," : "", s.colors[i][0], s.colors[i][1], s.colors[i][2]);
    }
    snprintf(out + used, sizeof(out) - used, "],\"pixel\":[%u,%u,%u],\"phase\":%.3f}", pixel[0], pixel[1], pixel[2], phase);
    telemetry_emit("%s\n", out); fflush(stdout);
}

bool breathing_led_command(const char *line)
{
    if (strcmp(line, "RGB STATUS") == 0) { breathing_led_report(); return true; }
    if (strncmp(line, "RGB SET ", 8) != 0) return false;
    cJSON *root = cJSON_Parse(line + 8);
    if (!cJSON_IsObject(root)) { cJSON_Delete(root); report_error("invalid_json", 0); return true; }
    cJSON *mode = cJSON_GetObjectItemCaseSensitive(root, "mode");
    cJSON *freq = cJSON_GetObjectItemCaseSensitive(root, "frequency");
    cJSON *bright = cJSON_GetObjectItemCaseSensitive(root, "brightness");
    cJSON *colors = cJSON_GetObjectItemCaseSensitive(root, "colors");
    cJSON *request = cJSON_GetObjectItemCaseSensitive(root, "request");
    settings_t next = {0};
    int rid = cJSON_IsNumber(request) && request->valuedouble >= 0 && request->valuedouble <= 2147483647.0 ? request->valueint : 0;
    next.request = rid;
    next.mode = -1;
    if (cJSON_IsString(mode)) for (int i = 0; i < 4; ++i) if (strcmp(mode->valuestring, mode_names[i]) == 0) next.mode = i;
    if (next.mode < 0 || !cJSON_IsNumber(freq) || !isfinite(freq->valuedouble) || freq->valuedouble < 0.05 || freq->valuedouble > 2.0 ||
        !cJSON_IsNumber(bright) || bright->valuedouble < 0 || bright->valuedouble > 100 || floor(bright->valuedouble) != bright->valuedouble ||
        !cJSON_IsArray(colors) || (next.count = cJSON_GetArraySize(colors)) < 1 || next.count > MAX_COLORS) {
        cJSON_Delete(root); report_error("invalid_settings", rid); return true;
    }
    next.frequency = freq->valuedouble; next.brightness = bright->valueint;
    for (int i = 0; i < next.count; ++i) {
        cJSON *color = cJSON_GetArrayItem(colors, i);
        if (!cJSON_IsString(color) || strlen(color->valuestring) != 7 || color->valuestring[0] != '#') {
            cJSON_Delete(root); report_error("invalid_color", rid); return true;
        }
        for (int j=1; j<7; ++j) {
            if (!isxdigit((unsigned char)color->valuestring[j])) { cJSON_Delete(root); report_error("invalid_color", rid); return true; }
        }
        char *end;
        unsigned long value = strtoul(color->valuestring + 1, &end, 16);
        if (*end != '\0' || end != color->valuestring + 7) {
            cJSON_Delete(root); report_error("invalid_color", rid); return true;
        }
        next.colors[i][0] = value >> 16; next.colors[i][1] = value >> 8; next.colors[i][2] = value;
    }
    cJSON_Delete(root);
    portENTER_CRITICAL(&lock); next.revision = settings.revision + 1; settings = next; portEXIT_CRITICAL(&lock);
    breathing_led_report();
    return true;
}

static void hue_rgb(float hue, float color[3])
{
    float p = hue * 6, f = p - floorf(p);
    int k = (int)p % 6;
    float values[6][3] = {{1,f,0},{1-f,1,0},{0,1,f},{0,1-f,1},{f,0,1},{1,0,1-f}};
    for (int i = 0; i < 3; ++i) color[i] = values[k][i] * 255;
}

static void breathing_task(void *arg)
{
    (void)arg;
    const rmt_transmit_config_t tx = {.loop_count = 0, .flags.eot_level = 0};
    TickType_t wake = xTaskGetTickCount();
    int64_t start = esp_timer_get_time();
    unsigned revision = 0;
    for (;;) {
        settings_t s;
        portENTER_CRITICAL(&lock); s = settings; portEXIT_CRITICAL(&lock);
        int64_t now = esp_timer_get_time();
        if (revision != s.revision) { start = now; revision = s.revision; }
        double cycles = (now-start) / 1000000.0 * s.frequency;
        float phase = cycles - floor(cycles);
        float wave = (1.0f - cosf(6.28318530718f * phase)) * 0.5f;
        float level = s.mode == 3 ? 0 : wave * wave * s.brightness / 100.0f;
        float color[3];
        if (s.mode == 2) {
            double hue = cycles / 3.0;
            hue_rgb(hue - floor(hue), color);
        } else if (s.mode == 1) {
            double pos = fmod(cycles, s.count);
            int first = (int)pos, second = (first + 1) % s.count;
            float t = pos - first;
            t = t*t*(3-2*t);
            for (int i = 0; i < 3; ++i) color[i] = s.colors[first][i]*(1-t)+s.colors[second][i]*t;
        } else {
            for (int i = 0; i < 3; ++i) color[i] = s.colors[0][i];
        }
        uint8_t rgb[3];
        for (int i = 0; i < 3; ++i) rgb[i] = (uint8_t)(color[i]*level + 0.5f);
        uint8_t grb[3] = {rgb[1], rgb[0], rgb[2]};
        ESP_ERROR_CHECK(rmt_transmit(channel, encoder, grb, sizeof(grb), &tx));
        ESP_ERROR_CHECK(rmt_tx_wait_all_done(channel, 100));
        portENTER_CRITICAL(&lock); memcpy(current_pixel, rgb, sizeof(rgb)); current_phase = phase; portEXIT_CRITICAL(&lock);
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(20));
    }
}

void breathing_led_start(void)
{
    const rmt_tx_channel_config_t tx = {.gpio_num=48, .clk_src=RMT_CLK_SRC_DEFAULT, .resolution_hz=10000000, .mem_block_symbols=64, .trans_queue_depth=1};
    ESP_ERROR_CHECK(rmt_new_tx_channel(&tx, &channel));
    const rmt_bytes_encoder_config_t config = {
        .bit0={.level0=1,.duration0=3,.level1=0,.duration1=9},
        .bit1={.level0=1,.duration0=9,.level1=0,.duration1=3}, .flags.msb_first=1,
    };
    ESP_ERROR_CHECK(rmt_new_bytes_encoder(&config, &encoder));
    ESP_ERROR_CHECK(rmt_enable(channel));
    if (xTaskCreate(breathing_task,"breathing",4096,NULL,2,NULL)!=pdPASS) ESP_ERROR_CHECK(ESP_ERR_NO_MEM);
    ESP_LOGI("BREATH", "GPIO48 WS2812 configurable multicolor breathing started");
}
