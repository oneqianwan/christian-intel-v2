import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { AdminLayout } from '../AdminLayout'

describe('AdminLayout', () => {
  it('主内容区提供独立纵向滚动容器，不依赖 body 滚动', () => {
    render(
      <MemoryRouter>
        <AdminLayout>
          <div>admin content</div>
        </AdminLayout>
      </MemoryRouter>,
    )

    const scrollContainer = screen.getByTestId('admin-layout-scroll-container')
    expect(scrollContainer).toHaveStyle({
      flex: '1',
      minHeight: '0',
      overflowY: 'auto',
      overflowX: 'hidden',
    })
  })
})
