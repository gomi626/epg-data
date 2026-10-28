#!/usr/bin/env python3
"""
NHK 総合(g1) 山形 EPG → XMLTV (GitHub Actions용, 표준 라이브러리만 사용)
NHK 番組表API v3 (program-api.nhk.jp/v3/papiPgDateTv) 사용
환경변수 NHK_API_KEY 필요. 결과: nhk_g1_yamagata.xml
"""
import datetime as dt
import json
import os
import sys
import time
import unicodedata
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
API = "https://program-api.nhk.jp/v3/papiPgDateTv"
JST = dt.timezone(dt.timedelta(hours=9))


def fail(msg):
    # GitHub Actions 요약 화면(Annotations)에 원인이 바로 보이도록 출력
    print(f"::error::{msg}")
    sys.exit(1)


def warn(msg):
    print(f"::warning::{msg}")


def fetch_day(key, date):
    """해당 방송일(05:00~익일 05:00)의 프로그램 목록. 실패 시 None."""
    q = urllib.parse.urlencode({"service": SERVICE, "area": AREA, "date": date, "key": key})
    try:
        with urllib.request.urlopen(f"{API}?{q}", timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300].replace("\n", " ")
        if e.code in (401, 403):
            fail(f"NHK API 인증 오류 HTTP {e.code}: API 키를 확인하세요. {body}")
        warn(f"[{date}] HTTP {e.code}: {body}")
        return None
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        warn(f"[{date}] 요청 실패: {e}")
        return None
    return (data.get(SERVICE) or {}).get("publication") or []


def xmltv_time(iso):
    return dt.datetime.fromisoformat(iso).strftime("%Y%m%d%H%M%S %z")


def add_programme(tv, p):
    ig = p.get("identifierGroup") or {}
    misc = p.get("misc") or {}
    prog = ET.SubElement(tv, "programme", {
        "start": xmltv_time(p["startDate"]),
        "stop": xmltv_time(p["endDate"]),
        "channel": CHANNEL_ID,
    })
    title = p.get("name") or ig.get("tvSeriesName") or ""
    ET.SubElement(prog, "title", {"lang": "ja"}).text = title

    sub = ig.get("tvEpisodeName")
    nfkc = lambda x: unicodedata.normalize("NFKC", x).replace(" ", "")
    if sub and nfkc(sub) not in nfkc(title):
        ET.SubElement(prog, "sub-title", {"lang": "ja"}).text = sub

    desc = "\n".join(x for x in (p.get("description"), misc.get("freeLine")) if x)
    if desc:
        ET.SubElement(prog, "desc", {"lang": "ja"}).text = desc

    acts = misc.get("actList") or []
    if acts:
        credits = ET.SubElement(prog, "credits")
        for a in acts:
            if a.get("name"):
                el = ET.SubElement(credits, "presenter" if "キャスター" in (a.get("role") or "") else "actor")
                el.text = a["name"]
                if el.tag == "actor" and a.get("role"):
                    el.set("role", a["role"])

    seen_cat = set()
    for g in ig.get("genre") or []:
        for name in (g.get("name1"), g.get("name2")):
            if name and name not in seen_cat:
                seen_cat.add(name)
                ET.SubElement(prog, "category", {"lang": "ja"}).text = name

    if p.get("id"):
        ET.SubElement(prog, "episode-num", {"system": "nhk-id"}).text = p["id"]


def main():
    key = os.environ.get("NHK_API_KEY")
    if not key:
        fail("NHK_API_KEY 가 설정되지 않았습니다 (Settings > Secrets and variables > Actions 확인).")

    tv = ET.Element("tv", {
        "generator-info-name": "nhk-epg-actions",
        "source-info-name": "NHK番組表API v3",
    })
    ch = ET.SubElement(tv, "channel", {"id": CHANNEL_ID})
    ET.SubElement(ch, "display-name", {"lang": "ja"}).text = CHANNEL_NAME
    ET.SubElement(ch, "display-name").text = "NHK G"

    # 새벽 0~5시는 아직 '전날 방송일'이므로 전날부터 받기
    now = dt.datetime.now(JST)
    start = (now - dt.timedelta(hours=5)).date()

    seen, programmes = set(), []
    for i in range(DAYS):
        date = (start + dt.timedelta(days=i)).isoformat()
        pubs = fetch_day(key, date)
        if pubs is None:
            if i == 0:
                fail(f"[{date}] 오늘 편성표를 받지 못했습니다.")
            break  # 제공 범위를 넘으면 중단
        print(f"[{date}] {len(pubs)}개")
        if not pubs:
            break
        for p in pubs:
            pid = p.get("id")
            if pid in seen or not p.get("startDate") or not p.get("endDate"):
                continue
            seen.add(pid)
            programmes.append(p)
        time.sleep(1)

    if not programmes:
        fail("프로그램을 하나도 받지 못해 기존 파일을 유지합니다.")

    programmes.sort(key=lambda p: p["startDate"])
    for p in programmes:
        add_programme(tv, p)

    ET.indent(tv, space="  ")
    with open(OUTFILE, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE tv SYSTEM "xmltv.dtd">\n')
        f.write(ET.tostring(tv, encoding="unicode") + "\n")
    print(f"::notice::완료: {OUTFILE} ({len(programmes)}개 프로그램, "
          f"{programmes[0]['startDate']} ~ {programmes[-1]['endDate']})")


if __name__ == "__main__":
    main()
