import { useState, useEffect } from 'react'

function normalizeBasePath(basePath: string): string {
  const trimmed = basePath.trim()
  if (!trimmed || trimmed === '/') {
    return ''
  }
  return trimmed.endsWith('/') ? trimmed.slice(0, -1) : trimmed
}

function pathToConversationId(pathname: string, conversationBasePath: string): string | null {
  const normalizedBasePath = normalizeBasePath(conversationBasePath)
  const chatPathPrefix = `${normalizedBasePath}/chat/`

  if (!pathname.startsWith(chatPathPrefix)) {
    return null
  }

  const maybeId = pathname.slice(chatPathPrefix.length)
  return maybeId || null
}

export function useConversationIdFromUrl(conversationBasePath: string): [string | null, (id: string | null) => void] {
  const normalizedBasePath = normalizeBasePath(conversationBasePath)

  const [conversationId, setConversationId] = useState(() => {
    return pathToConversationId(window.location.pathname, normalizedBasePath)
  })

  useEffect(() => {
    const handlePopState = () => {
      const newId = pathToConversationId(window.location.pathname, normalizedBasePath)
      setConversationId(newId)
    }

    window.addEventListener('popstate', handlePopState)
    // local event to handle same-tab updates
    window.addEventListener('history-state-changed', handlePopState)
    return () => {
      window.removeEventListener('popstate', handlePopState)
      window.removeEventListener('history-state-changed', handlePopState)
    }
  }, [normalizedBasePath])

  const setConversationIdAndUrl = (id: string | null) => {
    setConversationId(id)
    const url = new URL(window.location.toString())
    url.pathname = id ? `${normalizedBasePath}/chat/${id}` : normalizedBasePath || '/'
    window.history.pushState({}, '', url.toString())
    window.dispatchEvent(new Event('history-state-changed'))
  }

  return [conversationId, setConversationIdAndUrl]
}
