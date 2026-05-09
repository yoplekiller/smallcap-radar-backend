import httpx
import os
from dotenv import load_dotenv

load_dotenv()

DART_API_KEY = os.getenv("DART_API_KEY")
DART_BASE_URL = "https://opendart.fss.or.kr/api"


async def fetch_recent_disclosures(days: int = 1) -> list[dict]:
    """최근 N일 공시 전체 목록 조회 (페이지네이션 자동 처리)"""
    all_items = []
    page = 1

    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                f"{DART_BASE_URL}/list.json",
                params={
                    "crtfc_key": DART_API_KEY,
                    "bgn_de": _days_ago(days),
                    "end_de": _today(), 
                    "last_reprt_at": "N",
                    "page_no": page,
                    "page_count": 100,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "000":
                break

            items = data.get("list", [])
            all_items.extend(items)

            total_count = int(data.get("total_count", 0))
            if len(all_items) >= total_count or len(items) < 100:
                break

            page += 1

    return all_items


async def search_disclosures(corp_name: str, days: int = 30) -> list[dict]:
    """회사명으로 공시 검색 (corp_code 조회 → 공시 조회 병렬)"""
    from app.services.corp_code_service import find_corp_codes

    corp_list = await find_corp_codes(corp_name)
    if not corp_list:
        return []

    async with httpx.AsyncClient(timeout=10) as client:
        import asyncio

        async def fetch_for_corp(corp: dict) -> list[dict]:
            r = await client.get(
                f"{DART_BASE_URL}/list.json",
                params={
                    "crtfc_key": DART_API_KEY,
                    "corp_code": corp["corp_code"],
                    "bgn_de": _days_ago(days),
                    "end_de": _today(),
                    "last_reprt_at": "N",
                    "page_no": 1,
                    "page_count": 100,
                },
            )
            r.raise_for_status()
            data = r.json()
            return data.get("list", []) if data.get("status") == "000" else []

        results = await asyncio.gather(*[fetch_for_corp(c) for c in corp_list])

    merged = [item for sublist in results for item in sublist]
    merged.sort(key=lambda x: x.get("rcept_dt", ""), reverse=True)
    return merged


async def fetch_disclosure_detail(rcept_no: str) -> dict:
    """공시 상세 내용 조회"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DART_BASE_URL}/document.json",
            params={
                "crtfc_key": DART_API_KEY,
                "rcept_no": rcept_no,
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()


async def fetch_company_info(corp_code: str) -> dict:
    """기업 기본 정보 조회 (시총 확인용)"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DART_BASE_URL}/company.json",
            params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "000":
            raise ValueError(f"DART API 오류: {data.get('message')}")

        return data


def _guess_report_period(rcept_dt: str) -> tuple[str, str]:
    """공시 접수일 기준 사업연도/보고서코드 추정 (영업실적 공시용)

    DART reprt_code:
      11011 = 사업보고서(연간), 11013 = 1분기, 11012 = 반기, 11014 = 3분기
    """
    year = int(rcept_dt[:4])
    month = int(rcept_dt[4:6])
    if month <= 4:
        return str(year - 1), "11011"
    elif month <= 6:
        return str(year), "11013"
    elif month <= 9:
        return str(year), "11012"
    else:
        return str(year), "11014"


async def fetch_earnings_disclosures(days: int = 30) -> list[dict]:
    """영업실적 공시만 조회 (거래소공시 유형 + '실적' 키워드 필터, max 500건)"""
    all_items = []
    page = 1
    MAX_PAGES = 5

    async with httpx.AsyncClient() as client:
        while page <= MAX_PAGES:
            response = await client.get(
                f"{DART_BASE_URL}/list.json",
                params={
                    "crtfc_key": DART_API_KEY,
                    "bgn_de": _days_ago(days),
                    "end_de": _today(),
                    "last_reprt_at": "N",
                    "pblntf_ty": "I",
                    "page_no": page,
                    "page_count": 100,
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "000":
                break

            items = [
                item for item in data.get("list", [])
                if "실적" in item.get("report_nm", "")
            ]
            all_items.extend(items)

            raw_items = data.get("list", [])
            total_count = int(data.get("total_count", 0))
            if len(all_items) >= total_count or len(raw_items) < 100:
                break

            page += 1

    return all_items


async def fetch_operating_profit(corp_code: str, rcept_dt: str) -> dict | None:
    """영업이익 전년동기 비교 데이터 조회 (DART 단일회사 주요계정 API)"""
    bsns_year, reprt_code = _guess_report_period(rcept_dt)

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{DART_BASE_URL}/fnlttSinglAcnt.json",
            params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
            },
        )
        response.raise_for_status()
        data = response.json()

    if data.get("status") != "000":
        return None

    for item in data.get("list", []):
        if "영업이익" in item.get("account_nm", ""):
            return {
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "account_nm": item.get("account_nm", ""),
                "current": item.get("thstrm_amount", ""),
                "previous": item.get("frmtrm_amount", ""),
            }

    return None


def _today() -> str:
    from datetime import date
    return date.today().strftime("%Y%m%d")


def _days_ago(days: int) -> str:
    from datetime import date, timedelta
    return (date.today() - timedelta(days=days)).strftime("%Y%m%d")
