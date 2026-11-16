import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/version'
const columns = [
  "版本号",
  "关联服务",
  "变更描述",
  "兼容性标识",
  "灰度比例",
  "回滚脚本",
  "发布时间",
  "操作人"
]
const actions = [
  "启动灰度",
  "全量发布",
  "执行回滚"
]
const statuses = [
  "草稿",
  "灰度中",
  "全量发布",
  "已回滚"
]

type Row = Record<string, unknown>

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.join('、')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export default function VersionView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [showForm, setShowForm] = useState(false)
  const [formValues, setFormValues] = useState<Record<string, string>>({})
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const stats = useMemo(() => ([
    { label: '版本记录总数', value: total },
    { label: '全量版本', value: rows.filter((row) => row.status === '全量发布').length },
    { label: '灰度版本', value: rows.filter((row) => row.status === '灰度中').length },
  ]), [rows, total])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('版本记录列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '版本管理列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || '版本管理动作未生效，请稍后重试')
      }
      setNotice(payload.message || `版本记录已${action}`)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '版本管理操作失败')
    }
  }

  async function submitForm() {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ values: formValues }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || '版本记录登记失败')
      }
      setNotice(`版本记录已登记：${cellText(payload.entry?.['版本号'])}，兼容性标识、灰度比例、回滚脚本已一并保存`)
      setFormValues({})
      setShowForm(false)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '版本记录登记失败')
    }
  }

  return (
    <section className="page" data-module="version">
      <header className="page-head">
        <div>
          <h2>版本管理管理</h2>
          <p className="page-desc">维护版本管理的输入、执行约束与结果记录，为版本管理提供可验证的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setShowForm((prev) => !prev)}>
            登记版本记录
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出版本管理清单
          </button>
        </div>
      </header>

      {showForm && (
        <form
          className="panel"
          onSubmit={(event) => { event.preventDefault(); void submitForm() }}
        >
          <h3>登记版本记录</h3>
          <div className="form-grid">
            {columns.map((field) => (
              <label key={field} className="filter-item">
                <span>{field}</span>
                <input
                  value={formValues[field] ?? ''}
                  placeholder={`填写${field}`}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, [field]: event.target.value }))}
                />
              </label>
            ))}
          </div>
          <button className="btn primary" type="submit">提交登记</button>
        </form>
      )}

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{cellText(row[column])}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无版本管理数据，可先登记版本记录</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条版本管理记录</span>
        {notice && <span className="ok-text">{notice}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
