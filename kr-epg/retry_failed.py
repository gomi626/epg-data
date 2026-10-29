#!/usr/bin/env python3
"""첫 수집에서 편성 데이터를 하나도 못 받은 제공자만 골라 한 번 더 수집한다.
(LG처럼 간헐적으로 403을 주는 제공자 대비)

사용법: python retry_failed.py CONFIG CHANNELFILE FIRST_XML RETRY_XML [WAIT_SEC=90]
재시도할 제공자가 없으면 아무것도 하지 않고 끝난다.
"""
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def main(config, channelfile, first_xml, retry_xml, wait=90):
    cfg = json.loads(Path(config).read_text(encoding="utf-8"))
    enabled = [k for k, v in cfg.items() if k != "GLOBAL" and v.get("ENABLED", cfg["GLOBAL"].get("ENABLED", True))]

    got = Counter()
    try:
        for p in ET.parse(first_xml).getroot().iter("programme"):
            got[p.get("channel").rsplit(".", 1)[-1].upper()] += 1
    except Exception:
        pass  # 첫 결과가 아예 없으면 전부 재시도

    failed = [p for p in enabled if got[p] == 0]
    if not failed:
        print("재시도할 제공자 없음")
        return 0
    print(f"재시도: {', '.join(failed)} ({wait}초 대기 후)")

    # 실패한 제공자의 빈 채널 캐시는 지워야 다시 받아온다
    chpath = Path(channelfile)
    if chpath.exists():
        ch = json.loads(chpath.read_text(encoding="utf-8"))
        for p in failed:
            if not ch.get(p, {}).get("CHANNELS"):
                ch.pop(p, None)
        chpath.write_text(json.dumps(ch, ensure_ascii=False, indent=2), encoding="utf-8")

    for k, v in cfg.items():
        if k != "GLOBAL":
            v["ENABLED"] = k in failed
    retry_conf = Path(retry_xml).with_suffix(".json")
    retry_conf.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    time.sleep(int(wait))
    subprocess.run(["epg2xml", "run", "--config", str(retry_conf), "--channelfile", channelfile,
                    "--xmlfile", retry_xml, "--parallel"])
    return 0  # 재시도 실패는 치명적이지 않음 (병합 단계에서 판단)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:6]))
