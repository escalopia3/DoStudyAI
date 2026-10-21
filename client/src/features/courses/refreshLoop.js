// Schedule after settlement: slow requests never overlap.
export function createRefreshLoop(refresh, enabled, delay = 10000, clock = globalThis) {
  let timer, stopped = true
  async function tick() {
    if (stopped) return
    try { if (enabled()) await refresh() }
    finally { if (!stopped) timer = clock.setTimeout(tick, delay) }
  }
  return {
    start() {
      if (!stopped) return
      stopped = false
      timer = clock.setTimeout(tick, delay)
    },
    stop() { stopped = true; clock.clearTimeout(timer) }
  }
}
