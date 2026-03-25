import { useEffect, useRef } from 'react'

import { getRunStatus } from '@/lib/api'

const POLL_INTERVAL_MS = 4000

interface UseAgentActivityPollerOptions {
  apiBasePath: string
  conversationId: string | null
  chatStatus: string
  resumeStream: () => Promise<void>
}

/**
 * Polls the lightweight run-status endpoint while the chat is idle.
 * When an active run is detected, triggers `resumeStream()` to attach
 * the client to the in-progress SSE stream.
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
        const runStatus = await getRunStatus(apiBasePath, conversationId)
        // Signal may have been aborted while the fetch was in-flight.
        // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
        if (abortController.signal.aborted) return

        if (runStatus.active) {
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
