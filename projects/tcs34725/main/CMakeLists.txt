idf_component_register(SRCS "color_main.c" "dht_sensor.c" "led_control.c" "breathing_led.c" "servo_control.c" "telemetry.c" "cloud_network.c" INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_i2c esp_driver_gpio esp_timer esp_driver_uart esp_driver_rmt esp_driver_ledc esp_wifi esp_event esp_netif esp_http_client esp-tls nvs_flash)

if(EXISTS "${CMAKE_CURRENT_LIST_DIR}/gateway_ca.pem")
    target_add_binary_data(${COMPONENT_LIB} "gateway_ca.pem" TEXT)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE HAVE_GATEWAY_CA=1)
endif()
