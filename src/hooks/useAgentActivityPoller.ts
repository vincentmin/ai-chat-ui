import { useEffect, useRef } from 'react'

const POLL_INTERVAL_MS = 4000

interface UseAgentActivityPollerOptions {
  apiBasePath: string
  conversationId: string | null
  chatStatus: string
  resumeStream: () => Promise<void>
}

/**
 * Polls the agent's stream endpoint while the chat is idle.
 * When a non-204 response is detected (meaning a run is active),
 * triggers `resumeStream()` to attach the column to the new stream.
 */
export function useAgentActivityPoller({
  apiBasePath,
  conversationId,
  chatStatus,
  resumeStream,
}: UseAgentActivityPollerOptions) {
  const pollingRef = useRef(false)

  useEffect(() => {
    if (!conversationId || chatStatus !== 'ready') {
      return
    }

    const abortController = new AbortController()

    const poll = async () => {
      if (pollingRef.current || abortController.signal.aborted) return
      pollingRef.current = true

      try {
        const res = await fetch(`${apiBasePath}/chat/${conversationId}/stream`, {
          signal: abortController.signal,
        })
        // Signal may have been aborted while the fetch was in-flight.
        // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
        if (abortController.signal.aborted) return

        if (res.status !== 204) {
          // A run is active — attach to it. Consume the body to avoid leaking.
          await res.body?.cancel()
          await resumeStream()
        }
      } catch {
        // Network errors / aborts are non-fatal; retry on next tick.
      } finally {
        pollingRef.current = false
      }
    }

    const intervalId = setInterval(() => {
      poll().catch(() => {
        // Swallow — poll() handles its own errors internally.
      })
    }, POLL_INTERVAL_MS)

    return () => {
      abortController.abort()
      clearInterval(intervalId)
    }
  }, [apiBasePath, conversationId, chatStatus, resumeStream])
}
