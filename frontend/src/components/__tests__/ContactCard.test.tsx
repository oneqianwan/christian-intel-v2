import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ContactCard } from '../ContactCard'
import type { ContactPayload } from '../../types/contactIntelligence'

const buildPayload = (): ContactPayload => ({
  organization: {
    id: 'org-victory',
    name: 'Victory Philippines',
    source_url: 'https://org.example.com/source',
    source_name: 'manual_seed',
    organization_confidence: 0.82,
    updated_at: '2026-07-11T09:00:00Z',
  },
  contacts: [
    {
      id: 'contact-website',
      type: 'website',
      label: 'Official Website',
      value: 'https://victory.org.ph',
      normalized_value: 'https://victory.org.ph',
      source_url: 'https://org.example.com/source',
      source_name: 'manual_seed',
      confidence: null,
      verification_status: 'unverified',
      is_verified: false,
      usage: 'research',
      warnings: [],
    },
    {
      id: 'contact-email',
      type: 'email',
      label: 'Public Email',
      value: 'info@victory.org.ph',
      normalized_value: 'info@victory.org.ph',
      source_url: null,
      source_name: 'manual_seed',
      confidence: null,
      verification_status: 'unverified',
      is_verified: false,
      usage: 'research',
      warnings: ['field_level_source_missing'],
    },
    {
      id: 'contact-phone',
      type: 'phone',
      label: 'Public Phone',
      value: '+63 2 1234 5678',
      normalized_value: '+63 2 1234 5678',
      source_url: 'https://org.example.com/source',
      source_name: 'manual_seed',
      confidence: null,
      verification_status: 'unverified',
      is_verified: false,
      usage: 'research',
      warnings: [],
    },
    {
      id: 'contact-facebook',
      type: 'social_profile',
      platform: 'facebook',
      label: 'Facebook',
      value: 'https://facebook.com/victoryph',
      normalized_value: 'https://facebook.com/victoryph',
      source_url: 'https://org.example.com/source',
      source_name: 'manual_seed',
      confidence: null,
      verification_status: 'unverified',
      is_verified: false,
      usage: 'research',
      warnings: [],
    },
  ],
  summary: {
    contact_count: 4,
    email_count: 1,
    phone_count: 1,
    social_count: 1,
    website_count: 1,
    verified_count: 0,
    missing_source_count: 1,
    outreach_candidate_count: 0,
  },
  warnings: ['field_level_source_missing'],
  found: true,
})

describe('ContactCard', () => {
  it('renders real contact payload details', () => {
    render(<ContactCard payload={buildPayload()} />)

    expect(screen.getByTestId('contact-card-organization')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('contact-card-summary')).toHaveTextContent('官网数量')
    expect(screen.getByTestId('contact-card-summary')).toHaveTextContent('邮箱数量')

    const contactsSection = screen.getByTestId('contact-card-contacts')
    expect(contactsSection).toHaveTextContent('https://victory.org.ph')
    expect(contactsSection).toHaveTextContent('info@victory.org.ph')
    expect(contactsSection).toHaveTextContent('+63 2 1234 5678')
    expect(contactsSection).toHaveTextContent('https://facebook.com/victoryph')
    expect(contactsSection).toHaveTextContent('verification_status: unverified')
    expect(contactsSection).toHaveTextContent('is_verified: false')

    const warningsSection = screen.getByTestId('contact-card-warnings')
    expect(warningsSection).toHaveTextContent('字段级来源缺失')
    expect(screen.getAllByRole('link', { name: /source_url: https:\/\/org\.example\.com\/source/i })[0]).toHaveAttribute('href', 'https://org.example.com/source')
  })

  it('shows empty state and does not fabricate a source url', () => {
    const payload = buildPayload()
    payload.contacts = []
    payload.summary.contact_count = 0
    payload.summary.email_count = 0
    payload.summary.phone_count = 0
    payload.summary.social_count = 0
    payload.summary.website_count = 0
    payload.warnings = ['contact_missing']

    render(<ContactCard payload={payload} />)

    expect(screen.getByTestId('contact-card-empty')).toHaveTextContent('当前数据库没有记录这个机构的公开联系方式。')
    expect(screen.queryByTestId('contact-card-contacts')).not.toBeInTheDocument()
  })

  it('shows missing source without inventing a link', () => {
    const payload = buildPayload()
    payload.contacts = [
      {
        ...payload.contacts[1],
        id: 'contact-email-missing-source',
        source_url: null,
        warnings: ['field_level_source_missing'],
      },
    ]
    payload.summary.contact_count = 1
    payload.summary.email_count = 1
    payload.summary.phone_count = 0
    payload.summary.social_count = 0
    payload.summary.website_count = 0

    render(<ContactCard payload={payload} />)

    const contactsSection = screen.getByTestId('contact-card-contacts')
    expect(contactsSection).toHaveTextContent('info@victory.org.ph')
    expect(contactsSection).toHaveTextContent('source_url: N/A')
    expect(contactsSection).toHaveTextContent('字段级来源缺失')
    expect(within(contactsSection).queryByRole('link', { name: /source_url:/i })).not.toBeInTheDocument()
  })
})
