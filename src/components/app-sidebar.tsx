import { CirclePlus, MessageCircle, Trash } from 'lucide-react'
import type React from 'react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { ConversationEntry } from '@/types'
import { ModeToggle } from './mode-toggle'
import logoSvg from '../assets/logo.svg'

interface ConversationsResponse {
  conversations: ConversationEntry[]
}

async function fetchConversations(apiBasePath: string) {
  const res = await fetch(`${apiBasePath}/chats`)
  if (!res.ok) {
    throw new Error('Failed to fetch conversations')
  }
  return (await res.json()) as ConversationsResponse
}

async function deleteConversation(apiBasePath: string, conversationId: string) {
  const res = await fetch(`${apiBasePath}/chat/${conversationId}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    throw new Error('Failed to delete conversation')
  }
}

interface AppSidebarProps {
  apiBasePath: string
  conversationBasePath: string
  title: string
  conversationId: string | null
  onConversationIdChange: (id: string | null) => void
}

export function AppSidebar({
  apiBasePath,
  conversationBasePath,
  title,
  conversationId,
  onConversationIdChange,
}: AppSidebarProps) {
  const isSql = conversationBasePath === '/sql'
  const [refreshTick, setRefreshTick] = useState(0)
  const conversationsQuery = useQuery({
    queryFn: () => fetchConversations(apiBasePath),
    queryKey: ['conversations', apiBasePath, refreshTick],
  })
  const conversations = conversationsQuery.data?.conversations ?? []
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [conversationToDelete, setConversationToDelete] = useState<ConversationEntry | null>(null)

  useEffect(() => {
    const refresh = () => {
      setRefreshTick((value) => value + 1)
    }

    window.addEventListener('conversations-changed', refresh)
    return () => {
      window.removeEventListener('conversations-changed', refresh)
    }
  }, [])

  const handleDeleteClick = (e: React.MouseEvent, conversation: ConversationEntry) => {
    e.preventDefault()
    e.stopPropagation()
    setConversationToDelete(conversation)
    setDeleteDialogOpen(true)
  }

  const handleConfirmDelete = () => {
    if (conversationToDelete) {
      deleteConversation(apiBasePath, conversationToDelete.id)
        .then(() => {
          setDeleteDialogOpen(false)
          setConversationToDelete(null)
          setRefreshTick((value) => value + 1)

          if (conversationId === conversationToDelete.id) {
            onConversationIdChange(null)
          }

          toast.success('Chat deleted successfully')
        })
        .catch((error: unknown) => {
          console.error('Failed to delete conversation', error)
          toast.error('Failed to delete chat')
        })
    }
  }

  return (
    <TooltipProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <SidebarTrigger className="ml-auto" />
          <div className="ml-2 flex items-center">
            <h1 className="text-l font-medium text-balance truncate whitespace-nowrap">
              <img src={logoSvg} className="inline h-4 mr-2 mb-1" />
              <span className="group-data-[state=collapsed]:invisible">{title}</span>
            </h1>
          </div>
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup>
            <SidebarMenu className="mb-2">
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="Start a new conversation">
                  {isSql ? (
                    <Link to="/sql">
                      <CirclePlus />
                      <span>New conversation</span>
                    </Link>
                  ) : (
                    <Link to="/arxiv">
                      <CirclePlus />
                      <span>New conversation</span>
                    </Link>
                  )}
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>

            <SidebarGroupContent>
              <SidebarMenu>
                {conversations.map((conversation, index) => (
                  <SidebarMenuItem key={index} className="group/sidebar-menu-item">
                    <div className="flex items-center gap-1 h-auto">
                      <SidebarMenuButton asChild tooltip={conversation.firstMessage} className="flex-1">
                        {isSql ? (
                          <Link
                            to="/sql/chat/$conversationId"
                            params={{ conversationId: conversation.id }}
                            className={cn('h-auto flex items-start gap-2', {
                              'bg-accent pointer-events-none': conversation.id === conversationId,
                            })}
                          >
                            <MessageCircle className="size-3 mt-1" />
                            <span className="flex flex-col items-start">
                              <span className="truncate max-w-44">{conversation.firstMessage}</span>
                              <span className="text-xs opacity-30">
                                {new Date(conversation.timestamp).toLocaleString()}
                              </span>
                            </span>
                          </Link>
                        ) : (
                          <Link
                            to="/arxiv/chat/$conversationId"
                            params={{ conversationId: conversation.id }}
                            className={cn('h-auto flex items-start gap-2', {
                              'bg-accent pointer-events-none': conversation.id === conversationId,
                            })}
                          >
                            <MessageCircle className="size-3 mt-1" />
                            <span className="flex flex-col items-start">
                              <span className="truncate max-w-44">{conversation.firstMessage}</span>
                              <span className="text-xs opacity-30">
                                {new Date(conversation.timestamp).toLocaleString()}
                              </span>
                            </span>
                          </Link>
                        )}
                      </SidebarMenuButton>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-auto p-1.5 opacity-0 group-hover/sidebar-menu-item:opacity-100 transition-opacity group-data-[state=collapsed]:hidden absolute right-0 self-start"
                            onClick={(e) => {
                              handleDeleteClick(e, conversation)
                            }}
                          >
                            <Trash className="size-3" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Delete conversation</TooltipContent>
                      </Tooltip>
                    </div>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter>
          <ModeToggle />
        </SidebarFooter>

        <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
          <DialogContent
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                handleConfirmDelete()
              }
            }}
          >
            <DialogHeader>
              <DialogTitle>Delete conversation?</DialogTitle>
              <DialogDescription>
                Are you sure you want to delete this chat? This action cannot be undone.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setDeleteDialogOpen(false)
                }}
              >
                Cancel
              </Button>
              <Button variant="destructive" onClick={handleConfirmDelete} autoFocus>
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </Sidebar>
    </TooltipProvider>
  )
}
