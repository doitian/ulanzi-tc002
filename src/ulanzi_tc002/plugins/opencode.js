const BRIDGE_URL = "http://127.0.0.1:8009"

export default () => {
  const seen = new Set()
  const running = new Set()
  const pending = new Map()
  let inflight = false

  function drop(sid) {
    seen.delete(sid)
    running.delete(sid)
    for (const [id, session] of pending) if (session === sid) pending.delete(id)
  }

  function flush() {
    if (inflight) return
    inflight = true
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 200)
    const status = {}
    for (const sid of seen) status[sid] = running.has(sid) ? "busy" : "idle"
    fetch(`${BRIDGE_URL}/providers/opencode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: String(process.pid),
        status,
        blocking: [...new Set(pending.values())],
      }),
      signal: ctrl.signal,
    }).catch(() => {}).finally(() => {
      clearTimeout(timer)
      inflight = false
    })
  }

  function apply(event) {
    const type = String(event?.type || "")
    const props = event?.properties || {}
    const sid = props.sessionID || props.info?.id
    const requestID = props.id || props.permissionID || props.requestID
    if (type === "session.status" && sid) {
      const kind = props.status?.type
      if (kind === "busy" || kind === "retry") {
        seen.add(sid)
        running.add(sid)
      } else {
        running.delete(sid)
      }
    } else if (type === "session.idle" && sid) {
      running.delete(sid)
    } else if (type === "session.deleted" && sid) {
      drop(sid)
    } else if (sid && requestID && /permission|question/.test(type) && /asked|updated/.test(type)) {
      seen.add(sid)
      pending.set(requestID, sid)
    } else if (requestID && /replied|rejected/.test(type)) {
      pending.delete(requestID)
    }
  }

  const heartbeat = setInterval(flush, 1000)
  heartbeat.unref?.()
  return {
    event: ({ event }) => apply(event),
  }
}
