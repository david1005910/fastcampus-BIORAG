import { useRef, useState, useMemo, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Text, Sphere } from '@react-three/drei'
import * as THREE from 'three'
import { graphApi, type KnowledgeNode, type KnowledgeEdge } from '@/services/api'
import { Loader2, Network, RefreshCw, Maximize2, FileText, User, Tag, Search } from 'lucide-react'

// Extended node with 3D position
interface GraphNode extends KnowledgeNode {
  x: number
  y: number
  z: number
  color: string
  vx?: number
  vy?: number
  vz?: number
}

interface GraphLink extends KnowledgeEdge {
  color?: string
}

interface KnowledgeGraph3DProps {
  className?: string
  searchQuery?: string
  onNodeClick?: (node: GraphNode) => void
  onSearchChange?: (query: string) => void
}

// Color palette for different node types
const NODE_COLORS = {
  SearchTerm: '#f43f5e', // Rose - 검색어
  Paper: '#3b82f6',      // Blue - 논문
  Author: '#22c55e',     // Green - 저자
  Keyword: '#f59e0b',    // Amber - 키워드
}

// Link colors by relationship type
const LINK_COLORS = {
  FOUND: '#f43f5e',       // SearchTerm -> Paper
  AUTHORED_BY: '#22c55e', // Paper -> Author
  MENTIONS: '#f59e0b',    // Paper -> Keyword
}

// Get color by node type
const getNodeColor = (type: string): string => {
  return NODE_COLORS[type as keyof typeof NODE_COLORS] || '#64748b'
}

// Get link color by relationship type
const getLinkColor = (type: string): string => {
  return LINK_COLORS[type as keyof typeof LINK_COLORS] || '#06b6d4'
}

// 3D Node Component
function Node3D({
  node,
  onHover,
  onClick,
  isHovered,
  isSelected,
}: {
  node: GraphNode
  onHover: (node: GraphNode | null) => void
  onClick: (node: GraphNode) => void
  isHovered: boolean
  isSelected: boolean
}) {
  const textRef = useRef<THREE.Group>(null)
  const { camera } = useThree()

  // Size based on node type and size property
  const baseSize = node.type === 'SearchTerm' ? 1.2 :
                   node.type === 'Paper' ? 0.9 :
                   node.type === 'Author' ? 0.6 : 0.7
  const nodeSize = baseSize + (node.size * 0.05)
  const scale = isHovered ? 1.3 : isSelected ? 1.2 : 1

  useFrame(() => {
    if (textRef.current) {
      textRef.current.quaternion.copy(camera.quaternion)
    }
  })

  return (
    <group position={[node.x, node.y, node.z]}>
      {/* Glow effect */}
      <Sphere args={[nodeSize * scale * 1.5, 16, 16]}>
        <meshBasicMaterial
          color={node.color}
          transparent
          opacity={0.15}
        />
      </Sphere>

      {/* Main sphere */}
      <Sphere
        args={[nodeSize * scale, 32, 32]}
        onPointerOver={(e) => {
          e.stopPropagation()
          onHover(node)
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={() => {
          onHover(null)
          document.body.style.cursor = 'auto'
        }}
        onClick={(e) => {
          e.stopPropagation()
          onClick(node)
        }}
      >
        <meshStandardMaterial
          color={node.color}
          emissive={node.color}
          emissiveIntensity={isHovered ? 0.5 : isSelected ? 0.3 : 0.1}
          roughness={0.3}
          metalness={0.7}
        />
      </Sphere>

      {/* Label */}
      <group ref={textRef} position={[0, nodeSize * scale + 1.0, 0]}>
        <Text
          fontSize={0.5}
          color="#ffffff"
          anchorX="center"
          anchorY="middle"
          outlineWidth={0.08}
          outlineColor="#000000"
          strokeWidth={0.02}
          strokeColor="#000000"
          maxWidth={10}
          fontWeight="bold"
        >
          {node.label}
        </Text>
      </group>
    </group>
  )
}

// 3D Link Component with Tube geometry
function Link3D({
  source,
  target,
  linkType,
  index,
}: {
  source: GraphNode
  target: GraphNode
  linkType: string
  index: number
}) {
  const color = getLinkColor(linkType)

  const tubeGeometry = useMemo(() => {
    const start = new THREE.Vector3(source.x, source.y, source.z)
    const end = new THREE.Vector3(target.x, target.y, target.z)
    const midPoint = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5)

    // Deterministic curve offset based on index for consistency
    const angle = (index * 0.7) % (Math.PI * 2)
    const curveAmount = 1.0
    const offset = new THREE.Vector3(
      Math.cos(angle) * curveAmount,
      Math.sin(angle * 1.3) * curveAmount,
      Math.cos(angle * 0.7) * curveAmount
    )
    midPoint.add(offset)

    const curve = new THREE.QuadraticBezierCurve3(start, midPoint, end)
    const tubeRadius = 0.06
    return new THREE.TubeGeometry(curve, 32, tubeRadius, 8, false)
  }, [source.x, source.y, source.z, target.x, target.y, target.z, index])

  return (
    <mesh geometry={tubeGeometry}>
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.4}
        transparent
        opacity={0.7}
        roughness={0.3}
        metalness={0.5}
      />
    </mesh>
  )
}

// Force simulation for 3D layout
function useForceSimulation(
  nodes: GraphNode[],
  links: GraphLink[],
  enabled: boolean
) {
  const [simulatedNodes, setSimulatedNodes] = useState<GraphNode[]>(nodes)

  useEffect(() => {
    if (!enabled || nodes.length === 0) {
      setSimulatedNodes(nodes)
      return
    }

    // Initialize positions - SearchTerm at center, others spread out
    const nodesCopy: GraphNode[] = nodes.map((n, i) => {
      if (n.type === 'SearchTerm') {
        return { ...n, x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0 }
      }
      // Spread other nodes in a sphere around center
      const phi = Math.acos(-1 + (2 * i) / nodes.length)
      const theta = Math.sqrt(nodes.length * Math.PI) * phi
      const radius = 15 + (Math.random() * 5)
      return {
        ...n,
        x: radius * Math.cos(theta) * Math.sin(phi),
        y: radius * Math.sin(theta) * Math.sin(phi),
        z: radius * Math.cos(phi),
        vx: 0,
        vy: 0,
        vz: 0,
      }
    })

    // Create node index map
    const nodeMap = new Map(nodesCopy.map(n => [n.id, n]))

    // Force simulation
    let iteration = 0
    const maxIterations = 200

    const simulate = () => {
      if (iteration >= maxIterations) {
        setSimulatedNodes([...nodesCopy])
        return
      }

      const alpha = 1 - iteration / maxIterations

      // Apply forces
      for (const node of nodesCopy) {
        node.vx = (node.vx || 0) * 0.85
        node.vy = (node.vy || 0) * 0.85
        node.vz = (node.vz || 0) * 0.85

        // Repulsion from other nodes
        for (const other of nodesCopy) {
          if (node.id === other.id) continue

          const dx = node.x - other.x
          const dy = node.y - other.y
          const dz = node.z - other.z
          const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1
          const force = (30 / (dist * dist)) * alpha

          node.vx! += (dx / dist) * force
          node.vy! += (dy / dist) * force
          node.vz! += (dz / dist) * force
        }

        // Keep SearchTerm at center
        if (node.type === 'SearchTerm') {
          node.vx! -= node.x * 0.1
          node.vy! -= node.y * 0.1
          node.vz! -= node.z * 0.1
        } else {
          // Slight center gravity for others
          node.vx! -= node.x * 0.005 * alpha
          node.vy! -= node.y * 0.005 * alpha
          node.vz! -= node.z * 0.005 * alpha
        }
      }

      // Link attraction
      for (const link of links) {
        const source = nodeMap.get(link.source as string)
        const target = nodeMap.get(link.target as string)

        if (source && target) {
          const dx = target.x - source.x
          const dy = target.y - source.y
          const dz = target.z - source.z
          const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1
          const idealDist = 8
          const force = (dist - idealDist) * 0.03 * alpha

          const fx = (dx / dist) * force
          const fy = (dy / dist) * force
          const fz = (dz / dist) * force

          source.vx! += fx
          source.vy! += fy
          source.vz! += fz
          target.vx! -= fx
          target.vy! -= fy
          target.vz! -= fz
        }
      }

      // Update positions
      for (const node of nodesCopy) {
        node.x += node.vx || 0
        node.y += node.vy || 0
        node.z += node.vz || 0
      }

      iteration++

      if (iteration % 10 === 0) {
        setSimulatedNodes([...nodesCopy])
      }

      requestAnimationFrame(simulate)
    }

    simulate()
  }, [nodes, links, enabled])

  return simulatedNodes
}

// 3D Scene Component
function Scene({
  nodes,
  links,
  hoveredNode,
  selectedNode,
  onHover,
  onClick,
}: {
  nodes: GraphNode[]
  links: GraphLink[]
  hoveredNode: GraphNode | null
  selectedNode: GraphNode | null
  onHover: (node: GraphNode | null) => void
  onClick: (node: GraphNode) => void
}) {
  const simulatedNodes = useForceSimulation(nodes, links, true)
  const nodeMap = useMemo(() => new Map(simulatedNodes.map(n => [n.id, n])), [simulatedNodes])

  return (
    <>
      {/* Lighting */}
      <ambientLight intensity={0.6} />
      <pointLight position={[30, 30, 30]} intensity={1.5} />
      <pointLight position={[-30, -30, -30]} intensity={0.8} />
      <pointLight position={[0, 40, 0]} intensity={1} />

      {/* Links */}
      {links.map((link, i) => {
        const source = nodeMap.get(link.source as string)
        const target = nodeMap.get(link.target as string)
        if (!source || !target) return null

        return (
          <Link3D
            key={`link-${i}`}
            source={source}
            target={target}
            linkType={link.type}
            index={i}
          />
        )
      })}

      {/* Nodes */}
      {simulatedNodes.map((node) => (
        <Node3D
          key={node.id}
          node={node}
          onHover={onHover}
          onClick={onClick}
          isHovered={hoveredNode?.id === node.id}
          isSelected={selectedNode?.id === node.id}
        />
      ))}

      {/* Controls */}
      <OrbitControls
        enablePan={true}
        enableZoom={true}
        enableRotate={true}
        autoRotate={true}
        autoRotateSpeed={0.3}
      />
    </>
  )
}

// Get node type label in Korean
const getNodeTypeLabel = (type: string): string => {
  switch (type) {
    case 'SearchTerm': return '검색어'
    case 'Paper': return '논문'
    case 'Author': return '저자'
    case 'Keyword': return '키워드'
    default: return type
  }
}

// Get node type icon
const NodeTypeIcon = ({ type, size = 16 }: { type: string; size?: number }) => {
  switch (type) {
    case 'SearchTerm': return <Search size={size} />
    case 'Paper': return <FileText size={size} />
    case 'Author': return <User size={size} />
    case 'Keyword': return <Tag size={size} />
    default: return <Network size={size} />
  }
}

export function KnowledgeGraph3D({
  className = '',
  searchQuery,
  onNodeClick,
  onSearchChange,
}: KnowledgeGraph3DProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)

  // Fetch knowledge network from GraphDB
  const { data: networkData, isLoading, error, refetch } = useQuery({
    queryKey: ['knowledgeNetwork', searchQuery],
    queryFn: () => graphApi.getKnowledgeNetwork(searchQuery, 50),
    staleTime: 5 * 60 * 1000,
  })

  // Process graph data
  const { nodes, links, stats } = useMemo(() => {
    if (!networkData || networkData.nodes.length === 0) {
      return { nodes: [], links: [], stats: { papers: 0, authors: 0, keywords: 0 } }
    }

    // Convert to GraphNode with colors
    const graphNodes: GraphNode[] = networkData.nodes.map((node) => ({
      ...node,
      color: getNodeColor(node.type),
      x: 0,
      y: 0,
      z: 0,
    }))

    // Convert edges to links
    const graphLinks: GraphLink[] = networkData.edges.map(edge => ({
      ...edge,
      color: getLinkColor(edge.type),
    }))

    // Calculate stats
    const stats = {
      papers: graphNodes.filter(n => n.type === 'Paper').length,
      authors: graphNodes.filter(n => n.type === 'Author').length,
      keywords: graphNodes.filter(n => n.type === 'Keyword').length,
    }

    return { nodes: graphNodes, links: graphLinks, stats }
  }, [networkData])

  // Handle node click
  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode(node)

    // Always call onNodeClick for any node type
    onNodeClick?.(node)

    // Only trigger search change for SearchTerm nodes
    // Keyword/Author/Paper nodes should not trigger a new network search
    // because they may not exist as SearchTerm in the database
    if (node.type === 'SearchTerm') {
      onSearchChange?.(node.label)
    }
    // For Keyword nodes, we just select and show info without re-fetching
  }, [onNodeClick, onSearchChange])

  // Handle fullscreen toggle
  const toggleFullscreen = () => {
    if (!containerRef.current) return
    if (!isFullscreen) {
      containerRef.current.parentElement?.requestFullscreen?.()
    } else {
      document.exitFullscreen?.()
    }
    setIsFullscreen(!isFullscreen)
  }

  if (error) {
    return (
      <div className={`glossy-panel p-8 ${className}`}>
        <div className="text-center text-red-400">
          <Network className="mx-auto mb-4 opacity-50" size={48} />
          <p>지식 네트워크를 불러오는데 실패했습니다.</p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 rounded-lg text-red-300 flex items-center gap-2 mx-auto"
          >
            <RefreshCw size={16} />
            다시 시도
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className={`glossy-panel overflow-hidden ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <Network className="text-purple-400" size={24} />
          <div>
            <h3 className="text-lg font-semibold text-white">
              {searchQuery ? `"${searchQuery}" 지식 네트워크` : '지식 네트워크 3D'}
            </h3>
            <p className="text-sm text-gray-400">
              {isLoading
                ? '데이터 로딩 중...'
                : nodes.length > 0
                  ? `논문 ${stats.papers}개 · 저자 ${stats.authors}명 · 키워드 ${stats.keywords}개`
                  : '데이터 없음'}
            </p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
            title="새로고침"
          >
            <RefreshCw size={18} className="text-gray-400" />
          </button>
          <button
            onClick={toggleFullscreen}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
            title="전체화면"
          >
            <Maximize2 size={18} className="text-gray-400" />
          </button>
        </div>
      </div>

      {/* 3D Graph Container */}
      <div
        ref={containerRef}
        className="relative"
        style={{ height: '500px', minHeight: '500px', backgroundColor: '#0f172a' }}
      >
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-900/80 z-10">
            <div className="text-center">
              <Loader2 className="animate-spin text-purple-400 mx-auto mb-4" size={48} />
              <p className="text-gray-300">지식 네트워크 생성 중...</p>
            </div>
          </div>
        )}

        {!isLoading && nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="text-center text-gray-400">
              <Network className="mx-auto mb-4 opacity-30" size={64} />
              <p className="text-lg mb-2">네트워크 데이터가 없습니다</p>
              <p className="text-sm">검색어와 연결된 논문이 없습니다.</p>
              <p className="text-sm mt-1">벡터 DB에 논문을 저장하고 검색하면 연결됩니다!</p>
            </div>
          </div>
        )}

        {nodes.length > 0 && (
          <Canvas
            camera={{ position: [0, 0, 45], fov: 70 }}
            style={{
              background: '#0f172a',
              width: '100%',
              height: '100%',
              position: 'absolute',
              top: 0,
              left: 0,
            }}
            gl={{ antialias: true, alpha: false }}
            dpr={[1, 2]}
          >
            <Scene
              nodes={nodes}
              links={links}
              hoveredNode={hoveredNode}
              selectedNode={selectedNode}
              onHover={setHoveredNode}
              onClick={handleNodeClick}
            />
          </Canvas>
        )}

        {/* Hovered Node Info */}
        {hoveredNode && (
          <div
            className="absolute top-4 left-4 backdrop-blur-md p-4 rounded-xl text-sm z-20 pointer-events-none max-w-sm shadow-2xl"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.95)',
              border: `2px solid ${hoveredNode.color}`,
              boxShadow: `0 0 20px ${hoveredNode.color}40`,
            }}
          >
            <div className="flex items-center gap-2 mb-2">
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center"
                style={{ backgroundColor: hoveredNode.color }}
              >
                <NodeTypeIcon type={hoveredNode.type} size={16} />
              </div>
              <span
                className="text-sm font-bold px-3 py-1 rounded-full"
                style={{ backgroundColor: hoveredNode.color, color: '#fff' }}
              >
                {getNodeTypeLabel(hoveredNode.type)}
              </span>
            </div>
            <div className="font-bold text-xl mt-2" style={{ color: '#ffffff' }}>{hoveredNode.label}</div>
            {hoveredNode.pmid && (
              <div className="text-cyan-300 text-sm mt-2 font-medium">PMID: {hoveredNode.pmid}</div>
            )}
          </div>
        )}

        {/* Selected Node Info */}
        {selectedNode && (
          <div
            className="absolute bottom-4 left-4 right-4 backdrop-blur-md p-5 rounded-xl z-20 shadow-2xl"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.95)',
              border: `3px solid ${selectedNode.color}`,
              boxShadow: `0 0 30px ${selectedNode.color}50`,
            }}
          >
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-3">
                  <div
                    className="w-10 h-10 rounded-full flex items-center justify-center"
                    style={{ backgroundColor: selectedNode.color }}
                  >
                    <NodeTypeIcon type={selectedNode.type} size={20} />
                  </div>
                  <span
                    className="text-sm font-bold px-4 py-1.5 rounded-full"
                    style={{ backgroundColor: selectedNode.color, color: '#fff' }}
                  >
                    {getNodeTypeLabel(selectedNode.type)}
                  </span>
                </div>
                <div className="font-bold text-2xl" style={{ color: '#ffffff' }}>{selectedNode.label}</div>
                {selectedNode.pmid && (
                  <div className="text-cyan-300 text-base mt-2 font-medium">PMID: {selectedNode.pmid}</div>
                )}
              </div>
              <button
                onClick={() => setSelectedNode(null)}
                className="w-10 h-10 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center text-white text-xl font-bold transition-colors ml-4"
              >
                ✕
              </button>
            </div>
          </div>
        )}

        {/* Instructions */}
        <div className="absolute bottom-4 right-4 text-xs text-gray-500 bg-black/50 px-2 py-1 rounded">
          드래그: 회전 | 스크롤: 줌 | 클릭: 선택
        </div>
      </div>

      {/* Legend */}
      <div className="p-4 border-t border-white/10 flex items-center justify-center gap-6 text-sm flex-wrap">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: NODE_COLORS.SearchTerm }} />
          <Search size={14} className="text-gray-500" />
          <span className="text-gray-400">검색어</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: NODE_COLORS.Paper }} />
          <FileText size={14} className="text-gray-500" />
          <span className="text-gray-400">논문</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: NODE_COLORS.Author }} />
          <User size={14} className="text-gray-500" />
          <span className="text-gray-400">저자</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: NODE_COLORS.Keyword }} />
          <Tag size={14} className="text-gray-500" />
          <span className="text-gray-400">키워드</span>
        </div>
      </div>
    </div>
  )
}

export default KnowledgeGraph3D
