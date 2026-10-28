#!/usr/bin/env python3
"""
NHK 総合(g1) 山形 EPG → XMLTV (GitHub Actions용, 표준 라이브러리만 사용)
환경변수 NHK_API_KEY 필요. 결과: nhk_g1_yamagata.xml
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

AREA = os.environ.get("NHK_AREA", "060")      # 山形
SERVICE = os.environ.get("NHK_SERVICE", "g1")  # NHK総合1
DAYS = int(os.environ.get("EPG_DAYS", "7"))
OUTFILE = os.environ.get("EPG_OUTFILE", "nhk_g1_yamagata.xml")
CHANNEL_ID = "NHKG.Yamagata.jp"
CHANNEL_NAME = "NHK総合・山形"
BASE = "https://api.nhk.or.jp/v2/pg/list/{area}/{service}/{date}.json"
JST = dt.timezone(dt.timedelta(hours=9))


def fetch_day(key, date):
    url = BASE.format(area=AREA, service=SERVICE, date=date)
    url += "?" + urllib.parse.urlencode({"key": key})
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r).get("list", {}).get(SERVICE, [])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[{date}] 데이터 없음 (404)")
            return []
        sys.exit(f"NHK API 오류 {e.code} ({date})")


def xmltv_time(iso):
    return dt.datetime.fromisoformat(iso).strftime("%Y%m%d%H%M%S %z")


def main():
    key = os.environ.get("NHK_API_KEY")
    if not key:
        sys.exit("NHK_API_KEY 가 설정되지 않았습니다 (저장소 Secrets 확인).")

    tv = ET.Element("tv", {
        "generator-info-name": "nhk-epg-actions",
        "source-info-name": "NHK番組表API v2",
    })
    ch = ET.SubElement(tv, "channel", {"id": CHANNEL_ID})
    ET.SubElement(ch, "display-name", {"lang": "ja"}).text = CHANNEL_NAME
    ET.SubElement(ch, "display-name").text = "NHK G"

    seen, count = set(), 0
    today = dt.datetime.now(JST).date()
    for i in range(DAYS):
        date = (today + dt.timedelta(days=i)).isoformat()
        programs = fetch_day(key, date)
        print(f"[{date}] {len(programs)}개")
        for p in programs:
            pid = p.get("id")
            if pid in seen:
                continue
            seen.add(pid)
            prog = ET.SubElement(tv, "programme", {
                "start": xmltv_time(p["start_time"]),
                "stop": xmltv_time(p["end_time"]),
                "channel": CHANNEL_ID,
            })
            ET.SubElement(prog, "title", {"lang": "ja"}).text = p.get("title", "")
            if p.get("subtitle"):
                ET.SubElement(prog, "sub-title", {"lang": "ja"}).text = p["subtitle"]
            desc = "\n".join(x for x in (p.get("content"), p.get("act")) if x)
            if desc:
                ET.SubElement(prog, "desc", {"lang": "ja"}).text = desc
            for g in p.get("genres") or []:
                ET.SubElement(prog, "category").text = str(g)
            if pid:
                ET.SubElement(prog, "episode-num", {"system": "nhk-id"}).text = pid
            count += 1
        time.sleep(1)

    if count == 0:
        sys.exit("프로그램을 하나도 받지 못해 기존 파일을 유지합니다.")

    ET.indent(tv, space="  ")
    with open(OUTFILE, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE tv SYSTEM "xmltv.dtd">\n')
        f.write(ET.tostring(tv, encoding="unicode") + "\n")
    print(f"완료: {OUTFILE} ({count}개 프로그램)")


if __name__ == "__main__":
    main()
