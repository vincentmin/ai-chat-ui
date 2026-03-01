import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  type ColumnDef,
  type PaginationState,
  type SortingState,
  useReactTable,
} from '@tanstack/react-table'
import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'

export interface SqlResultData {
  sql_query: string
  columns: string[]
  rows: Record<string, unknown>[]
  row_count: number
  column_count: number
}

type SqlResultRow = Record<string, unknown> & { __rowIndex: number }

function toCellText(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }
  if (typeof value === 'string') {
    return value
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return JSON.stringify(value)
}

interface SqlResultTableProps {
  result: SqlResultData
}

export function SqlResultTable({ result }: SqlResultTableProps) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 25,
  })

  const columns = useMemo<ColumnDef<SqlResultRow>[]>(
    () =>
      result.columns.map((column) => ({
        id: column,
        accessorFn: (row) => row[column],
        header: column,
        cell: ({ getValue }) => toCellText(getValue()),
        sortingFn: 'alphanumeric',
      })),
    [result.columns],
  )

  const data = useMemo<SqlResultRow[]>(
    () => result.rows.map((row, index) => ({ ...row, __rowIndex: index })),
    [result.rows],
  )

  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      pagination,
    },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  })

  const pageCount = table.getPageCount()
  const pageIndex = table.getState().pagination.pageIndex
  const pageSize = table.getState().pagination.pageSize
  const hasColumns = columns.length > 0

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-max caption-bottom text-sm">
          <thead className="border-b bg-muted/40">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const canSort = header.column.getCanSort()
                  const sorted = header.column.getIsSorted()
                  const sortIndicator = sorted === 'asc' ? ' ▲' : sorted === 'desc' ? ' ▼' : ''

                  return (
                    <th key={header.id} className="h-10 px-3 text-left align-middle font-medium text-foreground">
                      {header.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 hover:underline"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {sortIndicator}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  )
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {hasColumns && table.getRowModel().rows.length > 0 ? (
              table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="border-b transition-colors hover:bg-muted/30">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="max-w-xl px-3 py-2 align-top whitespace-pre-wrap wrap-break-word">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-3 py-6 text-center text-muted-foreground" colSpan={Math.max(columns.length, 1)}>
                  No rows returned.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-muted-foreground">
          Showing {table.getRowModel().rows.length} of {result.row_count} rows
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm text-muted-foreground" htmlFor="sql-table-page-size">
            Rows per page
          </label>
          <select
            id="sql-table-page-size"
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={pageSize}
            onChange={(event) => {
              table.setPageSize(Number(event.target.value))
            }}
          >
            {[10, 25, 50, 100].map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>

          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              table.previousPage()
            }}
            disabled={!table.getCanPreviousPage()}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              table.nextPage()
            }}
            disabled={!table.getCanNextPage()}
          >
            Next
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {pageCount === 0 ? 0 : pageIndex + 1} of {pageCount}
          </span>
        </div>
      </div>
    </div>
  )
}
