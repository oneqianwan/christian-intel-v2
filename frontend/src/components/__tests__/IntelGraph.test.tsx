import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { IntelGraph } from '../IntelGraph'
import type { RelationshipGraphPayload } from '../../types/relationshipGraph'

const buildGraph = (): RelationshipGraphPayload => ({
  center: {
    id: 'org-victory',
    graph_id: 'org:org-victory',
    type: 'organization',
    name: 'Victory Philippines',
    region: 'Philippines',
    denomination: 'Evangelical',
    people_score: 64,
    digital_score: 28,
    intel_score: 65,
  },
  nodes: [
    {
      id: 'org:org-life',
      entity_id: 'org-life',
      type: 'organization',
      label: 'Life.Church',
      name: 'Life.Church',
      region: 'United States',
      denomination: 'Evangelical',
      people_score: 70,
      digital_score: 50,
      intel_score: 60,
      confidence: 0.82,
      source_count: 2,
    },
  ],
  edges: [
    {
      id: 'edge-1',
      source: 'org:org-victory',
      target: 'org:org-life',
      relation_type: 'partner',
      direction: 'outbound',
      strength: 0.7,
      confidence: 0.82,
      is_verified: true,
      evidence_url: 'https://example.com/partner-proof',
      evidence_source: 'Public partnership page',
      evidence_date: '2026-07-10',
      reason: '公开来源显示两者存在合作关系',
      missing_evidence: false,
    },
  ],
  summary: {
    node_count: 2,
    edge_count: 1,
    verified_edge_count: 1,
    unverified_edge_count: 0,
    missing_evidence_count: 0,
  },
  warnings: [
    {
      code: 'unverified_filtered',
      message: '1 unverified edge filtered out',
    },
  ],
  found: true,
  depth: 1,
  limit: 50,
  include_unverified: false,
})

describe('IntelGraph', () => {
  it('renders real graph payload details', () => {
    render(<IntelGraph graph={buildGraph()} />)

    expect(screen.getByTestId('intel-graph-center')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('intel-graph-nodes')).toHaveTextContent('Life.Church')
    expect(screen.getByTestId('intel-graph-edges')).toHaveTextContent('relation_type: partner')
    expect(screen.getByTestId('intel-graph-edges')).toHaveTextContent('confidence: 0.82')
    expect(screen.getByTestId('intel-graph-edges')).toHaveTextContent('is_verified: true')
    expect(screen.getByTestId('intel-graph-summary')).toHaveTextContent('节点总数')
    expect(screen.getByTestId('intel-graph-summary')).toHaveTextContent('关系总数')
    expect(screen.getByTestId('intel-graph-warnings')).toHaveTextContent('unverified_filtered')
    expect(screen.getByRole('link', { name: /evidence_url:/i })).toHaveAttribute('href', 'https://example.com/partner-proof')
  })

  it('shows empty state and does not fabricate evidence url', () => {
    const graph = buildGraph()
    graph.edges = []
    graph.summary.edge_count = 0
    graph.summary.verified_edge_count = 0
    graph.summary.node_count = 1
    graph.warnings = [{ code: 'no_relations', message: 'No graph relations found for this organization' }]

    render(<IntelGraph graph={graph} />)

    expect(screen.getByTestId('intel-graph-empty')).toHaveTextContent('当前数据库没有发现有证据支持的关系图谱。')
    expect(screen.queryByRole('link', { name: /evidence_url:/i })).not.toBeInTheDocument()
  })

  it('shows missing evidence without inventing a url', () => {
    const graph = buildGraph()
    graph.edges = [
      {
        ...graph.edges[0],
        id: 'edge-2',
        evidence_url: null,
        evidence_source: 'Archived report',
        missing_evidence: true,
      },
    ]
    graph.summary.missing_evidence_count = 1

    render(<IntelGraph graph={graph} />)

    const edgeSection = screen.getByTestId('intel-graph-edges')
    expect(edgeSection).toHaveTextContent('evidence_source: Archived report')
    expect(edgeSection).toHaveTextContent('missing_evidence: true')
    expect(within(edgeSection).queryByRole('link', { name: /evidence_url:/i })).not.toBeInTheDocument()
    expect(edgeSection).toHaveTextContent('evidence_url: N/A')
  })
})
