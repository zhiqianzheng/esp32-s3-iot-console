#!/usr/bin/env python3
import concurrent.futures, hashlib, json, pathlib, time, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
items={
'docs/boards/REFERENCE_ONLY_DevKitC-1_V1.1_schematic.pdf':'https://dl.espressif.com/dl/schematics/SCH_ESP32-S3-DevKitC-1_V1.1_20221130.pdf',
'docs/boards/REFERENCE_ONLY_DevKitC-1_V1.1_PCB.pdf':'https://dl.espressif.com/dl/schematics/PCB_ESP32-S3-DevKitC-1_V1.1_20220429.pdf',
'docs/hardware/esp32-s3_datasheet_cn.pdf':'https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_cn.pdf',
'docs/hardware/esp32-s3_technical_reference_manual_cn.pdf':'https://documentation.espressif.com/esp32-s3_technical_reference_manual_cn.pdf',
'docs/hardware/esp32-s3-wroom-1_wroom-1u_datasheet_cn.pdf':'https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_cn.pdf',
'docs/hardware/hardware_design_guidelines_cn.pdf':'https://docs.espressif.com/projects/esp-hardware-design-guidelines/zh_CN/latest/esp32s3/esp-hardware-design-guidelines-zh_CN-master-esp32s3.pdf',
'docs/hardware/chip_errata_cn.pdf':'https://docs.espressif.com/projects/esp-chip-errata/zh_CN/latest/esp32s3/esp-chip-errata-zh_CN-master-esp32s3.pdf',
'docs/boards/official_esp32s3_devkits_reference_cn.pdf':'https://docs.espressif.com/projects/esp-dev-kits/zh_CN/latest/esp32s3/esp-dev-kits-zh_CN-master-esp32s3.pdf',
'downloads/esp-idf-zh_CN-v6.1.1.zip':'https://docs.espressif.com/projects/esp-idf/zh_CN/v6.1.1/esp32s3/esp-idf-zh_CN-v6.1.1.zip',
}
def get(item):
 name,url=item; p=ROOT/name
 for attempt in range(3):
  try:
   if p.exists():
    data=p.read_bytes(); final=url
   else:
    with urllib.request.urlopen(url,timeout=90) as r: data=r.read(); final=r.url
   if name.endswith('.pdf') and not data.startswith(b'%PDF'): raise ValueError('Not PDF')
   if name.endswith('.zip') and not data.startswith(b'PK'): raise ValueError('Not ZIP')
   p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)
   print(f'OK {name} {len(data)}',flush=True)
   return dict(path=name,url=url,final_url=final,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),downloaded_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
  except Exception as e:
   if attempt==2: print(f'FAILED {name}: {e}',flush=True); return dict(path=name,url=url,error=str(e))
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(get,items.items()))
(ROOT/'docs/download-manifest.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
