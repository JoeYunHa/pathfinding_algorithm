import pytest
import logging
import time
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import memory_profiler  # (요청사항 4)
import tracemalloc
from typing import Set

# --- 로깅 설정 (pytest.ini와 연동) ---
log = logging.getLogger(__name__)

# --- [!!! 핵심 수정 !!!] ---
# 'profile'은 'mprof run'으로 실행할 때만 builtins에 주입됩니다.
# pytest가 NameError를 일으키지 않도록 더미 데코레이터를 정의합니다.
try:
    # 'mprof run'으로 실행 중인지 확인
    profile
except NameError:
    # pytest로 실행 중일 때: 'profile'을 아무것도 안 하는 함수로 정의
    def profile(func):
        return func
# --- [!!! 수정 끝 !!!] ---


# --- 프로젝트 경로 설정 ---
# (테스트 파일이 프로젝트 루트/test/ 폴더에 있다고 가정)
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    sys.path.insert(0, parent_dir)

    # .env 파일 로드 (DB_CONFIG 위함)
    load_dotenv(os.path.join(parent_dir, ".env"))

    from database import initialize_pool, close_pool
    from mc_raptor import McRaptor
    from label import Label
except ImportError as e:
    print(f"ImportError: {e}. 경로 및 .env 설정을 확인하세요.")
    sys.exit(1)


# --- 테스트 케이스 정의 ---
TEST_CASES = [
    {
        "name": "광화문 -> 남성 (PHY)",
        "origin": "2534", # 5호선 광화문
        "destinations": {"2739"}, # 7호선 남성
        "disability_type": "PHY",
    },
    {
        "name": "충무로 -> 동묘앞 (VIS)",
        "origin": "0321", # 3호선 충무로 (4호선 '0423'도 가능)
        "destinations": {"0159", "2637"}, # 1호선, 6호선 동묘앞
        "disability_type": "VIS",
    },
    {
        "name": "구반포 -> 서울역 (AUD)",
        "origin": "2920", # 9호선 구반포
        "destinations": {"0150", "0426", "A01", "P313"}, # 1, 4, 공항, 경의중앙
        "disability_type": "AUD",
    },
    {
        "name": "청구 -> 숙대입구 (ELD)",
        "origin": "2537", # 5호선 청구 (6호선 '2637'도 가능)
        "destinations": {"0427"}, # 4호선 숙대입구
        "disability_type": "ELD",
    },
]

# --- Pytest Fixture (테스트 환경 설정) ---

@pytest.fixture(scope="module")
def raptor_instance():
    """
    테스트 모듈 전체에서 McRaptor 인스턴스를 한 번만 초기화.
    (DB 연결 포함)
    """
    log.info("--- Pytest Fixture: DB 풀 및 McRaptor 초기화 시작 ---")
    start_time = time.time()
    initialize_pool()
    instance = McRaptor() # __init__에서 모든 데이터를 로드
    init_time = time.time() - start_time
    log.info(f"--- Pytest Fixture: McRaptor 초기화 완료 ({init_time:.2f}초) ---")
    
    yield instance # 테스트 실행
    
    # --- 테스트 종료 후 실행 ---
    log.info("--- Pytest Fixture: DB 풀 종료 ---")
    close_pool()

# --- Pytest 테스트 함수 ---

@pytest.mark.parametrize("case", TEST_CASES)
def test_find_route_correctness(raptor_instance: McRaptor, case: dict):
    """
    (요청사항 2) 경로 찾기 기능이 올바르게 동작하는지 (경로를 1개 이상 찾는지) 확인
    """
    log.info(f"--- [테스트 시작] 경로 탐색: {case['name']} ---")
    departure_time = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    
    routes = raptor_instance.find_routes(
        origin_cd=case["origin"],
        destination_cd_set=case["destinations"],
        departure_time=departure_time,
        disability_type=case["disability_type"],
        max_rounds=5, # 최대 4회 환승
    )
    
    assert routes is not None
    assert len(routes) > 0, "경로를 찾지 못했습니다 (0개 반환)."
    log.info(f"[테스트 통과] {case['name']}: {len(routes)}개 파레토 최적 경로 발견")

    # (선택) 상위 1개 경로 정보 로깅
    ranked_routes = raptor_instance.rank_routes(routes, case["disability_type"])
    if ranked_routes:
        top_route, top_score = ranked_routes[0]
        log.info(f"  [상위 1위] Score: {top_score:.4f}, Time: {top_route.arrival_time:.1f}분, Transfers: {top_route.transfers}회")
        log.info(f"  [상위 1위] MaxDifficulty: {top_route.max_transfer_difficulty:.2f}, AvgConvenience: {top_route.avg_convenience:.2f}, AvgCongestion: {top_route.avg_congestion:.2f}")
        
        # [수정] '출발역 -> 환승역 -> 도착역' 형식으로 경로 재구성
        path_cds = top_route.reconstruct_route()
        start_name = raptor_instance.stations.get(path_cds[0], {}).get("station_name", path_cds[0])
        end_name = raptor_instance.stations.get(path_cds[-1], {}).get("station_name", path_cds[-1])
        
        transfers = top_route.reconstruct_transfer_context()
        transfer_names_list = [
            raptor_instance.stations.get(st_cd, {}).get("station_name", st_cd) 
            for (st_cd, f_line, t_line) in transfers
        ]
        
        display_path = [start_name]
        last_added = start_name
        for name in transfer_names_list:
            if name != last_added:
                display_path.append(name)
                last_added = name
        if end_name != last_added:
            display_path.append(end_name)
            
        log.info(f"  [경로] {' -> '.join(display_path)}")
        
        transfer_details = []
        for (st_cd, f_line, t_line) in transfers:
            name = raptor_instance.stations.get(st_cd, {}).get("station_name", st_cd)
            transfer_details.append(f"{name}({f_line}→{t_line})")
        log.info(f"  [환승] {', '.join(transfer_details)}")
    log.info(f"--- [테스트 종료] {case['name']} ---")


@pytest.mark.parametrize("case", TEST_CASES)
def test_benchmark_find_routes(raptor_instance: McRaptor, case: dict, benchmark):
    """
    (요청사항 3) pytest-benchmark를 사용하여 알고리즘 수행 시간 측정
    """
    log.info(f"--- [벤치마크 시작] {case['name']} ---")
    departure_time = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)

    def run_find_routes():
        raptor_instance.find_routes(
            origin_cd=case["origin"],
            destination_cd_set=case["destinations"],
            departure_time=departure_time,
            disability_type=case["disability_type"],
            max_rounds=5,
        )
        
    benchmark(run_find_routes)
    log.info(f"--- [벤치마크 종료] {case['name']} ---")


# (요청사항 4) @profile은 이제 더미 데코레이터(pytest) 또는 
# 실제 데코레이터(mprof)로 정의됩니다.
@profile
def _run_find_routes_for_memory_test(raptor, case, departure_time):
    """(요청사항 4) 메모리 프로파일링을 위한 래퍼 함수"""
    routes = raptor.find_routes(
        origin_cd=case["origin"],
        destination_cd_set=case["destinations"],
        departure_time=departure_time,
        disability_type=case["disability_type"],
        max_rounds=5,
    )
    return routes

@pytest.mark.parametrize("case", TEST_CASES)
def test_memory_usage_find_routes(raptor_instance: McRaptor, case: dict):
    """
    (요청사항 4, 5) memory-profiler 및 tracemalloc을 사용하여 메모리 사용량 측정
    """
    log.info(f"--- [메모리 테스트 (tracemalloc)] {case['name']} ---")
    
    raptor_instance.distance_calculator.cache.clear()
    
    tracemalloc.start()
    
    departure_time = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    routes = _run_find_routes_for_memory_test(raptor_instance, case, departure_time)
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    log.info(f"  [tracemalloc] 경로 탐색 중 Peak 메모리: {peak / 1024**2:.2f} MB")
    
    log.info(f"  [Cache] ANP 혼잡도 캐시 크기 (Key 개수): {len(raptor_instance.anp_calculator.congestion_data)}")
    log.info(f"  [Cache] 거리 계산 캐시 크기 (Key 개수): {len(raptor_instance.distance_calculator.cache)}")
    
    assert routes is not None
    log.info(f"--- [메모리 테스트 (mprof)] {case['name']} ---")
    log.info("  (전체 메모리 프로파일링을 보려면 'mprof run pytest -k test_memory_usage'로 실행하세요)")