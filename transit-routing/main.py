from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import logging

# 환경변수 로드
load_dotenv()

from label import Label
from mc_raptor import McRaptor
from anp_weights import ANPWeightCalculator
from database import (
    get_all_stations,
    get_station_by_code,
)
from config import (
    DISABILITY_TYPES,
    DEFAULT_TRANSFER_DISTANCE,
    WALKING_SPEED,
    CONGESTION_CONFIG
)

# logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 전역 변수
raptor_instance: Optional[McRaptor] = None
anp_calculator: Optional[ANPWeightCalculator] = None

# 장애 유형별 선호 편의시설 매핑 => 추후 db 구축 후에 로직 변경 + 구현 예정
# PREFERRED_FACILITIES = {
#     "PHY": ["elevator", "wheelchair_ramp", "wheelchair_lift"],
#     "VIS": ["braille_block", "voice_guide", "screen_door"],
#     "AUD": ["visual_display", "screen_door"],
#     "ELD": ["elevator", "escalator", "rest_area"],
# }

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global raptor_instance, anp_calculator

    try:
        logger.info("서버 시작: 데이터 로딩 중...")

        # database connection pool 초기화
        from database import initialize_pool

        initialize_pool()
        logger.info("database connection pool 초기화 완료")

        # anp_calculator 초기화 + 혼잡도 데이터 로드
        anp_calculator = ANPWeightCalculator()
        logger.info("ANP Calculator 초기화 완료")

        # McRaptor 초기화 (내부적으로 데이터 로드)
        raptor_instance = McRaptor()
        logger.info("RAPTOR 초기화 완료")

    except Exception as e:
        logger.error(f"초기화 실패: {e}")
        raise

    yield

    # Shutdown 전에
    from database import close_pool

    close_pool()
    logger.info("Database connection pool 종료")
    logger.info("서버 종료")


app = FastAPI(title="KindMap API", version="3.0.0", lifespan=lifespan)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Pydantic Models ====================

class RouteRequest(BaseModel):
    """경로 탐색 요청 모델"""
    origin: str  # 출발지 역명 또는 역 코드
    destination: str  # 도착지 역명 또는 역 코드
    origin_line: Optional[str] = None  # 출발지 노선 (역명인 경우 필수)
    destination_line: Optional[str] = None  # 도착지 노선 (역명인 경우 필수)
    departure_time: Optional[str] = None  # ISO 형식 (예: "2024-03-15T09:00:00")
    disability_type: str = "PHY"  # PHY, VIS, AUD, ELD
    max_rounds: int = 5  # 최대 환승 횟수 + 1


class TransferInfo(BaseModel):
    """환승 정보 모델"""
    station_cd: str
    station_name: str
    from_line: str
    to_line: str


class RouteResponse(BaseModel):
    """단일 경로 응답 모델"""
    route: List[str]  # 역 코드 리스트
    route_names: List[str]  # 역 이름 리스트
    lines: List[str]  # 노선 리스트
    arrival_time: float  # 총 도착 시간 (분)
    transfers: int  # 환승 횟수
    transfer_info: List[TransferInfo]  # 환승 정보
    convenience_score: float  # 평균 편의성 점수
    congestion_score: float  # 평균 혼잡도 점수
    max_transfer_difficulty: float  # 최대 환승 난이도
    route_length: int  # 경로 길이 (역 개수)
    weighted_penalty: float  # 가중치 기반 패널티 점수
    rank: int  # 순위


class RoutesResponse(BaseModel):
    """경로 탐색 응답 모델"""
    success: bool
    routes: List[RouteResponse]
    total_routes: int
    disability_type: str
    departure_time: str
    computation_time: float  # 계산 시간 (초)


class StationInfo(BaseModel):
    """역 정보 모델"""
    station_cd: str
    station_name: str
    line: str
    lat: Optional[float] = None
    lng: Optional[float] = None


class ErrorResponse(BaseModel):
    """에러 응답 모델"""
    success: bool = False
    error: str
    detail: Optional[str] = None


# ==================== Utility Functions ====================

def label_to_dict(label: Label, rank: int, disability_type: str) -> Dict[str, Any]:
    """Label 객체를 딕셔너리로 변환"""
    route_cds = label.reconstruct_route()
    lines = label.reconstruct_lines()
    transfer_info_list = label.reconstruct_transfer_info()

    # 역 이름 가져오기
    route_names = []
    for station_cd in route_cds:
        station = get_station_by_code(station_cd)
        if station:
            route_names.append(station['name'])
        else:
            route_names.append(station_cd)

    # 환승 정보 변환
    transfers_formatted = []
    for station_cd, from_line, to_line in transfer_info_list:
        station = get_station_by_code(station_cd)
        transfers_formatted.append({
            "station_cd": station_cd,
            "station_name": station['name'] if station else station_cd,
            "from_line": from_line,
            "to_line": to_line
        })

    # ANP 가중치 기반 패널티 계산
    weights = anp_calculator.calculate_weights(disability_type)
    weighted_penalty = label.calculate_weighted_score(weights)

    return {
        "route": route_cds,
        "route_names": route_names,
        "lines": lines,
        "arrival_time": round(label.arrival_time, 2),
        "transfers": label.transfers,
        "transfer_info": transfers_formatted,
        "convenience_score": round(label.avg_convenience, 3),
        "congestion_score": round(label.avg_congestion, 3),
        "max_transfer_difficulty": round(label.max_transfer_difficulty, 3),
        "route_length": label.route_length,
        "weighted_penalty": round(weighted_penalty, 3),
        "rank": rank
    }


def parse_departure_time(time_str: Optional[str]) -> datetime:
    """출발 시간 파싱"""
    if not time_str:
        return datetime.now()

    try:
        return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
    except ValueError:
        logger.warning(f"Invalid datetime format: {time_str}, using current time")
        return datetime.now()


def validate_disability_type(disability_type: str) -> str:
    """장애 유형 검증"""
    disability_type = disability_type.upper()
    if disability_type not in DISABILITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid disability type. Must be one of: {', '.join(DISABILITY_TYPES)}"
        )
    return disability_type


def get_station_cd(identifier: str, line: Optional[str] = None) -> str:
    """역명 또는 역 코드를 역 코드로 변환"""
    # 이미 역 코드 형식인지 확인 (예: "0150" 형식)
    if identifier.isdigit() and len(identifier) == 4:
        station = get_station_by_code(identifier)
        if station:
            return identifier

    # 역명으로 검색
    if line and raptor_instance:
        station_cd = raptor_instance._get_station_cd_by_name(identifier, line)
        if station_cd:
            return station_cd

    # 역을 찾지 못한 경우
    raise HTTPException(
        status_code=404,
        detail=f"Station not found: {identifier}" + (f" on line {line}" if line else "")
    )


# ==================== API Endpoints ====================

@app.get("/", tags=["Health"])
async def root():
    """API 루트 엔드포인트"""
    return {
        "service": "KindMap API",
        "version": "3.0.0",
        "status": "running",
        "description": "Multi-Criteria Transit Routing API for Accessibility"
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "raptor_initialized": raptor_instance is not None,
        "anp_calculator_initialized": anp_calculator is not None
    }


@app.post("/route", response_model=RoutesResponse, tags=["Routing"])
async def find_route(request: RouteRequest):
    """
    경로 탐색 엔드포인트

    - **origin**: 출발지 역명 또는 역 코드
    - **destination**: 도착지 역명 또는 역 코드
    - **origin_line**: 출발지 노선 (역명인 경우 필수)
    - **destination_line**: 도착지 노선 (역명인 경우 필수)
    - **departure_time**: 출발 시간 (ISO 형식, 생략시 현재 시간)
    - **disability_type**: 장애 유형 (PHY/VIS/AUD/ELD, 기본값: PHY)
    - **max_rounds**: 최대 라운드 수 (기본값: 5)
    """
    import time
    start_time = time.time()

    try:
        # 초기화 확인
        if not raptor_instance or not anp_calculator:
            raise HTTPException(
                status_code=503,
                detail="Service not ready. Please try again later."
            )

        # 입력 검증
        disability_type = validate_disability_type(request.disability_type)
        departure_time = parse_departure_time(request.departure_time)

        # 역 코드 변환
        origin_cd = get_station_cd(request.origin, request.origin_line)
        destination_cd = get_station_cd(request.destination, request.destination_line)

        logger.info(
            f"Route search: {origin_cd} -> {destination_cd}, "
            f"disability: {disability_type}, time: {departure_time}"
        )

        # 경로 탐색
        routes = raptor_instance.find_routes(
            origin_cd=origin_cd,
            destination_cd_set={destination_cd},
            departure_time=departure_time,
            disability_type=disability_type,
            max_rounds=request.max_rounds
        )

        if not routes:
            logger.info(f"No routes found: {origin_cd} -> {destination_cd}")
            return RoutesResponse(
                success=True,
                routes=[],
                total_routes=0,
                disability_type=disability_type,
                departure_time=departure_time.isoformat(),
                computation_time=round(time.time() - start_time, 3)
            )

        # 경로 순위화
        ranked_routes = raptor_instance.rank_routes(routes, disability_type)

        # 응답 생성
        route_responses = []
        for rank, (label, penalty) in enumerate(ranked_routes, start=1):
            route_dict = label_to_dict(label, rank, disability_type)
            route_responses.append(RouteResponse(**route_dict))

        computation_time = time.time() - start_time
        logger.info(
            f"Found {len(route_responses)} routes in {computation_time:.3f}s"
        )

        return RoutesResponse(
            success=True,
            routes=route_responses,
            total_routes=len(route_responses),
            disability_type=disability_type,
            departure_time=departure_time.isoformat(),
            computation_time=round(computation_time, 3)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Route search error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.get("/stations", response_model=List[StationInfo], tags=["Stations"])
async def get_stations(line: Optional[str] = None):
    """
    역 목록 조회

    - **line**: 노선 필터 (선택사항)
    """
    try:
        stations = get_all_stations(line=line)

        station_list = []
        for station in stations:
            station_list.append(StationInfo(
                station_cd=station['station_cd'],
                station_name=station['name'],
                line=station['line'],
                lat=station.get('lat'),
                lng=station.get('lng')
            ))

        return station_list

    except Exception as e:
        logger.error(f"Error fetching stations: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch stations: {str(e)}"
        )


@app.get("/stations/{station_cd}", response_model=StationInfo, tags=["Stations"])
async def get_station(station_cd: str):
    """
    특정 역 정보 조회

    - **station_cd**: 역 코드
    """
    try:
        station = get_station_by_code(station_cd)

        if not station:
            raise HTTPException(
                status_code=404,
                detail=f"Station not found: {station_cd}"
            )

        return StationInfo(
            station_cd=station['station_cd'],
            station_name=station['name'],
            line=station['line'],
            lat=station.get('lat'),
            lng=station.get('lng')
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching station {station_cd}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch station: {str(e)}"
        )


@app.get("/disability-types", tags=["Configuration"])
async def get_disability_types():
    """
    지원하는 장애 유형 목록 조회
    """
    return {
        "disability_types": DISABILITY_TYPES,
        "descriptions": {
            "PHY": "Physical disability (wheelchair users)",
            "VIS": "Visual impairment",
            "AUD": "Hearing impairment",
            "ELD": "Elderly"
        }
    }


@app.get("/anp-weights/{disability_type}", tags=["Configuration"])
async def get_anp_weights(disability_type: str):
    """
    특정 장애 유형의 ANP 가중치 조회

    - **disability_type**: 장애 유형 (PHY/VIS/AUD/ELD)
    """
    try:
        disability_type = validate_disability_type(disability_type)

        if not anp_calculator:
            raise HTTPException(
                status_code=503,
                detail="ANP calculator not initialized"
            )

        weights = anp_calculator.calculate_weights(disability_type)

        return {
            "disability_type": disability_type,
            "weights": weights,
            "criteria": list(weights.keys())
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating ANP weights: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to calculate weights: {str(e)}"
        )


# ==================== Error Handlers ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """HTTP 예외 핸들러"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.detail,
            "status_code": exc.status_code
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """일반 예외 핸들러"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "detail": str(exc)
        }
    )

