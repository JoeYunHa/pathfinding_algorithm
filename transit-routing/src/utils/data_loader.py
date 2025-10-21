import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from pathlib import Path


class SubwayDataLoader:
    """지하철(1~9호선) 데이터 로더"""

    def __init__(self, data_dir: str = "data/raw"):
        self.data_dir = Path(data_dir)
        self.stations_df = None
        self.elevator_df = None
        self.escalator_df = None
        self.wheelchair_lift_df = None
        self.wheelchair_ramp_df = None
        self.transfer_stations_df = None  # 환승역만 따로 dataframe으로 저장
        self.graph = None

    def load_all_data(self):
        """전체 데이터 로드"""
        self.stations_df = pd.read_csv(self.data_dir / "final_subway_sorted.csv")
        self.elevator_df = pd.read_csv(self.data_dir / "elevator_processed.csv")
        self.escalator_df = pd.read_csv(self.data_dir / "escalator_processed.csv")
        self.wheelchair_lift_df = pd.read_csv(
            self.data_dir / "wheelchair_lift_processed.csv"
        )
        self.wheelchair_ramp_df = pd.read_csv(
            self.data_dir / "wheelchair_ramp_processed.csv"
        )
        self.transfer_stations_df = pd.read_csv(
            self.data_dir / "transfer_stations_final.csv"
        )
        # data 개수 확인용 출력
        print(f"stations: {len(self.stations_df)}")
        print(f"transfer_stations: {len(self.transfer_stations_df)}")
        print(f"elevator: {len(self.elevator_df)}")
        print(f"escalator: {len(self.escalator_df)}")
        print(f"wheelchair_lift: {len(self.wheelchair_lift_df)}")
        print(f"wheelchair_ramp: {len(self.wheelchair_ramp_df)}")

        return self

    def build_graph(self) -> Dict:
        """그래프 구조 생성"""
        if self.stations_df is None:
            raise ValueError("call load_all_data() first")

        graph = {"nodes": {}, "edges": [], "transfers": {}, "accessibility": {}}

        # node 생성 -> WGS84 좌표계 사용
        for _, row in self.stations_df.iterrows():
            station_id = row["station_id"]
            graph["nodes"][station_id] = {
                "name_k": row["station_name_k"],
                "name_e": row["station_name_e"],
                "line_id": row["line_id"],
                "line_num": row["line_num"],
                "x_coord": row["x_coord"], # 경도
                "y_coord": row["y_coord"], # 위도
                # tranfer_line_num과 express_info 모두 0이면 환승역/급행 정차역 아님
                "is_transfer": pd.notna(row["transfer_line_num"])
                and row["transfer_line_num"] > 0,
                "is_express": pd.notna(row["express_info"]) and row["express_info"] > 0,
            }

            # 편의시설 정보 추가
            # self._add_accessibility_info(graph)

            # edge 생성 -> 호선 연결
            # 시작역, 종착역의 경우 이전 역/다음 역이 본인의 station_id
            for _, row in self.stations_df.iterrows():
                station_id = row["station_id"]
                next_station = row["next_station_id"]
                prev_station = row["prev_station_id"]

                # type 변환, 시작역/종착역 처리
                if (
                    pd.notna(next_station)
                    and next_station > 0
                    and next_station != station_id
                ):
                    next_station = int(next_station)

                    # next_station이 존재하는지 확인
                    if next_station in graph["nodes"]:
                        # 거리 계산
                        curr_node = graph["nodes"][station_id]
                        next_node = graph["nodes"][next_station]

                        distance = np
