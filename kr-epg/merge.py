#!/usr/bin/env python3
"""epg2xml 결과(WAVVE·TVING·LG·SK·NAVER 전체)를 우선순위대로 중복 제거해 하나의 XMLTV로 합친다.

규칙
- 채널 이름을 정규화해서 같은 채널을 묶는다 (aliases.json으로 보정 가능).
- 묶음마다 PRIORITY 순서대로, 편성 데이터가 있고 가장 긴 후보보다 12시간 넘게 짧지 않은
  첫 제공자의 채널만 남긴다.
  → 상위 제공자가 차단·장애로 비어 있으면 자동으로 다음 제공자로 넘어간다.
- 채널 ID는 제공자와 무관한 고정 ID로 바꾼다 → 제공자가 바뀌어도 IPTV 앱 매핑 유지.

사용법: python merge.py OUT_XML REPORT_MD RAW_XML [RAW_XML ...]
(RAW_XML 여러 개 = 첫 수집 + 재수집 결과를 함께 병합)
"""
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

PRIORITY = ["wavve", "tving", "lg", "sk", "naver"]  # 앞쪽일수록 우선
SHORT_TOLERANCE = timedelta(hours=12)  # 상위 제공자 데이터가 이만큼 넘게 짧으면 다음 순위 사용
HERE = Path(__file__).resolve().parent


def coverage_end(progs):
    """프로그램 목록의 마지막 종료(없으면 시작) 시각."""
    end = None
    for p in progs:
        t = p.get("stop") or p.get("start")
        try:
            dt = datetime.strptime(t[:14], "%Y%m%d%H%M%S")
        except (TypeError, ValueError):
            continue
        if end is None or dt > end:
            end = dt
    return end or datetime.min
ALIASES_FILE = HERE / "aliases.json"


def normalize(name: str) -> str:
    """'KBS 1TV', 'KBS1 HD', 'kbs1' → 'kbs1' 처럼 표기 차이를 없앤 비교용 키."""
    s = unicodedata.normalize("NFKC", name).lower()
    s = re.sub(r"[\s\-_.·:'\"()\[\]/]", "", s)  # 공백·구두점 제거 ('+', '&'는 의미가 있어 유지)
    s = s.replace("플러스", "+").replace("plus", "+")  # 'MBN Plus' = 'MBN 플러스' = 'MBN+'
    s = re.sub(r"(?:uhd|fhd|hd)$", "", s)  # 끝의 화질 표기
    if s.startswith("hd") and len(s) >= 5:  # 앞의 화질 표기 ('HD OBS W')
        s = s[2:]
    if re.search(r"(?:채널|channel)$", s) and len(re.sub(r"(?:채널|channel)$", "", s)) >= 2:
        s = re.sub(r"(?:채널|channel)$", "", s)  # '히스토리채널'→'히스토리', 'Fox News Channel'→'foxnews'
    if s.endswith("tv"):  # 'kbs1tv'→'kbs1', '디원TV'→'디원' (단, 'ktv'·'jtv' 같은 짧은 이름은 유지)
        rest = s[:-2]
        if len(rest) >= 3 or len(re.findall(r"[가-힣]", rest)) >= 2:
            s = rest
    return s


def load_aliases():
    """aliases.json → (이름 키 → 고정 ID), (원본 채널 ID → 고정 ID), 제외할 키/원본 ID."""
    if not ALIASES_FILE.exists():
        return {}, {}, set(), []
    data = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
    by_key, by_srcid = {}, {}
    for canon, names in data.get("ALIASES", {}).items():
        by_key[normalize(canon)] = canon
        for n in names:
            # '1.kt' 처럼 '.제공자'로 끝나면 원본 채널 ID, 아니면 채널 이름으로 취급
            if n.rsplit(".", 1)[-1] in PRIORITY:
                by_srcid[n] = canon
            else:
                by_key[normalize(n)] = canon
    exclude = {normalize(x) if x.rsplit(".", 1)[-1] not in PRIORITY else x for x in data.get("EXCLUDE", [])}
    patterns = [re.compile(x, re.I) for x in data.get("EXCLUDE_PATTERNS", [])]
    return by_key, by_srcid, exclude, patterns


def main(out_path, report_path, *raw_paths):
    root = None
    for rp in raw_paths:
        try:
            r = ET.parse(rp).getroot()
        except Exception as e:  # 빈 파일·손상·없음
            print(f"{rp}: 읽을 수 없어 건너뜀 ({e})")
            continue
        if root is None:
            root = r
        else:
            root.extend(list(r))
    if root is None:
        print("::error::epg2xml 결과를 읽을 수 없습니다")
        return 1

    by_key, by_srcid, exclude, patterns = load_aliases()

    progs_by_ch = defaultdict(list)
    for p in root.findall("programme"):
        progs_by_ch[p.get("channel")].append(p)

    # 고정 ID별로 제공자 후보 모으기
    groups = defaultdict(dict)  # canon_id -> {provider: channel_elem}
    for ch in root.findall("channel"):
        src_id = ch.get("id")
        provider = src_id.rsplit(".", 1)[-1]
        if provider not in PRIORITY:
            continue
        name = ch.findtext("display-name") or src_id
        key = normalize(name)
        if src_id in exclude or key in exclude or any(r.search(name) for r in patterns):
            continue
        canon = by_srcid.get(src_id) or by_key.get(key) or key
        # 같은 제공자 안에 같은 이름이 여럿이면 프로그램이 더 많은 쪽 사용
        prev = groups[canon].get(provider)
        if prev is None or len(progs_by_ch[src_id]) > len(progs_by_ch[prev.get("id")]):
            groups[canon][provider] = ch

    # 보고서용: ID를 바꾸기 전에 원래 ID와 프로그램 수를 기록
    orig = {
        canon: {p: (c.get("id"), len(progs_by_ch[c.get("id")])) for p, c in cands.items()}
        for canon, cands in groups.items()
    }

    out = ET.Element("tv", root.attrib)
    out_progs = []
    rows, stats = [], defaultdict(int)
    for canon in sorted(groups):
        cands = groups[canon]
        # 편성 데이터가 있는 후보 중, 가장 멀리까지 있는 후보보다 SHORT_TOLERANCE 이상 짧지 않은
        # 첫 우선순위 제공자를 채택 (예: WAVVE가 하루치뿐이고 TVING이 3일치면 TVING)
        ends = {p: coverage_end(progs_by_ch[c.get("id")]) for p, c in cands.items() if progs_by_ch[c.get("id")]}
        best = max(ends.values(), default=None)
        chosen = next((p for p in PRIORITY if p in ends and best - ends[p] <= SHORT_TOLERANCE), None)
        if chosen is None:
            rows.append((canon, "-", cands))
            continue
        ch = cands[chosen]
        src_id = ch.get("id")
        ch.set("id", canon)
        out.append(ch)
        for p in progs_by_ch[src_id]:
            p.set("channel", canon)
            out_progs.append(p)
        stats[chosen] += 1
        rows.append((canon, chosen, cands))

    if not out_progs:
        print("::error::남은 프로그램이 없어 기존 파일을 유지합니다")
        return 1

    out.extend(out_progs)
    ET.indent(out)
    tree = ET.ElementTree(out)
    with open(out_path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE tv SYSTEM "xmltv.dtd">\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)
        f.write(b"\n")

    total = sum(stats.values())
    print(f"채널 {total}개 (중복 제거 전 {len(root.findall('channel'))}개), 프로그램 {len(out_progs)}개")
    fetched = defaultdict(int)  # 제공자별로 편성 데이터를 실제로 받은 채널 수
    for cid, progs in progs_by_ch.items():
        if progs:
            fetched[cid.rsplit(".", 1)[-1]] += 1
    for p in PRIORITY:
        print(f"  {p.upper():6} 채택 {stats[p]:3}개 / 수집 {fetched[p]:3}개")
        if fetched[p] == 0:
            print(f"::warning::{p.upper()}에서 편성 데이터를 하나도 받지 못했습니다 (접속 차단·장애 가능성 — 실행 주석 확인)")

    if report_path:
        lines = [
            "# KR EPG 중복 제거 결과",
            "",
            f"우선순위: {' > '.join(p.upper() for p in PRIORITY)} · 채널 {total}개 · "
            + " · ".join(f"{p.upper()} {stats[p]}/{fetched[p]}" for p in PRIORITY),
            "",
            "제공자 옆 숫자는 `채택/수집` 채널 수. 표 안 괄호는 받은 프로그램 수, **굵게** 표시가 채택된 쪽.",
            "",
            "같은 채널인데 다른 줄로 나뉘어 있으면 `aliases.json`에 묶어주세요.",
            "",
            "| 고정 ID | 채널명 | 채택 | " + " | ".join(p.upper() for p in PRIORITY) + " |",
            "|---|---|---|" + "---|" * len(PRIORITY),
        ]
        for canon, chosen, cands in rows:
            name = next((c.findtext("display-name") for c in cands.values()), "")
            cells = []
            for p in PRIORITY:
                if p not in orig[canon]:
                    cells.append("")
                    continue
                oid, n = orig[canon][p]
                cell = f"{oid} ({n})"
                cells.append(f"**{cell}**" if p == chosen else cell)
            lines.append(f"| {canon} | {name} | {chosen.upper() if chosen != '-' else '없음'} | " + " | ".join(cells) + " |")
        Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
