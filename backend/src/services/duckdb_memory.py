"""
DuckDB Memory System for RAG Application
=========================================
대화 메모리 + 검색 분석 통합 시스템

사용법:
1. requirements.txt에 추가: duckdb>=1.1.0
2. 이 파일을 src/services/ 폴더에 복사
3. main.py에서 라우터 등록

작성일: 2025-01-03
"""

import duckdb
import json
import uuid
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
from contextlib import contextmanager

# FastAPI imports (선택적)
try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from pydantic import BaseModel
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# DuckDB 연결 관리자
# =============================================================================

class DuckDBManager:
    """
    DuckDB 연결 관리자 (싱글톤 패턴)

    사용 예시:
        db = DuckDBManager()
        db.conn.execute("SELECT * FROM chat_sessions")
    """

    _instance: Optional['DuckDBManager'] = None
    _conn: Optional[duckdb.DuckDBPyConnection] = None

    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._db_path = db_path
        return cls._instance

    def __init__(self, db_path: str = None):
        if self._conn is None:
            self._initialize(db_path or self._db_path)

    def _initialize(self, db_path: str = None):
        """DuckDB 초기화"""
        if db_path is None:
            # 기본 경로: data/memory.duckdb
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "memory.duckdb")

        # 인메모리 모드
        if db_path == ':memory:':
            self._conn = duckdb.connect(':memory:')
            logger.info("DuckDB initialized in memory mode")
        else:
            self._conn = duckdb.connect(db_path)
            logger.info(f"DuckDB initialized at {db_path}")

        self._create_tables()

    def _create_tables(self):
        """테이블 생성"""

        # 1. 대화 세션 테이블
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                title VARCHAR DEFAULT '새 대화',
                metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. 대화 메시지 테이블
        self._conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS msg_id_seq START 1;
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER DEFAULT nextval('msg_id_seq') PRIMARY KEY,
                session_id VARCHAR NOT NULL,
                role VARCHAR NOT NULL,
                content TEXT NOT NULL,
                metadata JSON,
                tokens_used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. 검색 로그 테이블
        self._conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS search_log_id_seq START 1;
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS search_logs (
                id INTEGER DEFAULT nextval('search_log_id_seq') PRIMARY KEY,
                user_id VARCHAR,
                query TEXT NOT NULL,
                query_type VARCHAR DEFAULT 'semantic',
                results_count INTEGER DEFAULT 0,
                top_score FLOAT,
                response_time_ms FLOAT,
                metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 4. 문서 메타데이터 테이블
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS document_metadata (
                doc_id VARCHAR PRIMARY KEY,
                pmid VARCHAR,
                title TEXT,
                authors JSON,
                journal VARCHAR,
                published_date DATE,
                abstract TEXT,
                keywords JSON,
                chunk_count INTEGER DEFAULT 0,
                embedding_status VARCHAR DEFAULT 'pending',
                metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 5. 사용자 활동 로그 테이블
        self._conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS activity_id_seq START 1;
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                id INTEGER DEFAULT nextval('activity_id_seq') PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                action_type VARCHAR NOT NULL,
                action_detail JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 인덱스 생성
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON chat_messages(session_id, created_at)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_user
            ON chat_sessions(user_id, updated_at)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_logs_user
            ON search_logs(user_id, created_at)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_logs_query
            ON search_logs(query)
        """)

        logger.info("DuckDB tables created successfully")

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """DuckDB 연결 반환"""
        return self._conn

    def execute(self, query: str, params: list = None):
        """쿼리 실행 헬퍼"""
        if params:
            return self._conn.execute(query, params)
        return self._conn.execute(query)

    def fetchone(self, query: str, params: list = None):
        """단일 결과 조회"""
        result = self.execute(query, params)
        return result.fetchone()

    def fetchall(self, query: str, params: list = None):
        """전체 결과 조회"""
        result = self.execute(query, params)
        return result.fetchall()

    def close(self):
        """연결 종료"""
        if self._conn:
            self._conn.close()
            self._conn = None
            DuckDBManager._instance = None
            logger.info("DuckDB connection closed")

    @classmethod
    def reset(cls):
        """싱글톤 인스턴스 리셋 (테스트용)"""
        if cls._instance and cls._instance._conn:
            cls._instance._conn.close()
        cls._instance = None
        cls._conn = None


def get_duckdb(db_path: str = None) -> DuckDBManager:
    """DuckDB 매니저 인스턴스 반환"""
    return DuckDBManager(db_path)


# =============================================================================
# 대화 메모리 서비스
# =============================================================================

class ChatMemoryService:
    """
    대화 메모리 관리 서비스

    기능:
    - 대화 세션 생성/조회/삭제
    - 메시지 저장/조회
    - 대화 기록 검색
    - 통계 분석
    """

    def __init__(self, db_path: str = None):
        self.db = get_duckdb(db_path)

    # ==================== 세션 관리 ====================

    def create_session(
        self,
        user_id: str,
        title: str = None,
        metadata: Dict = None
    ) -> Dict:
        """새 대화 세션 생성"""
        session_id = str(uuid.uuid4())
        metadata_json = json.dumps(metadata) if metadata else None

        self.db.execute("""
            INSERT INTO chat_sessions (session_id, user_id, title, metadata)
            VALUES (?, ?, ?, ?)
        """, [session_id, user_id, title or "새 대화", metadata_json])

        logger.info(f"Created session: {session_id} for user: {user_id}")

        return {
            "session_id": session_id,
            "user_id": user_id,
            "title": title or "새 대화",
            "created_at": datetime.now().isoformat()
        }

    def get_session(self, session_id: str) -> Optional[Dict]:
        """세션 정보 조회"""
        result = self.db.fetchone("""
            SELECT session_id, user_id, title, metadata, created_at, updated_at
            FROM chat_sessions
            WHERE session_id = ?
        """, [session_id])

        if not result:
            return None

        return {
            "session_id": result[0],
            "user_id": result[1],
            "title": result[2],
            "metadata": json.loads(result[3]) if result[3] else None,
            "created_at": result[4],
            "updated_at": result[5]
        }

    def get_user_sessions(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict]:
        """사용자의 대화 세션 목록"""
        results = self.db.fetchall("""
            SELECT
                s.session_id,
                s.title,
                s.created_at,
                s.updated_at,
                (SELECT COUNT(*) FROM chat_messages WHERE session_id = s.session_id) as message_count,
                (SELECT content FROM chat_messages
                 WHERE session_id = s.session_id
                 ORDER BY created_at DESC LIMIT 1) as last_message
            FROM chat_sessions s
            WHERE s.user_id = ?
            ORDER BY s.updated_at DESC
            LIMIT ? OFFSET ?
        """, [user_id, limit, offset])

        return [
            {
                "session_id": row[0],
                "title": row[1],
                "created_at": row[2],
                "updated_at": row[3],
                "message_count": row[4],
                "last_message": row[5][:100] + "..." if row[5] and len(row[5]) > 100 else row[5]
            }
            for row in results
        ]

    def update_session(
        self,
        session_id: str,
        title: str = None,
        metadata: Dict = None
    ) -> bool:
        """세션 정보 업데이트"""
        updates = ["updated_at = now()"]
        params = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)

        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))

        params.append(session_id)

        self.db.execute(f"""
            UPDATE chat_sessions
            SET {', '.join(updates)}
            WHERE session_id = ?
        """, params)

        return True

    def delete_session(self, session_id: str, user_id: str = None) -> bool:
        """대화 세션 삭제"""
        # 메시지 먼저 삭제
        self.db.execute("""
            DELETE FROM chat_messages WHERE session_id = ?
        """, [session_id])

        # 세션 삭제
        if user_id:
            self.db.execute("""
                DELETE FROM chat_sessions WHERE session_id = ? AND user_id = ?
            """, [session_id, user_id])
        else:
            self.db.execute("""
                DELETE FROM chat_sessions WHERE session_id = ?
            """, [session_id])

        logger.info(f"Deleted session: {session_id}")
        return True

    # ==================== 메시지 관리 ====================

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Dict = None,
        tokens_used: int = 0
    ) -> Dict:
        """메시지 추가"""
        metadata_json = json.dumps(metadata) if metadata else None

        self.db.execute("""
            INSERT INTO chat_messages (session_id, role, content, metadata, tokens_used)
            VALUES (?, ?, ?, ?, ?)
        """, [session_id, role, content, metadata_json, tokens_used])

        # 세션 업데이트 시간 갱신
        self.db.execute("""
            UPDATE chat_sessions
            SET updated_at = now()
            WHERE session_id = ?
        """, [session_id])

        return {
            "session_id": session_id,
            "role": role,
            "content": content,
            "tokens_used": tokens_used,
            "created_at": datetime.now().isoformat()
        }

    def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
        order: str = 'asc'
    ) -> List[Dict]:
        """세션의 메시지 조회"""
        order_clause = "ASC" if order.lower() == 'asc' else "DESC"

        results = self.db.fetchall(f"""
            SELECT id, role, content, metadata, tokens_used, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at {order_clause}
            LIMIT ? OFFSET ?
        """, [session_id, limit, offset])

        messages = [
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "metadata": json.loads(row[3]) if row[3] else None,
                "tokens_used": row[4],
                "created_at": row[5]
            }
            for row in results
        ]

        return messages

    def get_recent_context(
        self,
        session_id: str,
        max_messages: int = 10,
        max_tokens: int = None
    ) -> List[Dict]:
        """
        LLM 컨텍스트용 최근 메시지 (OpenAI 형식)

        반환 형식:
            [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        """
        results = self.db.fetchall("""
            SELECT role, content, tokens_used
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, [session_id, max_messages])

        messages = []
        total_tokens = 0

        for row in reversed(results):
            if max_tokens and total_tokens + (row[2] or 0) > max_tokens:
                break
            messages.append({
                "role": row[0],
                "content": row[1]
            })
            total_tokens += row[2] or 0

        return messages

    def get_last_message(self, session_id: str) -> Optional[Dict]:
        """마지막 메시지 조회"""
        result = self.db.fetchone("""
            SELECT id, role, content, metadata, tokens_used, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, [session_id])

        if not result:
            return None

        return {
            "id": result[0],
            "role": result[1],
            "content": result[2],
            "metadata": json.loads(result[3]) if result[3] else None,
            "tokens_used": result[4],
            "created_at": result[5]
        }

    # ==================== 검색 ====================

    def search_in_history(
        self,
        session_id: str,
        keyword: str,
        limit: int = 20
    ) -> List[Dict]:
        """세션 내 대화 검색"""
        results = self.db.fetchall("""
            SELECT id, role, content, created_at
            FROM chat_messages
            WHERE session_id = ?
              AND content ILIKE ?
            ORDER BY created_at DESC
            LIMIT ?
        """, [session_id, f'%{keyword}%', limit])

        return [
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "created_at": row[3],
                "highlight": self._highlight_keyword(row[2], keyword)
            }
            for row in results
        ]

    def search_all_history(
        self,
        user_id: str,
        keyword: str,
        limit: int = 50
    ) -> List[Dict]:
        """사용자의 모든 대화에서 검색"""
        results = self.db.fetchall("""
            SELECT
                m.id,
                m.session_id,
                s.title as session_title,
                m.role,
                m.content,
                m.created_at
            FROM chat_messages m
            JOIN chat_sessions s ON m.session_id = s.session_id
            WHERE s.user_id = ?
              AND m.content ILIKE ?
            ORDER BY m.created_at DESC
            LIMIT ?
        """, [user_id, f'%{keyword}%', limit])

        return [
            {
                "id": row[0],
                "session_id": row[1],
                "session_title": row[2],
                "role": row[3],
                "content": row[4],
                "created_at": row[5],
                "highlight": self._highlight_keyword(row[4], keyword)
            }
            for row in results
        ]

    def _highlight_keyword(self, text: str, keyword: str, context_length: int = 50) -> str:
        """키워드 주변 텍스트 추출"""
        lower_text = text.lower()
        lower_keyword = keyword.lower()
        pos = lower_text.find(lower_keyword)

        if pos == -1:
            return text[:100] + "..." if len(text) > 100 else text

        start = max(0, pos - context_length)
        end = min(len(text), pos + len(keyword) + context_length)

        result = ""
        if start > 0:
            result += "..."
        result += text[start:end]
        if end < len(text):
            result += "..."

        return result

    # ==================== 통계 ====================

    def get_session_stats(self, session_id: str) -> Dict:
        """세션 통계"""
        result = self.db.fetchone("""
            SELECT
                COUNT(*) as total_messages,
                COUNT(CASE WHEN role = 'user' THEN 1 END) as user_messages,
                COUNT(CASE WHEN role = 'assistant' THEN 1 END) as assistant_messages,
                COALESCE(SUM(tokens_used), 0) as total_tokens,
                MIN(created_at) as first_message,
                MAX(created_at) as last_message
            FROM chat_messages
            WHERE session_id = ?
        """, [session_id])

        return {
            "total_messages": result[0] or 0,
            "user_messages": result[1] or 0,
            "assistant_messages": result[2] or 0,
            "total_tokens": result[3] or 0,
            "first_message": result[4],
            "last_message": result[5]
        }

    def get_user_stats(self, user_id: str) -> Dict:
        """사용자 전체 통계"""
        result = self.db.fetchone("""
            SELECT
                COUNT(DISTINCT s.session_id) as total_sessions,
                COALESCE(COUNT(m.id), 0) as total_messages,
                COALESCE(SUM(m.tokens_used), 0) as total_tokens,
                MIN(s.created_at) as first_session,
                MAX(s.updated_at) as last_activity
            FROM chat_sessions s
            LEFT JOIN chat_messages m ON s.session_id = m.session_id
            WHERE s.user_id = ?
        """, [user_id])

        return {
            "total_sessions": result[0] or 0,
            "total_messages": result[1] or 0,
            "total_tokens": result[2] or 0,
            "first_session": result[3],
            "last_activity": result[4]
        }


# =============================================================================
# 검색 분석 서비스
# =============================================================================

class SearchAnalyticsService:
    """
    검색 로그 및 분석 서비스

    기능:
    - 검색 로그 저장
    - 인기 검색어 분석
    - 검색 트렌드
    - 성능 통계
    """

    def __init__(self, db_path: str = None):
        self.db = get_duckdb(db_path)

    # ==================== 로그 저장 ====================

    def log_search(
        self,
        query: str,
        user_id: str = None,
        query_type: str = "semantic",
        results_count: int = 0,
        top_score: float = None,
        response_time_ms: float = None,
        metadata: Dict = None
    ):
        """검색 로그 저장"""
        metadata_json = json.dumps(metadata) if metadata else None

        self.db.execute("""
            INSERT INTO search_logs
            (user_id, query, query_type, results_count, top_score, response_time_ms, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [user_id, query, query_type, results_count, top_score, response_time_ms, metadata_json])

    @contextmanager
    def track_search(self, query: str, user_id: str = None, query_type: str = "semantic"):
        """검색 시간 자동 측정 컨텍스트 매니저"""
        class SearchTracker:
            def __init__(self, service, query, user_id, query_type):
                self.service = service
                self.query = query
                self.user_id = user_id
                self.query_type = query_type
                self.start_time = time.time()
                self.results_count = 0
                self.top_score = None
                self.metadata = None

            def set_results(self, count: int, top_score: float = None, metadata: Dict = None):
                self.results_count = count
                self.top_score = top_score
                self.metadata = metadata

        tracker = SearchTracker(self, query, user_id, query_type)
        try:
            yield tracker
        finally:
            response_time = (time.time() - tracker.start_time) * 1000
            self.log_search(
                query=tracker.query,
                user_id=tracker.user_id,
                query_type=tracker.query_type,
                results_count=tracker.results_count,
                top_score=tracker.top_score,
                response_time_ms=response_time,
                metadata=tracker.metadata
            )

    # ==================== 분석 쿼리 ====================

    def get_popular_queries(
        self,
        days: int = 7,
        limit: int = 10,
        user_id: str = None
    ) -> List[Dict]:
        """인기 검색어"""
        # DuckDB doesn't support ? placeholder in INTERVAL, use string formatting
        query = f"""
            SELECT
                query,
                COUNT(*) as search_count,
                AVG(results_count) as avg_results,
                AVG(top_score) as avg_top_score,
                AVG(response_time_ms) as avg_response_time
            FROM search_logs
            WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '{days}' DAY
        """
        params = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        query += """
            GROUP BY query
            ORDER BY search_count DESC
            LIMIT ?
        """
        params.append(limit)

        results = self.db.fetchall(query, params) if params else self.db.fetchall(query)

        return [
            {
                "query": row[0],
                "search_count": row[1],
                "avg_results": round(row[2], 1) if row[2] else 0,
                "avg_top_score": round(row[3], 3) if row[3] else 0,
                "avg_response_time_ms": round(row[4], 2) if row[4] else 0
            }
            for row in results
        ]

    def get_search_trends(
        self,
        days: int = 30,
        user_id: str = None
    ) -> List[Dict]:
        """일별 검색 트렌드"""
        query = f"""
            SELECT
                DATE_TRUNC('day', created_at) as date,
                COUNT(*) as search_count,
                COUNT(DISTINCT user_id) as unique_users,
                AVG(response_time_ms) as avg_response_time,
                AVG(results_count) as avg_results
            FROM search_logs
            WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '{days}' DAY
        """
        params = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        query += """
            GROUP BY DATE_TRUNC('day', created_at)
            ORDER BY date
        """

        results = self.db.fetchall(query, params) if params else self.db.fetchall(query)

        return [
            {
                "date": row[0].strftime("%Y-%m-%d") if row[0] else None,
                "search_count": row[1],
                "unique_users": row[2],
                "avg_response_time_ms": round(row[3], 2) if row[3] else 0,
                "avg_results": round(row[4], 1) if row[4] else 0
            }
            for row in results
        ]

    def get_hourly_distribution(self, days: int = 7) -> List[Dict]:
        """시간대별 검색 분포"""
        results = self.db.fetchall(f"""
            SELECT
                EXTRACT(HOUR FROM created_at) as hour,
                COUNT(*) as search_count
            FROM search_logs
            WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '{days}' DAY
            GROUP BY EXTRACT(HOUR FROM created_at)
            ORDER BY hour
        """)

        return [
            {"hour": int(row[0]), "search_count": row[1]}
            for row in results
        ]

    def get_user_search_history(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[Dict]:
        """사용자 검색 기록"""
        results = self.db.fetchall("""
            SELECT
                query,
                query_type,
                results_count,
                top_score,
                response_time_ms,
                created_at
            FROM search_logs
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, [user_id, limit])

        return [
            {
                "query": row[0],
                "query_type": row[1],
                "results_count": row[2],
                "top_score": row[3],
                "response_time_ms": row[4],
                "created_at": row[5]
            }
            for row in results
        ]

    def get_zero_result_queries(
        self,
        days: int = 7,
        limit: int = 20
    ) -> List[Dict]:
        """결과 없는 검색어 (개선 필요)"""
        results = self.db.fetchall(f"""
            SELECT
                query,
                COUNT(*) as attempt_count,
                MAX(created_at) as last_attempt
            FROM search_logs
            WHERE results_count = 0
              AND created_at > CURRENT_TIMESTAMP - INTERVAL '{days}' DAY
            GROUP BY query
            ORDER BY attempt_count DESC
            LIMIT ?
        """, [limit])

        return [
            {
                "query": row[0],
                "attempt_count": row[1],
                "last_attempt": row[2]
            }
            for row in results
        ]

    def get_performance_stats(self, days: int = 7) -> Dict:
        """성능 통계"""
        result = self.db.fetchone(f"""
            SELECT
                COUNT(*) as total_searches,
                COUNT(DISTINCT user_id) as unique_users,
                AVG(response_time_ms) as avg_response_time,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY response_time_ms) as p50_response_time,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_ms) as p95_response_time,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY response_time_ms) as p99_response_time,
                AVG(results_count) as avg_results,
                AVG(top_score) as avg_top_score,
                SUM(CASE WHEN results_count = 0 THEN 1 ELSE 0 END) as zero_result_count
            FROM search_logs
            WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '{days}' DAY
        """)

        total = result[0] or 1  # 0으로 나누기 방지

        return {
            "total_searches": result[0] or 0,
            "unique_users": result[1] or 0,
            "avg_response_time_ms": round(result[2], 2) if result[2] else 0,
            "p50_response_time_ms": round(result[3], 2) if result[3] else 0,
            "p95_response_time_ms": round(result[4], 2) if result[4] else 0,
            "p99_response_time_ms": round(result[5], 2) if result[5] else 0,
            "avg_results_per_search": round(result[6], 1) if result[6] else 0,
            "avg_top_score": round(result[7], 3) if result[7] else 0,
            "zero_result_count": result[8] or 0,
            "zero_result_rate": round((result[8] or 0) / total * 100, 2)
        }


# =============================================================================
# 문서 메타데이터 서비스
# =============================================================================

class DocumentMetadataService:
    """
    문서 메타데이터 관리 서비스

    기능:
    - 문서 정보 저장/조회
    - 임베딩 상태 관리
    - 문서 검색 및 필터링
    """

    def __init__(self, db_path: str = None):
        self.db = get_duckdb(db_path)

    def upsert_document(
        self,
        doc_id: str,
        pmid: str = None,
        title: str = None,
        authors: List[str] = None,
        journal: str = None,
        published_date: str = None,
        abstract: str = None,
        keywords: List[str] = None,
        chunk_count: int = 0,
        embedding_status: str = "pending",
        metadata: Dict = None
    ) -> Dict:
        """문서 메타데이터 저장/업데이트"""
        authors_json = json.dumps(authors) if authors else None
        keywords_json = json.dumps(keywords) if keywords else None
        metadata_json = json.dumps(metadata) if metadata else None

        self.db.execute("""
            INSERT INTO document_metadata
            (doc_id, pmid, title, authors, journal, published_date,
             abstract, keywords, chunk_count, embedding_status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (doc_id) DO UPDATE SET
                pmid = EXCLUDED.pmid,
                title = EXCLUDED.title,
                authors = EXCLUDED.authors,
                journal = EXCLUDED.journal,
                published_date = EXCLUDED.published_date,
                abstract = EXCLUDED.abstract,
                keywords = EXCLUDED.keywords,
                chunk_count = EXCLUDED.chunk_count,
                embedding_status = EXCLUDED.embedding_status,
                metadata = EXCLUDED.metadata,
                updated_at = now()
        """, [doc_id, pmid, title, authors_json, journal, published_date,
              abstract, keywords_json, chunk_count, embedding_status, metadata_json])

        return {"doc_id": doc_id, "status": "upserted"}

    def get_document(self, doc_id: str) -> Optional[Dict]:
        """문서 정보 조회"""
        result = self.db.fetchone("""
            SELECT doc_id, pmid, title, authors, journal, published_date,
                   abstract, keywords, chunk_count, embedding_status,
                   metadata, created_at, updated_at
            FROM document_metadata
            WHERE doc_id = ?
        """, [doc_id])

        if not result:
            return None

        return {
            "doc_id": result[0],
            "pmid": result[1],
            "title": result[2],
            "authors": json.loads(result[3]) if result[3] else [],
            "journal": result[4],
            "published_date": result[5],
            "abstract": result[6],
            "keywords": json.loads(result[7]) if result[7] else [],
            "chunk_count": result[8],
            "embedding_status": result[9],
            "metadata": json.loads(result[10]) if result[10] else None,
            "created_at": result[11],
            "updated_at": result[12]
        }

    def search_documents(
        self,
        keyword: str = None,
        journal: str = None,
        start_date: str = None,
        end_date: str = None,
        embedding_status: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """문서 검색"""
        query = "SELECT doc_id, pmid, title, journal, published_date, embedding_status FROM document_metadata WHERE 1=1"
        params = []

        if keyword:
            query += " AND (title ILIKE ? OR abstract ILIKE ?)"
            params.extend([f'%{keyword}%', f'%{keyword}%'])

        if journal:
            query += " AND journal ILIKE ?"
            params.append(f'%{journal}%')

        if start_date:
            query += " AND published_date >= ?"
            params.append(start_date)

        if end_date:
            query += " AND published_date <= ?"
            params.append(end_date)

        if embedding_status:
            query += " AND embedding_status = ?"
            params.append(embedding_status)

        query += " ORDER BY published_date DESC LIMIT ?"
        params.append(limit)

        results = self.db.fetchall(query, params)

        return [
            {
                "doc_id": row[0],
                "pmid": row[1],
                "title": row[2],
                "journal": row[3],
                "published_date": row[4],
                "embedding_status": row[5]
            }
            for row in results
        ]

    def update_embedding_status(self, doc_id: str, status: str) -> bool:
        """임베딩 상태 업데이트"""
        self.db.execute("""
            UPDATE document_metadata
            SET embedding_status = ?, updated_at = now()
            WHERE doc_id = ?
        """, [status, doc_id])
        return True

    def get_pending_documents(self, limit: int = 100) -> List[Dict]:
        """임베딩 대기 중인 문서 조회"""
        results = self.db.fetchall("""
            SELECT doc_id, pmid, title, abstract
            FROM document_metadata
            WHERE embedding_status = 'pending'
            ORDER BY created_at
            LIMIT ?
        """, [limit])

        return [
            {
                "doc_id": row[0],
                "pmid": row[1],
                "title": row[2],
                "abstract": row[3]
            }
            for row in results
        ]

    def get_stats(self) -> Dict:
        """문서 통계"""
        result = self.db.fetchone("""
            SELECT
                COUNT(*) as total_documents,
                COUNT(CASE WHEN embedding_status = 'completed' THEN 1 END) as embedded_count,
                COUNT(CASE WHEN embedding_status = 'pending' THEN 1 END) as pending_count,
                COUNT(CASE WHEN embedding_status = 'failed' THEN 1 END) as failed_count,
                SUM(chunk_count) as total_chunks,
                COUNT(DISTINCT journal) as unique_journals
            FROM document_metadata
        """)

        return {
            "total_documents": result[0] or 0,
            "embedded_count": result[1] or 0,
            "pending_count": result[2] or 0,
            "failed_count": result[3] or 0,
            "total_chunks": result[4] or 0,
            "unique_journals": result[5] or 0
        }


# =============================================================================
# FastAPI 라우터 (선택적)
# =============================================================================

if FASTAPI_AVAILABLE:

    # Pydantic 모델
    class CreateSessionRequest(BaseModel):
        title: Optional[str] = None
        metadata: Optional[Dict] = None

    class AddMessageRequest(BaseModel):
        role: str
        content: str
        metadata: Optional[Dict] = None
        tokens_used: Optional[int] = 0

    class SearchRequest(BaseModel):
        keyword: str
        limit: Optional[int] = 20

    class LogSearchRequest(BaseModel):
        query: str
        query_type: Optional[str] = "semantic"
        results_count: Optional[int] = 0
        top_score: Optional[float] = None
        response_time_ms: Optional[float] = None

    # 라우터 생성
    router = APIRouter(prefix="/memory", tags=["Memory & Analytics"])

    # 의존성
    def get_chat_memory():
        return ChatMemoryService()

    def get_search_analytics():
        return SearchAnalyticsService()

    def get_doc_metadata():
        return DocumentMetadataService()

    # ==================== 세션 API ====================

    @router.post("/sessions")
    async def create_session(
        request: CreateSessionRequest,
        user_id: str = Query(..., description="사용자 ID"),
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """새 대화 세션 생성"""
        return memory.create_session(
            user_id=user_id,
            title=request.title,
            metadata=request.metadata
        )

    @router.get("/sessions")
    async def get_sessions(
        user_id: str = Query(..., description="사용자 ID"),
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """대화 세션 목록 조회"""
        return memory.get_user_sessions(user_id, limit, offset)

    @router.get("/sessions/{session_id}")
    async def get_session(
        session_id: str,
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """세션 상세 정보"""
        session = memory.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    @router.delete("/sessions/{session_id}")
    async def delete_session(
        session_id: str,
        user_id: str = Query(...),
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """세션 삭제"""
        memory.delete_session(session_id, user_id)
        return {"status": "deleted"}

    # ==================== 메시지 API ====================

    @router.post("/sessions/{session_id}/messages")
    async def add_message(
        session_id: str,
        request: AddMessageRequest,
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """메시지 추가"""
        return memory.add_message(
            session_id=session_id,
            role=request.role,
            content=request.content,
            metadata=request.metadata,
            tokens_used=request.tokens_used
        )

    @router.get("/sessions/{session_id}/messages")
    async def get_messages(
        session_id: str,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """메시지 조회"""
        return memory.get_messages(session_id, limit, offset)

    @router.get("/sessions/{session_id}/context")
    async def get_context(
        session_id: str,
        max_messages: int = Query(10, ge=1, le=50),
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """LLM 컨텍스트용 메시지"""
        return memory.get_recent_context(session_id, max_messages)

    # ==================== 검색 API ====================

    @router.post("/sessions/{session_id}/search")
    async def search_in_session(
        session_id: str,
        request: SearchRequest,
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """세션 내 검색"""
        return memory.search_in_history(session_id, request.keyword, request.limit)

    @router.post("/search/all")
    async def search_all(
        request: SearchRequest,
        user_id: str = Query(...),
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """전체 대화 검색"""
        return memory.search_all_history(user_id, request.keyword, request.limit)

    # ==================== 통계 API ====================

    @router.get("/sessions/{session_id}/stats")
    async def get_session_stats(
        session_id: str,
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """세션 통계"""
        return memory.get_session_stats(session_id)

    @router.get("/stats/user/{user_id}")
    async def get_user_stats(
        user_id: str,
        memory: ChatMemoryService = Depends(get_chat_memory)
    ):
        """사용자 통계"""
        return memory.get_user_stats(user_id)

    # ==================== 검색 분석 API ====================

    @router.post("/analytics/log")
    async def log_search(
        request: LogSearchRequest,
        user_id: str = Query(None),
        analytics: SearchAnalyticsService = Depends(get_search_analytics)
    ):
        """검색 로그 저장"""
        analytics.log_search(
            query=request.query,
            user_id=user_id,
            query_type=request.query_type,
            results_count=request.results_count,
            top_score=request.top_score,
            response_time_ms=request.response_time_ms
        )
        return {"status": "logged"}

    @router.get("/analytics/popular")
    async def get_popular_queries(
        days: int = Query(7, ge=1, le=90),
        limit: int = Query(10, ge=1, le=50),
        user_id: str = Query(None),
        analytics: SearchAnalyticsService = Depends(get_search_analytics)
    ):
        """인기 검색어"""
        return analytics.get_popular_queries(days, limit, user_id)

    @router.get("/analytics/trends")
    async def get_trends(
        days: int = Query(30, ge=1, le=90),
        user_id: str = Query(None),
        analytics: SearchAnalyticsService = Depends(get_search_analytics)
    ):
        """검색 트렌드"""
        return analytics.get_search_trends(days, user_id)

    @router.get("/analytics/performance")
    async def get_performance(
        days: int = Query(7, ge=1, le=90),
        analytics: SearchAnalyticsService = Depends(get_search_analytics)
    ):
        """성능 통계"""
        return analytics.get_performance_stats(days)

    @router.get("/analytics/zero-results")
    async def get_zero_results(
        days: int = Query(7, ge=1, le=90),
        limit: int = Query(20, ge=1, le=100),
        analytics: SearchAnalyticsService = Depends(get_search_analytics)
    ):
        """결과 없는 검색어"""
        return analytics.get_zero_result_queries(days, limit)

    @router.get("/analytics/history/{user_id}")
    async def get_search_history(
        user_id: str,
        limit: int = Query(50, ge=1, le=200),
        analytics: SearchAnalyticsService = Depends(get_search_analytics)
    ):
        """사용자 검색 기록"""
        return analytics.get_user_search_history(user_id, limit)


# =============================================================================
# 편의 함수 (전역 인스턴스)
# =============================================================================

# 전역 서비스 인스턴스
_chat_memory: Optional[ChatMemoryService] = None
_search_analytics: Optional[SearchAnalyticsService] = None
_doc_metadata: Optional[DocumentMetadataService] = None


def get_chat_memory_service(db_path: str = None) -> ChatMemoryService:
    """대화 메모리 서비스 인스턴스"""
    global _chat_memory
    if _chat_memory is None:
        _chat_memory = ChatMemoryService(db_path)
    return _chat_memory


def get_search_analytics_service(db_path: str = None) -> SearchAnalyticsService:
    """검색 분석 서비스 인스턴스"""
    global _search_analytics
    if _search_analytics is None:
        _search_analytics = SearchAnalyticsService(db_path)
    return _search_analytics


def get_document_metadata_service(db_path: str = None) -> DocumentMetadataService:
    """문서 메타데이터 서비스 인스턴스"""
    global _doc_metadata
    if _doc_metadata is None:
        _doc_metadata = DocumentMetadataService(db_path)
    return _doc_metadata
