import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional
from contextlib import contextmanager
import logging
from config import DB_CONFIG
import time

logger = logging.getLogger(__name__)

# 모듈 레벨에서 한 번만 생성 -> 싱글톤 패턴 사용 안함
_connection_pool = None


def initialize_pool():
    """application 시작 시 한 번만 호출"""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=10, maxconn=50, **DB_CONFIG  # RDS db.t3.micro: 최대 연결 87개
        )
        logger.info("RDS Database connection pool 초기화")


def close_pool():
    """application 종료 시 호출"""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        logger.info("RDS Database connection pool 종료")


@contextmanager
def get_db_connection():
    """connection 가져오기"""
    if _connection_pool is None:
        raise RuntimeError(
            "Connection pool이 초기화되지 않았습니다. 초기화 함수를 먼저 호출하시오."
        )

    connection = None
    try:
        connection = _connection_pool.getconn()
        yield connection
    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        if connection:
            connection.rollback()
        raise
    finally:
        if connection:
            _connection_pool.putconn(connection)


@contextmanager
def get_db_cursor(cursor_factory=RealDictCursor):
    """Cursor 가져오기"""
    with get_db_connection as connection:
        cursor = connection.cursor(cursor_factory=cursor_factory)
        try:
            yield cursor
            connection.commit()
        except Exception as e:
            connection.rollback()
            logger.error(f"Transaction rolled back: {e}")
            raise
        finally:
            cursor.close()


# 정보 조회 쿼리 함수들


def get_all_stations(line: Optional[str] = None) -> List[Dict]:
    """해당 호선의 모든 역 정보 조회 order by station_id"""
    if line:
        query = """
        SELECT station_id, line, name, lat, lng, station_cd
        FROM subway_station
        WHERE line = %(line)s
        ORDER BY station_id
        """
        params = {"line": line}
    else:
        query = """
        SELECT station_id, line, name, lat, lng, station_cd
        FROM subway_station
        ORDER BY station_id
        """
        params = None

    with get_db_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def get_station_by_code(station_cd: str) -> Optional[Dict]:
    """station_cd로 단일 역 정보 조회"""
    query = """
    SELECT station_id, line, name, lat,lng, station_cd
    FROM subway_station
    WHERE station_cd = %(station_cd)s
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"station_cd": station_cd})
        return cursor.fetchone()


def get_stations_by_codes(station_cds: List[str]) -> List[Dict]:
    """station_cd 사용하여 여러 역 배치 조회 => 경로 표시용"""
    query = """
    SELECT station_id, line, name, lat, lng, station_cd
    FROM subway_station
    WHERE station_cd = ANY(%(station_cd)s)
    ORDER BY array_position(%(station_cd)s, station_cd)
    """

    with get_db_cursor() as cursor:
        cursor.execute(query, {"station_cds": station_cds})
        return cursor.fetchall()


def get_all_sections(line: Optional[str] = None) -> List[Dict]:
    """모든 구간 정보 조회"""
    if line:
        query = """
        SELECT section_id, line, up_station_name, down_station_name, section_order, via_coordinates
        FROM subway_section
        WHERE line = %(line)s
        ORDER BY section_order
        """
        params = {"line": line}
    else:
        query = """
        SELECT section_id, line, up_station_name, down_station_name, section_order, via_coordinates
        FROM subway_section
        ORDER BY line, section_order
        """
        params = None

    with get_db_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()

    def get_all_transfer_station_conv_scores() -> List[Dict]:
        """모든 환승역 편의성 점수 조회"""
        query = """
        SELECT * FROM transfer_station_convenience
        ORDER BY station_id
        """

        with get_db_cursor() as cursor:
            cursor.execute(query)
            return cursor.fetchall()

    def get_transfer_conv_score_by_code(station_cd: str) -> Optional[Dict]:
        """station_cd로 특정 역의 환승 편의도 조회"""
        query = """
        SELECT * FORM transfer_station_convenience
        WHERE station_cd = %(station_cd)s
        """

        with get_db_cursor() as cursor:
            cursor.execute(query, {"station_cd": station_cd})
            return cursor.fetchone()


# 추가해야 하는 함수 목록
# 특정 역의 특정 타입의 환승 편의도 조회
# 특정 역의 편의시설 정보 조회
