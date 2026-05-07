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


def _today() -> str:
    from datetime import date
    return date.today().strftime("%Y%m%d")


def _days_ago(days: int) -> str:
    from datetime import date, timedelta
    return (date.today() - timedelta(days=days)).strftime("%Y%m%d")
