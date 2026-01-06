"""
Memory Backend Factory
======================
Redis와 DuckDB 메모리 백엔드를 선택적으로 사용

환경변수:
- MEMORY_BACKEND: "redis" 또는 "duckdb" (기본값: duckdb)

사용법:
    from src.services.memory_factory import get_memory_services

    chat, analytics, docs = get_memory_services()
"""

import logging
from typing import Tuple, Any, Optional
from functools import lru_cache

from src.core.config import settings

logger = logging.getLogger(__name__)


# 백엔드 타입 정의
BACKEND_REDIS = "redis"
BACKEND_DUCKDB = "duckdb"


def get_memory_backend() -> str:
    """현재 설정된 메모리 백엔드 반환"""
    backend = settings.MEMORY_BACKEND.lower()
    if backend not in [BACKEND_REDIS, BACKEND_DUCKDB]:
        logger.warning(f"Unknown memory backend: {backend}, defaulting to duckdb")
        return BACKEND_DUCKDB
    return backend


# =============================================================================
# DuckDB 서비스 (동기)
# =============================================================================

def get_duckdb_services() -> Tuple[Any, Any, Any]:
    """DuckDB 기반 서비스 반환"""
    from src.services.duckdb_memory import (
        ChatMemoryService,
        SearchAnalyticsService,
        DocumentMetadataService
    )

    db_path = settings.DUCKDB_PATH if settings.DUCKDB_PATH else None

    return (
        ChatMemoryService(db_path),
        SearchAnalyticsService(db_path),
        DocumentMetadataService(db_path)
    )


def get_duckdb_chat_memory():
    """DuckDB 채팅 메모리 서비스"""
    from src.services.duckdb_memory import ChatMemoryService
    db_path = settings.DUCKDB_PATH if settings.DUCKDB_PATH else None
    return ChatMemoryService(db_path)


def get_duckdb_search_analytics():
    """DuckDB 검색 분석 서비스"""
    from src.services.duckdb_memory import SearchAnalyticsService
    db_path = settings.DUCKDB_PATH if settings.DUCKDB_PATH else None
    return SearchAnalyticsService(db_path)


def get_duckdb_doc_metadata():
    """DuckDB 문서 메타데이터 서비스"""
    from src.services.duckdb_memory import DocumentMetadataService
    db_path = settings.DUCKDB_PATH if settings.DUCKDB_PATH else None
    return DocumentMetadataService(db_path)


# =============================================================================
# Redis 서비스 (비동기)
# =============================================================================

def get_redis_services() -> Tuple[Any, Any, Any]:
    """Redis 기반 서비스 반환"""
    from src.services.redis_memory import (
        RedisChatMemoryService,
        RedisSearchAnalyticsService,
        RedisDocumentMetadataService
    )

    return (
        RedisChatMemoryService(),
        RedisSearchAnalyticsService(),
        RedisDocumentMetadataService()
    )


def get_redis_chat_memory():
    """Redis 채팅 메모리 서비스"""
    from src.services.redis_memory import RedisChatMemoryService
    return RedisChatMemoryService()


def get_redis_search_analytics():
    """Redis 검색 분석 서비스"""
    from src.services.redis_memory import RedisSearchAnalyticsService
    return RedisSearchAnalyticsService()


def get_redis_doc_metadata():
    """Redis 문서 메타데이터 서비스"""
    from src.services.redis_memory import RedisDocumentMetadataService
    return RedisDocumentMetadataService()


# =============================================================================
# 통합 팩토리 함수
# =============================================================================

def get_memory_services() -> Tuple[Any, Any, Any]:
    """
    설정에 따른 메모리 서비스 반환

    Returns:
        Tuple[ChatMemoryService, SearchAnalyticsService, DocumentMetadataService]
    """
    backend = get_memory_backend()

    if backend == BACKEND_REDIS:
        logger.info("Using Redis memory backend")
        return get_redis_services()
    else:
        logger.info("Using DuckDB memory backend")
        return get_duckdb_services()


def get_chat_memory_service():
    """채팅 메모리 서비스 반환"""
    backend = get_memory_backend()
    if backend == BACKEND_REDIS:
        return get_redis_chat_memory()
    return get_duckdb_chat_memory()


def get_search_analytics_service():
    """검색 분석 서비스 반환"""
    backend = get_memory_backend()
    if backend == BACKEND_REDIS:
        return get_redis_search_analytics()
    return get_duckdb_search_analytics()


def get_document_metadata_service():
    """문서 메타데이터 서비스 반환"""
    backend = get_memory_backend()
    if backend == BACKEND_REDIS:
        return get_redis_doc_metadata()
    return get_duckdb_doc_metadata()


# =============================================================================
# FastAPI 라우터
# =============================================================================

try:
    from fastapi import APIRouter, Depends, HTTPException, Query
    from pydantic import BaseModel
    from typing import Dict, List, Optional

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


if FASTAPI_AVAILABLE:

    router = APIRouter(prefix="/memory", tags=["Memory & Analytics"])

    # Pydantic 모델
    class CreateSessionRequest(BaseModel):
        title: Optional[str] = None
        metadata: Optional[Dict] = None

    class AddMessageRequest(BaseModel):
        role: str
        content: str
        metadata: Optional[Dict] = None
        tokens_used: Optional[int] = 0

    class LogSearchRequest(BaseModel):
        query: str
        query_type: Optional[str] = "semantic"
        results_count: Optional[int] = 0
        top_score: Optional[float] = None
        response_time_ms: Optional[float] = None

    class UpsertDocumentRequest(BaseModel):
        doc_id: str
        pmid: Optional[str] = None
        title: Optional[str] = None
        authors: Optional[List[str]] = None
        journal: Optional[str] = None
        abstract: Optional[str] = None
        embedding_status: Optional[str] = "pending"

    # ==================== 정보 API ====================

    @router.get("/backend")
    async def get_backend_info():
        """현재 메모리 백엔드 정보"""
        return {
            "backend": get_memory_backend(),
            "available_backends": [BACKEND_REDIS, BACKEND_DUCKDB]
        }

    # ==================== 세션 API ====================

    @router.post("/sessions")
    async def create_session(
        request: CreateSessionRequest,
        user_id: str = Query(..., description="사용자 ID")
    ):
        """새 대화 세션 생성"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            memory = get_redis_chat_memory()
            return await memory.create_session(
                user_id=user_id,
                title=request.title or "새 대화",
                metadata=request.metadata
            )
        else:
            memory = get_duckdb_chat_memory()
            return memory.create_session(
                user_id=user_id,
                title=request.title or "새 대화",
                metadata=request.metadata
            )

    @router.get("/sessions")
    async def get_sessions(
        user_id: str = Query(..., description="사용자 ID"),
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0)
    ):
        """대화 세션 목록 조회"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            memory = get_redis_chat_memory()
            return await memory.get_user_sessions(user_id, limit, offset)
        else:
            memory = get_duckdb_chat_memory()
            return memory.get_user_sessions(user_id, limit, offset)

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        """세션 정보 조회"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            memory = get_redis_chat_memory()
            result = await memory.get_session(session_id)
        else:
            memory = get_duckdb_chat_memory()
            result = memory.get_session(session_id)

        if not result:
            raise HTTPException(status_code=404, detail="Session not found")
        return result

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str):
        """세션 삭제"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            memory = get_redis_chat_memory()
            success = await memory.delete_session(session_id)
        else:
            memory = get_duckdb_chat_memory()
            success = memory.delete_session(session_id)

        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "deleted"}

    @router.post("/sessions/{session_id}/messages")
    async def add_message(
        session_id: str,
        request: AddMessageRequest
    ):
        """메시지 추가"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            memory = get_redis_chat_memory()
            return await memory.add_message(
                session_id=session_id,
                role=request.role,
                content=request.content,
                metadata=request.metadata,
                tokens_used=request.tokens_used
            )
        else:
            memory = get_duckdb_chat_memory()
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
        offset: int = Query(0, ge=0)
    ):
        """세션 메시지 조회"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            memory = get_redis_chat_memory()
            return await memory.get_messages(session_id, limit, offset)
        else:
            memory = get_duckdb_chat_memory()
            return memory.get_messages(session_id, limit, offset)

    @router.get("/sessions/{session_id}/stats")
    async def get_session_stats(session_id: str):
        """세션 통계"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            memory = get_redis_chat_memory()
            return await memory.get_session_stats(session_id)
        else:
            memory = get_duckdb_chat_memory()
            return memory.get_session_stats(session_id)

    # ==================== 분석 API ====================

    @router.post("/analytics/log")
    async def log_search(
        request: LogSearchRequest,
        user_id: str = Query(..., description="사용자 ID")
    ):
        """검색 로그 기록"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            analytics = get_redis_search_analytics()
            return await analytics.log_search(
                user_id=user_id,
                query=request.query,
                query_type=request.query_type,
                results_count=request.results_count,
                top_score=request.top_score,
                response_time_ms=request.response_time_ms
            )
        else:
            analytics = get_duckdb_search_analytics()
            return analytics.log_search(
                user_id=user_id,
                query=request.query,
                query_type=request.query_type,
                results_count=request.results_count,
                top_score=request.top_score,
                response_time_ms=request.response_time_ms
            )

    @router.get("/analytics/popular")
    async def get_popular_queries(
        days: int = Query(7, ge=1, le=90),
        limit: int = Query(20, ge=1, le=100)
    ):
        """인기 검색어"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            analytics = get_redis_search_analytics()
            return await analytics.get_popular_queries(days, limit)
        else:
            analytics = get_duckdb_search_analytics()
            return analytics.get_popular_queries(days, limit)

    @router.get("/analytics/trends")
    async def get_trends(days: int = Query(7, ge=1, le=90)):
        """검색 트렌드"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            analytics = get_redis_search_analytics()
            return await analytics.get_search_trends(days)
        else:
            analytics = get_duckdb_search_analytics()
            return analytics.get_search_trends(days)

    @router.get("/analytics/performance")
    async def get_performance(days: int = Query(7, ge=1, le=90)):
        """성능 통계"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            analytics = get_redis_search_analytics()
            return await analytics.get_performance_stats(days)
        else:
            analytics = get_duckdb_search_analytics()
            return analytics.get_performance_stats(days)

    @router.get("/analytics/history/{user_id}")
    async def get_search_history(
        user_id: str,
        limit: int = Query(50, ge=1, le=200)
    ):
        """사용자 검색 기록"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            analytics = get_redis_search_analytics()
            return await analytics.get_user_search_history(user_id, limit)
        else:
            analytics = get_duckdb_search_analytics()
            return analytics.get_user_search_history(user_id, limit)

    # ==================== 문서 API ====================

    @router.post("/documents")
    async def upsert_document(request: UpsertDocumentRequest):
        """문서 메타데이터 저장"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            docs = get_redis_doc_metadata()
            return await docs.upsert_document(
                doc_id=request.doc_id,
                pmid=request.pmid,
                title=request.title,
                authors=request.authors,
                journal=request.journal,
                abstract=request.abstract,
                embedding_status=request.embedding_status
            )
        else:
            docs = get_duckdb_doc_metadata()
            return docs.upsert_document(
                doc_id=request.doc_id,
                pmid=request.pmid,
                title=request.title,
                authors=request.authors,
                journal=request.journal,
                abstract=request.abstract,
                embedding_status=request.embedding_status
            )

    @router.get("/documents/{doc_id}")
    async def get_document(doc_id: str):
        """문서 정보 조회"""
        backend = get_memory_backend()

        if backend == BACKEND_REDIS:
            docs = get_redis_doc_metadata()
            result = await docs.get_document(doc_id)
        else:
            docs = get_duckdb_doc_metadata()
            result = docs.get_document(doc_id)

        if not result:
            raise HTTPException(status_code=404, detail="Document not found")
        return result
