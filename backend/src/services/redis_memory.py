"""
Redis Memory System for RAG Application
========================================
대화 메모리 + 검색 분석 시스템 (Redis 백엔드)

Redis 데이터 구조:
- chat:sessions:{user_id} - 사용자별 세션 목록 (Sorted Set)
- chat:session:{session_id} - 세션 메타데이터 (Hash)
- chat:messages:{session_id} - 세션 메시지 (List)
- analytics:searches - 검색 로그 (Stream)
- analytics:queries - 쿼리 카운터 (Sorted Set)
- docs:metadata:{doc_id} - 문서 메타데이터 (Hash)
"""

import json
import uuid
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import redis.asyncio as redis
from redis.asyncio import Redis

from src.core.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# Redis 연결 관리자
# =============================================================================

class RedisManager:
    """Redis 연결 관리자 (싱글톤)"""

    _instance: Optional['RedisManager'] = None
    _client: Optional[Redis] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def get_client(self) -> Redis:
        """Redis 클라이언트 반환"""
        if self._client is None:
            self._client = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            logger.info(f"Redis connected: {settings.REDIS_URL}")
        return self._client

    async def close(self):
        """연결 종료"""
        if self._client:
            await self._client.close()
            self._client = None


_redis_manager = RedisManager()


async def get_redis() -> Redis:
    """Redis 클라이언트 획득"""
    return await _redis_manager.get_client()


# =============================================================================
# 채팅 메모리 서비스 (Redis)
# =============================================================================

class RedisChatMemoryService:
    """
    Redis 기반 대화 메모리 서비스

    키 구조:
    - chat:sessions:{user_id} - Sorted Set (score=timestamp)
    - chat:session:{session_id} - Hash
    - chat:messages:{session_id} - List
    """

    def __init__(self):
        self._redis: Optional[Redis] = None

    async def _get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = await get_redis()
        return self._redis

    async def create_session(
        self,
        user_id: str,
        title: str = "새 대화",
        metadata: Dict = None
    ) -> Dict:
        """새 대화 세션 생성"""
        r = await self._get_redis()
        session_id = str(uuid.uuid4())
        now = datetime.now()
        timestamp = now.timestamp()

        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "title": title,
            "metadata": json.dumps(metadata) if metadata else "",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat()
        }

        # 세션 데이터 저장
        await r.hset(f"chat:session:{session_id}", mapping=session_data)

        # 사용자 세션 목록에 추가
        await r.zadd(f"chat:sessions:{user_id}", {session_id: timestamp})

        return {
            "session_id": session_id,
            "user_id": user_id,
            "title": title,
            "created_at": now.isoformat()
        }

    async def get_session(self, session_id: str) -> Optional[Dict]:
        """세션 정보 조회"""
        r = await self._get_redis()
        data = await r.hgetall(f"chat:session:{session_id}")

        if not data:
            return None

        return {
            "session_id": data["session_id"],
            "user_id": data["user_id"],
            "title": data["title"],
            "metadata": json.loads(data["metadata"]) if data.get("metadata") else None,
            "created_at": data["created_at"],
            "updated_at": data["updated_at"]
        }

    async def get_user_sessions(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict]:
        """사용자의 세션 목록 조회"""
        r = await self._get_redis()

        # 최신순으로 세션 ID 조회
        session_ids = await r.zrevrange(
            f"chat:sessions:{user_id}",
            offset,
            offset + limit - 1
        )

        sessions = []
        for sid in session_ids:
            session = await self.get_session(sid)
            if session:
                # 메시지 수 추가
                msg_count = await r.llen(f"chat:messages:{sid}")
                session["message_count"] = msg_count
                sessions.append(session)

        return sessions

    async def update_session(
        self,
        session_id: str,
        title: str = None,
        metadata: Dict = None
    ) -> bool:
        """세션 정보 업데이트"""
        r = await self._get_redis()

        updates = {"updated_at": datetime.now().isoformat()}
        if title is not None:
            updates["title"] = title
        if metadata is not None:
            updates["metadata"] = json.dumps(metadata)

        await r.hset(f"chat:session:{session_id}", mapping=updates)
        return True

    async def delete_session(self, session_id: str) -> bool:
        """세션 삭제"""
        r = await self._get_redis()

        # 세션 정보 조회
        session = await self.get_session(session_id)
        if not session:
            return False

        # 메시지 삭제
        await r.delete(f"chat:messages:{session_id}")

        # 세션 삭제
        await r.delete(f"chat:session:{session_id}")

        # 사용자 세션 목록에서 제거
        await r.zrem(f"chat:sessions:{session['user_id']}", session_id)

        return True

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Dict = None,
        tokens_used: int = 0
    ) -> Dict:
        """메시지 추가"""
        r = await self._get_redis()
        now = datetime.now()

        message = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "metadata": json.dumps(metadata) if metadata else "",
            "tokens_used": tokens_used,
            "created_at": now.isoformat()
        }

        # 메시지 저장
        await r.rpush(f"chat:messages:{session_id}", json.dumps(message))

        # 세션 업데이트 시간 갱신
        await r.hset(f"chat:session:{session_id}", "updated_at", now.isoformat())

        return {
            "session_id": session_id,
            "role": role,
            "content": content,
            "tokens_used": tokens_used,
            "created_at": now.isoformat()
        }

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """세션의 메시지 조회"""
        r = await self._get_redis()

        # 최신 메시지 조회 (역순)
        messages_raw = await r.lrange(
            f"chat:messages:{session_id}",
            -offset - limit if offset else -limit,
            -offset - 1 if offset else -1
        )

        messages = []
        for msg_json in messages_raw:
            msg = json.loads(msg_json)
            messages.append({
                "session_id": msg["session_id"],
                "role": msg["role"],
                "content": msg["content"],
                "metadata": json.loads(msg["metadata"]) if msg.get("metadata") else None,
                "tokens_used": msg["tokens_used"],
                "created_at": msg["created_at"]
            })

        return list(reversed(messages))

    async def get_context_messages(
        self,
        session_id: str,
        max_messages: int = 10,
        max_tokens: int = 4000
    ) -> List[Dict]:
        """컨텍스트용 최근 메시지 조회"""
        r = await self._get_redis()

        messages_raw = await r.lrange(f"chat:messages:{session_id}", -max_messages, -1)

        messages = []
        total_tokens = 0

        for msg_json in reversed(messages_raw):
            msg = json.loads(msg_json)
            if total_tokens + msg["tokens_used"] > max_tokens:
                break
            messages.insert(0, {
                "role": msg["role"],
                "content": msg["content"]
            })
            total_tokens += msg["tokens_used"]

        return messages

    async def get_session_stats(self, session_id: str) -> Dict:
        """세션 통계"""
        r = await self._get_redis()

        messages_raw = await r.lrange(f"chat:messages:{session_id}", 0, -1)

        total_messages = len(messages_raw)
        user_messages = 0
        assistant_messages = 0
        total_tokens = 0
        first_message = None
        last_message = None

        for msg_json in messages_raw:
            msg = json.loads(msg_json)
            if msg["role"] == "user":
                user_messages += 1
            elif msg["role"] == "assistant":
                assistant_messages += 1
            total_tokens += msg.get("tokens_used", 0)

            if first_message is None:
                first_message = msg["created_at"]
            last_message = msg["created_at"]

        return {
            "total_messages": total_messages,
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "total_tokens": total_tokens,
            "first_message": first_message,
            "last_message": last_message
        }


# =============================================================================
# 검색 분석 서비스 (Redis)
# =============================================================================

class RedisSearchAnalyticsService:
    """
    Redis 기반 검색 분석 서비스

    키 구조:
    - analytics:searches - Stream (검색 로그)
    - analytics:queries - Sorted Set (쿼리별 카운트)
    - analytics:daily:{date} - Hash (일별 통계)
    """

    def __init__(self):
        self._redis: Optional[Redis] = None

    async def _get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = await get_redis()
        return self._redis

    async def log_search(
        self,
        user_id: str,
        query: str,
        query_type: str = "semantic",
        results_count: int = 0,
        top_score: float = None,
        response_time_ms: float = None,
        metadata: Dict = None
    ) -> Dict:
        """검색 로그 기록"""
        r = await self._get_redis()
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        log_entry = {
            "user_id": user_id,
            "query": query,
            "query_type": query_type,
            "results_count": str(results_count),
            "top_score": str(top_score) if top_score else "",
            "response_time_ms": str(response_time_ms) if response_time_ms else "",
            "metadata": json.dumps(metadata) if metadata else "",
            "created_at": now.isoformat()
        }

        # Stream에 로그 추가
        await r.xadd("analytics:searches", log_entry, maxlen=100000)

        # 쿼리 카운터 증가
        await r.zincrby("analytics:queries", 1, query.lower())

        # 일별 통계 업데이트
        await r.hincrby(f"analytics:daily:{today}", "search_count", 1)
        await r.hincrby(f"analytics:daily:{today}", "total_results", results_count)
        if response_time_ms:
            await r.hincrbyfloat(f"analytics:daily:{today}", "total_response_time", response_time_ms)

        # 일별 통계 TTL 설정 (30일)
        await r.expire(f"analytics:daily:{today}", 30 * 24 * 3600)

        return {"status": "logged", "timestamp": now.isoformat()}

    async def get_popular_queries(
        self,
        days: int = 7,
        limit: int = 20
    ) -> List[Dict]:
        """인기 검색어 조회"""
        r = await self._get_redis()

        # 전체 인기 검색어 (최근 N일 필터링은 Stream 기반으로 별도 구현 필요)
        results = await r.zrevrange("analytics:queries", 0, limit - 1, withscores=True)

        return [
            {"query": query, "search_count": int(count)}
            for query, count in results
        ]

    async def get_search_trends(self, days: int = 7) -> List[Dict]:
        """일별 검색 트렌드"""
        r = await self._get_redis()
        trends = []

        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            stats = await r.hgetall(f"analytics:daily:{date}")

            if stats:
                search_count = int(stats.get("search_count", 0))
                total_response_time = float(stats.get("total_response_time", 0))
                total_results = int(stats.get("total_results", 0))

                trends.append({
                    "date": date,
                    "search_count": search_count,
                    "avg_response_time_ms": round(total_response_time / search_count, 2) if search_count else 0,
                    "avg_results": round(total_results / search_count, 1) if search_count else 0
                })
            else:
                trends.append({
                    "date": date,
                    "search_count": 0,
                    "avg_response_time_ms": 0,
                    "avg_results": 0
                })

        return list(reversed(trends))

    async def get_performance_stats(self, days: int = 7) -> Dict:
        """성능 통계"""
        r = await self._get_redis()

        total_searches = 0
        total_response_time = 0
        total_results = 0

        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            stats = await r.hgetall(f"analytics:daily:{date}")

            if stats:
                total_searches += int(stats.get("search_count", 0))
                total_response_time += float(stats.get("total_response_time", 0))
                total_results += int(stats.get("total_results", 0))

        return {
            "total_searches": total_searches,
            "unique_users": 0,  # Redis에서는 별도 추적 필요
            "avg_response_time_ms": round(total_response_time / total_searches, 2) if total_searches else 0,
            "p50_response_time_ms": 0,  # Stream 분석 필요
            "p95_response_time_ms": 0,
            "p99_response_time_ms": 0,
            "avg_results_per_search": round(total_results / total_searches, 1) if total_searches else 0,
            "avg_top_score": 0,
            "zero_result_count": 0,
            "zero_result_rate": 0
        }

    async def get_user_search_history(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[Dict]:
        """사용자 검색 기록"""
        r = await self._get_redis()

        # Stream에서 사용자별 검색 기록 조회
        entries = await r.xrevrange("analytics:searches", count=1000)

        history = []
        for entry_id, data in entries:
            if data.get("user_id") == user_id:
                history.append({
                    "query": data["query"],
                    "query_type": data["query_type"],
                    "results_count": int(data["results_count"]),
                    "top_score": float(data["top_score"]) if data.get("top_score") else None,
                    "response_time_ms": float(data["response_time_ms"]) if data.get("response_time_ms") else None,
                    "created_at": data["created_at"]
                })
                if len(history) >= limit:
                    break

        return history


# =============================================================================
# 문서 메타데이터 서비스 (Redis)
# =============================================================================

class RedisDocumentMetadataService:
    """
    Redis 기반 문서 메타데이터 서비스

    키 구조:
    - docs:metadata:{doc_id} - Hash
    - docs:by_pmid:{pmid} - String (doc_id 매핑)
    - docs:by_status:{status} - Set
    """

    def __init__(self):
        self._redis: Optional[Redis] = None

    async def _get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = await get_redis()
        return self._redis

    async def upsert_document(
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
        r = await self._get_redis()
        now = datetime.now().isoformat()

        doc_data = {
            "doc_id": doc_id,
            "pmid": pmid or "",
            "title": title or "",
            "authors": json.dumps(authors) if authors else "[]",
            "journal": journal or "",
            "published_date": published_date or "",
            "abstract": abstract or "",
            "keywords": json.dumps(keywords) if keywords else "[]",
            "chunk_count": str(chunk_count),
            "embedding_status": embedding_status,
            "metadata": json.dumps(metadata) if metadata else "",
            "created_at": now,
            "updated_at": now
        }

        # 기존 문서 확인
        existing = await r.exists(f"docs:metadata:{doc_id}")
        if existing:
            # 기존 created_at 유지
            old_data = await r.hget(f"docs:metadata:{doc_id}", "created_at")
            if old_data:
                doc_data["created_at"] = old_data

        # 문서 저장
        await r.hset(f"docs:metadata:{doc_id}", mapping=doc_data)

        # PMID 인덱스
        if pmid:
            await r.set(f"docs:by_pmid:{pmid}", doc_id)

        # 상태별 인덱스
        await r.sadd(f"docs:by_status:{embedding_status}", doc_id)

        return {"doc_id": doc_id, "status": "upserted"}

    async def get_document(self, doc_id: str) -> Optional[Dict]:
        """문서 정보 조회"""
        r = await self._get_redis()
        data = await r.hgetall(f"docs:metadata:{doc_id}")

        if not data:
            return None

        return {
            "doc_id": data["doc_id"],
            "pmid": data["pmid"] or None,
            "title": data["title"] or None,
            "authors": json.loads(data["authors"]) if data.get("authors") else [],
            "journal": data["journal"] or None,
            "published_date": data["published_date"] or None,
            "abstract": data["abstract"] or None,
            "keywords": json.loads(data["keywords"]) if data.get("keywords") else [],
            "chunk_count": int(data["chunk_count"]),
            "embedding_status": data["embedding_status"],
            "metadata": json.loads(data["metadata"]) if data.get("metadata") else None,
            "created_at": data["created_at"],
            "updated_at": data["updated_at"]
        }

    async def get_document_by_pmid(self, pmid: str) -> Optional[Dict]:
        """PMID로 문서 조회"""
        r = await self._get_redis()
        doc_id = await r.get(f"docs:by_pmid:{pmid}")

        if not doc_id:
            return None

        return await self.get_document(doc_id)

    async def update_embedding_status(self, doc_id: str, status: str) -> bool:
        """임베딩 상태 업데이트"""
        r = await self._get_redis()

        # 기존 상태 확인
        old_status = await r.hget(f"docs:metadata:{doc_id}", "embedding_status")

        if old_status:
            await r.srem(f"docs:by_status:{old_status}", doc_id)

        await r.hset(f"docs:metadata:{doc_id}", mapping={
            "embedding_status": status,
            "updated_at": datetime.now().isoformat()
        })
        await r.sadd(f"docs:by_status:{status}", doc_id)

        return True

    async def get_pending_documents(self, limit: int = 100) -> List[Dict]:
        """임베딩 대기 중인 문서 조회"""
        r = await self._get_redis()

        doc_ids = await r.srandmember(f"docs:by_status:pending", limit)

        documents = []
        for doc_id in doc_ids or []:
            doc = await self.get_document(doc_id)
            if doc:
                documents.append({
                    "doc_id": doc["doc_id"],
                    "pmid": doc["pmid"],
                    "title": doc["title"],
                    "abstract": doc["abstract"]
                })

        return documents


# =============================================================================
# 서비스 인스턴스 팩토리
# =============================================================================

_chat_memory: Optional[RedisChatMemoryService] = None
_search_analytics: Optional[RedisSearchAnalyticsService] = None
_doc_metadata: Optional[RedisDocumentMetadataService] = None


def get_redis_chat_memory() -> RedisChatMemoryService:
    """Redis 채팅 메모리 서비스"""
    global _chat_memory
    if _chat_memory is None:
        _chat_memory = RedisChatMemoryService()
    return _chat_memory


def get_redis_search_analytics() -> RedisSearchAnalyticsService:
    """Redis 검색 분석 서비스"""
    global _search_analytics
    if _search_analytics is None:
        _search_analytics = RedisSearchAnalyticsService()
    return _search_analytics


def get_redis_document_metadata() -> RedisDocumentMetadataService:
    """Redis 문서 메타데이터 서비스"""
    global _doc_metadata
    if _doc_metadata is None:
        _doc_metadata = RedisDocumentMetadataService()
    return _doc_metadata
