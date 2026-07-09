import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  AdminApiError,
  listAdminUsers,
  revokeAdminUserSessions,
  updateAdminUserRole,
  updateAdminUserStatus,
} from '../admin'

function mockJsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'ERROR',
    text: vi.fn().mockResolvedValue(JSON.stringify(body)),
  } as unknown as Response
}

describe('adminApi', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8001/api')
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  it('使用 credentials include 请求 admin users 列表', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockJsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
    )

    await listAdminUsers()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('http://127.0.0.1:8001/api/admin/users')
    expect(init?.credentials).toBe('include')
    expect(init?.method).toBe('GET')
  })

  it('role/status/revoke 请求使用 public_id 路径且不发送前端 role 伪造字段', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockJsonResponse({
        public_id: 'user-public-1',
        email: 'target@example.com',
        display_name: 'Target',
        role: 'admin',
        status: 'active',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    )

    await updateAdminUserRole('user-public-1', 'admin')
    await updateAdminUserStatus('user-public-1', 'active')
    await revokeAdminUserSessions('user-public-1')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8001/api/admin/users/user-public-1/role',
      expect.objectContaining({
        method: 'PATCH',
        credentials: 'include',
        body: JSON.stringify({ role: 'admin' }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://127.0.0.1:8001/api/admin/users/user-public-1/status',
      expect.objectContaining({
        method: 'PATCH',
        credentials: 'include',
        body: JSON.stringify({ status: 'active' }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      'http://127.0.0.1:8001/api/admin/users/user-public-1/sessions/revoke',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
      }),
    )
  })

  it('403 返回明确权限错误，不降级成普通失败', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockJsonResponse(
        {
          detail: {
            error_code: 'ROLE_FORBIDDEN',
            message: 'Insufficient permissions',
          },
        },
        403,
      ),
    )

    await expect(listAdminUsers()).rejects.toEqual(
      expect.objectContaining<Partial<AdminApiError>>({
        status: 403,
        errorCode: 'ROLE_FORBIDDEN',
        message: 'Insufficient permissions',
      }),
    )
  })

  it('409 与 422 保留后端 message', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    fetchMock
      .mockResolvedValueOnce(
        mockJsonResponse(
          {
            detail: {
              error_code: 'LAST_SUPER_ADMIN_PROTECTED',
              message: 'Cannot disable the last active super admin',
            },
          },
          409,
        ),
      )
      .mockResolvedValueOnce(
        mockJsonResponse(
          {
            detail: {
              error_code: 'VALIDATION_ERROR',
              message: 'Unknown role',
            },
          },
          422,
        ),
      )

    await expect(updateAdminUserStatus('user-public-1', 'disabled')).rejects.toEqual(
      expect.objectContaining<Partial<AdminApiError>>({
        status: 409,
        message: 'Cannot disable the last active super admin',
      }),
    )
    await expect(updateAdminUserRole('user-public-1', 'viewer')).rejects.toEqual(
      expect.objectContaining<Partial<AdminApiError>>({
        status: 422,
        message: 'Unknown role',
      }),
    )
  })
})
