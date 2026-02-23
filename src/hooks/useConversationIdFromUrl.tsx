import { useState, useEffect } from 'react'

const CHAT_PATH_PREFIX = '/chat/'

function pathToConversationId(pathname: string): string | null {
  if (!pathname.startsWith(CHAT_PATH_PREFIX)) {
    return null
  }

  const maybeId = pathname.slice(CHAT_PATH_PREFIX.length)
  return maybeId || null
}

export function useConversationIdFromUrl(): [string | null, (id: string | null) => void] {
  const [conversationId, setConversationId] = useState(() => {
    return pathToConversationId(window.location.pathname)
  })

  useEffect(() => {
    const handlePopState = () => {
      const newId = pathToConversationId(window.location.pathname)
      setConversationId(newId)
    }

    window.addEventListener('popstate', handlePopState)
    // local event to handle same-tab updates
    window.addEventListener('history-state-changed', handlePopState)
    return () => {
      window.removeEventListener('popstate', handlePopState)
      window.removeEventListener('history-state-changed', handlePopState)
    }
  }, [])

  const setConversationIdAndUrl = (id: string | null) => {
    setConversationId(id)
    const url = new URL(window.location.toString())
    url.pathname = id ? `${CHAT_PATH_PREFIX}${id}` : '/'
    window.history.pushState({}, '', url.toString())
    window.dispatchEvent(new Event('history-state-changed'))
  }

  return [conversationId, setConversationIdAndUrl]
}
