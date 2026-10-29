# KR EPG (epg2xml)

[epg2xml](https://github.com/epg2xml/epg2xml) v2.8.2로 KT · WAVVE · TVING 편성표를 수집하고,
**WAVVE > TVING > KT** 우선순위로 중복을 없애 저장소 루트의 `kr_epg.xml` 하나로 만듭니다.
워크플로: `.github/workflows/kr-epg.yml` (매일 04:43 KST)

## 흐름
1. epg2xml이 세 제공자의 전체 채널을 수집 (`epg2xml.json`, 모두 `"*"`)
2. `merge.py`가 채널 이름을 정규화해 같은 채널끼리 묶음
3. 묶음마다 우선순위가 가장 높고 **편성 데이터가 실제로 있는** 제공자 하나만 남김
   — WAVVE가 차단·장애로 비어 있으면 그 채널은 자동으로 TVING, 다음 KT로 넘어감
4. 채널 ID를 제공자와 무관한 고정 ID(예: `KBS1`, `tvN`)로 바꿔 저장
   — 제공자가 바뀌어도 IPTV 앱의 `tvg-id` 매핑은 그대로 유지
5. 결과 요약을 `REPORT.md`에 기록 (Actions 실행 요약에도 표시)

## 파일
| 파일 | 역할 |
|---|---|
| `epg2xml.json` | epg2xml 설정 |
| `aliases.json` | 채널 묶기·고정 ID·제외 설정 (직접 편집) |
| `merge.py` | 중복 제거 스크립트. 우선순위는 맨 위 `PRIORITY` |
| `REPORT.md` | 마지막 실행에서 어떤 채널을 어느 제공자로 채택했는지 |
| `Channel.json` | 제공자별 전체 채널 목록(캐시). **읽기 전용** |

## 이름 맞추기 (`aliases.json`)
이름의 공백·구두점·대소문자·끝의 `HD`/`TV` 차이는 자동으로 무시합니다
(`KBS 1TV` = `KBS1` = `kbs1 HD`). 그래도 `REPORT.md`에서 같은 채널이 두 줄로 나뉘어 있으면 묶어주세요.

```json
{
  "ALIASES": {
    "TV조선": ["TV CHOSUN"],          // 키 = 고정 ID, 값 = 다른 표기들
    "OCN Movies": ["C01234.tving"]    // '.wavve/.tving/.kt'로 끝나면 원본 채널 ID로 지정
  },
  "EXCLUDE": ["홈쇼핑채널", "123.kt"]  // 아예 빼고 싶은 채널(이름 또는 원본 ID)
}
```
(`//` 설명은 이해를 돕기 위한 것이니 실제 파일에는 넣지 마세요.)
별칭에 없는 채널의 고정 ID는 정규화된 이름(소문자·공백 제거)입니다.

## 해외 IP 차단
GitHub Actions 서버는 해외에 있어 일부 제공자가 응답하지 않을 수 있습니다.
실행 요약에 `WAVVE에서 채택된 채널이 없습니다` 같은 경고가 나오면, 한국 IP 프록시 주소를
Settings → Secrets and variables → Actions에 `EPG2XML_PROXY`(예: `http://id:pw@host:port`)로 등록하세요.

## 버전 올리기
워크플로의 `EPG2XML_VERSION`만 바꿉니다. 새 버전에서 설정 항목이 추가되면 epg2xml이
설정을 고친 뒤 종료하므로, 그 경우 로컬에서 한 번 실행해 갱신된 `epg2xml.json`을 커밋하세요.
