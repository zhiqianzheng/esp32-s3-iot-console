#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "telemetry.h"
static const char *types[]={"color","dht","led","rgb","servo","wifi"};
static char cache[6][1200];
static portMUX_TYPE cache_lock=portMUX_INITIALIZER_UNLOCKED;
void telemetry_emit(const char *format,...)
{
    char line[1400];va_list args;va_start(args,format);vsnprintf(line,sizeof(line),format,args);va_end(args);
    printf("%s",line);fflush(stdout);
    const char *prefix=strstr(line,"SENSOR_JSON:");if(!prefix)return;
    cJSON *o=cJSON_Parse(prefix+12);if(!o)return;
    cJSON *type=cJSON_GetObjectItemCaseSensitive(o,"type");
    if(cJSON_IsString(type))for(int i=0;i<6;i++)if(strcmp(type->valuestring,types[i])==0){
        cJSON_AddNumberToObject(o,"t_ms",esp_timer_get_time()/1000);
        char *json=cJSON_PrintUnformatted(o);
        if(json&&strlen(json)<sizeof(cache[i])){portENTER_CRITICAL(&cache_lock);strcpy(cache[i],json);portEXIT_CRITICAL(&cache_lock);}
        cJSON_free(json);break;
    }
    cJSON_Delete(o);
}
char *telemetry_state(const char *type)
{
    char tmp[1200];tmp[0]=0;
    for(int i=0;i<6;i++)if(strcmp(type,types[i])==0){portENTER_CRITICAL(&cache_lock);strcpy(tmp,cache[i]);portEXIT_CRITICAL(&cache_lock);break;}
    return strdup(tmp);
}
char *telemetry_snapshot(void)
{
    cJSON *all=cJSON_CreateObject();if(!all)return NULL;
    for(int i=0;i<6;i++){
        char *text=telemetry_state(types[i]);cJSON *o=text?cJSON_Parse(text):NULL;free(text);
        if(o)cJSON_AddItemToObject(all,types[i],o);
    }
    char *result=cJSON_PrintUnformatted(all);cJSON_Delete(all);return result;
}
