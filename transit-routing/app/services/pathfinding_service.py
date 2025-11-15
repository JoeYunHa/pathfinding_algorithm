# 경로 찾기 서비스

import logging
from datetime import datetime
from typing import Optional, Dict, Any

from app.db.database import get_all_stations, get_station_cd_by_name
from app.algorithms.mc_raptor import McRaptor
from app.core.exceptions import RouteNotFoundException, StationNotFoundException

logger = logging.getLogger(__name__)

class PathfindingService:

    def __init__(self):
        self.stations_list = get_all_stations()
        self.stations = 
    
    def claculate_route(
            self,
            origin_name: str,
            destination_name: str,
            disability_type: str
    ) -> Optional[Dict[str, Any]]:
        try:
            # DB의 쿼리 함수 사용
            origin_cd = get_station_cd_by_name(origin_name)
            destination_cd = get_station_cd_by_name(destination_name)

            if not origin_cd:
                raise StationNotFoundException(f"출발지 역을 찾을 수 없습니다: {origin_name}")
            
            if not destination_cd:
                raise StationNotFoundException(f"목적지 역을 찾을 수 없습니다: {destination_name}")
            
            departure_time = datetime.now()

            routes = self.
            
