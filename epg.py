#!/usr/bin/env python3
"""
NHK EPG → XMLTV (GitHub Actions용, 표준 라이브러리만 사용)
NHK 番組表API v3 (program-api.nhk.jp) 사용. 환경변수 NHK_API_KEY 필요.

채널을 추가하려면 아래 CHANNELS 목록에 한 줄 추가하면 됩니다.
  service: g1(総合) e1(Eテレ) r1(AM) r3(FM) 등
  area   : 130(東京) 060(山形) 270(大阪) 등
  kind   : "tv" 또는 "radio"
  file   : 출력 파일. 같은 file 값을 가진 채널은 한 XML 파일로 합쳐집니다.
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

CHANNELS = [
    {"kind": "tv",    "service": "g1", "area": "060", "id": "NHKG.Yamagata.jp",
     "name": "NHK総合・山形", "short": "NHK G",  "file": "nhk_g1_yamagata.xml"},
    {"kind": "radio", "service": "r1", "area": "130", "id": "NHKAM.Tokyo.jp",
     "name": "NHK AM・東京",  "short": "NHK AM", "file": "nhk_radio_tokyo.xml"},
    {"kind": "radio", "service": "r3", "area": "130", "id": "NHKFM.Tokyo.jp",
     "name": "NHK FM・東京",  "short": "NHK FM", "file": "nhk_radio_tokyo.xml"},
]

DAYS = int(os.environ.get("EPG_DAYS", "7"))
API = {
    "tv": "https://program-api.nhk.jp/v3/papiPgDateTv",
    "radio": "https://program-api.nhk.jp/v3/papiPgDateRadio",
}
JST = dt.timezone(dt.timedelta(hours=9))


class AuthError(Exception):
    pass


def warn(msg):
    print(f"::warning::{msg}")


def fetch_day(key, ch, date):
    """해당 방송일(05:00~익일 05:00)의 (프로그램 목록, 채널 정보). 실패 시 None."""
    q = urllib.parse.urlencode({"service": ch["service"], "area": ch["area"],
                                "date": date, "key": key})
    try:
        with urllib.request.urlopen(f"{API[ch['kind']]}?{q}", timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300].replace("\n", " ")
        if e.code in (401, 403):
            raise AuthError(f"NHK API 인증 오류 HTTP {e.code}: API 키를 확인하세요. {body}")
        warn(f"[{ch['service']} {date}] HTTP {e.code}: {body}")
        return None
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        warn(f"[{ch['service']} {date}] 요청 실패: {e}")
        return None
    svc = data.get(ch["service"]) or {}
    return svc.get("publication") or [], (svc.get("publishedOn") or [{}])[0]


def xmltv_time(iso):
    return dt.datetime.fromisoformat(iso).strftime("%Y%m%d%H%M%S %z")


def pick_logo(info):
    """채널 정보의 logo 항목에서 가장 큰 이미지 URL 선택."""
    best = (0, None)

    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            url = o.get("url")
            if isinstance(url, str) and url.startswith("http") and \
                    url.lower().split("?")[0].endswith((".png", ".jpg", ".jpeg", ".svg", ".webp")):
                size = int(o.get("width") or 0) * int(o.get("height") or 0) or 1
                if size > best[0]:
                    best = (size, url)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(info.get("logo") or {})
    return best[1]


def nfkc(x):
    return unicodedata.normalize("NFKC", x).replace(" ", "")


def add_programme(tv, ch, p):
    ig = p.get("identifierGroup") or {}
    misc = p.get("misc") or {}
    pre = "tv" if ch["kind"] == "tv" else "radio"   # tvEpisodeName / radioEpisodeName
    prog = ET.SubElement(tv, "programme", {
        "start": xmltv_time(p["startDate"]),
        "stop": xmltv_time(p["endDate"]),
        "channel": ch["id"],
    })
    title = p.get("name") or ig.get(f"{pre}SeriesName") or ""
    ET.SubElement(prog, "title", {"lang": "ja"}).text = title

    sub = ig.get(f"{pre}EpisodeName")
    if sub and nfkc(sub) not in nfkc(title):
        ET.SubElement(prog, "sub-title", {"lang": "ja"}).text = sub

    desc = "\n".join(x for x in (p.get("description"), misc.get("freeLine")) if x)
    if desc:
        ET.SubElement(prog, "desc", {"lang": "ja"}).text = desc

    acts = [a for a in (misc.get("actList") or []) if a.get("name")]
    if acts:
        credits = ET.SubElement(prog, "credits")
        for a in acts:
            role = a.get("role") or ""
            el = ET.SubElement(credits, "presenter" if ("キャスター" in role or "案内" in role) else "actor")
            el.text = a["name"]
            if el.tag == "actor" and role:
                el.set("role", role)

    seen_cat = set()
    for g in ig.get("genre") or []:
        for name in (g.get("name1"), g.get("name2")):
            if name and name not in seen_cat:
                seen_cat.add(name)
                ET.SubElement(prog, "category", {"lang": "ja"}).text = name

    if p.get("id"):
        ET.SubElement(prog, "episode-num", {"system": "nhk-id"}).text = p["id"]


def fetch_channel(key, ch, start):
    """채널 하나의 프로그램 목록과 채널 정보를 받아온다. 실패하면 사유 문자열을 던진다."""
    seen, programmes, info = set(), [], {}
    for i in range(DAYS):
        date = (start + dt.timedelta(days=i)).isoformat()
        res = fetch_day(key, ch, date)
        if res is None:
            if i == 0:
                raise ValueError(f"{ch['name']}: 오늘 편성표를 받지 못했습니다.")
            break  # 제공 범위를 넘으면 중단
        pubs, day_info = res
        info = info or day_info
        print(f"[{ch['service']} {date}] {len(pubs)}개")
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
        raise ValueError(f"{ch['name']}: 프로그램을 하나도 받지 못했습니다.")
    programmes.sort(key=lambda p: p["startDate"])
    return programmes, info


def write_file(path, results):
    """results: [(ch, programmes, info), ...] 를 XMLTV 파일 하나로 저장."""
    tv = ET.Element("tv", {
        "generator-info-name": "nhk-epg-actions",
        "source-info-name": "NHK番組表API v3",
    })
    # XMLTV 규칙상 <channel> 들이 먼저, 그다음 <programme> 들
    for ch, _, info in results:
        c = ET.SubElement(tv, "channel", {"id": ch["id"]})
        ET.SubElement(c, "display-name", {"lang": "ja"}).text = ch["name"]
        ET.SubElement(c, "display-name").text = ch["short"]
        logo = pick_logo(info)
        if logo:
            ET.SubElement(c, "icon", {"src": logo})
    for ch, programmes, _ in results:
        for p in programmes:
            add_programme(tv, ch, p)

    ET.indent(tv, space="  ")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE tv SYSTEM "xmltv.dtd">\n')
        f.write(ET.tostring(tv, encoding="unicode") + "\n")
    summary = ", ".join(f"{ch['short']} {len(pr)}개" for ch, pr, _ in results)
    print(f"::notice::완료: {path} ({summary})")


def main():
    key = os.environ.get("NHK_API_KEY")
    if not key:
        print("::error::NHK_API_KEY 가 설정되지 않았습니다 (Settings > Secrets and variables > Actions 확인).")
        sys.exit(1)

    # 새벽 0~5시는 아직 '전날 방송일'이므로 전날부터 받기
    start = (dt.datetime.now(JST) - dt.timedelta(hours=5)).date()

    # 출력 파일별로 채널 묶기 (순서 유지)
    files = {}
    for ch in CHANNELS:
        files.setdefault(ch["file"], []).append(ch)

    errors = []
    for path, chans in files.items():
        results = []
        try:
            for ch in chans:
                programmes, info = fetch_channel(key, ch, start)
                results.append((ch, programmes, info))
        except AuthError as e:
            print(f"::error::{e}")
            sys.exit(1)
        except ValueError as e:
            # 한 채널이라도 실패하면 그 파일은 덮어쓰지 않고 기존 파일 유지
            errors.append(f"{e} → {path} 는 기존 파일을 유지합니다.")
            continue
        write_file(path, results)

    # 다른 파일은 저장·커밋되도록 끝에서만 실패 처리
    for e in errors:
        print(f"::error::{e}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
