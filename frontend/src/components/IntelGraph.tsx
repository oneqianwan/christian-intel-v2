import { useEffect, useMemo, useRef, useState } from 'react'

type GraphNode = {
  id: string
  name: string
  type: string
  x: number
  y: number
  color: string
}

type GraphEdge = {
  from: string
  to: string
  label: string
}

type RelationItem = {
  entity: { name: string; type?: string }
  type: string
  direction?: string
  amount?: number
  description?: string
}

interface IntelGraphProps {
  centerEntity: string
  relations: RelationItem[]
  width?: number
  height?: number
}

export function IntelGraph({
  centerEntity,
  relations,
  width = 600,
  height = 400,
}: IntelGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)

  const { nodes, edges } = useMemo(() => {
    const centerX = width / 2
    const centerY = height / 2
    const radius = 140

    const graphNodes: GraphNode[] = [
      {
        id: 'center',
        name: centerEntity,
        type: 'center',
        x: centerX,
        y: centerY,
        color: '#4f46e5',
      },
    ]

    const graphEdges: GraphEdge[] = []

    relations.slice(0, 8).forEach((rel, idx) => {
      const count = Math.max(Math.min(relations.length, 8), 1)
      const angle = (idx / count) * 2 * Math.PI - Math.PI / 2
      const x = centerX + Math.cos(angle) * radius
      const y = centerY + Math.sin(angle) * radius
      const nodeId = `node-${idx}`

      const typeColorMap: Record<string, string> = {
        investment: '#059669',
        partnership: '#d97706',
        collaboration: '#7c3aed',
        competition: '#dc2626',
      }

      graphNodes.push({
        id: nodeId,
        name: rel.entity.name,
        type: rel.type,
        x,
        y,
        color: typeColorMap[rel.type] || '#6b7280',
      })

      graphEdges.push({
        from: rel.direction === 'outgoing' ? 'center' : nodeId,
        to: rel.direction === 'outgoing' ? nodeId : 'center',
        label: rel.amount ? `$${(rel.amount / 1000000).toFixed(1)}M` : rel.type,
      })
    })

    return { nodes: graphNodes, edges: graphEdges }
  }, [centerEntity, relations, width, height])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    canvas.style.width = `${width}px`
    canvas.style.height = `${height}px`
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.scale(dpr, dpr)

    ctx.clearRect(0, 0, width, height)

    edges.forEach((edge) => {
      const fromNode = nodes.find((node) => node.id === edge.from)
      const toNode = nodes.find((node) => node.id === edge.to)
      if (!fromNode || !toNode) return

      ctx.beginPath()
      ctx.moveTo(fromNode.x, fromNode.y)
      ctx.lineTo(toNode.x, toNode.y)
      ctx.strokeStyle = hoveredNode === edge.from || hoveredNode === edge.to ? '#4f46e5' : '#d1d5db'
      ctx.lineWidth = hoveredNode === edge.from || hoveredNode === edge.to ? 2.5 : 1.5
      ctx.stroke()

      const midX = (fromNode.x + toNode.x) / 2
      const midY = (fromNode.y + toNode.y) / 2
      ctx.fillStyle = '#6b7280'
      ctx.font = '11px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(edge.label, midX, midY - 5)
    })

    nodes.forEach((node) => {
      const isHovered = hoveredNode === node.id
      const radius = node.id === 'center' ? 28 : 22

      if (isHovered) {
        ctx.beginPath()
        ctx.arc(node.x, node.y, radius + 6, 0, 2 * Math.PI)
        ctx.fillStyle = `${node.color}20`
        ctx.fill()
      }

      ctx.beginPath()
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
      ctx.fillStyle = node.color
      ctx.fill()

      ctx.strokeStyle = isHovered ? '#1f2937' : '#ffffff'
      ctx.lineWidth = isHovered ? 3 : 2
      ctx.stroke()

      ctx.fillStyle = '#ffffff'
      ctx.font = node.id === 'center' ? 'bold 12px sans-serif' : '11px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'

      const maxLen = 8
      const displayName = node.name.length > maxLen ? `${node.name.slice(0, maxLen)}..` : node.name
      ctx.fillText(displayName, node.x, node.y)
    })
  }, [edges, height, hoveredNode, nodes, width])

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top

    let found: string | null = null
    nodes.forEach((node) => {
      const radius = node.id === 'center' ? 28 : 22
      const distance = Math.sqrt((x - node.x) ** 2 + (y - node.y) ** 2)
      if (distance < radius + 5) found = node.id
    })
    setHoveredNode(found)
  }

  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: '14px', background: '#fff', padding: '16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', gap: '12px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '14px', fontWeight: 700, color: '#111827' }}>关系图谱</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '12px', color: '#6b7280', flexWrap: 'wrap' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ width: '8px', height: '8px', borderRadius: '999px', background: '#4f46e5', display: 'inline-block' }} />中心</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ width: '8px', height: '8px', borderRadius: '999px', background: '#059669', display: 'inline-block' }} />投资</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ width: '8px', height: '8px', borderRadius: '999px', background: '#d97706', display: 'inline-block' }} />合作</span>
        </div>
      </div>
      <canvas
        ref={canvasRef}
        style={{ width, height, maxWidth: '100%', cursor: 'pointer' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredNode(null)}
      />
      {hoveredNode && (
        <div style={{ marginTop: '10px', fontSize: '12px', color: '#4b5563' }}>
          {nodes.find((node) => node.id === hoveredNode)?.name}
          {hoveredNode !== 'center' && (
            <span style={{ color: '#9ca3af', marginLeft: '6px' }}>
              （{relations.find((_, index) => `node-${index}` === hoveredNode)?.description || ''}）
            </span>
          )}
        </div>
      )}
    </div>
  )
}
