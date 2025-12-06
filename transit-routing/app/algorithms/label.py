from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict
import math

EMPTY_FROZENSET = frozenset()


# slots=True => 파이썬 객체가 기본적으로 생성하는 딕셔너리를 방지,
# 클래스에 정의된 필드만을 위해 고정된 메모리 공간 사용
# 메모리 절감 및 빠른 접근, 동적 속성 추가 방지로 버그 방지
@dataclass(slots=True)
class Label:
    arrival_time: float
    transfers: int
    # 편의도, 혼잡도 => 누적합 활용 및 추후 평균 비교
    convenience_sum: float
    congestion_sum: float
    # 환승 난이도 => 최댓값(최악) 활용
    max_transfer_difficulty: float

    # Label class 경량화를 위한 새로운 필드
    # 부모 라벨을 가리키는 pointer
    parent_label: Optional["Label"]
    current_station_cd: str
    current_line: str
    current_direction: str
    # 방문한 역 저장
    # U턴 방지를 위해 frozenset 사용, Union 연산으로 효율적 생성 + 불변성 유지
    visited_stations: frozenset = field(default_factory=lambda: EMPTY_FROZENSET)
    # 동일한 부모 라벨로부터 여러 라벨 생성됨
    # 트리 구조와 유사 => depth를 기록하여 비교가 필요할 때를 판단, 역추적 활용
    depth: int = 1
    # transfer_context => transfer_info : 변수 이름 통일 _info
    transfer_info: Optional[Tuple[str, str, str]] = None  # station, from_line, to_line
    # 양방향 탐색이 필요할 경우(출발역, 환승 직후) 판단용
    is_first_move: bool = False
    created_round: int = 0

    @property
    def route_length(self) -> int:
        return self.depth

    @property
    def avg_convenience(self) -> float:
        """평균 편의도"""
        return self.convenience_sum / self.depth

    @property
    def avg_congestion(self) -> float:
        """평균 혼잡도"""
        return self.congestion_sum / self.depth

    # 중요!!! 역추적 로직!!!
    # leaf -> root 탐색하는 로직과 동일
    def reconstruct_route(
        self, line_stations: Dict = None, station_order_map: Dict = None
    ) -> List[str]:
        """
        전체 경로 역추적 + 중간역 포함

        Args:
            line_stations: McRaptor의 line_stations 맵 {(station_cd, line): {"up": [...], "down": [...]}}
            station_order_map: McRaptor의 station_order_map {(station_cd, line): order}

        Returns:
            완전한 역 순서 리스트 (중간역 포함)
        """
        # Phase 1 : 모든 라벨 수집 leaf -> root
        labels_path = []
        cur = self
        while cur is not None:
            labels_path.append(cur)
            cur = cur.parent_label
        labels_path = labels_path[::-1]  # root -> leaf

        # helper data가 없으면 원래 동작으로 fallback 하위 호환성을 위함
        if line_stations is None or station_order_map is None:
            return [label.current_station_cd for label in labels_path]

        # Phase 2 : 중간 역 포함한 완전한 경로 구축
        complete_route = []

        for i, label in enumerate(labels_path):
            if i == 0:
                # 출발지
                complete_route.append(label.current_station_cd)
                continue

            prev_label = labels_path[i - 1]
            curr_label = label

            # 환승인지 판단(노선 변화 감지)
            is_transfer = prev_label.current_line != curr_label.current_line

            if is_transfer:
                # 환승 : 현재 역만 추가 -> 같은 위치에 다른 station_cd일 수 있음
                # 중복 방지를 위해 station_cd가 다를 때만 추가
                if curr_label.current_station_cd != prev_label.current_station_cd:
                    complete_route.append(curr_label.current_station_cd)
            else:
                # 환승 X => 같은 노선 : 중간 역 채우기
                intermediates = _get_intermediate_stations(
                    prev_label.current_station_cd,
                    curr_label.current_station_cd,
                    curr_label.current_line,
                    curr_label.current_direction,
                    line_stations,
                    station_order_map,
                )
                # intermediates는 목적지 포함, 출발지 제외
                complete_route.extend(intermediates)
        return complete_route

    def reconstruct_lines(
        self, line_stations: Dict = None, station_order_map: Dict = None
    ) -> List[str]:
        """전체 노선 정보 재구성 -> route_sequence와 동이리 길이로 확장"""
        if line_stations is None or station_order_map is None:
            # 원래 동작 (하위 호환성을 위함)
            lines = []
            cur = self
            while cur is not None:
                lines.append(cur.current_line)
                cur = cur.parent_label
            return lines[::-1]

        # 중간 역 포함하여 구축
        labels_path = []
        cur = self
        while cur is not None:
            labels_path.append(cur)
            cur = cur.parent_label
        labels_path = labels_path[::-1]

        complete_lines = []

        for i, label in enumerate(labels_path):
            if i == 0:
                complete_lines.append(label.current_line)
                continue

            prev_label = labels_path[i - 1]
            curr_label = label

            is_transfer = prev_label.current_line != curr_label.current_line

            if is_transfer:
                if curr_label.current_station_cd != prev_label.current_station_cd:
                    complete_lines.append(curr_label.current_line)
            else:
                # 같은 노선: 중간 역 개수 세기
                intermediates = _get_intermediate_stations(
                    prev_label.current_station_cd,
                    curr_label.current_station_cd,
                    curr_label.current_line,
                    curr_label.current_direction,
                    line_stations,
                    station_order_map,
                )
                # 각 중간 역에 대해 노선 추가
                complete_lines.extend([curr_label.current_line] * len(intermediates))

        return complete_lines

    def reconstruct_transfer_info(self) -> List[Tuple[str, str, str]]:
        """환승 정보 재구성"""
        transfers = []
        cur = self
        while cur is not None:
            if cur.transfer_info is not None:
                transfers.append(cur.transfer_info)
            cur = cur.parent_label
        return transfers[::-1]

    def __eq__(self, other):
        if not isinstance(other, Label):
            return False
        return (
            self.current_station_cd == other.current_station_cd
            and self.current_line == other.current_line
            and self.transfers == other.transfers
        )

    # 해싱!!!
    def __hash__(self):
        return hash((self.current_station_cd, self.current_line, self.transfers))

    # epsilon 제거 => 단순 비교로 변경
    def dominates(self, other: "Label") -> bool:
        """파레토 우위 판단(단순 비교) 평균을 비교"""

        # 비교 대상이 아닌 라벨 => False
        if self.current_station_cd != other.current_station_cd:
            return False
        if self.current_line != other.current_line:
            return False
        # # 환승 횟수가 다르면 비교 생략 => 열등한 라벨 생존으로 이어질 수 있음
        if self.transfers != other.transfers:
            return False

        better_in_any = False

        # 최소화해야 하는 기준 -> 환승 횟수 소요 시간, 평균 혼잡도, 환승 난이도
        if self.transfers < other.transfers:
            better_in_any = True
        elif self.transfers > other.transfers:
            return False

        if self.max_transfer_difficulty < other.max_transfer_difficulty:
            better_in_any = True
        elif self.max_transfer_difficulty > other.max_transfer_difficulty:
            return False

        if self.arrival_time < other.arrival_time:
            better_in_any = True
        elif self.arrival_time > other.arrival_time:
            return False

        if self.avg_congestion < other.avg_congestion:
            better_in_any = True
        elif self.avg_congestion > other.avg_congestion:
            return False

        # 최대화해야 하는 기준 -> 편의도
        if self.avg_convenience > other.avg_convenience:
            better_in_any = True
        elif self.avg_convenience < other.avg_convenience:
            return False

        return better_in_any

    # 교통약자 유형별 가중치를 받아 최종 스코어(페널티)를 계산
    def calculate_weighted_score(self, weights: Dict[str, float]) -> float:
        """anp_weights가 계산한 가중치를 입력받아 스코어를 계산"""

        norm_time = min(self.arrival_time / 120.0, 1.0)  # 120분 기준
        norm_transfers = min(self.transfers / 4.0, 1.0)  # 4회 기준

        # 이미 정규화 적용된 값
        norm_difficulty = self.max_transfer_difficulty

        # 편의도는 높을 수록 좋으므로 역변환
        norm_convenience = 1.0 - (self.avg_convenience / 5.0)

        # 혼잡도 <- 1+ 가능
        norm_congestion = min(self.avg_congestion, 1.0)

        score = (
            weights.get("travel_time", 0.2) * norm_time
            + weights.get("transfers", 0.2) * norm_transfers
            + weights.get("transfer_difficulty", 0.2) * norm_difficulty
            + weights.get("convenience", 0.2) * norm_convenience
            + weights.get("congestion", 0.2) * norm_congestion
        )

        return score

    # epsilon-pruning 구현을 위한 정규화 벡터 반환
    def get_normalized_vector(self) -> List[float]:
        """
        cost vector를 정규화하여 반환[0,1]

        Returns:
            [norm_time, norm_transfers, norm_difficulty, norm_convenience, norm_congestion]
        """

        # travel_time => 90분을 기준으로 정규화, 서울 지하철 전체 횡단 시간 == 90분
        norm_time = self.arrival_time / 90.0

        # 환승 최대 3회로 정규화 => round 별로 변경하며 조정
        norm_transfers = self.transfers / 3.0

        # 환승 난이도 => 이미 정규화
        norm_difficulty = self.max_transfer_difficulty

        # 편의도 => 해당 벡터는 epsilon 공간을 계산하기 위함이므로 반전하지 않음
        # [0, 5] => [0, 1]
        norm_convenience = self.avg_convenience / 5.0

        # 혼잡도 : 1.3을 최대값으로 하여 정규화
        norm_congestion = self.avg_congestion / 1.3

        return [
            norm_time,
            norm_transfers,
            norm_difficulty,
            norm_convenience,
            norm_congestion,
        ]

    def weighted_distance(self, other: "Label", anp_weights: Dict[str, float]) -> float:
        """
        다른 라벨과의 가중 유클리드 거리 계산
        ANP 가중치를 사용하여 기준별 중요도 반영
        """

        v1 = self.get_normalized_vector()
        v2 = other.get_normalized_vector()

        criteria = [
            "travel_time",
            "transfers",
            "transfer_difficulty",
            "convenience",
            "congestion",
        ]

        diff_sq = 0.0
        for i, criterion in enumerate(criteria):
            weight = anp_weights.get(criterion, 0.2)
            diff = v1[i] - v2[i]

            diff_sq += weight * diff * diff

        return math.sqrt(diff_sq)

    def epsilon_similar(
        self, other: "Label", epsilon: float, anp_weights: Dict[str, float]
    ) -> bool:
        """다른 라벨과 epsilon 값 내에서 유사한지 판단"""

        distance = self.weighted_distance(other, anp_weights)
        return distance <= epsilon


def _get_intermediate_stations(
    from_station_cd: str,
    to_station_cd: str,
    line: str,
    direction: str,
    line_stations: Dict,
    station_order_map: Dict,
) -> List[str]:
    """
    [수정된 버전] 리스트 순회 대신 station_order(순서 번호)를 사용하여 수학적으로 중간 역을 계산합니다.
    """

    # 1. 출발역과 도착역의 순서(Order)를 가져옵니다.
    from_order = station_order_map.get((from_station_cd, line))
    to_order = station_order_map.get((to_station_cd, line))

    # 데이터가 없으면 도착역만 반환 (Fallback)
    if from_order is None or to_order is None:
        # [DEBUG] 로그: 순서 정보 누락
        print(
            f"[WARN] 순서 정보 없음: {from_station_cd}({from_order}) -> {to_station_cd}({to_order})"
        )
        return [to_station_cd]

    # 2. 순서 차이 계산
    # 예: 광화문(20) -> 군자(31) 이면 range(21, 32)
    start_idx = min(from_order, to_order)
    end_idx = max(from_order, to_order)

    # 3. 해당 범위에 있는 모든 역을 찾습니다. (DB가 완벽하므로 이 방식이 가장 안전함)
    # station_order_map = { (station_cd, line): order, ... } 구조라고 가정
    intermediate_candidates = []

    for (s_cd, s_line), s_order in station_order_map.items():
        # 같은 노선이고, 출발~도착 순서 사이에 있는 역만 추출
        if s_line == line and start_idx < s_order <= end_idx:
            intermediate_candidates.append((s_order, s_cd))

    # 4. 순서대로 정렬
    # 상행/하행 여부에 따라 정렬 순서를 결정합니다.
    # from_order < to_order 이면 정방향(오름차순), 반대면 역방향(내림차순)
    is_ascending = from_order < to_order
    intermediate_candidates.sort(key=lambda x: x[0], reverse=not is_ascending)

    # 5. 결과 추출 (역 코드만 리스트로 변환)
    result_stations = [code for order, code in intermediate_candidates]

    # [검증] 결과가 비어있다면, 5호선 갈림길 등의 문제로 범위가 꼬인 경우
    if not result_stations:
        print(
            f"[WARN] 중간역 탐색 실패 (범위 내 역 없음): {from_station_cd} -> {to_station_cd}"
        )
        return [to_station_cd]

    return result_stations
