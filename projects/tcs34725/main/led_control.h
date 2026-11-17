#pragma once
#include <stdbool.h>
void led_control_start(void);

bool device_execute_command(const char *line, bool from_cloud);
