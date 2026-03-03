import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { ArrowDownIcon } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'
import { useCallback } from 'react'
import { StickToBottom, useStickToBottomContext } from 'use-stick-to-bottom'

export type ConversationProps = ComponentProps<typeof StickToBottom>

export const Conversation = ({ className, ...props }: ConversationProps) => (
  <StickToBottom
    className={cn('relative flex-1 custom-scrollbar overflow-hidden', className)}
    initial="smooth"
    resize="smooth"
    role="log"
    {...props}
  />
)

export type ConversationContentProps = ComponentProps<typeof StickToBottom.Content>

export const ConversationContent = ({ className, ...props }: ConversationContentProps) => (
  <StickToBottom.Content className={cn('p-4 stick-to-bottom', className)} {...props} />
)

export type ConversationEmptyStateProps = ComponentProps<'div'> & {
  title?: string
  description?: string
  icon?: ReactNode
}

export const ConversationEmptyState = ({
  className,
  title = 'No messages yet',
  description = 'Start a conversation to see messages here.',
  icon,
  children,
  ...props
}: ConversationEmptyStateProps) => (
  <div className={cn('flex flex-col items-center justify-center gap-3 px-6 py-12 text-center', className)} {...props}>
    {icon}
    <div className="space-y-1">
      <p className="font-medium text-sm">{title}</p>
      <p className="text-muted-foreground text-sm">{description}</p>
    </div>
    {children}
  </div>
)

export type ConversationScrollButtonProps = ComponentProps<typeof Button>

export const ConversationScrollButton = ({ className, ...props }: ConversationScrollButtonProps) => {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext()

  const handleScrollToBottom = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-floating-promises
    scrollToBottom()
  }, [scrollToBottom])

  return (
    !isAtBottom && (
      <Button
        className={cn('absolute bottom-4 left-[50%] translate-x-[-50%] rounded-full', className)}
        onClick={handleScrollToBottom}
        size="icon"
        type="button"
        variant="outline"
        {...props}
      >
        <ArrowDownIcon className="size-4" />
      </Button>
    )
  )
}
