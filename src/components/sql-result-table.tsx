import DataTable, { type TableColumn } from 'react-data-table-component'
import { useMemo } from 'react'

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
  const columns = useMemo<TableColumn<SqlResultRow>[]>(
    () =>
      result.columns.map((column) => ({
        id: column,
        name: column,
        selector: (row) => toCellText(row[column]),
        wrap: true,
      })),
    [result.columns],
  )

  const data = useMemo<SqlResultRow[]>(
    () => result.rows.map((row, index) => ({ ...row, __rowIndex: index })),
    [result.rows],
  )

  return (
    <DataTable
      columns={columns}
      data={data}
      dense
      pagination
      paginationPerPage={25}
      paginationRowsPerPageOptions={[10, 25, 50, 100]}
      highlightOnHover
      responsive
      defaultSortFieldId={result.columns[0]}
      customStyles={{
        table: { style: { minWidth: '100%' } },
      }}
    />
  )
}
