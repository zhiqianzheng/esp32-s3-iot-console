#pragma once
void telemetry_emit(const char *format, ...) __attribute__((format(printf,1,2)));
char *telemetry_snapshot(void);
char *telemetry_state(const char *type);
