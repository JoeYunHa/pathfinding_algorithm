from typing import List, Dict, Set, Tuple
from dataclasses import dataclass, field


# label class와 mc_raptor 분리
# @property annotation 사용 <- 메서드를 변수처럼 접근, 캡슐화, 내부 데이터를 노출하지 않고 계산한 값을 노출할 수 있음
# like C++ getter
@dataclass
class Label:
    """경로 라벨 (파레토 최적해) <- 누적 합 방식 적용"""

    arrival_time: float  # 총 소요시간 (분)
    transfers: int  # 환승 횟수
    # 누적합으로 변경!!!
    # 중요!!! -> 환승 난이도는 평균보다 가장 난이도가 높은 것을 비교하는 게 더 중요, 합리적
    # 환승역들의 난이도를 list로 저장
    transfer_difficulty_list: List[float] = field(default_factory=list)
    convenience_sum: float  # 편의도 누적합!!!
    congestion_sum: float  # 혼잡도 누적합!!!
    route: List[str] = field(
        default_factory=list
    )  # 경로를 지나가는 역의 정보 station_cd
    lines: List[str] = field(default_factory=list)  # 역들의 호선 정보 -> 환승 횟수 계산
    transfer_context: List[Tuple[str, str, str]] = field(
        default_factory=list
    )  # 환승 상세정보 제공을 위한 (station_cd, from_line, to_line)
    created_round: int = 0  # 라벨이 생성된 라운드

    @property
    def route_length(self) -> int:
        """경로의 역 개수"""
        return max(1, len(self.route))

    @property
    def avg_convenience(self) -> float:
        """평균 편의도 <- 평가 시에만 사용"""
        return self.convenience_sum / self.route_length

    @property
    def avg_congestion(self) -> float:
        """평균 혼잡도 <- 평가 시에만 사용"""
        return self.congestion_sum / self.route_length

    @property
    def max_transfer_difficulty(self) -> float:
        """경로 내 최악(최대) 환승 난이도"""
        return max(self.transfer_difficulty_list, default=0.0)

    def dominates(self, other: "Label") -> bool:
        """
        파레토 우위 판단 (5개 기준)
        - 환승 난이도는 최악값으로 비교
        - 나머지는 평균으로 비교
        Returns:
            True if self가 other를 지배함
        """
        better_in_one = False

        criteria = [
            (self.arrival_time, other.arrival_time, False),  # 최소화
            (self.transfers, other.transfers, False),  # 최소화
            (
                self.max_transfer_difficulty,
                other.max_transfer_difficulty,
                False,
            ),  # 최댓값 역시 낮을 수록 좋음
            (self.avg_convenience, other.avg_convenience, True),  # 최대화
            (self.avg_congestion, other.avg_congestion, False),  # 최소화
        ]

        for self_val, other_val, maximize in criteria:
            if maximize:  # 최대화
                if self_val < other_val:
                    return False
                elif self_val > other_val:
                    better_in_one = True
            else:  # 최소화
                if self_val > other_val:
                    return False
                elif self_val < other_val:
                    better_in_one = True

        return better_in_one

    def calculate_weighted_score(self, anp_weights: Dict[str, float]) -> float:
        """
        ANP 가중치를 적용한 종합 점수(페널티) 계산(환승 난이도는 최악값 기준)
        """
        # 정규화 (0-1 범위)
        norm_time = min(self.arrival_time / 120.0, 1.0)  # 120분 기준
        norm_transfers = min(self.transfers / 4.0, 1.0)  # 4회 기준

        # 최악 환승 난이도를 기준으로 비교 <- 이미 정규화된 값이므로 정규화 생략
        norm_difficulty = self.max_transfer_difficulty

        # 편의도: 5점 만점을 0-1로 변환 (높을수록 좋으므로 역변환)
        norm_convenience = 1.0 - (self.convenience_score / 5.0)

        # 혼잡도: 이미 0-1 범위
        norm_congestion = min(self.congestion_score, 1.0)

        # 가중 합산
        score = (
            anp_weights.get("travel_time", 0.2) * norm_time
            + anp_weights.get("transfers", 0.2) * norm_transfers
            + anp_weights.get("transfer_difficulty", 0.2) * norm_difficulty
            + anp_weights.get("convenience", 0.2) * norm_convenience
            + anp_weights.get("congestion", 0.2) * norm_congestion
        )

        return score

    def __eq__(self, other: "Label") -> bool:
        """라벨 동등성 검사 (경로 비교)"""
        if not isinstance(other, Label):
            return False
        # 환승 컨텍스트도 동등 비교에 포함 -> 기준 강화
        return self.route == other.route and tuple(self.transfer_context) == tuple(
            other.transfer_context
        )

    def __hash__(self) -> int:
        """해시 함수 (Set에서 사용)"""
        return hash((tuple(self.route), tuple(self.transfer_context)))
