"""
Neo4j Graph Database Service
============================
검색어 관계 분석 및 지식 그래프 구축

노드 타입:
- SearchTerm: 검색어
- Paper: 논문
- Author: 저자
- Keyword: 키워드/MeSH 용어

관계 타입:
- SEARCHED_WITH: 검색어 간 동시 검색 관계
- MENTIONS: 논문이 키워드를 포함
- AUTHORED_BY: 논문의 저자
- SIMILAR_TO: 유사 논문
- LEADS_TO: 검색 흐름 (A 검색 후 B 검색)
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import contextmanager

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable, AuthError

from src.core.config import settings

logger = logging.getLogger(__name__)


class Neo4jService:
    """Neo4j 그래프 데이터베이스 서비스"""

    _driver: Optional[Driver] = None

    def __init__(self):
        self._connect()

    def _connect(self):
        """Neo4j 연결"""
        try:
            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
                max_connection_lifetime=3600
            )
            # 연결 테스트
            self._driver.verify_connectivity()
            logger.info(f"Connected to Neo4j at {settings.NEO4J_URI}")
        except ServiceUnavailable as e:
            logger.warning(f"Neo4j not available: {e}")
            self._driver = None
        except AuthError as e:
            logger.error(f"Neo4j authentication failed: {e}")
            self._driver = None
        except Exception as e:
            logger.error(f"Neo4j connection error: {e}")
            self._driver = None

    def close(self):
        """연결 종료"""
        if self._driver:
            self._driver.close()
            self._driver = None

    @property
    def is_connected(self) -> bool:
        """연결 상태 확인"""
        return self._driver is not None

    def _execute_query(self, query: str, parameters: Dict = None) -> List[Dict]:
        """쿼리 실행"""
        if not self._driver:
            logger.warning("Neo4j not connected")
            return []

        try:
            with self._driver.session() as session:
                result = session.run(query, parameters or {})
                return [record.data() for record in result]
        except Exception as e:
            logger.error(f"Neo4j query error: {e}")
            return []

    def _execute_write(self, query: str, parameters: Dict = None) -> bool:
        """쓰기 쿼리 실행"""
        if not self._driver:
            logger.warning("Neo4j not connected")
            return False

        try:
            with self._driver.session() as session:
                session.run(query, parameters or {})
                return True
        except Exception as e:
            logger.error(f"Neo4j write error: {e}")
            return False

    # =========================================================================
    # 스키마 초기화
    # =========================================================================

    def init_schema(self):
        """그래프 스키마 및 인덱스 초기화"""
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:SearchTerm) REQUIRE t.term IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Paper) REQUIRE p.pmid IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (k:Keyword) REQUIRE k.term IS UNIQUE",
        ]

        indexes = [
            "CREATE INDEX IF NOT EXISTS FOR (t:SearchTerm) ON (t.count)",
            "CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.title)",
            "CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.created_at)",
        ]

        for query in constraints + indexes:
            self._execute_write(query)

        logger.info("Neo4j schema initialized")

    # =========================================================================
    # 검색어 관련 메서드
    # =========================================================================

    def add_search_term(self, term: str, user_id: str = None) -> Dict:
        """검색어 노드 추가/업데이트"""
        query = """
        MERGE (t:SearchTerm {term: $term})
        ON CREATE SET t.count = 1, t.created_at = datetime()
        ON MATCH SET t.count = t.count + 1, t.last_searched = datetime()
        SET t.last_user = $user_id
        RETURN t.term as term, t.count as count
        """
        result = self._execute_query(query, {"term": term.lower(), "user_id": user_id})
        return result[0] if result else {}

    def add_search_cooccurrence(self, term1: str, term2: str, user_id: str = None):
        """검색어 동시 출현 관계 추가"""
        query = """
        MATCH (t1:SearchTerm {term: $term1})
        MATCH (t2:SearchTerm {term: $term2})
        MERGE (t1)-[r:SEARCHED_WITH]-(t2)
        ON CREATE SET r.count = 1, r.created_at = datetime()
        ON MATCH SET r.count = r.count + 1
        RETURN t1.term, t2.term, r.count
        """
        return self._execute_query(query, {
            "term1": term1.lower(),
            "term2": term2.lower()
        })

    def add_search_flow(self, from_term: str, to_term: str, user_id: str = None):
        """검색 흐름 기록 (A 검색 후 B 검색)"""
        query = """
        MATCH (t1:SearchTerm {term: $from_term})
        MATCH (t2:SearchTerm {term: $to_term})
        MERGE (t1)-[r:LEADS_TO]->(t2)
        ON CREATE SET r.count = 1, r.created_at = datetime()
        ON MATCH SET r.count = r.count + 1
        RETURN t1.term, t2.term, r.count
        """
        return self._execute_query(query, {
            "from_term": from_term.lower(),
            "to_term": to_term.lower()
        })

    def get_related_terms(self, term: str, limit: int = 10) -> List[Dict]:
        """관련 검색어 조회"""
        query = """
        MATCH (t:SearchTerm {term: $term})-[r:SEARCHED_WITH]-(related:SearchTerm)
        RETURN related.term as term, related.count as search_count, r.count as cooccurrence
        ORDER BY r.count DESC, related.count DESC
        LIMIT $limit
        """
        return self._execute_query(query, {"term": term.lower(), "limit": limit})

    def get_search_flow(self, term: str, limit: int = 10) -> List[Dict]:
        """검색 흐름 조회 (이 검색어 다음에 뭘 검색했는지)"""
        query = """
        MATCH (t:SearchTerm {term: $term})-[r:LEADS_TO]->(next:SearchTerm)
        RETURN next.term as term, r.count as flow_count
        ORDER BY r.count DESC
        LIMIT $limit
        """
        return self._execute_query(query, {"term": term.lower(), "limit": limit})

    def get_popular_terms(self, limit: int = 20) -> List[Dict]:
        """인기 검색어 조회"""
        query = """
        MATCH (t:SearchTerm)
        RETURN t.term as term, t.count as count
        ORDER BY t.count DESC
        LIMIT $limit
        """
        return self._execute_query(query, {"limit": limit})

    # =========================================================================
    # 논문 관련 메서드
    # =========================================================================

    def add_paper(self, pmid: str, title: str, authors: List[str] = None,
                  keywords: List[str] = None, abstract: str = None) -> Dict:
        """논문 노드 추가"""
        query = """
        MERGE (p:Paper {pmid: $pmid})
        ON CREATE SET p.title = $title, p.abstract = $abstract, p.created_at = datetime()
        ON MATCH SET p.title = $title, p.abstract = $abstract
        RETURN p.pmid as pmid, p.title as title
        """
        result = self._execute_query(query, {
            "pmid": pmid,
            "title": title,
            "abstract": abstract
        })

        # 저자 연결
        if authors:
            for author in authors[:10]:  # 최대 10명
                self._add_author_relation(pmid, author)

        # 키워드 연결
        if keywords:
            for keyword in keywords[:20]:  # 최대 20개
                self._add_keyword_relation(pmid, keyword)

        return result[0] if result else {}

    def _add_author_relation(self, pmid: str, author_name: str):
        """논문-저자 관계 추가"""
        query = """
        MATCH (p:Paper {pmid: $pmid})
        MERGE (a:Author {name: $author})
        MERGE (p)-[:AUTHORED_BY]->(a)
        """
        self._execute_write(query, {"pmid": pmid, "author": author_name})

    def _add_keyword_relation(self, pmid: str, keyword: str):
        """논문-키워드 관계 추가"""
        query = """
        MATCH (p:Paper {pmid: $pmid})
        MERGE (k:Keyword {term: $keyword})
        MERGE (p)-[:MENTIONS]->(k)
        """
        self._execute_write(query, {"pmid": pmid, "keyword": keyword.lower()})

    def link_search_to_paper(self, term: str, pmid: str, relevance: float = 1.0):
        """검색어와 논문 연결"""
        query = """
        MATCH (t:SearchTerm {term: $term})
        MATCH (p:Paper {pmid: $pmid})
        MERGE (t)-[r:FOUND]->(p)
        ON CREATE SET r.relevance = $relevance, r.count = 1
        ON MATCH SET r.count = r.count + 1
        """
        self._execute_write(query, {
            "term": term.lower(),
            "pmid": pmid,
            "relevance": relevance
        })

    def add_paper_similarity(self, pmid1: str, pmid2: str, similarity: float):
        """논문 유사도 관계 추가"""
        query = """
        MATCH (p1:Paper {pmid: $pmid1})
        MATCH (p2:Paper {pmid: $pmid2})
        MERGE (p1)-[r:SIMILAR_TO]-(p2)
        SET r.score = $similarity
        """
        self._execute_write(query, {
            "pmid1": pmid1,
            "pmid2": pmid2,
            "similarity": similarity
        })

    def get_related_papers(self, pmid: str, limit: int = 10) -> List[Dict]:
        """관련 논문 조회"""
        query = """
        MATCH (p:Paper {pmid: $pmid})-[r:SIMILAR_TO]-(related:Paper)
        RETURN related.pmid as pmid, related.title as title, r.score as similarity
        ORDER BY r.score DESC
        LIMIT $limit
        """
        return self._execute_query(query, {"pmid": pmid, "limit": limit})

    def get_papers_by_keyword(self, keyword: str, limit: int = 20) -> List[Dict]:
        """키워드로 논문 검색"""
        query = """
        MATCH (k:Keyword {term: $keyword})<-[:MENTIONS]-(p:Paper)
        RETURN p.pmid as pmid, p.title as title
        LIMIT $limit
        """
        return self._execute_query(query, {"keyword": keyword.lower(), "limit": limit})

    # =========================================================================
    # 저자 관련 메서드
    # =========================================================================

    def get_author_papers(self, author_name: str, limit: int = 20) -> List[Dict]:
        """저자의 논문 조회"""
        query = """
        MATCH (a:Author {name: $author})<-[:AUTHORED_BY]-(p:Paper)
        RETURN p.pmid as pmid, p.title as title
        LIMIT $limit
        """
        return self._execute_query(query, {"author": author_name, "limit": limit})

    def get_coauthors(self, author_name: str, limit: int = 20) -> List[Dict]:
        """공동 저자 조회"""
        query = """
        MATCH (a:Author {name: $author})<-[:AUTHORED_BY]-(p:Paper)-[:AUTHORED_BY]->(coauthor:Author)
        WHERE coauthor.name <> $author
        RETURN coauthor.name as name, count(p) as collaboration_count
        ORDER BY collaboration_count DESC
        LIMIT $limit
        """
        return self._execute_query(query, {"author": author_name, "limit": limit})

    # =========================================================================
    # 분석 메서드
    # =========================================================================

    def get_keyword_network(self, keyword: str, depth: int = 2, limit: int = 50) -> Dict:
        """키워드 네트워크 조회 (시각화용)"""
        query = """
        MATCH path = (k:Keyword {term: $keyword})<-[:MENTIONS]-(p:Paper)-[:MENTIONS]->(related:Keyword)
        WHERE related.term <> $keyword
        WITH related, count(p) as paper_count
        ORDER BY paper_count DESC
        LIMIT $limit
        RETURN related.term as keyword, paper_count
        """
        nodes = self._execute_query(query, {"keyword": keyword.lower(), "limit": limit})

        # 엣지 정보도 가져오기
        edge_query = """
        MATCH (k1:Keyword {term: $keyword})<-[:MENTIONS]-(p:Paper)-[:MENTIONS]->(k2:Keyword)
        WHERE k2.term IN $related_keywords
        WITH k1, k2, count(p) as weight
        RETURN k1.term as source, k2.term as target, weight
        """
        related_keywords = [n["keyword"] for n in nodes]
        edges = self._execute_query(edge_query, {
            "keyword": keyword.lower(),
            "related_keywords": related_keywords
        })

        return {
            "center": keyword,
            "nodes": nodes,
            "edges": edges
        }

    def get_search_term_network(self, limit: int = 100) -> Dict:
        """검색어 네트워크 조회 (시각화용)"""
        # 노드
        node_query = """
        MATCH (t:SearchTerm)
        RETURN t.term as id, t.term as label, t.count as size
        ORDER BY t.count DESC
        LIMIT $limit
        """
        nodes = self._execute_query(node_query, {"limit": limit})

        # 엣지
        edge_query = """
        MATCH (t1:SearchTerm)-[r:SEARCHED_WITH]-(t2:SearchTerm)
        WHERE t1.count >= 2 AND t2.count >= 2
        RETURN t1.term as source, t2.term as target, r.count as weight
        ORDER BY r.count DESC
        LIMIT $limit
        """
        edges = self._execute_query(edge_query, {"limit": limit * 2})

        return {
            "nodes": nodes,
            "edges": edges
        }

    def get_knowledge_network(self, search_term: str = None, limit: int = 50) -> Dict:
        """
        지식 네트워크 조회 - 논문, 저자, 키워드 관계 시각화
        검색어가 주어지면 해당 검색어와 연결된 논문들을 중심으로 네트워크 생성
        """
        nodes = []
        edges = []
        node_ids = set()

        if search_term:
            # 검색어 노드 추가
            search_node = {
                "id": f"search_{search_term}",
                "label": search_term,
                "type": "SearchTerm",
                "size": 20
            }
            nodes.append(search_node)
            node_ids.add(search_node["id"])

            # 검색어와 연결된 논문 조회
            paper_query = """
            MATCH (t:SearchTerm {term: $term})-[f:FOUND]->(p:Paper)
            RETURN p.pmid as pmid, p.title as title, f.relevance as relevance
            ORDER BY f.relevance DESC
            LIMIT $limit
            """
            papers = self._execute_query(paper_query, {"term": search_term.lower(), "limit": limit})

            for paper in papers:
                paper_id = f"paper_{paper['pmid']}"
                if paper_id not in node_ids:
                    # 제목을 30자로 제한
                    title = paper['title'][:30] + "..." if len(paper['title']) > 30 else paper['title']
                    nodes.append({
                        "id": paper_id,
                        "label": title,
                        "type": "Paper",
                        "size": 10,
                        "pmid": paper['pmid']
                    })
                    node_ids.add(paper_id)

                edges.append({
                    "source": search_node["id"],
                    "target": paper_id,
                    "type": "FOUND",
                    "weight": paper.get('relevance', 1)
                })

                # 논문의 저자 조회
                author_query = """
                MATCH (p:Paper {pmid: $pmid})-[:AUTHORED_BY]->(a:Author)
                RETURN a.name as name
                LIMIT 5
                """
                authors = self._execute_query(author_query, {"pmid": paper['pmid']})
                for author in authors:
                    author_id = f"author_{author['name']}"
                    if author_id not in node_ids:
                        # 이름을 20자로 제한
                        name = author['name'][:20] + "..." if len(author['name']) > 20 else author['name']
                        nodes.append({
                            "id": author_id,
                            "label": name,
                            "type": "Author",
                            "size": 5
                        })
                        node_ids.add(author_id)

                    edges.append({
                        "source": paper_id,
                        "target": author_id,
                        "type": "AUTHORED_BY",
                        "weight": 1
                    })

                # 논문의 키워드 조회
                keyword_query = """
                MATCH (p:Paper {pmid: $pmid})-[:MENTIONS]->(k:Keyword)
                RETURN k.term as term
                LIMIT 5
                """
                keywords = self._execute_query(keyword_query, {"pmid": paper['pmid']})
                for keyword in keywords:
                    keyword_id = f"keyword_{keyword['term']}"
                    if keyword_id not in node_ids:
                        nodes.append({
                            "id": keyword_id,
                            "label": keyword['term'],
                            "type": "Keyword",
                            "size": 7
                        })
                        node_ids.add(keyword_id)

                    edges.append({
                        "source": paper_id,
                        "target": keyword_id,
                        "type": "MENTIONS",
                        "weight": 1
                    })

        else:
            # 검색어 없이 전체 네트워크 - 최근 논문과 관련 저자/키워드
            paper_query = """
            MATCH (p:Paper)
            RETURN p.pmid as pmid, p.title as title
            ORDER BY p.created_at DESC
            LIMIT $limit
            """
            papers = self._execute_query(paper_query, {"limit": min(limit, 20)})

            for paper in papers:
                paper_id = f"paper_{paper['pmid']}"
                if paper_id not in node_ids:
                    title = paper['title'][:30] + "..." if len(paper['title']) > 30 else paper['title']
                    nodes.append({
                        "id": paper_id,
                        "label": title,
                        "type": "Paper",
                        "size": 10,
                        "pmid": paper['pmid']
                    })
                    node_ids.add(paper_id)

                # 저자 조회
                author_query = """
                MATCH (p:Paper {pmid: $pmid})-[:AUTHORED_BY]->(a:Author)
                RETURN a.name as name
                LIMIT 3
                """
                authors = self._execute_query(author_query, {"pmid": paper['pmid']})
                for author in authors:
                    author_id = f"author_{author['name']}"
                    if author_id not in node_ids:
                        name = author['name'][:20] + "..." if len(author['name']) > 20 else author['name']
                        nodes.append({
                            "id": author_id,
                            "label": name,
                            "type": "Author",
                            "size": 5
                        })
                        node_ids.add(author_id)

                    edges.append({
                        "source": paper_id,
                        "target": author_id,
                        "type": "AUTHORED_BY",
                        "weight": 1
                    })

                # 키워드 조회
                keyword_query = """
                MATCH (p:Paper {pmid: $pmid})-[:MENTIONS]->(k:Keyword)
                RETURN k.term as term
                LIMIT 3
                """
                keywords = self._execute_query(keyword_query, {"pmid": paper['pmid']})
                for keyword in keywords:
                    keyword_id = f"keyword_{keyword['term']}"
                    if keyword_id not in node_ids:
                        nodes.append({
                            "id": keyword_id,
                            "label": keyword['term'],
                            "type": "Keyword",
                            "size": 7
                        })
                        node_ids.add(keyword_id)

                    edges.append({
                        "source": paper_id,
                        "target": keyword_id,
                        "type": "MENTIONS",
                        "weight": 1
                    })

        return {
            "nodes": nodes,
            "edges": edges,
            "search_term": search_term
        }

    def get_stats(self) -> Dict:
        """그래프 통계"""
        stats = {}

        # 노드 수
        node_counts = self._execute_query("""
            MATCH (n)
            RETURN labels(n)[0] as label, count(n) as count
        """)
        stats["nodes"] = {item["label"]: item["count"] for item in node_counts}

        # 관계 수
        rel_counts = self._execute_query("""
            MATCH ()-[r]->()
            RETURN type(r) as type, count(r) as count
        """)
        stats["relationships"] = {item["type"]: item["count"] for item in rel_counts}

        return stats


# 싱글톤 인스턴스
_graph_service: Optional[Neo4jService] = None


def get_graph_service() -> Neo4jService:
    """GraphDB 서비스 인스턴스 반환"""
    global _graph_service
    if _graph_service is None:
        _graph_service = Neo4jService()
    return _graph_service


def close_graph_service():
    """GraphDB 서비스 종료"""
    global _graph_service
    if _graph_service:
        _graph_service.close()
        _graph_service = None
