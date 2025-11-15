from typing import List, Optional, Tuple
from pydantic import BaseModel, Field

# service 별 응답 구조 정의

# 경로 찾기 응답
class RouteCalculatedResponse(BaseModel):
    route_id: str = Field(..., description="경로 ID")
    origin: str = Field(..., description="출발지")
    destination: str = Field(..., description="목적지")
    route_sequence: List[str] = Field(..., description="역 코드 순서")
    route_lines: List[str] = Field(..., description="노선 순서")
    total_time: float = Field(..., description="총 소요시간 (분)")
    transfers: int = Field(..., description="환승 횟수")
    transfer_stations: List[str] = Field(..., description="환승역 코드 리스트")
    transfer_info: List[Tuple[str, str, str]] = Field(..., description="환승 상세 정보")

# 경로 안내 응답
class NavigationUpdateResponse(BaseModel):
    current_station: str = Field(..., description="현재 역 코드")
    current_station_name: str = Field(..., description="현재 역 이름")
    next_station: Optional[str] = Field(None, description="다음 역 코드")
    next_station_name: Optional[str] = Field(None, description="다음 역 이름")
    distance_to_next: Optional[float] = Field(None, description="다음 역까지 거리 (미터)")
    remaining_stations: int = Field(..., description="남은 역 수")
    is_transfer: bool = Field(default=False, description="환승역 여부")
    transfer_to_line: Optional[str] = Field(None, description="환승 노선")
    message: str = Field(..., description="안내 메시지")
    progress_percent: int = Field(..., description="진행률 (%)")

# 에러 응답
class ErrorResponse(BaseModel):
    error: str = Field(..., description="에러 메시지")
    code: Optional[str] = Field(None, description="에러 코드")