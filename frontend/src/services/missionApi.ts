const API_BASE = 'http://localhost:8000/api'

export async function createMission(query: string, country: string = '菲律宾') {
  const url = new URL(`${API_BASE}/missions`)
  url.searchParams.append('query', query)
  url.searchParams.append('country', country)
  const r = await fetch(url.toString(), { method: 'POST' })
  return r.json()
}

export async function getMissionStatus(missionId: string) {
  const r = await fetch(`${API_BASE}/missions/${missionId}`)
  return r.json()
}
