const BRIDGE_URL = "http://127.0.0.1:8009"

export default function (pi) {
  const seen = new Set()
  const running = new Set()
  const pending = new Set()
  let heartbeat
  let inflight = false

  function sid(ctx) {
    const id = ctx.sessionManager.getSessionId()
    if (typeof id === "string" && id) return id
    const file = ctx.sessionManager.getSessionFile()
    if (typeof file === "string" && file) return file
    return String(process.pid)
  }

  function prune(keep) {
    for (const id of [...seen]) {
      if (id === keep || running.has(id) || pending.has(id)) continue
      seen.delete(id)
    }
  }

  function flush() {
    if (inflight) return
    inflight = true
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 200)
    const status = {}
    for (const id of seen) status[id] = running.has(id) ? "busy" : "idle"
    fetch(`${BRIDGE_URL}/providers/pi`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: String(process.pid),
        status,
        blocking: [...pending],
      }),
      signal: ctrl.signal,
    }).catch(() => {}).finally(() => {
      clearTimeout(timer)
      inflight = false
    })
  }

  function start() {
    if (heartbeat) return
    heartbeat = setInterval(flush, 1000)
    heartbeat.unref?.()
  }

  function stop() {
    if (heartbeat) clearInterval(heartbeat)
    heartbeat = undefined
  }

  pi.on("session_start", async (event, ctx) => {
    const id = sid(ctx)
    if (event.reason === "new" || event.reason === "resume" || event.reason === "fork") {
      prune(id)
    }
    if (!ctx.isIdle()) {
      seen.add(id)
      running.add(id)
    }
    start()
    flush()
  })

  pi.on("agent_start", async (_event, ctx) => {
    const id = sid(ctx)
    seen.add(id)
    running.add(id)
    flush()
  })

  pi.on("agent_settled", async (_event, ctx) => {
    const id = sid(ctx)
    running.delete(id)
    if (seen.has(id)) prune(id)
    flush()
  })

  pi.on("ui_prompt_start", async (_event, ctx) => {
    const id = sid(ctx)
    seen.add(id)
    pending.add(id)
    flush()
  })

  pi.on("ui_prompt_end", async (_event, ctx) => {
    pending.delete(sid(ctx))
    flush()
  })

  pi.on("session_shutdown", async () => {
    stop()
  })
}
