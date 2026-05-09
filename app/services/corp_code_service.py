import httpx
import zipfile
import io
import xml.etree.ElementTree as ET
import os

DART_API_KEY = os.getenv("DART_API_KEY")
CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"

_corp_map: dict[str, list[dict]] | None = None  # 이름 → [{corp_code, corp_name, stock_code}]


async def _load_corp_map() -> dict[str, list[dict]]:
    """DART 전체 회사코드 XML 다운로드 및 파싱 (최초 1회)"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(CORP_CODE_URL, params={"crtfc_key": DART_API_KEY})
        r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        xml_bytes = z.read(z.namelist()[0])

    root = ET.fromstring(xml_bytes)
    corp_map: dict[str, list[dict]] = {}

    for item in root.findall("list"):
        corp_code = (item.findtext("corp_code") or "").strip()
        corp_name = (item.findtext("corp_name") or "").strip()
        stock_code = (item.findtext("stock_code") or "").strip()

        if not corp_code or not corp_name:
            continue

        entry = {"corp_code": corp_code, "corp_name": corp_name, "stock_code": stock_code}
        corp_map.setdefault(corp_name, []).append(entry)

    return corp_map


async def find_corp_codes(query: str) -> list[dict]:
    """회사명으로 corp_code 목록 반환 (부분 일치, 정확도순 정렬)"""
    global _corp_map
    if _corp_map is None:
        _corp_map = await _load_corp_map()

    query_lower = query.lower()
    matches = [
        entry
        for name, entries in _corp_map.items()
        if query_lower in name.lower()
        for entry in entries
        if entry.get("stock_code")  # 상장사만
    ]
    # 이름 길이 기준 정렬: 짧을수록 검색어와 더 정확히 일치
    matches.sort(key=lambda e: len(e["corp_name"]))
    return matches[:30]
