import type {
  RelationshipGraphEdge,
  RelationshipGraphNode,
  RelationshipGraphPayload,
} from '../types/relationshipGraph'

interface IntelGraphProps {
  graph: RelationshipGraphPayload
}

const shellStyle: React.CSSProperties = {
  border: '1px solid #e5e7eb',
  borderRadius: '14px',
  background: '#fff',
  padding: '16px',
}

const chipStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '4px 8px',
  borderRadius: '999px',
  fontSize: '12px',
  fontWeight: 600,
  background: '#eef2ff',
  color: '#4338ca',
}

const labelStyle: React.CSSProperties = {
  fontSize: '12px',
  color: '#6b7280',
}

const valueStyle: React.CSSProperties = {
  fontSize: '14px',
  color: '#111827',
  fontWeight: 600,
}

const scoreValue = (value?: number | null) => (typeof value === 'number' ? value : 'N/A')

const nodeLabel = (node: RelationshipGraphNode) => node.label || node.name || node.id

const edgeCounterpartyName = (
  edge: RelationshipGraphEdge,
  centerGraphId: string | undefined,
  nodeMap: Map<string, string>,
) => {
  if (!centerGraphId) {
    return nodeMap.get(edge.target) || nodeMap.get(edge.source) || edge.target || edge.source
  }
  const otherSide = edge.source === centerGraphId ? edge.target : edge.source
  return nodeMap.get(otherSide) || otherSide
}

export function IntelGraph({ graph }: IntelGraphProps) {
  const center = graph.center
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : []
  const edges = Array.isArray(graph.edges) ? graph.edges : []
  const warnings = Array.isArray(graph.warnings) ? graph.warnings : []
  const summary = graph.summary
  const nodeMap = new Map<string, string>()

  if (center?.graph_id) {
    nodeMap.set(center.graph_id, center.name)
  }
  nodes.forEach((node) => {
    nodeMap.set(node.id, nodeLabel(node))
  })

  const emptyState = !center || !graph.found || edges.length === 0

  return (
    <section style={shellStyle} data-testid="intel-graph">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
        <div>
          <div style={{ fontSize: '16px', fontWeight: 800, color: '#111827', marginBottom: '4px' }}>关系图谱</div>
          <div style={{ fontSize: '13px', color: '#6b7280' }}>仅展示数据库证据支持的关系，不使用前端假节点或假边。</div>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <span style={chipStyle}>nodes {summary?.node_count ?? 0}</span>
          <span style={chipStyle}>edges {summary?.edge_count ?? 0}</span>
          <span style={chipStyle}>verified {summary?.verified_edge_count ?? 0}</span>
        </div>
      </div>

      {center ? (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
            gap: '12px',
            padding: '14px',
            borderRadius: '12px',
            background: '#f8fafc',
            border: '1px solid #e2e8f0',
            marginBottom: '16px',
          }}
          data-testid="intel-graph-center"
        >
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={labelStyle}>中心机构</div>
            <div style={{ ...valueStyle, fontSize: '18px' }}>{center.name}</div>
          </div>
          <div>
            <div style={labelStyle}>类型</div>
            <div style={valueStyle}>{center.type || 'organization'}</div>
          </div>
          <div>
            <div style={labelStyle}>地区</div>
            <div style={valueStyle}>{center.region || 'N/A'}</div>
          </div>
          <div>
            <div style={labelStyle}>宗派</div>
            <div style={valueStyle}>{center.denomination || 'N/A'}</div>
          </div>
          <div>
            <div style={labelStyle}>People</div>
            <div style={valueStyle}>{scoreValue(center.people_score)}</div>
          </div>
          <div>
            <div style={labelStyle}>Digital</div>
            <div style={valueStyle}>{scoreValue(center.digital_score)}</div>
          </div>
          <div>
            <div style={labelStyle}>Intel</div>
            <div style={valueStyle}>{scoreValue(center.intel_score)}</div>
          </div>
        </div>
      ) : null}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: '12px',
          marginBottom: '16px',
        }}
        data-testid="intel-graph-summary"
      >
        <div style={{ padding: '12px', borderRadius: '12px', background: '#f8fafc', border: '1px solid #e2e8f0' }}>
          <div style={labelStyle}>节点总数</div>
          <div style={valueStyle}>{summary?.node_count ?? 0}</div>
        </div>
        <div style={{ padding: '12px', borderRadius: '12px', background: '#f8fafc', border: '1px solid #e2e8f0' }}>
          <div style={labelStyle}>关系总数</div>
          <div style={valueStyle}>{summary?.edge_count ?? 0}</div>
        </div>
        <div style={{ padding: '12px', borderRadius: '12px', background: '#f8fafc', border: '1px solid #e2e8f0' }}>
          <div style={labelStyle}>已验证关系</div>
          <div style={valueStyle}>{summary?.verified_edge_count ?? 0}</div>
        </div>
        <div style={{ padding: '12px', borderRadius: '12px', background: '#f8fafc', border: '1px solid #e2e8f0' }}>
          <div style={labelStyle}>缺证据关系</div>
          <div style={valueStyle}>{summary?.missing_evidence_count ?? 0}</div>
        </div>
      </div>

      <div style={{ marginBottom: '16px' }} data-testid="intel-graph-warnings">
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>Warnings</div>
        {warnings.length === 0 ? (
          <div style={{ fontSize: '13px', color: '#6b7280' }}>无 warnings</div>
        ) : (
          <div style={{ display: 'grid', gap: '8px' }}>
            {warnings.map((warning, index) => (
              <div
                key={`${warning.code}-${index}`}
                style={{
                  padding: '10px 12px',
                  borderRadius: '10px',
                  border: '1px solid #fde68a',
                  background: '#fffbeb',
                  color: '#92400e',
                  fontSize: '13px',
                }}
              >
                <strong>{warning.code}</strong>: {warning.message}
              </div>
            ))}
          </div>
        )}
      </div>

      {emptyState ? (
        <div
          style={{
            padding: '18px',
            borderRadius: '12px',
            border: '1px dashed #cbd5e1',
            background: '#f8fafc',
            color: '#475569',
            fontSize: '14px',
          }}
          data-testid="intel-graph-empty"
        >
          当前数据库没有发现有证据支持的关系图谱。
        </div>
      ) : (
        <>
          <div style={{ marginBottom: '16px' }} data-testid="intel-graph-nodes">
            <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>相关机构</div>
            <div style={{ display: 'grid', gap: '10px' }}>
              {nodes.map((node) => (
                <div
                  key={node.id}
                  style={{
                    padding: '12px 14px',
                    borderRadius: '12px',
                    border: '1px solid #e5e7eb',
                    background: '#ffffff',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', marginBottom: '6px' }}>
                    <div style={{ fontSize: '14px', fontWeight: 700, color: '#111827' }}>{nodeLabel(node)}</div>
                    <span style={chipStyle}>{node.type || 'organization'}</span>
                  </div>
                  <div style={{ fontSize: '13px', color: '#475569' }}>
                    confidence: {node.confidence} | source_count: {node.source_count} | region: {node.region || 'N/A'}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div data-testid="intel-graph-edges">
            <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>关系边</div>
            <div style={{ display: 'grid', gap: '12px' }}>
              {edges.map((edge) => (
                <div
                  key={edge.id}
                  style={{
                    padding: '14px',
                    borderRadius: '12px',
                    border: '1px solid #dbeafe',
                    background: '#f8fbff',
                  }}
                >
                  <div style={{ fontSize: '15px', fontWeight: 700, color: '#1e3a8a', marginBottom: '8px' }}>
                    {(center?.name || nodeMap.get(edge.source) || edge.source)} {'->'} {edgeCounterpartyName(edge, center?.graph_id, nodeMap)}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px', fontSize: '13px', color: '#334155' }}>
                    <div>relation_type: {edge.relation_type || 'unknown'}</div>
                    <div>direction: {edge.direction || 'unknown'}</div>
                    <div>confidence: {edge.confidence}</div>
                    <div>is_verified: {String(Boolean(edge.is_verified))}</div>
                    <div>strength: {edge.strength ?? 'N/A'}</div>
                    <div>evidence_source: {edge.evidence_source || 'N/A'}</div>
                    <div>evidence_date: {edge.evidence_date || 'N/A'}</div>
                    <div>missing_evidence: {String(Boolean(edge.missing_evidence))}</div>
                  </div>
                  <div style={{ marginTop: '8px', fontSize: '13px', color: '#475569' }}>reason: {edge.reason || 'N/A'}</div>
                  <div style={{ marginTop: '8px', fontSize: '13px' }}>
                    {edge.evidence_url ? (
                      <a href={edge.evidence_url} target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>
                        evidence_url: {edge.evidence_url}
                      </a>
                    ) : (
                      <span style={{ color: '#64748b' }}>evidence_url: N/A</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  )
}
