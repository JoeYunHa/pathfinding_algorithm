import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import logging

# 프로젝트 루트 경로 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

load_dotenv()

from database import (
    initialize_pool,
    close_pool,
    get_all_stations,
    get_all_sections,
    get_all_transfer_station_conv_scores,
)
from mc_raptor import McRaptor
from anp_weights import ANPWeightCalculator
from config import DISABILITY_TYPES

# 로깅 설정
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_routing_direct():
    """서버 없이 직접 경로 탐색 테스트"""

    logger.info("\n" + "=" * 80)
    logger.info("경로 탐색 직접 테스트 (서버 불필요)")
    logger.info("=" * 80)

    try:
        # 1. DB 연결 초기화
        logger.info("\n[1/6] DB 연결 초기화...")
        initialize_pool()
        logger.info("✓ DB 연결 완료")

        # 2. 데이터 로드
        logger.info("\n[2/6] 데이터 로딩...")
        stations = get_all_stations()
        sections = get_all_sections()
        convenience_scores = get_all_transfer_station_conv_scores()

        logger.info(f"✓ 역 정보: {len(stations)}개")
        logger.info(f"✓ 구간 정보: {len(sections)}개")
        logger.info(f"✓ 편의성 점수: {len(convenience_scores)}개")

        # 3. ANP 계산기 초기화
        logger.info("\n[3/6] ANP 계산기 초기화...")
        anp_calculator = ANPWeightCalculator()
        logger.info("✓ ANP 계산기 초기화 완료")

        # 4. McRaptor 초기화
        logger.info("\n[4/6] McRaptor 초기화...")
        mc_raptor = McRaptor(
            stations=stations,
            sections=sections,
            convenience_scores=convenience_scores,
            anp_calculator=anp_calculator,
        )
        logger.info(f"✓ 그래프 노드: {len(mc_raptor.graph)}개")

        # 5. 테스트 케이스 정의
        test_cases = [
            ("광화문", "남성", "PHY"),
            ("충무로", "동묘앞", "VIS"),
            ("구반포", "서울", "AUD"),
            ("청구", "숙대입구", "ELD"),
        ]

        logger.info("\n[5/6] 경로 탐색 테스트 시작")
        logger.info("=" * 80)

        success_count = 0
        fail_count = 0

        # 6. 각 테스트 케이스 실행
        for idx, (origin, destination, disability_type) in enumerate(test_cases, 1):
            logger.info(
                f"\n[테스트 {idx}/{len(test_cases)}] {origin} → {destination} ({disability_type})"
            )
            logger.info("-" * 60)

            try:
                # 출발 시각 설정 (오전 9시)
                departure_time = datetime.now().replace(
                    hour=9, minute=0, second=0, microsecond=0
                )

                # 경로 탐색
                routes = mc_raptor.find_routes(
                    origin=origin,
                    destination=destination,
                    departure_time=departure_time,
                    disability_type=disability_type,
                    max_rounds=4,
                )

                if routes:
                    logger.info(f"✓ 찾은 경로: {len(routes)}개")

                    # 경로 순위 매기기
                    ranked_routes = mc_raptor.rank_routes(routes, disability_type)

                    # 상위 3개 경로 출력
                    for rank, (route, score) in enumerate(ranked_routes[:3], 1):
                        logger.info(f"\n  [순위 {rank}] 점수: {score:.4f}")
                        logger.info(f"    소요시간: {route.arrival_time:.1f}분")
                        logger.info(f"    환승횟수: {route.transfers}회")
                        logger.info(f"    환승난이도: {route.transfer_difficulty:.2f}")
                        logger.info(f"    편의도: {route.convenience_score:.2f}/5.0")
                        logger.info(f"    혼잡도: {route.congestion_score:.2f}")
                        logger.info(f"    경로: {' → '.join(route.route)}")
                        if route.transfer_stations:
                            logger.info(
                                f"    환승역: {', '.join(route.transfer_stations)}"
                            )

                    success_count += 1
                else:
                    logger.warning("✗ 경로를 찾지 못했습니다")
                    fail_count += 1

            except Exception as e:
                logger.error(f"✗ 오류 발생: {e}")
                logger.exception("상세 에러:")
                fail_count += 1

        # 7. 결과 요약
        logger.info("\n" + "=" * 80)
        logger.info("[6/6] 테스트 완료")
        logger.info(f"성공: {success_count}/{len(test_cases)}")
        logger.info(f"실패: {fail_count}/{len(test_cases)}")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"초기화 오류: {e}")
        logger.exception("상세 에러:")

    finally:
        # DB 연결 종료
        logger.info("\nDB 연결 종료...")
        close_pool()
        logger.info("✓ 정리 완료")


if __name__ == "__main__":
    test_routing_direct()
