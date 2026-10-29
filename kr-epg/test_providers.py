#!/usr/bin/env python3
"""제공자 접속 테스트: 지정한 제공자만 켜서 채널 목록을 받고, 무작위 N개 채널의 하루치 EPG를 받아본다.
kr_epg.xml·Channel.json 등 저장소 파일은 건드리지 않는다 (모든 산출물은 작업 폴더에만 생성).

사용법: python test_providers.py WORKDIR "LG,SK,NAVER" [N=10]
결과는 GitHub Actions 주석(::notice/::warning)과 표로 출력된다.
"""
import json
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def epg2xml(*args, log):
    r = subprocess.run(["epg2xml", *args], capture_output=True, text=True)
    log.write(r.stdout + r.stderr)
    return r.returncode


def main(workdir, providers, n=10):
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    providers = [p.strip().upper() for p in providers.split(",") if p.strip()]
    n = int(n)

    cfg = json.loads((HERE / "epg2xml.json").read_text(encoding="utf-8"))
    for k, v in cfg.items():
        if k != "GLOBAL":
            v["ENABLED"] = k in providers
            v["MY_CHANNELS"] = []
    cfg["GLOBAL"]["FETCH_LIMIT"] = 1
    conf, chfile, xml = work / "test.json", work / "Channel.json", work / "test.xml"
    conf.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(work / "epg2xml.log", "w", encoding="utf-8") as log:
        # 1) 채널 목록
        epg2xml("update_channels", "--config", str(conf), "--channelfile", str(chfile), log=log)
        chjson = json.loads(chfile.read_text(encoding="utf-8")) if chfile.exists() else {}
        totals = {p: len(chjson.get(p, {}).get("CHANNELS", [])) for p in providers}

        # 2) 무작위 n개 채널로 EPG
        rng = random.Random()
        for p in providers:
            chans = chjson.get(p, {}).get("CHANNELS", [])
            cfg[p]["MY_CHANNELS"] = [{"ServiceId": c["ServiceId"]} for c in rng.sample(chans, min(n, len(chans)))]
        conf.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        if any(totals.values()):
            epg2xml("run", "--config", str(conf), "--channelfile", str(chfile),
                    "--xmlfile", str(xml), "--parallel", log=log)

    chan_cnt, prog_cnt, names = Counter(), Counter(), {}
    try:
        root = ET.parse(xml).getroot()
        for c in root.findall("channel"):
            src = c.get("id").rsplit(".", 1)[-1].upper()
            chan_cnt[src] += 1
            names.setdefault(src, []).append(c.findtext("display-name") or "")
        for pr in root.findall("programme"):
            prog_cnt[pr.get("channel").rsplit(".", 1)[-1].upper()] += 1
    except Exception:
        pass

    print("| 제공자 | 전체 채널 목록 | 시험 채널 | EPG 받은 채널 | 프로그램 | 결과 |")
    print("|---|---|---|---|---|---|")
    for p in providers:
        tried = len(cfg[p]["MY_CHANNELS"])
        ok = totals[p] > 0 and prog_cnt[p] > 0
        print(f"| {p} | {totals[p]} | {tried} | {chan_cnt[p]} | {prog_cnt[p]} | {'✅ 성공' if ok else '❌ 실패'} |")
        sample = ", ".join(names.get(p, [])[:5])
        if ok:
            print(f"::notice title={p} 성공::채널 목록 {totals[p]}개, 시험 {tried}개 중 {chan_cnt[p]}개에서 프로그램 {prog_cnt[p]}개 (예: {sample})",
                  file=sys.stderr)
        else:
            why = "채널 목록부터 못 받음" if totals[p] == 0 else "채널 목록은 받았지만 편성 데이터 없음"
            print(f"::warning title={p} 실패::{why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:4]))
