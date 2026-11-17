#pragma once
#include <stdbool.h>
void breathing_led_start(void);
bool breathing_led_command(const char *line);
void breathing_led_report(void);
