async function req(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export const api = {
  health: () => req('/api/health'),
  overview: () => req('/api/overview'),
  bay: () => req('/api/bay'),
  occupancies: () => req('/api/occupancies'),
  events: () => req('/api/events'),
  quarantine: () => req('/api/quarantine'),
  proofs: () => req('/api/occupancy-proofs'),
  settings: () => req('/api/settings'),
  setOverdue: (overdue_hours) =>
    req('/api/settings/overdue-hours', { method: 'PUT', body: JSON.stringify({ overdue_hours }) }),
  ingest: () => req('/api/ingest/run', { method: 'POST', body: '{}' }),
  channelBuckets: (batch_id) =>
    req(batch_id ? `/api/channel-buckets?batch_id=${encodeURIComponent(batch_id)}` : '/api/channel-buckets'),
  channelBucketProofs: () => req('/api/channel-bucket-proofs'),
  channelBucketVerify: () => req('/api/channel-bucket-proofs/verify'),
}
