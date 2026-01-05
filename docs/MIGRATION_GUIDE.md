# 3D Graph 마이그레이션 가이드

이 문서는 Obsidian 3D Graph 플러그인의 핵심 기술을 다른 프로젝트에 적용하기 위한 상세 가이드입니다.

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [아키텍처 분석](#2-아키텍처-분석)
3. [핵심 의존성](#3-핵심-의존성)
4. [데이터 구조 마이그레이션](#4-데이터-구조-마이그레이션)
5. [3D 렌더링 엔진 통합](#5-3d-렌더링-엔진-통합)
6. [상태 관리 시스템](#6-상태-관리-시스템)
7. [설정 시스템 구현](#7-설정-시스템-구현)
8. [이벤트 핸들링](#8-이벤트-핸들링)
9. [프레임워크별 통합 예제](#9-프레임워크별-통합-예제)
10. [성능 최적화](#10-성능-최적화)

---

## 1. 프로젝트 개요

### 원본 프로젝트 구조

```
src/
├── graph/                    # 핵심 데이터 구조
│   ├── Graph.ts             # 그래프 컨테이너 & 알고리즘
│   ├── Node.ts              # 노드 표현
│   └── Link.ts              # 엣지/링크 표현
├── settings/                # 설정 시스템
│   ├── GraphSettings.ts
│   └── categories/
│       ├── DisplaySettings.ts
│       ├── FilterSettings.ts
│       └── GroupSettings.ts
├── util/                    # 유틸리티
│   ├── State.ts            # 반응형 상태 관리
│   ├── EventBus.ts         # 이벤트 시스템
│   └── ObsidianTheme.ts    # 테마 추출
├── views/                   # UI 컴포넌트
│   ├── graph/
│   │   ├── Graph3dView.ts  # 메인 뷰 컨테이너
│   │   └── ForceGraph.ts   # 3D 그래프 렌더러
│   └── settings/
└── main.ts                  # 엔트리 포인트
```

### 핵심 기술 스택

| 기술 | 역할 | 대체 가능 |
|------|------|----------|
| **3d-force-graph** | 3D 렌더링 엔진 | Three.js 직접 사용 |
| **D3.js** | 포스 시뮬레이션 | 자체 물리 엔진 |
| **observable-slim** | 반응형 상태 | MobX, Zustand, Redux |
| **TypeScript** | 타입 안전성 | JavaScript |

---

## 2. 아키텍처 분석

### 데이터 흐름도

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Data Source   │────▶│   Graph Model    │────▶│  Force Graph    │
│  (Files, API)   │     │ (Nodes, Links)   │     │   Renderer      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │                         │
                               ▼                         ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │  Settings State  │────▶│    3D Scene     │
                        │   (Observable)   │     │   (Three.js)    │
                        └──────────────────┘     └─────────────────┘
```

### 레이어 분리

```typescript
// Layer 1: Data Layer (순수 데이터 구조)
class Node { id, name, neighbors, links }
class Link { source, target }
class Graph { nodes, links, getLocalGraph() }

// Layer 2: State Layer (반응형 상태)
class State<T> { value, onChange() }

// Layer 3: Rendering Layer (3D 시각화)
class ForceGraph { instance, createNodes(), createLinks() }

// Layer 4: View Layer (UI 통합)
class Graph3dView { forceGraph, settings }
```

---

## 3. 핵심 의존성

### 필수 패키지 설치

```bash
# NPM
npm install 3d-force-graph d3 observable-slim

# Yarn
yarn add 3d-force-graph d3 observable-slim

# PNPM
pnpm add 3d-force-graph d3 observable-slim
```

### TypeScript 타입 정의

```bash
npm install -D @types/d3
```

### package.json 예시

```json
{
  "dependencies": {
    "3d-force-graph": "^1.70.12",
    "d3": "^7.6.1",
    "observable-slim": "^0.1.6"
  },
  "devDependencies": {
    "@types/d3": "^7.4.0",
    "typescript": "^5.0.0"
  }
}
```

---

## 4. 데이터 구조 마이그레이션

### 4.1 Node 클래스

```typescript
// src/graph/Node.ts
export interface INode {
  id: string;
  name: string;
  val?: number;
  neighbors: INode[];
  links: ILink[];
  [key: string]: any; // 추가 데이터용
}

export default class Node implements INode {
  public readonly id: string;
  public readonly name: string;
  public readonly val: number;
  public readonly neighbors: Node[] = [];
  public readonly links: Link[] = [];

  // 커스텀 속성 (프로젝트별 확장)
  public readonly metadata: Record<string, any>;

  constructor(
    id: string,
    name: string,
    metadata: Record<string, any> = {}
  ) {
    this.id = id;
    this.name = name;
    this.val = 10; // 노드 크기 가중치
    this.metadata = metadata;
  }

  /**
   * 이웃 노드 추가 및 링크 생성
   */
  addNeighbor(neighbor: Node): Link | null {
    if (!this.isNeighborOf(neighbor)) {
      const link = new Link(this.id, neighbor.id);

      this.neighbors.push(neighbor);
      this.links.push(link);

      neighbor.neighbors.push(this);
      neighbor.links.push(link);

      return link;
    }
    return null;
  }

  isNeighborOf(node: Node): boolean {
    return this.neighbors.some(n => n.id === node.id);
  }

  /**
   * 데이터 소스에서 노드 배열 생성
   * @example API 응답에서 변환
   */
  static createFromData<T extends { id: string; name: string }>(
    items: T[]
  ): [Node[], Map<string, number>] {
    const nodeMap = new Map<string, number>();
    const nodes: Node[] = [];

    items.forEach((item, index) => {
      if (!nodeMap.has(item.id)) {
        const node = new Node(item.id, item.name, item);
        nodeMap.set(item.id, index);
        nodes.push(node);
      }
    });

    return [nodes, nodeMap];
  }
}
```

### 4.2 Link 클래스

```typescript
// src/graph/Link.ts
export interface ILink {
  source: string;
  target: string;
  value?: number;
}

export default class Link implements ILink {
  public readonly source: string;
  public readonly target: string;
  public readonly value: number;

  // 커스텀 속성
  public readonly metadata: Record<string, any>;

  constructor(
    source: string,
    target: string,
    metadata: Record<string, any> = {}
  ) {
    this.source = source;
    this.target = target;
    this.value = 1;
    this.metadata = metadata;
  }

  /**
   * 관계 데이터에서 링크 배열 생성
   * @example { "nodeA": ["nodeB", "nodeC"], "nodeB": ["nodeD"] }
   */
  static createFromRelations(
    relations: Record<string, string[]>,
    nodes: Node[],
    nodeIndex: Map<string, number>
  ): [Link[], Map<string, Map<string, number>>] {
    const links: Link[] = [];
    const linkIndex = new Map<string, Map<string, number>>();

    Object.entries(relations).forEach(([sourceId, targetIds]) => {
      targetIds.forEach(targetId => {
        const sourceIdx = nodeIndex.get(sourceId);
        const targetIdx = nodeIndex.get(targetId);

        if (sourceIdx !== undefined && targetIdx !== undefined) {
          const link = nodes[sourceIdx].addNeighbor(nodes[targetIdx]);
          if (link) {
            links.push(link);
          }
        }
      });
    });

    // 링크 인덱스 생성 (O(1) 조회용)
    links.forEach((link, index) => {
      if (!linkIndex.has(link.source)) {
        linkIndex.set(link.source, new Map());
      }
      linkIndex.get(link.source)!.set(link.target, index);
    });

    return [links, linkIndex];
  }
}
```

### 4.3 Graph 클래스

```typescript
// src/graph/Graph.ts
import Node from './Node';
import Link from './Link';

export default class Graph {
  public readonly nodes: Node[];
  public readonly links: Link[];
  private readonly nodeIndex: Map<string, number>;
  private readonly linkIndex: Map<string, Map<string, number>>;

  constructor(
    nodes: Node[],
    links: Link[],
    nodeIndex: Map<string, number>,
    linkIndex: Map<string, Map<string, number>>
  ) {
    this.nodes = nodes;
    this.links = links;
    this.nodeIndex = nodeIndex;
    this.linkIndex = linkIndex;
  }

  /**
   * ID로 노드 조회 (O(1))
   */
  getNodeById(id: string): Node | null {
    const index = this.nodeIndex.get(id);
    return index !== undefined ? this.nodes[index] : null;
  }

  /**
   * Source-Target ID로 링크 조회 (O(1))
   */
  getLinkByIds(sourceId: string, targetId: string): Link | null {
    const sourceLinks = this.linkIndex.get(sourceId);
    if (!sourceLinks) return null;

    const index = sourceLinks.get(targetId);
    return index !== undefined ? this.links[index] : null;
  }

  /**
   * 특정 노드에 연결된 모든 링크 조회
   */
  getLinksWithNode(nodeId: string): Link[] {
    return this.links.filter(
      link => link.source === nodeId || link.target === nodeId
    );
  }

  /**
   * 로컬 그래프 추출 (중심 노드 + 1-hop 이웃)
   * 대규모 그래프에서 부분 시각화에 유용
   */
  getLocalGraph(nodeId: string): Graph {
    const centerNode = this.getNodeById(nodeId);
    if (!centerNode) {
      return new Graph([], [], new Map(), new Map());
    }

    // 중심 노드 + 이웃 노드
    const localNodes = [centerNode, ...centerNode.neighbors];
    const localNodeIndex = new Map<string, number>();

    localNodes.forEach((node, index) => {
      localNodeIndex.set(node.id, index);
    });

    // 로컬 노드 간의 링크만 필터
    const localLinks: Link[] = [];
    const localLinkIndex = new Map<string, Map<string, number>>();

    this.links.forEach(link => {
      if (localNodeIndex.has(link.source) && localNodeIndex.has(link.target)) {
        const linkIdx = localLinks.length;
        localLinks.push(link);

        if (!localLinkIndex.has(link.source)) {
          localLinkIndex.set(link.source, new Map());
        }
        localLinkIndex.get(link.source)!.set(link.target, linkIdx);
      }
    });

    return new Graph(localNodes, localLinks, localNodeIndex, localLinkIndex);
  }

  /**
   * 그래프 복제
   */
  clone(): Graph {
    return new Graph(
      [...this.nodes],
      [...this.links],
      new Map(this.nodeIndex),
      new Map(this.linkIndex)
    );
  }

  /**
   * 데이터 소스에서 그래프 생성 (팩토리 메서드)
   *
   * @example
   * const data = {
   *   items: [{ id: 'a', name: 'Node A' }, { id: 'b', name: 'Node B' }],
   *   relations: { 'a': ['b'] }
   * };
   * const graph = Graph.createFromData(data);
   */
  static createFromData(data: {
    items: Array<{ id: string; name: string; [key: string]: any }>;
    relations: Record<string, string[]>;
  }): Graph {
    const [nodes, nodeIndex] = Node.createFromData(data.items);
    const [links, linkIndex] = Link.createFromRelations(
      data.relations,
      nodes,
      nodeIndex
    );

    return new Graph(nodes, links, nodeIndex, linkIndex);
  }
}
```

### 4.4 사용 예시: API 데이터 변환

```typescript
// 예시: REST API 응답을 그래프로 변환
interface ApiNode {
  id: string;
  title: string;
  category: string;
  connections: string[];
}

async function fetchAndCreateGraph(apiUrl: string): Promise<Graph> {
  const response = await fetch(apiUrl);
  const apiData: ApiNode[] = await response.json();

  // 노드 데이터 변환
  const items = apiData.map(node => ({
    id: node.id,
    name: node.title,
    category: node.category
  }));

  // 관계 데이터 변환
  const relations: Record<string, string[]> = {};
  apiData.forEach(node => {
    relations[node.id] = node.connections;
  });

  return Graph.createFromData({ items, relations });
}

// 사용
const graph = await fetchAndCreateGraph('/api/knowledge-graph');
console.log(`Loaded ${graph.nodes.length} nodes, ${graph.links.length} links`);
```

---

## 5. 3D 렌더링 엔진 통합

### 5.1 ForceGraph 클래스 (핵심)

```typescript
// src/views/ForceGraph.ts
import ForceGraph3D, { ForceGraph3DInstance } from '3d-force-graph';
import Graph from '../graph/Graph';
import Node from '../graph/Node';
import Link from '../graph/Link';

export interface ForceGraphConfig {
  nodeSize: number;
  linkThickness: number;
  particleCount: number;
  particleSize: number;
  backgroundColor: string;
  nodeColor: string;
  linkColor: string;
  highlightColor: string;
}

export const DEFAULT_CONFIG: ForceGraphConfig = {
  nodeSize: 4,
  linkThickness: 2,
  particleCount: 4,
  particleSize: 4,
  backgroundColor: 'rgba(0,0,0,0)',
  nodeColor: '#888888',
  linkColor: '#444444',
  highlightColor: '#ff6600'
};

export default class ForceGraph {
  private instance: ForceGraph3DInstance;
  private graph: Graph;
  private config: ForceGraphConfig;
  private rootElement: HTMLElement;

  // 하이라이트 상태
  private hoveredNode: Node | null = null;
  private highlightedNodes = new Set<string>();
  private highlightedLinks = new Set<Link>();

  constructor(
    rootElement: HTMLElement,
    graph: Graph,
    config: Partial<ForceGraphConfig> = {}
  ) {
    this.rootElement = rootElement;
    this.graph = graph;
    this.config = { ...DEFAULT_CONFIG, ...config };

    this.createInstance();
    this.setupNodes();
    this.setupLinks();
    this.setupInteractions();
  }

  /**
   * 3D Force Graph 인스턴스 생성
   */
  private createInstance(): void {
    const { width, height } = this.rootElement.getBoundingClientRect();

    this.instance = ForceGraph3D()(this.rootElement)
      .graphData(this.getGraphData())
      .width(width)
      .height(height)
      .backgroundColor(this.config.backgroundColor)
      .nodeRelSize(this.config.nodeSize)
      .nodeLabel((node: Node) =>
        `<div class="node-label">${node.name}</div>`
      );
  }

  /**
   * 그래프 데이터 포맷 변환
   */
  private getGraphData(): { nodes: Node[]; links: Link[] } {
    return {
      nodes: this.graph.nodes,
      links: this.graph.links
    };
  }

  /**
   * 노드 렌더링 설정
   */
  private setupNodes(): void {
    this.instance
      .nodeColor((node: Node) => this.getNodeColor(node))
      .nodeVisibility((node: Node) => this.isNodeVisible(node))
      .onNodeHover(this.handleNodeHover.bind(this))
      .onNodeClick(this.handleNodeClick.bind(this));
  }

  /**
   * 링크 렌더링 설정
   */
  private setupLinks(): void {
    this.instance
      .linkWidth((link: Link) =>
        this.isHighlightedLink(link)
          ? this.config.linkThickness * 1.5
          : this.config.linkThickness
      )
      .linkColor((link: Link) =>
        this.isHighlightedLink(link)
          ? this.config.highlightColor
          : this.config.linkColor
      )
      .linkDirectionalParticles((link: Link) =>
        this.isHighlightedLink(link) ? this.config.particleCount : 0
      )
      .linkDirectionalParticleWidth(this.config.particleSize)
      .linkVisibility((link: Link) => this.isLinkVisible(link))
      .onLinkHover(this.handleLinkHover.bind(this));
  }

  /**
   * 카메라 및 컨트롤 설정
   */
  private setupInteractions(): void {
    // 초기 카메라 위치
    this.instance.cameraPosition({ z: 500 });

    // 리사이즈 핸들러
    const resizeObserver = new ResizeObserver(() => {
      const { width, height } = this.rootElement.getBoundingClientRect();
      this.instance.width(width).height(height);
    });
    resizeObserver.observe(this.rootElement);
  }

  /**
   * 노드 색상 결정
   */
  private getNodeColor(node: Node): string {
    if (this.isHighlightedNode(node)) {
      return node === this.hoveredNode
        ? this.config.highlightColor
        : this.lightenColor(this.config.highlightColor, 0.3);
    }
    return this.config.nodeColor;
  }

  /**
   * 노드 하이라이트 여부
   */
  private isHighlightedNode(node: Node): boolean {
    return this.highlightedNodes.has(node.id);
  }

  /**
   * 링크 하이라이트 여부
   */
  private isHighlightedLink(link: Link): boolean {
    return this.highlightedLinks.has(link);
  }

  /**
   * 노드 표시 여부 (필터링용)
   */
  private isNodeVisible(node: Node): boolean {
    // 기본적으로 모든 노드 표시
    // 필터 로직 추가 가능
    return true;
  }

  /**
   * 링크 표시 여부
   */
  private isLinkVisible(link: Link): boolean {
    return true;
  }

  /**
   * 노드 호버 핸들러
   */
  private handleNodeHover(node: Node | null): void {
    if ((!node && !this.highlightedNodes.size) ||
        (node && this.hoveredNode === node)) {
      return;
    }

    this.clearHighlights();

    if (node) {
      // 호버된 노드 하이라이트
      this.highlightedNodes.add(node.id);

      // 이웃 노드 하이라이트
      node.neighbors.forEach(neighbor => {
        this.highlightedNodes.add(neighbor.id);
      });

      // 연결된 링크 하이라이트
      const nodeLinks = this.graph.getLinksWithNode(node.id);
      nodeLinks.forEach(link => this.highlightedLinks.add(link));
    }

    this.hoveredNode = node;
    this.updateHighlight();
  }

  /**
   * 링크 호버 핸들러
   */
  private handleLinkHover(link: Link | null): void {
    this.clearHighlights();

    if (link) {
      this.highlightedLinks.add(link);
      this.highlightedNodes.add(link.source);
      this.highlightedNodes.add(link.target);
    }

    this.updateHighlight();
  }

  /**
   * 노드 클릭 핸들러
   */
  private handleNodeClick(node: Node, event: MouseEvent): void {
    // 커스텀 이벤트 발생
    const customEvent = new CustomEvent('nodeClick', {
      detail: { node, event }
    });
    this.rootElement.dispatchEvent(customEvent);

    // 노드로 카메라 이동
    this.focusOnNode(node);
  }

  /**
   * 특정 노드로 카메라 포커스
   */
  public focusOnNode(node: Node): void {
    const distance = 100;
    const distRatio = 1 + distance /
      Math.hypot((node as any).x, (node as any).y, (node as any).z);

    this.instance.cameraPosition(
      {
        x: (node as any).x * distRatio,
        y: (node as any).y * distRatio,
        z: (node as any).z * distRatio
      },
      node as any,
      2000 // 애니메이션 duration (ms)
    );
  }

  /**
   * 하이라이트 초기화
   */
  private clearHighlights(): void {
    this.highlightedNodes.clear();
    this.highlightedLinks.clear();
  }

  /**
   * 렌더링 업데이트
   */
  private updateHighlight(): void {
    this.instance
      .nodeColor(this.instance.nodeColor())
      .linkWidth(this.instance.linkWidth())
      .linkColor(this.instance.linkColor())
      .linkDirectionalParticles(this.instance.linkDirectionalParticles());
  }

  /**
   * 색상 밝기 조정 유틸리티
   */
  private lightenColor(color: string, percent: number): string {
    const num = parseInt(color.replace('#', ''), 16);
    const amt = Math.round(2.55 * percent * 100);
    const R = Math.min(255, (num >> 16) + amt);
    const G = Math.min(255, ((num >> 8) & 0x00FF) + amt);
    const B = Math.min(255, (num & 0x0000FF) + amt);
    return `#${(0x1000000 + R * 0x10000 + G * 0x100 + B)
      .toString(16).slice(1)}`;
  }

  // ========== Public API ==========

  /**
   * 그래프 데이터 업데이트
   */
  public updateGraph(graph: Graph): void {
    this.graph = graph;
    this.instance.graphData(this.getGraphData());
  }

  /**
   * 설정 업데이트
   */
  public updateConfig(config: Partial<ForceGraphConfig>): void {
    this.config = { ...this.config, ...config };

    if (config.nodeSize !== undefined) {
      this.instance.nodeRelSize(config.nodeSize);
    }
    if (config.backgroundColor !== undefined) {
      this.instance.backgroundColor(config.backgroundColor);
    }

    this.instance.refresh();
  }

  /**
   * 새로고침
   */
  public refresh(): void {
    this.instance.refresh();
  }

  /**
   * 인스턴스 반환 (고급 커스터마이징용)
   */
  public getInstance(): ForceGraph3DInstance {
    return this.instance;
  }

  /**
   * 리소스 정리
   */
  public dispose(): void {
    this.instance._destructor();
  }
}
```

### 5.2 간단한 사용 예시

```typescript
// 기본 사용법
import ForceGraph from './views/ForceGraph';
import Graph from './graph/Graph';

// 컨테이너 준비
const container = document.getElementById('graph-container')!;
container.style.width = '100%';
container.style.height = '600px';

// 샘플 데이터
const sampleData = {
  items: [
    { id: '1', name: 'JavaScript' },
    { id: '2', name: 'TypeScript' },
    { id: '3', name: 'React' },
    { id: '4', name: 'Vue' },
    { id: '5', name: 'Angular' }
  ],
  relations: {
    '1': ['2', '3', '4', '5'],
    '2': ['3', '5'],
    '3': ['4']
  }
};

// 그래프 생성 및 렌더링
const graph = Graph.createFromData(sampleData);
const forceGraph = new ForceGraph(container, graph, {
  nodeSize: 6,
  highlightColor: '#00ff88',
  backgroundColor: '#1a1a2e'
});

// 노드 클릭 이벤트 리스닝
container.addEventListener('nodeClick', (e: CustomEvent) => {
  console.log('Clicked node:', e.detail.node);
});
```

---

## 6. 상태 관리 시스템

### 6.1 State 클래스 (반응형 상태)

```typescript
// src/util/State.ts
import ObservableSlim from 'observable-slim';

export interface StateChange {
  type: 'add' | 'delete' | 'update';
  property: string;
  currentPath: string;
  target: any;
  previousValue?: any;
  newValue?: any;
}

export type StateListener = (change: StateChange) => void;

export default class State<T> {
  private val: T;
  private proxy: T;
  private readonly listeners = new Map<number, StateListener>();
  private listenerIdCounter = 0;

  constructor(initialValue: T, useProxy = true) {
    this.val = initialValue;

    if (useProxy && typeof initialValue === 'object' && initialValue !== null) {
      this.proxy = ObservableSlim.create(
        initialValue,
        true, // deep observe
        (changes: StateChange[]) => {
          changes.forEach(change => {
            this.listeners.forEach(listener => listener(change));
          });
        }
      );
    } else {
      this.proxy = initialValue;
    }
  }

  /**
   * 현재 값 조회
   */
  get value(): T {
    return this.proxy;
  }

  /**
   * 값 설정 (전체 교체)
   */
  set value(newVal: T) {
    const oldVal = this.val;
    this.val = newVal;

    if (typeof newVal === 'object' && newVal !== null) {
      this.proxy = ObservableSlim.create(
        newVal,
        true,
        (changes: StateChange[]) => {
          changes.forEach(change => {
            this.listeners.forEach(listener => listener(change));
          });
        }
      );
    } else {
      this.proxy = newVal;
    }

    // 전체 교체 알림
    this.listeners.forEach(listener => {
      listener({
        type: 'update',
        property: '',
        currentPath: '',
        target: newVal,
        previousValue: oldVal,
        newValue: newVal
      });
    });
  }

  /**
   * 원본 값 조회 (프록시 아님)
   */
  getRawValue(): T {
    return this.val;
  }

  /**
   * 변경 구독
   */
  onChange(callback: StateListener): () => void {
    const id = this.listenerIdCounter++;
    this.listeners.set(id, callback);

    // 구독 해제 함수 반환
    return () => {
      this.listeners.delete(id);
    };
  }

  /**
   * 하위 상태 생성 (특정 경로만 구독)
   */
  createSubState<K extends keyof T>(key: K): State<T[K]> {
    const subState = new State(this.value[key], false);

    this.onChange(change => {
      if (change.currentPath.startsWith(String(key))) {
        // 하위 상태에도 변경 전파
        (subState as any).listeners.forEach((listener: StateListener) => {
          listener({
            ...change,
            currentPath: change.currentPath.replace(`${String(key)}.`, '')
          });
        });
      }
    });

    return subState;
  }
}
```

### 6.2 EventBus 클래스

```typescript
// src/util/EventBus.ts
type EventHandler = (...args: any[]) => void;

class EventBus {
  private events = new Map<string, Set<EventHandler>>();

  /**
   * 이벤트 구독
   */
  on(event: string, handler: EventHandler): () => void {
    if (!this.events.has(event)) {
      this.events.set(event, new Set());
    }
    this.events.get(event)!.add(handler);

    // 구독 해제 함수 반환
    return () => this.off(event, handler);
  }

  /**
   * 구독 해제
   */
  off(event: string, handler: EventHandler): void {
    this.events.get(event)?.delete(handler);
  }

  /**
   * 이벤트 발생
   */
  trigger(event: string, ...args: any[]): void {
    this.events.get(event)?.forEach(handler => {
      try {
        handler(...args);
      } catch (error) {
        console.error(`EventBus error in "${event}":`, error);
      }
    });
  }

  /**
   * 일회성 구독
   */
  once(event: string, handler: EventHandler): () => void {
    const onceHandler = (...args: any[]) => {
      this.off(event, onceHandler);
      handler(...args);
    };
    return this.on(event, onceHandler);
  }
}

// 싱글톤 인스턴스
export default new EventBus();
```

### 6.3 상태 관리 사용 예시

```typescript
import State from './util/State';
import EventBus from './util/EventBus';

// 설정 상태 생성
interface AppSettings {
  display: {
    nodeSize: number;
    theme: 'light' | 'dark';
  };
  filters: {
    showOrphans: boolean;
    minConnections: number;
  };
}

const settingsState = new State<AppSettings>({
  display: { nodeSize: 4, theme: 'dark' },
  filters: { showOrphans: true, minConnections: 0 }
});

// 변경 구독
const unsubscribe = settingsState.onChange(change => {
  console.log(`Setting changed: ${change.currentPath}`);
  console.log(`  Old: ${change.previousValue} -> New: ${change.newValue}`);

  // 자동 저장
  localStorage.setItem('settings', JSON.stringify(settingsState.getRawValue()));
});

// 값 변경 (자동으로 구독자에게 알림)
settingsState.value.display.nodeSize = 6;
settingsState.value.filters.showOrphans = false;

// 이벤트 버스 사용
EventBus.on('graph-refresh', () => {
  console.log('Refreshing graph...');
});

EventBus.trigger('graph-refresh');

// 정리
unsubscribe();
```

---

## 7. 설정 시스템 구현

### 7.1 설정 클래스들

```typescript
// src/settings/DisplaySettings.ts
export class DisplaySettings {
  nodeSize = 4;
  linkThickness = 2;
  particleSize = 4;
  particleCount = 4;
  showLabels = true;

  static fromStore(data: any): DisplaySettings {
    const settings = new DisplaySettings();
    if (data) {
      Object.assign(settings, data);
    }
    return settings;
  }

  toObject(): Record<string, any> {
    return { ...this };
  }

  reset(): void {
    Object.assign(this, new DisplaySettings());
  }
}

// src/settings/FilterSettings.ts
export class FilterSettings {
  showOrphans = true;
  showAttachments = false;
  minConnections = 0;
  searchQuery = '';

  static fromStore(data: any): FilterSettings {
    const settings = new FilterSettings();
    if (data) {
      Object.assign(settings, data);
    }
    return settings;
  }

  toObject(): Record<string, any> {
    return { ...this };
  }

  reset(): void {
    Object.assign(this, new FilterSettings());
  }
}

// src/settings/GroupSettings.ts
export interface NodeGroup {
  id: string;
  name: string;
  query: string;  // 매칭 쿼리 (예: "tag:important", "folder/")
  color: string;
}

export class GroupSettings {
  groups: NodeGroup[] = [];

  addGroup(group: NodeGroup): void {
    this.groups.push(group);
  }

  removeGroup(id: string): void {
    this.groups = this.groups.filter(g => g.id !== id);
  }

  /**
   * 노드가 그룹에 매칭되는지 확인
   */
  static matches(query: string, node: Node): boolean {
    // 태그 쿼리: "tag:javascript"
    if (query.startsWith('tag:')) {
      const tag = query.replace('tag:', '');
      return node.metadata?.tags?.includes(tag) ?? false;
    }

    // 경로 쿼리: "folder/"
    if (query.endsWith('/')) {
      return node.id.startsWith(query);
    }

    // 이름 쿼리
    return node.name.toLowerCase().includes(query.toLowerCase());
  }

  static fromStore(data: any): GroupSettings {
    const settings = new GroupSettings();
    if (data?.groups) {
      settings.groups = data.groups;
    }
    return settings;
  }

  toObject(): Record<string, any> {
    return { groups: [...this.groups] };
  }

  reset(): void {
    this.groups = [];
  }
}

// src/settings/GraphSettings.ts
import { DisplaySettings } from './DisplaySettings';
import { FilterSettings } from './FilterSettings';
import { GroupSettings } from './GroupSettings';

export default class GraphSettings {
  display: DisplaySettings;
  filters: FilterSettings;
  groups: GroupSettings;

  constructor(
    display = new DisplaySettings(),
    filters = new FilterSettings(),
    groups = new GroupSettings()
  ) {
    this.display = display;
    this.filters = filters;
    this.groups = groups;
  }

  static fromStore(data: any): GraphSettings {
    return new GraphSettings(
      DisplaySettings.fromStore(data?.display),
      FilterSettings.fromStore(data?.filters),
      GroupSettings.fromStore(data?.groups)
    );
  }

  toObject(): Record<string, any> {
    return {
      display: this.display.toObject(),
      filters: this.filters.toObject(),
      groups: this.groups.toObject()
    };
  }

  reset(): void {
    this.display.reset();
    this.filters.reset();
    this.groups.reset();
  }
}
```

### 7.2 설정 UI 컴포넌트 (Vanilla JS)

```typescript
// src/views/settings/SettingsPanel.ts
import State from '../../util/State';
import GraphSettings from '../../settings/GraphSettings';

export function createSettingsPanel(
  container: HTMLElement,
  settingsState: State<GraphSettings>
): void {
  container.innerHTML = `
    <div class="settings-panel">
      <div class="settings-header">
        <h3>Graph Settings</h3>
        <button class="reset-btn" title="Reset to defaults">↺</button>
      </div>

      <div class="settings-section">
        <h4>Display</h4>
        <div class="setting-item">
          <label>Node Size</label>
          <input type="range" id="nodeSize" min="1" max="20"
                 value="${settingsState.value.display.nodeSize}">
          <span class="value">${settingsState.value.display.nodeSize}</span>
        </div>
        <div class="setting-item">
          <label>Link Thickness</label>
          <input type="range" id="linkThickness" min="1" max="10"
                 value="${settingsState.value.display.linkThickness}">
          <span class="value">${settingsState.value.display.linkThickness}</span>
        </div>
      </div>

      <div class="settings-section">
        <h4>Filters</h4>
        <div class="setting-item">
          <label>
            <input type="checkbox" id="showOrphans"
                   ${settingsState.value.filters.showOrphans ? 'checked' : ''}>
            Show orphan nodes
          </label>
        </div>
        <div class="setting-item">
          <label>Min Connections</label>
          <input type="number" id="minConnections" min="0"
                 value="${settingsState.value.filters.minConnections}">
        </div>
      </div>

      <div class="settings-section">
        <h4>Groups</h4>
        <div id="groupsList"></div>
        <button class="add-group-btn">+ Add Group</button>
      </div>
    </div>
  `;

  // 이벤트 바인딩
  const nodeSizeInput = container.querySelector('#nodeSize') as HTMLInputElement;
  const nodeSizeValue = nodeSizeInput.nextElementSibling as HTMLSpanElement;

  nodeSizeInput.addEventListener('input', (e) => {
    const value = parseInt((e.target as HTMLInputElement).value);
    settingsState.value.display.nodeSize = value;
    nodeSizeValue.textContent = String(value);
  });

  const linkThicknessInput = container.querySelector('#linkThickness') as HTMLInputElement;
  const linkThicknessValue = linkThicknessInput.nextElementSibling as HTMLSpanElement;

  linkThicknessInput.addEventListener('input', (e) => {
    const value = parseInt((e.target as HTMLInputElement).value);
    settingsState.value.display.linkThickness = value;
    linkThicknessValue.textContent = String(value);
  });

  const showOrphansInput = container.querySelector('#showOrphans') as HTMLInputElement;
  showOrphansInput.addEventListener('change', (e) => {
    settingsState.value.filters.showOrphans = (e.target as HTMLInputElement).checked;
  });

  const resetBtn = container.querySelector('.reset-btn') as HTMLButtonElement;
  resetBtn.addEventListener('click', () => {
    settingsState.value.reset();
    // UI 업데이트
    nodeSizeInput.value = String(settingsState.value.display.nodeSize);
    nodeSizeValue.textContent = String(settingsState.value.display.nodeSize);
    // ... 다른 필드들도 업데이트
  });
}
```

### 7.3 설정 CSS

```css
/* src/styles/settings.css */
.settings-panel {
  background: var(--bg-secondary, #1e1e2e);
  border-radius: 8px;
  padding: 16px;
  color: var(--text-primary, #cdd6f4);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  max-width: 300px;
}

.settings-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color, #45475a);
}

.settings-header h3 {
  margin: 0;
  font-size: 16px;
}

.reset-btn {
  background: none;
  border: none;
  color: var(--text-muted, #6c7086);
  cursor: pointer;
  font-size: 18px;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.2s;
}

.reset-btn:hover {
  background: var(--bg-hover, #313244);
}

.settings-section {
  margin-bottom: 16px;
}

.settings-section h4 {
  font-size: 12px;
  text-transform: uppercase;
  color: var(--text-muted, #6c7086);
  margin: 0 0 8px 0;
}

.setting-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.setting-item label {
  flex: 1;
  font-size: 13px;
}

.setting-item input[type="range"] {
  flex: 2;
  accent-color: var(--accent-color, #89b4fa);
}

.setting-item .value {
  min-width: 24px;
  text-align: right;
  font-size: 12px;
  color: var(--text-muted, #6c7086);
}

.setting-item input[type="number"] {
  width: 60px;
  padding: 4px 8px;
  border: 1px solid var(--border-color, #45475a);
  border-radius: 4px;
  background: var(--bg-primary, #11111b);
  color: var(--text-primary, #cdd6f4);
}

.add-group-btn {
  width: 100%;
  padding: 8px;
  border: 1px dashed var(--border-color, #45475a);
  background: none;
  color: var(--text-muted, #6c7086);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.add-group-btn:hover {
  border-color: var(--accent-color, #89b4fa);
  color: var(--accent-color, #89b4fa);
}
```

---

## 8. 이벤트 핸들링

### 8.1 이벤트 타입 정의

```typescript
// src/types/events.ts
import Node from '../graph/Node';
import Link from '../graph/Link';

export interface GraphEvents {
  'node-click': { node: Node; event: MouseEvent };
  'node-hover': { node: Node | null };
  'link-click': { link: Link; event: MouseEvent };
  'link-hover': { link: Link | null };
  'graph-refresh': void;
  'settings-change': { path: string; value: any };
  'settings-reset': void;
}

export type GraphEventName = keyof GraphEvents;
```

### 8.2 타입 안전한 이벤트 버스

```typescript
// src/util/TypedEventBus.ts
import { GraphEvents, GraphEventName } from '../types/events';

type EventHandler<T> = (payload: T) => void;

class TypedEventBus {
  private events = new Map<string, Set<EventHandler<any>>>();

  on<K extends GraphEventName>(
    event: K,
    handler: EventHandler<GraphEvents[K]>
  ): () => void {
    if (!this.events.has(event)) {
      this.events.set(event, new Set());
    }
    this.events.get(event)!.add(handler);
    return () => this.off(event, handler);
  }

  off<K extends GraphEventName>(
    event: K,
    handler: EventHandler<GraphEvents[K]>
  ): void {
    this.events.get(event)?.delete(handler);
  }

  emit<K extends GraphEventName>(
    event: K,
    payload: GraphEvents[K]
  ): void {
    this.events.get(event)?.forEach(handler => handler(payload));
  }
}

export default new TypedEventBus();
```

### 8.3 이벤트 사용 예시

```typescript
import TypedEventBus from './util/TypedEventBus';

// 타입 안전한 이벤트 구독
TypedEventBus.on('node-click', ({ node, event }) => {
  console.log(`Clicked: ${node.name}`);

  if (event.ctrlKey) {
    // Ctrl+클릭 처리
    openInNewTab(node);
  } else {
    // 일반 클릭 처리
    selectNode(node);
  }
});

TypedEventBus.on('settings-change', ({ path, value }) => {
  console.log(`Setting ${path} changed to ${value}`);

  // ForceGraph 업데이트
  if (path.startsWith('display.')) {
    forceGraph.updateConfig({
      [path.replace('display.', '')]: value
    });
  }
});

// 이벤트 발생
TypedEventBus.emit('node-click', {
  node: someNode,
  event: mouseEvent
});
```

---

## 9. 프레임워크별 통합 예제

### 9.1 React 통합

```tsx
// src/components/Graph3D.tsx
import React, { useEffect, useRef, useState, useCallback } from 'react';
import ForceGraph from '../views/ForceGraph';
import Graph from '../graph/Graph';
import State from '../util/State';
import GraphSettings from '../settings/GraphSettings';

interface Graph3DProps {
  data: {
    items: Array<{ id: string; name: string }>;
    relations: Record<string, string[]>;
  };
  onNodeClick?: (node: Node) => void;
  settings?: Partial<GraphSettings>;
}

export const Graph3D: React.FC<Graph3DProps> = ({
  data,
  onNodeClick,
  settings = {}
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const forceGraphRef = useRef<ForceGraph | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);

  // 그래프 데이터 생성
  useEffect(() => {
    const newGraph = Graph.createFromData(data);
    setGraph(newGraph);
  }, [data]);

  // ForceGraph 초기화
  useEffect(() => {
    if (!containerRef.current || !graph) return;

    const forceGraph = new ForceGraph(
      containerRef.current,
      graph,
      {
        nodeSize: settings.display?.nodeSize ?? 4,
        linkThickness: settings.display?.linkThickness ?? 2,
        highlightColor: '#ff6600'
      }
    );

    forceGraphRef.current = forceGraph;

    // 노드 클릭 이벤트
    containerRef.current.addEventListener('nodeClick', ((e: CustomEvent) => {
      onNodeClick?.(e.detail.node);
    }) as EventListener);

    return () => {
      forceGraph.dispose();
    };
  }, [graph, settings]);

  // 설정 업데이트
  useEffect(() => {
    if (forceGraphRef.current && settings.display) {
      forceGraphRef.current.updateConfig({
        nodeSize: settings.display.nodeSize,
        linkThickness: settings.display.linkThickness
      });
    }
  }, [settings]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', minHeight: '400px' }}
    />
  );
};

// 사용 예시
export const App: React.FC = () => {
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [settings, setSettings] = useState({
    display: { nodeSize: 4, linkThickness: 2 }
  });

  const graphData = {
    items: [
      { id: '1', name: 'React' },
      { id: '2', name: 'Vue' },
      { id: '3', name: 'Angular' }
    ],
    relations: {
      '1': ['2', '3'],
      '2': ['3']
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <div style={{ flex: 1 }}>
        <Graph3D
          data={graphData}
          settings={settings}
          onNodeClick={setSelectedNode}
        />
      </div>
      <div style={{ width: '300px', padding: '16px' }}>
        <h3>Selected: {selectedNode?.name ?? 'None'}</h3>
        <label>
          Node Size: {settings.display.nodeSize}
          <input
            type="range"
            min="1"
            max="20"
            value={settings.display.nodeSize}
            onChange={(e) => setSettings(prev => ({
              ...prev,
              display: { ...prev.display, nodeSize: Number(e.target.value) }
            }))}
          />
        </label>
      </div>
    </div>
  );
};
```

### 9.2 Vue 3 통합

```vue
<!-- src/components/Graph3D.vue -->
<template>
  <div ref="containerRef" class="graph-container"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, defineProps, defineEmits } from 'vue';
import ForceGraph from '../views/ForceGraph';
import Graph from '../graph/Graph';

interface Props {
  data: {
    items: Array<{ id: string; name: string }>;
    relations: Record<string, string[]>;
  };
  nodeSize?: number;
  linkThickness?: number;
}

const props = withDefaults(defineProps<Props>(), {
  nodeSize: 4,
  linkThickness: 2
});

const emit = defineEmits<{
  (e: 'node-click', node: any): void;
  (e: 'node-hover', node: any | null): void;
}>();

const containerRef = ref<HTMLDivElement | null>(null);
let forceGraph: ForceGraph | null = null;

onMounted(() => {
  if (!containerRef.value) return;

  const graph = Graph.createFromData(props.data);

  forceGraph = new ForceGraph(containerRef.value, graph, {
    nodeSize: props.nodeSize,
    linkThickness: props.linkThickness
  });

  containerRef.value.addEventListener('nodeClick', ((e: CustomEvent) => {
    emit('node-click', e.detail.node);
  }) as EventListener);
});

onUnmounted(() => {
  forceGraph?.dispose();
});

// 설정 변경 감지
watch(() => props.nodeSize, (newSize) => {
  forceGraph?.updateConfig({ nodeSize: newSize });
});

watch(() => props.linkThickness, (newThickness) => {
  forceGraph?.updateConfig({ linkThickness: newThickness });
});

// 데이터 변경 감지
watch(() => props.data, (newData) => {
  const graph = Graph.createFromData(newData);
  forceGraph?.updateGraph(graph);
}, { deep: true });
</script>

<style scoped>
.graph-container {
  width: 100%;
  height: 100%;
  min-height: 400px;
}
</style>
```

```vue
<!-- 사용 예시: App.vue -->
<template>
  <div class="app">
    <Graph3D
      :data="graphData"
      :node-size="settings.nodeSize"
      :link-thickness="settings.linkThickness"
      @node-click="handleNodeClick"
    />

    <div class="sidebar">
      <h3>Selected: {{ selectedNode?.name ?? 'None' }}</h3>

      <label>
        Node Size: {{ settings.nodeSize }}
        <input
          type="range"
          min="1"
          max="20"
          v-model.number="settings.nodeSize"
        />
      </label>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue';
import Graph3D from './components/Graph3D.vue';

const selectedNode = ref(null);
const settings = reactive({
  nodeSize: 4,
  linkThickness: 2
});

const graphData = {
  items: [
    { id: '1', name: 'Vue' },
    { id: '2', name: 'React' },
    { id: '3', name: 'Svelte' }
  ],
  relations: {
    '1': ['2'],
    '2': ['3']
  }
};

const handleNodeClick = (node: any) => {
  selectedNode.value = node;
};
</script>
```

### 9.3 Vanilla TypeScript (프레임워크 없음)

```typescript
// src/app.ts
import ForceGraph, { ForceGraphConfig } from './views/ForceGraph';
import Graph from './graph/Graph';
import State from './util/State';
import GraphSettings from './settings/GraphSettings';
import { createSettingsPanel } from './views/settings/SettingsPanel';

class App {
  private container: HTMLElement;
  private settingsContainer: HTMLElement;
  private forceGraph: ForceGraph | null = null;
  private settingsState: State<GraphSettings>;

  constructor() {
    this.container = document.getElementById('graph')!;
    this.settingsContainer = document.getElementById('settings')!;

    // 설정 상태 초기화 (로컬 스토리지에서 복원)
    const savedSettings = localStorage.getItem('graphSettings');
    const initialSettings = savedSettings
      ? GraphSettings.fromStore(JSON.parse(savedSettings))
      : new GraphSettings();

    this.settingsState = new State(initialSettings);

    // 설정 변경 시 저장
    this.settingsState.onChange(() => {
      localStorage.setItem(
        'graphSettings',
        JSON.stringify(this.settingsState.getRawValue().toObject())
      );
      this.onSettingsChanged();
    });

    this.init();
  }

  private async init(): Promise<void> {
    // 데이터 로드 (예: API에서)
    const data = await this.loadData();
    const graph = Graph.createFromData(data);

    // ForceGraph 생성
    this.forceGraph = new ForceGraph(this.container, graph, {
      nodeSize: this.settingsState.value.display.nodeSize,
      linkThickness: this.settingsState.value.display.linkThickness
    });

    // 설정 패널 생성
    createSettingsPanel(this.settingsContainer, this.settingsState);

    // 이벤트 리스닝
    this.container.addEventListener('nodeClick', ((e: CustomEvent) => {
      this.onNodeClick(e.detail.node);
    }) as EventListener);
  }

  private async loadData(): Promise<any> {
    // 실제 구현에서는 API 호출
    return {
      items: [
        { id: 'node1', name: 'Node 1' },
        { id: 'node2', name: 'Node 2' },
        { id: 'node3', name: 'Node 3' }
      ],
      relations: {
        'node1': ['node2', 'node3'],
        'node2': ['node3']
      }
    };
  }

  private onSettingsChanged(): void {
    if (!this.forceGraph) return;

    this.forceGraph.updateConfig({
      nodeSize: this.settingsState.value.display.nodeSize,
      linkThickness: this.settingsState.value.display.linkThickness
    });
  }

  private onNodeClick(node: any): void {
    console.log('Node clicked:', node);
    // 추가 로직 구현
  }
}

// 앱 시작
document.addEventListener('DOMContentLoaded', () => {
  new App();
});
```

```html
<!-- index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>3D Graph</title>
  <link rel="stylesheet" href="styles/main.css">
</head>
<body>
  <div class="layout">
    <div id="graph" class="graph-container"></div>
    <aside id="settings" class="settings-sidebar"></aside>
  </div>
  <script type="module" src="app.ts"></script>
</body>
</html>
```

---

## 10. 성능 최적화

### 10.1 대규모 그래프 처리

```typescript
// src/util/GraphOptimizer.ts

/**
 * 대규모 그래프 최적화 유틸리티
 */
export class GraphOptimizer {
  /**
   * 노드 수에 따른 설정 자동 조정
   */
  static getOptimalConfig(nodeCount: number): Partial<ForceGraphConfig> {
    if (nodeCount > 10000) {
      return {
        nodeSize: 1,
        linkThickness: 0.5,
        particleCount: 0, // 파티클 비활성화
      };
    } else if (nodeCount > 1000) {
      return {
        nodeSize: 2,
        linkThickness: 1,
        particleCount: 2,
      };
    }
    return {}; // 기본값 사용
  }

  /**
   * 청크 단위 데이터 로딩
   */
  static async* loadInChunks<T>(
    items: T[],
    chunkSize = 100,
    delayMs = 16
  ): AsyncGenerator<T[]> {
    for (let i = 0; i < items.length; i += chunkSize) {
      yield items.slice(i, i + chunkSize);
      await new Promise(resolve => setTimeout(resolve, delayMs));
    }
  }

  /**
   * 뷰포트 기반 노드 컬링
   */
  static cullNodesOutsideViewport(
    nodes: Node[],
    camera: THREE.Camera,
    threshold = 1.5
  ): Set<string> {
    const visibleNodes = new Set<string>();
    const frustum = new THREE.Frustum();
    frustum.setFromProjectionMatrix(
      new THREE.Matrix4().multiplyMatrices(
        camera.projectionMatrix,
        camera.matrixWorldInverse
      )
    );

    nodes.forEach(node => {
      const position = new THREE.Vector3(
        (node as any).x,
        (node as any).y,
        (node as any).z
      );

      if (frustum.containsPoint(position)) {
        visibleNodes.add(node.id);
      }
    });

    return visibleNodes;
  }
}

// 사용 예시
const nodeCount = graph.nodes.length;
const optimizedConfig = GraphOptimizer.getOptimalConfig(nodeCount);

const forceGraph = new ForceGraph(container, graph, {
  ...defaultConfig,
  ...optimizedConfig
});
```

### 10.2 메모리 관리

```typescript
// 인스턴스 정리 패턴
class GraphManager {
  private instance: ForceGraph | null = null;
  private unsubscribers: Array<() => void> = [];

  create(container: HTMLElement, graph: Graph): void {
    // 기존 인스턴스 정리
    this.dispose();

    this.instance = new ForceGraph(container, graph);

    // 이벤트 구독 추적
    const unsub = settingsState.onChange(() => {
      this.instance?.refresh();
    });
    this.unsubscribers.push(unsub);
  }

  dispose(): void {
    // 모든 구독 해제
    this.unsubscribers.forEach(unsub => unsub());
    this.unsubscribers = [];

    // 인스턴스 정리
    this.instance?.dispose();
    this.instance = null;
  }
}
```

### 10.3 렌더링 최적화

```typescript
// 렌더 루프 최적화
class OptimizedForceGraph extends ForceGraph {
  private rafId: number | null = null;
  private needsUpdate = false;

  /**
   * 배치 업데이트 (여러 변경사항을 한 프레임에 처리)
   */
  queueUpdate(): void {
    this.needsUpdate = true;

    if (this.rafId === null) {
      this.rafId = requestAnimationFrame(() => {
        if (this.needsUpdate) {
          this.getInstance().refresh();
          this.needsUpdate = false;
        }
        this.rafId = null;
      });
    }
  }

  /**
   * 디바운스된 설정 업데이트
   */
  private updateConfigDebounced = debounce(
    (config: Partial<ForceGraphConfig>) => {
      super.updateConfig(config);
    },
    100
  );

  updateConfig(config: Partial<ForceGraphConfig>): void {
    this.updateConfigDebounced(config);
  }
}

// 유틸리티: 디바운스 함수
function debounce<T extends (...args: any[]) => any>(
  fn: T,
  delay: number
): T {
  let timeoutId: ReturnType<typeof setTimeout>;

  return ((...args: Parameters<T>) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  }) as T;
}
```

---

## 마이그레이션 체크리스트

### 필수 단계

- [ ] 의존성 설치 (`3d-force-graph`, `d3`, `observable-slim`)
- [ ] Node, Link, Graph 클래스 복사/수정
- [ ] ForceGraph 클래스 복사/수정
- [ ] State 관리 시스템 구현
- [ ] 데이터 소스 어댑터 작성 (API → Graph 변환)

### 선택적 단계

- [ ] 설정 시스템 구현
- [ ] 이벤트 버스 구현
- [ ] 설정 UI 컴포넌트 작성
- [ ] 테마 시스템 통합
- [ ] 성능 최적화 적용

### 테스트 항목

- [ ] 그래프 렌더링 확인
- [ ] 노드 호버/클릭 동작
- [ ] 링크 하이라이팅
- [ ] 설정 변경 실시간 반영
- [ ] 메모리 누수 없음 확인
- [ ] 대규모 데이터 (1000+ 노드) 테스트

---

## 참고 자료

- [3d-force-graph 문서](https://github.com/vasturiano/3d-force-graph)
- [Three.js 문서](https://threejs.org/docs/)
- [D3.js Force Layout](https://d3js.org/d3-force)
- [observable-slim](https://github.com/AnnoyingReactDev/observable-slim)

---

*이 문서는 Obsidian 3D Graph 플러그인 (v1.0.5) 분석을 기반으로 작성되었습니다.*
