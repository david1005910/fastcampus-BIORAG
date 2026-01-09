"""
Graph Database API Endpoints
============================
검색어 관계 분석 및 지식 그래프 API
"""

import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.services.graph_service import get_graph_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ============== Schemas ==============

class SearchTermInput(BaseModel):
    """검색어 입력"""
    term: str
    user_id: Optional[str] = None


class SearchCooccurrenceInput(BaseModel):
    """검색어 동시 출현 입력"""
    terms: List[str]
    user_id: Optional[str] = None


class SearchFlowInput(BaseModel):
    """검색 흐름 입력"""
    from_term: str
    to_term: str
    user_id: Optional[str] = None


class PaperInput(BaseModel):
    """논문 입력"""
    pmid: str
    title: str
    authors: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    abstract: Optional[str] = None


class PaperLinkInput(BaseModel):
    """검색어-논문 연결 입력"""
    term: str
    pmid: str
    relevance: Optional[float] = 1.0


class PaperSimilarityInput(BaseModel):
    """논문 유사도 입력"""
    pmid1: str
    pmid2: str
    similarity: float


class RelatedTermResponse(BaseModel):
    """관련 검색어 응답"""
    term: str
    search_count: int
    cooccurrence: int


class NetworkResponse(BaseModel):
    """네트워크 응답"""
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


# ============== Status Endpoints ==============

@router.get("/status")
async def get_graph_status():
    """GraphDB 상태 확인"""
    graph = get_graph_service()
    return {
        "connected": graph.is_connected,
        "uri": "bolt://neo4j:7687" if graph.is_connected else None
    }


@router.get("/stats")
async def get_graph_stats():
    """그래프 통계"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_stats()


@router.post("/init")
async def init_schema():
    """스키마 초기화"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    graph.init_schema()
    return {"status": "initialized"}


# ============== Search Term Endpoints ==============

@router.post("/search-terms")
async def add_search_term(input: SearchTermInput):
    """검색어 추가/업데이트"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    result = graph.add_search_term(input.term, input.user_id)
    return result


@router.post("/search-terms/cooccurrence")
async def add_cooccurrence(input: SearchCooccurrenceInput):
    """검색어 동시 출현 기록"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    if len(input.terms) < 2:
        raise HTTPException(status_code=400, detail="At least 2 terms required")

    # 각 검색어 추가
    for term in input.terms:
        graph.add_search_term(term, input.user_id)

    # 동시 출현 관계 추가
    results = []
    for i, term1 in enumerate(input.terms):
        for term2 in input.terms[i + 1:]:
            result = graph.add_search_cooccurrence(term1, term2, input.user_id)
            results.extend(result)

    return {"status": "recorded", "relationships": len(results)}


@router.post("/search-terms/flow")
async def add_search_flow(input: SearchFlowInput):
    """검색 흐름 기록"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    # 검색어 추가
    graph.add_search_term(input.from_term, input.user_id)
    graph.add_search_term(input.to_term, input.user_id)

    # 흐름 관계 추가
    result = graph.add_search_flow(input.from_term, input.to_term, input.user_id)
    return {"status": "recorded", "flow": result}


@router.get("/search-terms/related/{term}")
async def get_related_terms(
    term: str,
    limit: int = Query(10, ge=1, le=50)
):
    """관련 검색어 조회"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_related_terms(term, limit)


@router.get("/search-terms/flow/{term}")
async def get_search_flow(
    term: str,
    limit: int = Query(10, ge=1, le=50)
):
    """검색 흐름 조회"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_search_flow(term, limit)


@router.get("/search-terms/popular")
async def get_popular_terms(
    limit: int = Query(20, ge=1, le=100)
):
    """인기 검색어"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_popular_terms(limit)


# ============== Paper Endpoints ==============

@router.post("/papers")
async def add_paper(input: PaperInput):
    """논문 추가"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    result = graph.add_paper(
        pmid=input.pmid,
        title=input.title,
        authors=input.authors,
        keywords=input.keywords,
        abstract=input.abstract
    )
    return result


@router.post("/papers/link")
async def link_search_to_paper(input: PaperLinkInput):
    """검색어와 논문 연결"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    graph.link_search_to_paper(input.term, input.pmid, input.relevance)
    return {"status": "linked"}


@router.post("/papers/similarity")
async def add_paper_similarity(input: PaperSimilarityInput):
    """논문 유사도 추가"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    graph.add_paper_similarity(input.pmid1, input.pmid2, input.similarity)
    return {"status": "added"}


@router.get("/papers/related/{pmid}")
async def get_related_papers(
    pmid: str,
    limit: int = Query(10, ge=1, le=50)
):
    """관련 논문 조회"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_related_papers(pmid, limit)


@router.get("/papers/by-keyword/{keyword}")
async def get_papers_by_keyword(
    keyword: str,
    limit: int = Query(20, ge=1, le=100)
):
    """키워드로 논문 검색"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_papers_by_keyword(keyword, limit)


# ============== Author Endpoints ==============

@router.get("/authors/{author_name}/papers")
async def get_author_papers(
    author_name: str,
    limit: int = Query(20, ge=1, le=100)
):
    """저자의 논문 조회"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_author_papers(author_name, limit)


@router.get("/authors/{author_name}/coauthors")
async def get_coauthors(
    author_name: str,
    limit: int = Query(20, ge=1, le=100)
):
    """공동 저자 조회"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_coauthors(author_name, limit)


# ============== Network Visualization Endpoints ==============

@router.get("/network/keywords/{keyword}")
async def get_keyword_network(
    keyword: str,
    depth: int = Query(2, ge=1, le=3),
    limit: int = Query(50, ge=10, le=200)
):
    """키워드 네트워크 (시각화용)"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_keyword_network(keyword, depth, limit)


@router.get("/network/search-terms")
async def get_search_term_network(
    limit: int = Query(100, ge=10, le=500)
):
    """검색어 네트워크 (시각화용)"""
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_search_term_network(limit)


@router.get("/network/knowledge")
async def get_knowledge_network(
    search_term: Optional[str] = Query(None, description="검색어 (없으면 전체 네트워크)"),
    limit: int = Query(50, ge=10, le=200)
):
    """
    지식 네트워크 (시각화용)
    - 논문, 저자, 키워드 간의 관계를 반환
    - 검색어가 주어지면 해당 검색어와 연결된 논문 중심으로 네트워크 생성
    """
    graph = get_graph_service()
    if not graph.is_connected:
        raise HTTPException(status_code=503, detail="Neo4j not connected")

    return graph.get_knowledge_network(search_term, limit)
