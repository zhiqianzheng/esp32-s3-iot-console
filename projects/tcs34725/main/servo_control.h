#pragma once
#include <stdbool.h>
void servo_control_start(void);
bool servo_control_command(const char *line);
void servo_control_report(void);

bool servo_control_command_from(const char *line, bool from_cloud);
