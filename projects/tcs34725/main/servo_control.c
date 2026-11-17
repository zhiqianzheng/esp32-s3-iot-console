#include "telemetry.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"
#include "driver/ledc.h"
#include "esp_err.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "servo_control.h"

typedef struct {
    bool enabled, continuous, hold;
    float target, low, high, period, speed;
    int frequency, request;
    unsigned revision;
} settings_t;
typedef struct {float angle;bool enabled,moving;unsigned applied_revision;int pulse;} runtime_t;
static settings_t settings={.enabled=false,.hold=true,.target=90,.low=60,.high=120,.period=4,.speed=60,.frequency=50,.revision=1};
static runtime_t runtime={.angle=90};
static int64_t last_contact;
static bool link_timeout;
static bool cloud_owner;
static portMUX_TYPE lock=portMUX_INITIALIZER_UNLOCKED;

void servo_control_report(void)
{
    settings_t c;runtime_t r;bool timed_out,owner;
    portENTER_CRITICAL(&lock);c=settings;r=runtime;timed_out=link_timeout;owner=cloud_owner;portEXIT_CRITICAL(&lock);
    telemetry_emit("SENSOR_JSON:{\"type\":\"servo\",\"status\":\"ok\",\"request\":%d,\"revision\":%u,\"applied\":%s,\"enabled\":%s,\"moving\":%s,\"mode\":\"%s\",\"angle\":%.2f,\"target\":%.2f,\"low\":%.2f,\"high\":%.2f,\"period\":%.2f,\"speed\":%.2f,\"pwm_frequency\":%d,\"hold\":%s,\"pulse_us\":%d,\"gpio\":14,\"link_timeout\":%s,\"owner\":\"%s\"}\n",
           c.request,c.revision,r.applied_revision==c.revision?"true":"false",r.enabled?"true":"false",r.moving?"true":"false",c.continuous?"continuous":"single",r.angle,c.target,c.low,c.high,c.period,c.speed,c.frequency,c.hold?"true":"false",r.pulse,timed_out?"true":"false",owner?"cloud":"serial");
    fflush(stdout);
}

static void report_error(const char *error,int request)
{
    telemetry_emit("SENSOR_JSON:{\"type\":\"servo\",\"status\":\"error\",\"request\":%d,\"error\":\"%s\"}\n",request,error);fflush(stdout);
}
static bool number(cJSON *root,const char *key,double min,double max,float *out)
{
    cJSON *v=cJSON_GetObjectItemCaseSensitive(root,key);
    if(!cJSON_IsNumber(v)||!isfinite(v->valuedouble)||v->valuedouble<min||v->valuedouble>max)return false;
    *out=v->valuedouble;return true;
}

bool servo_control_command_from(const char *line, bool from_cloud)
{
    if(strcmp(line,"SERVO PING")==0||strcmp(line,"SERVO STATUS")==0){
        portENTER_CRITICAL(&lock);if(cloud_owner==from_cloud)last_contact=esp_timer_get_time();portEXIT_CRITICAL(&lock);
        if(strcmp(line,"SERVO STATUS")==0)servo_control_report();
        return true;
    }
    if(strncmp(line,"SERVO STOP",10)==0){
        char *end;long rid=0;
        if(line[10]==' '){rid=strtol(line+11,&end,10);if(*end||end==line+11||rid<0||rid>2147483647L)return true;}
        else if(line[10]!='\0')return false;
        portENTER_CRITICAL(&lock);settings.enabled=false;link_timeout=false;last_contact=esp_timer_get_time();settings.request=rid;++settings.revision;portEXIT_CRITICAL(&lock);
        return true;
    }
    if(strncmp(line,"SERVO SET ",10)!=0)return false;
    cJSON *root=cJSON_Parse(line+10);
    if(!cJSON_IsObject(root)){cJSON_Delete(root);report_error("invalid_json",0);return true;}
    settings_t next={0};float frequency=0;
    cJSON *rid=cJSON_GetObjectItemCaseSensitive(root,"request");
    int id=cJSON_IsNumber(rid)&&rid->valuedouble>=0&&rid->valuedouble<=2147483647.0?rid->valueint:0;
    cJSON *mode=cJSON_GetObjectItemCaseSensitive(root,"mode");
    cJSON *enabled=cJSON_GetObjectItemCaseSensitive(root,"enabled");
    cJSON *hold=cJSON_GetObjectItemCaseSensitive(root,"hold");
    bool valid=cJSON_IsNumber(rid)&&isfinite(rid->valuedouble)&&rid->valuedouble>=0&&rid->valuedouble<=2147483647.0&&floor(rid->valuedouble)==rid->valuedouble&&cJSON_IsString(mode)&&(strcmp(mode->valuestring,"single")==0||strcmp(mode->valuestring,"continuous")==0)&&cJSON_IsBool(enabled)&&cJSON_IsBool(hold)&&
        number(root,"target",0,180,&next.target)&&number(root,"low",0,180,&next.low)&&number(root,"high",0,180,&next.high)&&next.low<next.high&&
        number(root,"period",2,60,&next.period)&&number(root,"speed",5,180,&next.speed)&&number(root,"pwm_frequency",40,60,&frequency)&&floorf(frequency)==frequency;
    if(!valid){cJSON_Delete(root);report_error("invalid_settings",id);return true;}
    next.enabled=cJSON_IsTrue(enabled);next.hold=cJSON_IsTrue(hold);next.continuous=strcmp(mode->valuestring,"continuous")==0;next.frequency=(int)frequency;next.request=id;
    cJSON *delta=cJSON_GetObjectItemCaseSensitive(root,"delta");
    if(delta){
        if(!cJSON_IsNumber(delta)||!isfinite(delta->valuedouble)||fabs(delta->valuedouble)>30||fabs(delta->valuedouble)<0.1){cJSON_Delete(root);report_error("invalid_step",id);return true;}
        portENTER_CRITICAL(&lock);float angle=runtime.angle;portEXIT_CRITICAL(&lock);
        next.target=fminf(180,fmaxf(0,angle+delta->valuedouble));next.continuous=false;next.enabled=true;
    }
    cJSON_Delete(root);
    portENTER_CRITICAL(&lock);next.revision=settings.revision+1;settings=next;cloud_owner=from_cloud;last_contact=esp_timer_get_time();link_timeout=false;portEXIT_CRITICAL(&lock);
    return true;
}

static int output_angle(float angle,int frequency)
{
    unsigned pulse=(unsigned)(500.0f+2000.0f*angle/180.0f+0.5f);
    unsigned duty=(unsigned)((double)pulse*16384*frequency/1000000.0+0.5);
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,duty));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0));
    return pulse;
}

static void servo_task(void *arg)
{
    (void)arg;
    TickType_t wake=xTaskGetTickCount();
    int64_t previous=esp_timer_get_time(),last_report=0;
    unsigned revision=0;int frequency=50;
    bool active=false,moving=false;float angle=90,destination=90;
    for(;;){
        settings_t c;
        portENTER_CRITICAL(&lock);
        if(settings.enabled && esp_timer_get_time()-last_contact>5000000){settings.enabled=false;++settings.revision;link_timeout=true;}
        c=settings;
        portEXIT_CRITICAL(&lock);
        int64_t now=esp_timer_get_time();float dt=fminf(0.1f,(now-previous)/1000000.0f);previous=now;
        bool changed=c.revision!=revision;
        if(changed){
            revision=c.revision;
            if(frequency!=c.frequency){ESP_ERROR_CHECK(ledc_set_freq(LEDC_LOW_SPEED_MODE,LEDC_TIMER_0,c.frequency));frequency=c.frequency;}
            active=c.enabled;destination=c.continuous?c.low:c.target;
            if(!active)ESP_ERROR_CHECK(ledc_stop(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,0));
        }
        int pulse=0;
        bool was_moving=moving;
        moving=false;
        if(active){
            float step=(c.continuous?2*(c.high-c.low)/c.period:c.speed)*dt;
            float delta=destination-angle;
            if(fabsf(delta)<=step){
                angle=destination;
                if(c.continuous)destination=fabsf(destination-c.low)<0.01f?c.high:c.low;
                else if(!c.hold)active=false;
            }else{angle+=delta>0?step:-step;}
            moving=active&&(c.continuous||fabsf(destination-angle)>.01f);
            if(active)pulse=output_angle(angle,frequency);
            else{
                /* Issue the target pulse briefly before disabling on the next tick. */
                output_angle(angle,frequency);
                vTaskDelay(pdMS_TO_TICKS(40));
                ESP_ERROR_CHECK(ledc_stop(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,0));
            }
        }
        portENTER_CRITICAL(&lock);runtime=(runtime_t){.angle=angle,.enabled=active,.moving=moving,.applied_revision=revision,.pulse=pulse};portEXIT_CRITICAL(&lock);
        if(changed||moving!=was_moving||now-last_report>=250000){servo_control_report();last_report=now;}
        vTaskDelayUntil(&wake,pdMS_TO_TICKS(20));
    }
}

void servo_control_start(void)
{
    const ledc_timer_config_t timer={.speed_mode=LEDC_LOW_SPEED_MODE,.duty_resolution=LEDC_TIMER_14_BIT,.timer_num=LEDC_TIMER_0,.freq_hz=50,.clk_cfg=LEDC_AUTO_CLK};
    ESP_ERROR_CHECK(ledc_timer_config(&timer));
    const ledc_channel_config_t channel={.gpio_num=14,.speed_mode=LEDC_LOW_SPEED_MODE,.channel=LEDC_CHANNEL_0,.timer_sel=LEDC_TIMER_0,.duty=0,.hpoint=0};
    ESP_ERROR_CHECK(ledc_channel_config(&channel));
    ESP_ERROR_CHECK(ledc_stop(LEDC_LOW_SPEED_MODE,LEDC_CHANNEL_0,0));
    if(xTaskCreate(servo_task,"servo_control",6144,NULL,2,NULL)!=pdPASS)ESP_ERROR_CHECK(ESP_ERR_NO_MEM);
}

bool servo_control_command(const char *line){return servo_control_command_from(line,false);}
