import { useNavigate } from 'react-router-dom'

export function PricingPage() {
  const navigate = useNavigate()

  const plans = [
    {
      name: 'Free',
      price: '$0',
      period: '/month',
      description: 'Explore the Christian intelligence database',
      features: [
        'Browse 1,054 organizations',
        'View basic profiles & scores',
        'Country & type filters',
        'Public intelligence feed',
      ],
      cta: 'Get Started',
      highlighted: false,
    },
    {
      name: 'Pro',
      price: '$99',
      period: '/month',
      description: 'Full intelligence access for investors & researchers',
      features: [
        'Everything in Free',
        'Complete 3-dimension scores',
        'Investment evidence tracking',
        'Advanced filters & search',
        'CSV / PDF export',
        'API access (1,000 calls/mo)',
        'Priority intelligence alerts',
      ],
      cta: 'Start Pro Trial',
      highlighted: true,
    },
    {
      name: 'Enterprise',
      price: 'Custom',
      period: '',
      description: 'Custom intelligence solutions for institutions',
      features: [
        'Everything in Pro',
        'Unlimited API access',
        'Custom data collections',
        'White-label reports',
        'Dedicated support',
        'On-premise deployment option',
      ],
      cta: 'Contact Us',
      highlighted: false,
    },
  ]

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto', padding: '48px 24px' }}>
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <div
          style={{
            fontSize: 13,
            color: '#666',
            textTransform: 'uppercase',
            letterSpacing: 2,
            marginBottom: 12,
          }}
        >
          Pricing
        </div>
        <h1 style={{ fontSize: 36, fontWeight: 700, margin: '0 0 12px' }}>Invest in Intelligence</h1>
        <p style={{ fontSize: 16, color: '#666', maxWidth: 500, margin: '0 auto' }}>
          Choose the plan that fits your research and investment needs. Upgrade or downgrade anytime.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24 }}>
        {plans.map((plan) => (
          <div
            key={plan.name}
            style={{
              border: plan.highlighted ? '2px solid #2196f3' : '1px solid #e0e0e0',
              borderRadius: 16,
              padding: 32,
              background: plan.highlighted ? '#f0f7ff' : '#fff',
              boxShadow: plan.highlighted
                ? '0 4px 20px rgba(33,150,243,0.15)'
                : '0 1px 3px rgba(0,0,0,0.08)',
              position: 'relative',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            {plan.highlighted ? (
              <div
                style={{
                  position: 'absolute',
                  top: -1,
                  right: 24,
                  background: '#2196f3',
                  color: '#fff',
                  fontSize: 11,
                  fontWeight: 600,
                  padding: '4px 12px',
                  borderRadius: '0 0 8px 8px',
                }}
              >
                MOST POPULAR
              </div>
            ) : null}

            <div style={{ fontSize: 14, fontWeight: 600, color: '#666', marginBottom: 8 }}>{plan.name}</div>

            <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: 8 }}>
              <span style={{ fontSize: 40, fontWeight: 700 }}>{plan.price}</span>
              <span style={{ fontSize: 14, color: '#888' }}>{plan.period}</span>
            </div>

            <p style={{ fontSize: 13, color: '#666', marginBottom: 24, minHeight: 36 }}>{plan.description}</p>

            <button
              onClick={() => {
                if (plan.name === 'Free') navigate('/dashboard')
                else alert('Coming soon - Stripe integration in progress')
              }}
              style={{
                width: '100%',
                padding: '12px',
                borderRadius: 8,
                background: plan.highlighted ? '#2196f3' : '#fff',
                color: plan.highlighted ? '#fff' : '#333',
                border: plan.highlighted ? 'none' : '1px solid #ddd',
                fontSize: 14,
                fontWeight: 600,
                cursor: 'pointer',
                marginBottom: 24,
              }}
            >
              {plan.cta}
            </button>

            <div style={{ flex: 1 }}>
              {plan.features.map((feature, index) => (
                <div
                  key={index}
                  style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 10, fontSize: 13 }}
                >
                  <span style={{ color: '#4caf50', fontSize: 14, flexShrink: 0 }}>✓</span>
                  <span style={{ color: '#444' }}>{feature}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div style={{ textAlign: 'center', marginTop: 48, paddingTop: 24, borderTop: '1px solid #eee' }}>
        <p style={{ fontSize: 12, color: '#999' }}>
          All plans include SSL encryption and daily data updates. Enterprise plans include SLA guarantees.
        </p>
      </div>
    </div>
  )
}
