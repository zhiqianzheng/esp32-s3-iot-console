#include <inttypes.h>
#include "driver/ledc.h"
#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "servo.h"

#define SERVO_ENABLED 0
#define SERVO_GPIO 14
#define SERVO_PERIOD_US 20000U
#define SERVO_RESOLUTION_BITS 14U
#define SERVO_MIDDLE_US 1500U
#define SERVO_LOW_US 833U
#define SERVO_HIGH_US 2167U
#define SERVO_STEP_US 10U

static const char *TAG = "SERVO";

static void servo_pulse(uint32_t pulse_us)
{
    /* duty / 2^14 * 20000 us = desired high pulse width, rounded. */
    uint32_t duty = (pulse_us * (1U << SERVO_RESOLUTION_BITS) + SERVO_PERIOD_US / 2)
                    / SERVO_PERIOD_US;
    /* Only this task writes channel 0; no fade service is needed. */
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, duty));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0));
}

static void servo_task(void *arg)
{
    (void)arg;
    int current = SERVO_MIDDLE_US;
    ESP_LOGI(TAG, "GPIO14: 50 Hz PWM, pulse=1500 us (nominal 90 deg); hold 2 seconds");
    vTaskDelay(pdMS_TO_TICKS(2000));
    for (;;) {
        const int targets[] = {SERVO_LOW_US, SERVO_HIGH_US};
        for (unsigned i = 0; i < sizeof(targets) / sizeof(targets[0]); ++i) {
            const int target = targets[i];
            ESP_LOGI(TAG, "PWM command: %d us -> %d us (nominal %s deg)",
                     current, target, i == 0 ? "30" : "150");
            while (current != target) {
                int delta = target - current;
                if (delta > (int)SERVO_STEP_US) delta = SERVO_STEP_US;
                if (delta < -(int)SERVO_STEP_US) delta = -(int)SERVO_STEP_US;
                current += delta;
                servo_pulse(current);
                vTaskDelay(pdMS_TO_TICKS(20));
            }
            vTaskDelay(pdMS_TO_TICKS(2000));
        }
    }
}

void servo_start(void)
{
    if (!SERVO_ENABLED) {
        ESP_ERROR_CHECK(gpio_reset_pin(SERVO_GPIO));
        ESP_ERROR_CHECK(gpio_set_direction(SERVO_GPIO, GPIO_MODE_OUTPUT));
        ESP_ERROR_CHECK(gpio_set_level(SERVO_GPIO, 0));
        ESP_LOGI(TAG, "STOPPED: GPIO14 LOW, PWM disabled; automatic sweep disabled");
        return;
    }
    const ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_14_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = 50,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));
    const uint32_t initial_duty = (SERVO_MIDDLE_US * (1U << SERVO_RESOLUTION_BITS)
                                   + SERVO_PERIOD_US / 2) / SERVO_PERIOD_US;
    const ledc_channel_config_t channel = {
        .gpio_num = SERVO_GPIO,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = LEDC_TIMER_0,
        .duty = initial_duty,
        .hpoint = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&channel));
    if (xTaskCreate(servo_task, "servo", 3072, NULL, 4, NULL) != pdPASS) {
        ESP_ERROR_CHECK(ESP_ERR_NO_MEM);
    }
}
