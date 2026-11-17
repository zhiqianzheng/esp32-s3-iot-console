#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "nvs_flash.h"
#include "cloud_network.h"
#include "led_control.h"
#include "servo_control.h"
#include "telemetry.h"

#define CONNECTED BIT0
static EventGroupHandle_t wifi_events;
static char ssid[33],password[65],url[200],key[129];
static char service_key[129];
static char gateway[200];
#ifdef HAVE_GATEWAY_CA
extern const unsigned char gateway_ca_start[] asm("_binary_gateway_ca_pem_start");
#endif
static bool configured;
static char boot_id[20];
static const char *DEVICE_ID="esp32-demo";
static void wifi_report(const char *status,const char *error)
{
    wifi_ap_record_t ap;int rssi=0;
    if(esp_wifi_sta_get_ap_info(&ap)==ESP_OK)rssi=ap.rssi;
    telemetry_emit("SENSOR_JSON:{\"type\":\"wifi\",\"status\":\"%s\",\"state\":\"%s\",\"rssi\":%d,\"configured\":%s,\"error\":\"%s\"}\n",strcmp(status,"online")==0?"ok":"error",status,rssi,configured?"true":"false",error?error:"");
}
static void on_wifi(void *arg,esp_event_base_t base,int32_t id,void *data)
{
    (void)arg;(void)data;
    if(base==WIFI_EVENT&&id==WIFI_EVENT_STA_START)esp_wifi_connect();
    else if(base==WIFI_EVENT&&id==WIFI_EVENT_STA_DISCONNECTED){xEventGroupClearBits(wifi_events,CONNECTED);esp_wifi_connect();}
    else if(base==IP_EVENT&&id==IP_EVENT_STA_GOT_IP)xEventGroupSetBits(wifi_events,CONNECTED);
}
bool cloud_network_command(const char *line)
{
    if(strncmp(line,"NET GATEWAY ",12)==0){
        cJSON *o=cJSON_Parse(line+12),*u=o?cJSON_GetObjectItemCaseSensitive(o,"url"):NULL;
        if(!cJSON_IsString(u)||strlen(u->valuestring)>=sizeof(gateway)||(u->valuestring[0]&&strncmp(u->valuestring,"https://",8)!=0)){cJSON_Delete(o);wifi_report("config_error","invalid_gateway_config");return true;}
        nvs_handle_t nvs;esp_err_t err=nvs_open("cloud",NVS_READWRITE,&nvs);
        if(err==ESP_OK){err=nvs_set_str(nvs,"gateway",u->valuestring);if(err==ESP_OK)err=nvs_commit(nvs);nvs_close(nvs);}
        cJSON_Delete(o);if(err!=ESP_OK){wifi_report("config_error","nvs_write_failed");return true;}
        wifi_report("saved","restart_required");vTaskDelay(pdMS_TO_TICKS(300));esp_restart();return true;
    }
    if(strncmp(line,"NET SERVICE ",12)==0){
        cJSON *o=cJSON_Parse(line+12),*token=o?cJSON_GetObjectItemCaseSensitive(o,"token"):NULL;
        if(!cJSON_IsString(token)||strlen(token->valuestring)<32||strlen(token->valuestring)>=sizeof(service_key)||strchr(token->valuestring,'\r')||strchr(token->valuestring,'\n')){cJSON_Delete(o);wifi_report("config_error","invalid_service_config");return true;}
        nvs_handle_t nvs;esp_err_t err=nvs_open("cloud",NVS_READWRITE,&nvs);
        if(err==ESP_OK){err=nvs_set_str(nvs,"service",token->valuestring);if(err==ESP_OK)err=nvs_commit(nvs);nvs_close(nvs);}
        cJSON_Delete(o);if(err!=ESP_OK){wifi_report("config_error","nvs_write_failed");return true;}
        wifi_report("saved","restart_required");vTaskDelay(pdMS_TO_TICKS(300));esp_restart();return true;
    }
    if(strcmp(line,"NET STATUS")==0){wifi_report(configured?"configured":"unconfigured",NULL);return true;}
    bool wifi_only=strncmp(line,"NET WIFI ",9)==0;
    if(!wifi_only&&strncmp(line,"NET CONFIG ",11)!=0)return false;
    if(wifi_only&&!configured){wifi_report("config_error","cloud_not_provisioned");return true;}
    cJSON *o=cJSON_Parse(line+(wifi_only?9:11));
    if(wifi_only&&cJSON_IsObject(o)){cJSON_AddStringToObject(o,"url",url);cJSON_AddStringToObject(o,"device_key",key);}
    cJSON *s=o?cJSON_GetObjectItemCaseSensitive(o,"ssid"):NULL,*p=o?cJSON_GetObjectItemCaseSensitive(o,"password"):NULL,*u=o?cJSON_GetObjectItemCaseSensitive(o,"url"):NULL,*k=o?cJSON_GetObjectItemCaseSensitive(o,"device_key"):NULL;
    bool valid=cJSON_IsString(s)&&strlen(s->valuestring)>0&&strlen(s->valuestring)<=32&&cJSON_IsString(p)&&strlen(p->valuestring)<=64&&cJSON_IsString(u)&&strncmp(u->valuestring,"https://",8)==0&&strlen(u->valuestring)<sizeof(url)&&cJSON_IsString(k)&&strlen(k->valuestring)>=32&&strlen(k->valuestring)<sizeof(key);
    if(!valid){cJSON_Delete(o);wifi_report("config_error","invalid_config");return true;}
    nvs_handle_t nvs;esp_err_t err=nvs_open("cloud",NVS_READWRITE,&nvs);
    if(err==ESP_OK){err=nvs_set_str(nvs,"ssid",s->valuestring);if(err==ESP_OK)err=nvs_set_str(nvs,"pass",p->valuestring);if(err==ESP_OK)err=nvs_set_str(nvs,"url",u->valuestring);if(err==ESP_OK)err=nvs_set_str(nvs,"key",k->valuestring);if(err==ESP_OK)err=nvs_commit(nvs);nvs_close(nvs);}
    cJSON_Delete(o);
    if(err!=ESP_OK){wifi_report("config_error","nvs_write_failed");return true;}
    configured=true;wifi_report("saved","restart_required");vTaskDelay(pdMS_TO_TICKS(300));esp_restart();return true;
}

typedef struct{char data[7000];size_t used;} response_t;
static esp_err_t on_http(esp_http_client_event_t *e)
{
    response_t *r=e->user_data;
    if(e->event_id==HTTP_EVENT_ON_DATA){if(r->used+e->data_len>=sizeof(r->data))return ESP_FAIL;memcpy(r->data+r->used,e->data,e->data_len);r->used+=e->data_len;r->data[r->used]=0;}
    return ESP_OK;
}
static bool command_confirmed(const char *kind,int request,const char *command,char **state)
{
    const char *type=strcmp(kind,"servo_stop")==0?"servo":kind;
    for(int i=0;i<12;i++){
        char *raw=telemetry_state(type);cJSON *o=raw?cJSON_Parse(raw):NULL;
        bool ok=false;
        if(o){
            if(strcmp(type,"led")==0)ok=cJSON_IsTrue(cJSON_GetObjectItem(o,"on"))==(strcmp(command,"LED ON")==0);
            else{
                cJSON *rid=cJSON_GetObjectItem(o,"request");ok=cJSON_IsNumber(rid)&&rid->valueint==request;
                if(strcmp(type,"servo")==0)ok=ok&&cJSON_IsTrue(cJSON_GetObjectItem(o,"applied"));
            }
        }
        cJSON_Delete(o);if(ok){*state=raw;return true;}free(raw);vTaskDelay(pdMS_TO_TICKS(50));
    }
    return false;
}
static void network_task(void *arg)
{
    (void)arg;
    response_t *response=calloc(1,sizeof(response_t));if(!response)vTaskDelete(NULL);
    char endpoint[240];snprintf(endpoint,sizeof(endpoint),"%s/api/device/sync",gateway[0]?gateway:url);
    char authorization[150];snprintf(authorization,sizeof(authorization),"Bearer %s",key);
    esp_http_client_config_t cfg={.url=endpoint,.user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 ESP32SensorControl/1.0",.crt_bundle_attach=esp_crt_bundle_attach,.timeout_ms=6000,.event_handler=on_http,.user_data=response,.keep_alive_enable=true,.buffer_size=4096,.buffer_size_tx=2048};
#ifdef HAVE_GATEWAY_CA
    if(gateway[0]){cfg.crt_bundle_attach=NULL;cfg.cert_pem=(const char *)gateway_ca_start;}
#else
    if(gateway[0]){free(response);wifi_report("config_error","gateway_ca_missing");vTaskDelete(NULL);return;}
#endif
    esp_http_client_handle_t client=esp_http_client_init(&cfg);
    if(!client){free(response);vTaskDelete(NULL);return;}
    esp_http_client_set_method(client,HTTP_METHOD_POST);esp_http_client_set_header(client,"Content-Type","application/json");esp_http_client_set_header(client,"Authorization",authorization);
    if(service_key[0]&&!gateway[0]&&strcmp(url,"https://console.example.com")==0){char service_authorization[150];snprintf(service_authorization,sizeof(service_authorization),"Bearer %s",service_key);esp_http_client_set_header(client,"OAI-Sites-Authorization",service_authorization);}
    cJSON *acks=cJSON_CreateArray();int seen[16]={0};unsigned seen_index=0;
    bool sntp_started=false;
    for(;;){
        if(!(xEventGroupGetBits(wifi_events)&CONNECTED)){wifi_report("connecting","waiting_for_wifi");vTaskDelay(pdMS_TO_TICKS(3000));continue;}
        if(!sntp_started){esp_sntp_config_t sntp=ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");esp_netif_sntp_init(&sntp);sntp_started=true;}
        if(time(NULL)<1700000000){wifi_report("time_sync","waiting_for_network_time");vTaskDelay(pdMS_TO_TICKS(1000));continue;}
        cJSON *payload=cJSON_CreateObject();char *snapshot=telemetry_snapshot();
        cJSON_AddStringToObject(payload,"device_id",DEVICE_ID);cJSON_AddStringToObject(payload,"boot_id",boot_id);cJSON_AddNumberToObject(payload,"uptime",esp_timer_get_time()/1000);
        cJSON_AddRawToObject(payload,"states",snapshot?snapshot:"{}");free(snapshot);cJSON_AddItemToObject(payload,"acks",cJSON_Duplicate(acks,true));
        char *text=cJSON_PrintUnformatted(payload);cJSON_Delete(payload);response->used=0;response->data[0]=0;
        esp_http_client_set_post_field(client,text,strlen(text));esp_err_t err=esp_http_client_perform(client);int status=esp_http_client_get_status_code(client);cJSON_free(text);
        if(err!=ESP_OK||status!=200){char reason[80];snprintf(reason,sizeof(reason),err!=ESP_OK?"https_failed_%d":"http_%d",err!=ESP_OK?(int)err:status);if(status==403){if(strstr(response->data,"1010"))strcat(reason,"_cf1010");else if(strstr(response->data,"Just a moment")||strstr(response->data,"challenge-platform"))strcat(reason,"_browser_challenge");else if(strstr(response->data,"1020"))strcat(reason,"_cf1020");else if(strstr(response->data,"Cloudflare")||strstr(response->data,"cloudflare"))strcat(reason,"_cloudflare");else if(strstr(response->data,"Unauthorized"))strcat(reason,"_unauthorized");}wifi_report("cloud_error",reason);vTaskDelay(pdMS_TO_TICKS(2000));continue;}
        cJSON *reply=cJSON_Parse(response->data);
        if(!reply){wifi_report("cloud_error","invalid_response");vTaskDelay(pdMS_TO_TICKS(1000));continue;}
        cJSON_Delete(acks);acks=cJSON_CreateArray();wifi_report("online",NULL);
        if(cJSON_IsTrue(cJSON_GetObjectItem(reply,"servo_keepalive")))servo_control_command_from("SERVO PING",true);
        cJSON *commands=cJSON_GetObjectItem(reply,"commands"),*command;
        cJSON_ArrayForEach(command,commands){
            cJSON *id=cJSON_GetObjectItem(command,"id"),*kind=cJSON_GetObjectItem(command,"kind"),*line=cJSON_GetObjectItem(command,"command"),*rid=cJSON_GetObjectItem(command,"request");
            if(!cJSON_IsNumber(id)||!cJSON_IsString(kind)||!cJSON_IsString(line)||!cJSON_IsNumber(rid)||strlen(line->valuestring)>=500)continue;
            bool duplicate=false;for(int i=0;i<16;i++)if(seen[i]==id->valueint)duplicate=true;
            bool ok=true;char *state=NULL;
            if(!duplicate){ok=device_execute_command(line->valuestring,true);if(ok)ok=command_confirmed(kind->valuestring,rid->valueint,line->valuestring,&state);seen[seen_index++%16]=id->valueint;}
            cJSON *ack=cJSON_CreateObject();cJSON_AddNumberToObject(ack,"id",id->valueint);cJSON_AddBoolToObject(ack,"ok",ok);cJSON_AddBoolToObject(ack,"replayed",duplicate);
            if(state){cJSON_AddRawToObject(ack,"state",state);free(state);}cJSON_AddItemToArray(acks,ack);
        }
        cJSON_Delete(reply);vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
void cloud_network_start(void)
{
    esp_err_t err=nvs_flash_init();if(err!=ESP_OK){wifi_report("config_error","nvs_init_failed");return;}
    nvs_handle_t nvs;if(nvs_open("cloud",NVS_READONLY,&nvs)!=ESP_OK){wifi_report("unconfigured",NULL);return;}
    size_t a=sizeof(ssid),b=sizeof(password),c=sizeof(url),d=sizeof(key);
    configured=nvs_get_str(nvs,"ssid",ssid,&a)==ESP_OK&&nvs_get_str(nvs,"pass",password,&b)==ESP_OK&&nvs_get_str(nvs,"url",url,&c)==ESP_OK&&nvs_get_str(nvs,"key",key,&d)==ESP_OK;
    size_t service_size=sizeof(service_key);if(nvs_get_str(nvs,"service",service_key,&service_size)!=ESP_OK)service_key[0]=0;
    size_t gateway_size=sizeof(gateway);if(nvs_get_str(nvs,"gateway",gateway,&gateway_size)!=ESP_OK)gateway[0]=0;nvs_close(nvs);
    if(!configured){wifi_report("unconfigured",NULL);return;}
    snprintf(boot_id,sizeof(boot_id),"%08lx%08lx",(unsigned long)esp_random(),(unsigned long)esp_random());
    wifi_events=xEventGroupCreate();ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());esp_netif_create_default_wifi_sta();
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,on_wifi,NULL));ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,on_wifi,NULL));
    wifi_config_t wifi={0};strcpy((char*)wifi.sta.ssid,ssid);strcpy((char*)wifi.sta.password,password);wifi.sta.pmf_cfg.capable=true;wifi.sta.pmf_cfg.required=false;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&wifi));ESP_ERROR_CHECK(esp_wifi_start());
    if(xTaskCreate(network_task,"cloud_sync",24576,NULL,1,NULL)!=pdPASS)wifi_report("cloud_error","out_of_memory");
}
