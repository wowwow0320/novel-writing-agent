import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import ForceGraph3D from 'react-force-graph-3d'
import * as THREE from 'three'
import SpriteText from 'three-spritetext'
import {
  api,
  type GraphLink,
  type GraphNode,
  type GraphNodeType,
  type GraphSubgraphResponse,
} from '../api'

type Props = {
  storyId: string
  onClose: () => void
}

type OrbitalNode = GraphNode & {
  fx?: number
  fy?: number
  fz?: number
  orbit_ring?: number
}

const NODE_TYPE_COLORS: Record<string, string> = {
  CHAR: '#60a5fa',
  LOC: '#34d399',
  EVENT: '#f472b6',
  ITEM: '#fbbf24',
  ORG: '#a78bfa',
  SITUATION: '#94a3b8',
  SUMMARY: '#22d3ee',
  UNKNOWN: '#64748b',
}

const STATUS_OUTLINE: Record<string, string> = {
  alive: '#22c55e',
  dead: '#ef4444',
  unknown: 'rgba(255,255,255,0.4)',
}

/** 관계 타입별 링크·라벨 색 (우주 톤) */
const RELATION_ACCENT: Record<string, string> = {
  ENEMY_OF: '#fb7185',
  ALLY_OF: '#4ade80',
  FAMILY_OF: '#a5b4fc',
  LOVES: '#f472b6',
  BELONGS_TO: '#fbbf24',
  LOCATED_IN: '#5eead4',
  PARTICIPATED_IN: '#93c5fd',
  INVOLVED_IN: '#c4b5fd',
  CAUSES: '#f97316',
  AFTER: '#94a3b8',
  BEFORE: '#94a3b8',
  DIED_IN: '#64748b',
  TRIGGERED_BY: '#e879f9',
  LEADS_TO: '#38bdf8',
  HAS_SUMMARY: '#22d3ee',
  SUMMARIZES: '#67e8f9',
  MENTIONS_ENTITY: '#7dd3fc',
  COVERS_EVENT: '#f0abfc',
  DEFAULT: '#7dd3fc',
}

function relationAccent(relation: string | undefined): string {
  const k = (relation || '').trim().toUpperCase()
  return RELATION_ACCENT[k] || RELATION_ACCENT.DEFAULT
}

function linkCaptionMultiline(l: GraphLink): string {
  const rel = (l.relation || 'REL').trim()
  const ctx = (l.context || '').replace(/\s+/g, ' ').trim()
  if (!ctx) return rel
  return `${rel}\n${ctx.slice(0, 64)}${ctx.length > 64 ? '…' : ''}`
}

const DEFAULT_TYPE_FILTERS: GraphNodeType[] = [
  'CHAR',
  'LOC',
  'EVENT',
  'ITEM',
  'ORG',
  'SITUATION',
  'SUMMARY',
]

function resolveId(endpoint: string | GraphNode): string {
  return typeof endpoint === 'string' ? endpoint : endpoint.id
}

/**
 * Knowledge Graph 3D 뷰어.
 *
 * - react-force-graph-3d 로 노드/관계를 3차원 공간에 배치
 * - 타입 필터/검색/깊이/limit 조절을 모달 상단 툴바로 제공
 * - 노드 클릭 시 우측 상세 패널에 메타/엣지 목록 표시
 */
export default function GraphView3D({ storyId, onClose }: Props) {
  const fgRef = useRef<{
    cameraPosition: (pos: { x: number; y: number; z: number }, lookAt: object, ms: number) => void
    scene?: () => THREE.Scene
  } | null>(null)
  const fgRefCompat = fgRef as unknown as React.MutableRefObject<
    import('react-force-graph-3d').ForceGraphMethods<GraphNode, GraphLink> | undefined
  >
  const containerRef = useRef<HTMLDivElement | null>(null)
  const orbitalRingsRef = useRef<THREE.Group | null>(null)
  const [dims, setDims] = useState<{ w: number; h: number }>({ w: 960, h: 640 })

  const [data, setData] = useState<GraphSubgraphResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(false)
  const [err, setErr] = useState<string | null>(null)

  const [depth, setDepth] = useState<number>(2)
  const [limit, setLimit] = useState<number>(160)
  const [center, setCenter] = useState<string>('')
  const [activeTypes, setActiveTypes] = useState<GraphNodeType[]>(DEFAULT_TYPE_FILTERS)
  const [searchQ, setSearchQ] = useState<string>('')
  const [selected, setSelected] = useState<GraphNode | null>(null)
  /** 그래프 데이터 바뀔 때마다 한 번만 자동 프레이밍 */
  const cosmicFramePending = useRef(true)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const cr = entry.contentRect
        setDims({
          w: Math.max(320, Math.floor(cr.width)),
          h: Math.max(320, Math.floor(cr.height)),
        })
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const fetchGraph = useCallback(async () => {
    if (!storyId) return
    setLoading(true)
    setErr(null)
    try {
      const res = await api.agent.graphSubgraph(storyId, {
        center: center.trim() || undefined,
        depth,
        limit,
        node_types: activeTypes,
      })
      setData(res)
      setSelected(null)
      cosmicFramePending.current = true
    } catch (e) {
      setErr(String(e))
    } finally {
      setLoading(false)
    }
  }, [storyId, center, depth, limit, activeTypes])

  useEffect(() => {
    void fetchGraph()
  }, [fetchGraph])

  const filteredData = useMemo(() => {
    if (!data) return { nodes: [] as GraphNode[], links: [] as GraphLink[] }
    const q = searchQ.trim().toLowerCase()
    if (!q) return { nodes: data.nodes, links: data.links }
    const matched = new Set(
      data.nodes.filter((n) => n.id.toLowerCase().includes(q)).map((n) => n.id),
    )
    // 매칭된 노드와 그에 연결된 엣지 + 인접 노드까지 표시
    const links = data.links.filter((l) => {
      const s = resolveId(l.source)
      const t = resolveId(l.target)
      return matched.has(s) || matched.has(t)
    })
    const keep = new Set<string>(matched)
    links.forEach((l) => {
      keep.add(resolveId(l.source))
      keep.add(resolveId(l.target))
    })
    return {
      nodes: data.nodes.filter((n) => keep.has(n.id)),
      links,
    }
  }, [data, searchQ])

  const orbitalData = useMemo(() => {
    const nodes = filteredData.nodes
    const links = filteredData.links
    if (nodes.length === 0) return { nodes: [] as OrbitalNode[], links }

    const degree = new Map<string, number>()
    links.forEach((l) => {
      const s = resolveId(l.source)
      const t = resolveId(l.target)
      degree.set(s, (degree.get(s) ?? 0) + 1)
      degree.set(t, (degree.get(t) ?? 0) + 1)
    })
    const centerKey = center.trim().toLowerCase()
    const centerNode =
      nodes.find((n) => n.id.toLowerCase() === centerKey) ||
      nodes.find((n) => n.id.toLowerCase().includes(centerKey) && centerKey) ||
      [...nodes].sort((a, b) => {
        const da = degree.get(a.id) ?? 0
        const db = degree.get(b.id) ?? 0
        if (db !== da) return db - da
        return (b.importance ?? 0) - (a.importance ?? 0)
      })[0]

    const neighbors = new Map<string, Set<string>>()
    nodes.forEach((n) => neighbors.set(n.id, new Set()))
    links.forEach((l) => {
      const s = resolveId(l.source)
      const t = resolveId(l.target)
      neighbors.get(s)?.add(t)
      neighbors.get(t)?.add(s)
    })

    const ringById = new Map<string, number>()
    ringById.set(centerNode.id, 0)
    const queue = [centerNode.id]
    for (let head = 0; head < queue.length; head += 1) {
      const cur = queue[head]
      const ring = ringById.get(cur) ?? 0
      if (ring >= 3) continue
      neighbors.get(cur)?.forEach((next) => {
        if (!ringById.has(next)) {
          ringById.set(next, ring + 1)
          queue.push(next)
        }
      })
    }

    const byRing = new Map<number, GraphNode[]>()
    nodes.forEach((n) => {
      const ring = ringById.get(n.id) ?? 3
      const arr = byRing.get(ring) ?? []
      arr.push(n)
      byRing.set(ring, arr)
    })

    const radiusByRing = [0, 120, 220, 320]
    const positioned: OrbitalNode[] = []
    ;[0, 1, 2, 3].forEach((ring) => {
      const arr = byRing.get(ring) ?? []
      arr
        .sort((a, b) => a.id.localeCompare(b.id))
        .forEach((n, idx) => {
          if (ring === 0) {
            positioned.push({ ...n, fx: 0, fy: 0, fz: 0, orbit_ring: 0 })
            return
          }
          const radius = radiusByRing[ring]
          const angle = (idx / Math.max(1, arr.length)) * Math.PI * 2 + ring * 0.42
          const lift = Math.sin(angle * 2 + ring) * (ring === 1 ? 18 : 36)
          positioned.push({
            ...n,
            fx: Math.cos(angle) * radius,
            fy: lift,
            fz: Math.sin(angle) * radius,
            orbit_ring: ring,
          })
        })
    })
    return { nodes: positioned, links }
  }, [filteredData, center])

  useEffect(() => {
    if (!data || filteredData.nodes.length === 0) return
    let cancelled = false
    const id = requestAnimationFrame(() => {
      if (cancelled) return
      const fg = fgRef.current
      if (!fg?.scene) return
      const scene = fg.scene()
      scene.fog = new THREE.FogExp2(0x020510, 0.00095)
      if (orbitalRingsRef.current) {
        scene.remove(orbitalRingsRef.current)
      }
      const rings = new THREE.Group()
      ;[
        { radius: 120, color: 0x38bdf8, opacity: 0.3 },
        { radius: 220, color: 0xa78bfa, opacity: 0.22 },
        { radius: 320, color: 0x22d3ee, opacity: 0.14 },
      ].forEach((cfg, idx) => {
        const ring = new THREE.Mesh(
          new THREE.TorusGeometry(cfg.radius, 0.42, 8, 192),
          new THREE.MeshBasicMaterial({
            color: cfg.color,
            transparent: true,
            opacity: cfg.opacity,
            depthWrite: false,
          }),
        )
        ring.rotation.x = Math.PI / 2
        ring.rotation.z = idx * 0.18
        rings.add(ring)
      })
      scene.add(rings)
      orbitalRingsRef.current = rings
    })
    return () => {
      cancelled = true
      cancelAnimationFrame(id)
      const fg = fgRef.current
      if (fg?.scene) {
        const scene = fg.scene()
        scene.fog = null
        if (orbitalRingsRef.current) {
          scene.remove(orbitalRingsRef.current)
          orbitalRingsRef.current = null
        }
      }
    }
  }, [data, filteredData.nodes.length])

  /** 별처럼 멀리 퍼지도록 d3-force 반발·링크 길이·카메라 거리 조정 */
  useEffect(() => {
    if (!data || filteredData.nodes.length === 0) return
    const n = filteredData.nodes.length
    const m = filteredData.links.length

    const applyCosmicForces = () => {
      const fg = fgRefCompat.current
      if (!fg?.d3Force) return
      try {
        const charge = fg.d3Force('charge') as { strength?: (v: number) => void } | undefined
        const linkF = fg.d3Force('link') as {
          distance?: (d: number | ((link: unknown) => number)) => void
          strength?: (s: number) => void
        } | undefined
        const repulsion = -260 - Math.min(620, n * 42) - Math.min(240, m * 16)
        charge?.strength?.(repulsion)
        const linkDist = 150 + Math.min(320, n * 8) + Math.min(180, m * 3.2)
        linkF?.distance?.(linkDist)
        linkF?.strength?.(0.2)
        cosmicFramePending.current = true
        fg.d3ReheatSimulation?.()
        const z = Math.min(3200, 720 + n * 52 + m * 14)
        fg.cameraPosition?.({ x: 0, y: 0, z }, { x: 0, y: 0, z: 0 }, 0)
      } catch {
        /* noop */
      }
    }

    const r0 = requestAnimationFrame(applyCosmicForces)
    const t1 = setTimeout(applyCosmicForces, 160)
    return () => {
      cancelAnimationFrame(r0)
      clearTimeout(t1)
    }
  }, [data, filteredData.nodes.length, filteredData.links.length])

  const relatedLinks = useMemo(() => {
    if (!selected || !data) return [] as GraphLink[]
    return data.links.filter(
      (l) => resolveId(l.source) === selected.id || resolveId(l.target) === selected.id,
    )
  }, [selected, data])

  const handleNodeClick = (node: GraphNode) => {
    setSelected(node)
    const fg = fgRef.current
    if (!fg) return
    const anyNode = node as GraphNode & { x?: number; y?: number; z?: number }
    if (
      typeof anyNode.x === 'number' &&
      typeof anyNode.y === 'number' &&
      typeof anyNode.z === 'number'
    ) {
      const dist = 120
      const ratio = 1 + dist / Math.hypot(anyNode.x, anyNode.y, anyNode.z || 1)
      fg.cameraPosition(
        { x: anyNode.x * ratio, y: anyNode.y * ratio, z: (anyNode.z || 0) * ratio },
        { x: anyNode.x, y: anyNode.y, z: anyNode.z || 0 },
        800,
      )
    }
  }

  const toggleType = (t: GraphNodeType) => {
    setActiveTypes((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t],
    )
  }

  return (
    <div className="graph3d-overlay" role="dialog" aria-modal="true" aria-label="3D 지식 그래프">
      <div className="graph3d-shell">
        <header className="graph3d-header">
          <div className="graph3d-title">
            Jarvis Orbital Graph
            {data && (
              <span className="graph3d-count">
                {' '}
                · 노드 {filteredData.nodes.length}/{data.nodes.length} · 링크{' '}
                {filteredData.links.length}/{data.links.length}
                {data.graph_source === 'disabled'
                  ? ' · 앱설정:그래프OFF'
                  : ' · Neo4j(HTTP)'}
              </span>
            )}
          </div>
          <button type="button" className="graph3d-close" onClick={onClose}>
            닫기
          </button>
        </header>

        <div className="graph3d-toolbar">
          <label>
            <span>중심 엔티티</span>
            <input
              value={center}
              onChange={(e) => setCenter(e.target.value)}
              placeholder="(전체, 비워두면 최근 관계)"
            />
          </label>
          <label>
            <span>깊이</span>
            <input
              type="number"
              min={1}
              max={4}
              value={depth}
              onChange={(e) => setDepth(Math.max(1, Math.min(4, Number(e.target.value) || 2)))}
            />
          </label>
          <label>
            <span>최대 링크</span>
            <input
              type="number"
              min={10}
              max={400}
              step={10}
              value={limit}
              onChange={(e) =>
                setLimit(Math.max(10, Math.min(400, Number(e.target.value) || 160)))
              }
            />
          </label>
          <label className="graph3d-search">
            <span>검색</span>
            <input
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              placeholder="이름으로 필터"
            />
          </label>
          <button type="button" className="graph3d-refresh" disabled={loading} onClick={fetchGraph}>
            {loading ? '불러오는 중…' : '다시 조회'}
          </button>
        </div>

        <div className="graph3d-type-filters">
          {DEFAULT_TYPE_FILTERS.map((t) => {
            const active = activeTypes.includes(t)
            return (
              <button
                key={t}
                type="button"
                className={`graph3d-chip${active ? ' on' : ''}`}
                style={{
                  borderColor: NODE_TYPE_COLORS[t],
                  background: active ? NODE_TYPE_COLORS[t] : 'transparent',
                  color: active ? '#0b1120' : NODE_TYPE_COLORS[t],
                }}
                onClick={() => toggleType(t)}
              >
                {t}
              </button>
            )
          })}
        </div>

        <div className="graph3d-body">
          <div className="graph3d-canvas" ref={containerRef}>
            {err && <div className="graph3d-error">그래프 조회 실패: {err}</div>}
            {!err && data && filteredData.nodes.length === 0 && (
              <div className="graph3d-empty">
                {data.graph_source === 'disabled' ? (
                  <>
                    그래프 기능이 꺼져 있어 Neo4j를 조회하지 않았습니다.{' '}
                    <code>backend/.env</code>에서 <code>GRAPH_ENABLED=true</code>와 Neo4j 접속 정보를
                    넣은 뒤 서버를 다시 띄워 주세요.
                  </>
                ) : data.links.length === 0 ? (
                  <>
                    이 스토리에 그려질 <strong>관계(링크)</strong>가 없습니다. 3D 뷰는 Neo4j의{' '}
                    <code>RELATES</code> 엣지가 있을 때만 노드를 표시합니다. 확정 직후 토스트·플로우
                    로그의 <strong>관계 N개</strong>가 0이면 LLM이 본문에서 관계를 추출하지 못한
                    것이고, 필터/검색 문제가 아닙니다.
                  </>
                ) : (
                  <>표시할 노드가 없습니다. 타입 칩·검색을 완화해 보세요.</>
                )}
              </div>
            )}
            {data && filteredData.nodes.length > 0 && (
              <ForceGraph3D
                ref={fgRefCompat}
                width={dims.w}
                height={dims.h}
                graphData={orbitalData}
                backgroundColor="#020412"
                showNavInfo={false}
                nodeId="id"
                nodeRelSize={5.5}
                nodeLabel={(n: GraphNode) =>
                  `${n.id} [${n.node_type}] · 중요도 ${n.importance} · ${n.status}`
                }
                nodeThreeObject={(n: GraphNode) => {
                  const g = new THREE.Group()
                  const hex = NODE_TYPE_COLORS[n.node_type] || NODE_TYPE_COLORS.UNKNOWN
                  const col = new THREE.Color(hex)
                  const orbitRing = (n as OrbitalNode).orbit_ring ?? 1
                  const coreR = 2.6 + Math.min(2.4, (n.importance || 3) * 0.38)
                  const core = new THREE.Mesh(
                    new THREE.SphereGeometry(coreR, 22, 22),
                    new THREE.MeshBasicMaterial({
                      color: col,
                      transparent: true,
                      opacity: 0.96,
                    }),
                  )
                  g.add(core)
                  const halo = new THREE.Mesh(
                    new THREE.SphereGeometry(coreR * 2.05, 16, 16),
                    new THREE.MeshBasicMaterial({
                      color: col,
                      transparent: true,
                      opacity: 0.16,
                      depthWrite: false,
                    }),
                  )
                  g.add(halo)
                  const orbit = new THREE.Mesh(
                    new THREE.TorusGeometry(coreR * 2.7, 0.16, 8, 64),
                    new THREE.MeshBasicMaterial({
                      color: col,
                      transparent: true,
                      opacity: orbitRing === 0 ? 0.48 : 0.24,
                      depthWrite: false,
                    }),
                  )
                  orbit.rotation.x = Math.PI / 2
                  g.add(orbit)
                  const label = new SpriteText(n.id)
                  label.color = '#e8eefc'
                  label.textHeight = 4.8 + Math.min(3.5, (n.importance || 3) * 0.85)
                  label.backgroundColor = 'rgba(4,8,22,0.78)'
                  label.padding = 3
                  label.borderRadius = 5
                  label.borderWidth = 0.35
                  label.borderColor =
                    STATUS_OUTLINE[n.status as keyof typeof STATUS_OUTLINE] ||
                    STATUS_OUTLINE.unknown
                  label.position.set(0, coreR * 2.75, 0)
                  g.add(label)
                  return g
                }}
                linkColor={(l: GraphLink) => {
                  const a = Math.max(0.2, Math.min(0.78, (l.confidence ?? 0.55) * 0.72))
                  const rgb = new THREE.Color(relationAccent(l.relation))
                  return `rgba(${Math.round(rgb.r * 255)},${Math.round(rgb.g * 255)},${Math.round(rgb.b * 255)},${a})`
                }}
                linkWidth={(l: GraphLink) =>
                  Math.max(0.32, Math.min(1.65, (l.confidence ?? 0.55) * 2.1))
                }
                linkCurvature={0.16}
                linkDirectionalArrowLength={1.8}
                linkDirectionalArrowRelPos={1}
                linkDirectionalParticles={(l: GraphLink) => {
                  const c = l.confidence ?? 0.45
                  if (c > 0.78) return 4
                  if (c > 0.52) return 2
                  return 1
                }}
                linkDirectionalParticleWidth={0.32}
                linkDirectionalParticleSpeed={0.0035}
                linkLabel={(l: GraphLink) =>
                  `${resolveId(l.source)} —[${l.relation}]→ ${resolveId(l.target)}${
                    l.context ? `\n${l.context}` : ''
                  }`
                }
                linkThreeObjectExtend
                linkThreeObject={(l: GraphLink) => {
                  const spr = new SpriteText(linkCaptionMultiline(l))
                  spr.color = relationAccent(l.relation)
                  spr.textHeight = 2.05
                  spr.backgroundColor = 'rgba(2,6,18,0.9)'
                  spr.padding = 4
                  spr.borderRadius = 5
                  spr.borderWidth = 0.22
                  spr.borderColor = 'rgba(125,211,252,0.4)'
                  return spr
                }}
                linkPositionUpdate={(sprite, { start, end }) => {
                  const t = 0.46
                  Object.assign(sprite.position, {
                    x: start.x + (end.x - start.x) * t,
                    y: start.y + (end.y - start.y) * t,
                    z: start.z + (end.z - start.z) * t,
                  })
                  return true
                }}
                onNodeClick={(n) => handleNodeClick(n as GraphNode)}
                onBackgroundClick={() => setSelected(null)}
                warmupTicks={40}
                cooldownTicks={90}
                d3VelocityDecay={0.38}
                d3AlphaDecay={0.04}
                onEngineStop={() => {
                  if (!cosmicFramePending.current) return
                  cosmicFramePending.current = false
                  const fg = fgRefCompat.current
                  const pad = Math.min(220, 64 + filteredData.nodes.length * 3)
                  fg?.zoomToFit?.(1100, pad)
                }}
                enableNodeDrag
              />
            )}
          </div>

          <aside className="graph3d-side">
            {!selected && (
              <div className="graph3d-hint">
                <h4>관계 궤도</h4>
                <ul>
                  <li>마우스 드래그: 회전 · 휠: 줌 · 우클릭: 팬</li>
                  <li>
                    중심 노드에서 가까운 관계일수록 안쪽 링에 배치됩니다. 중심 엔티티를 입력하면
                    궤도가 다시 계산됩니다.
                  </li>
                  <li>
                    링크 위 라벨은 관계 타입과 짧은 맥락입니다. 흐르는 입자는 관계 방향을 뜻합니다.
                  </li>
                  <li>노드를 클릭하면 이 패널에서 연결 관계와 relationship_id를 확인할 수 있습니다.</li>
                  <li>필터 칩으로 타입별 노드 표시를 켜고 끌 수 있습니다.</li>
                </ul>
                {data?.ontology && (
                  <details style={{ marginTop: 10 }}>
                    <summary>온톨로지</summary>
                    <div className="graph3d-onto">
                      <div>
                        <strong>노드 타입</strong>: {data.ontology.node_types.join(', ')}
                      </div>
                      <div>
                        <strong>관계 타입</strong>: {data.ontology.relation_types.join(', ')}
                      </div>
                    </div>
                  </details>
                )}
              </div>
            )}
            {selected && (
              <div className="graph3d-detail">
                <h4 style={{ color: NODE_TYPE_COLORS[selected.node_type] }}>
                  {selected.id}
                </h4>
                <dl>
                  <dt>타입</dt>
                  <dd>{selected.node_type}</dd>
                  <dt>중요도</dt>
                  <dd>{'★'.repeat(Math.max(0, Math.min(5, selected.importance)))}</dd>
                  <dt>상태</dt>
                  <dd>{selected.status}</dd>
                  {selected.origin_hint && (
                    <>
                      <dt>근거</dt>
                      <dd className="graph3d-hint-text">{selected.origin_hint}</dd>
                    </>
                  )}
                  <dt>연결된 관계</dt>
                  <dd>{relatedLinks.length}건</dd>
                </dl>
                <div className="graph3d-rel-list">
                  {relatedLinks.map((l, i) => {
                    const sId = resolveId(l.source)
                    const tId = resolveId(l.target)
                    const other = sId === selected.id ? tId : sId
                    const arrow = sId === selected.id ? '→' : '←'
                    return (
                      <button
                        key={`rel-${i}`}
                        type="button"
                        className="graph3d-rel-item"
                        onClick={() => {
                          const node = data?.nodes.find((n) => n.id === other)
                          if (node) handleNodeClick(node)
                        }}
                      >
                        <div className="graph3d-rel-row">
                          <span className="graph3d-rel-arrow">{arrow}</span>
                          <span className="graph3d-rel-name">{other}</span>
                          <span className="graph3d-rel-meta">
                            {l.confidence != null
                              ? `신뢰도 ${(l.confidence * 100).toFixed(0)}%`
                              : ''}
                          </span>
                        </div>
                        <span className="graph3d-rel-type">{l.relation}</span>
                        {l.context && (
                          <div className="graph3d-rel-context" title={l.context}>
                            {l.context}
                          </div>
                        )}
                        {l.relationship_id && (
                          <div className="graph3d-rel-context" title={l.relationship_id}>
                            relationship_id: {l.relationship_id.slice(0, 8)}…
                          </div>
                        )}
                      </button>
                    )
                  })}
                </div>
                <button
                  type="button"
                  className="graph3d-focus"
                  onClick={() => {
                    setCenter(selected.id)
                  }}
                >
                  이 노드를 중심으로 재조회
                </button>
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}
