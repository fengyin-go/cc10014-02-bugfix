import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/migration'
const statuses = ["待执行", "迁移中", "已完成", "部分失败", "已回滚"]

type Row = Record<string, unknown>

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.join('、')
  if (typeof value === 'object') return JSON.stringify(value, null, 0)
  return String(value)
}

function recordKeys(records: unknown): string[] {
  if (!Array.isArray(records)) return []
  const keys: string[] = []
  for (const item of records) {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      for (const key of Object.keys(item as Record<string, unknown>)) {
        if (!keys.includes(key)) keys.push(key)
      }
    }
  }
  return keys
}

function SnapshotTable({ title, records }: { title: string; records: unknown }) {
  const keys = recordKeys(records)
  const rows = Array.isArray(records) ? records : []
  return (
    <div className="panel">
      <h3>{title}（{rows.length} 条）</h3>
      {rows.length === 0 ? (
        <p className="muted">暂无数据</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>{keys.map((key) => <th key={key}>{key}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {keys.map((key) => (
                  <td key={key}>{cellText((row as Record<string, unknown>)?.[key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function MigrationView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [versionNo, setVersionNo] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [detail, setDetail] = useState<Row | null>(null)

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams()
    if (statusFilter) query.set('status', statusFilter)
    try {
      const response = await request(`${ENDPOINT}?${query.toString()}`)
      if (!response.ok) throw new Error('迁移批次列表读取失败')
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '迁移批次列表读取失败')
    }
  }, [statusFilter])

  useEffect(() => {
    void reload()
  }, [reload])

  const stats = useMemo(() => ([
    { label: '迁移批次总数', value: total },
    { label: '已完成批次', value: rows.filter((row) => row.status === '已完成').length },
    { label: '部分失败', value: rows.filter((row) => row.status === '部分失败').length },
    { label: '已回滚', value: rows.filter((row) => row.status === '已回滚').length },
  ]), [rows, total])

  async function call(path: string, fallback: string) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(path, { method: 'POST', body: JSON.stringify({ values: {} }) })
      const payload = await response.json()
      if (!response.ok || !payload.ok) throw new Error(payload.message || fallback)
      setNotice(payload.message || fallback)
      if (payload.entry) setDetail(payload.entry)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : fallback)
    }
  }

  async function createBatch() {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ values: { 版本号: versionNo.trim() } }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) throw new Error(payload.message || '迁移批次登记失败')
      setNotice(`${payload.message}：${cellText(payload.entry?.['批次号'])}，旧结果快照、兼容性标识、新字段清单已一并写入`)
      setDetail(payload.entry)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '迁移批次登记失败')
    }
  }

  async function openDetail(id: unknown) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${id}`)
      if (!response.ok) throw new Error('迁移批次明细读取失败')
      setDetail(await response.json())
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '迁移批次明细读取失败')
    }
  }

  const failedList = (detail?.['失败记录'] as unknown[]) ?? []
  const newFields = (detail?.['新字段清单'] as unknown[]) ?? []
  const details = (detail?.['迁移明细'] as unknown[]) ?? []

  return (
    <section className="page" data-module="migration">
      <header className="page-head">
        <div>
          <h2>版本迁移</h2>
          <p className="page-desc">以版本记录的旧查询定义与数据快照为起点，按兼容性标识迁移查询结果字段；批次同时写入旧结果快照、兼容性标识与新字段清单，回滚可恢复原查询结果。</p>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出迁移清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void createBatch() }}>
        <label className="filter-item">
          <span>版本号</span>
          <input value={versionNo} placeholder="如 VER-0002" onChange={(event) => setVersionNo(event.target.value)} />
        </label>
        <button className="btn primary" type="submit">登记迁移批次</button>
        <label className="filter-item">
          <span>状态</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">全部</option>
            {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </label>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            <th>批次号</th><th>版本号</th><th>兼容性标识</th><th>旧查询定义</th><th>新查询定义</th>
            <th>状态</th><th>仲裁说明</th><th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              <td>{cellText(row['批次号'])}</td>
              <td>{cellText(row['版本号'])}</td>
              <td>{cellText(row['兼容性标识'])}</td>
              <td>{cellText(row['旧查询定义'])}</td>
              <td>{cellText(row['新查询定义'])}</td>
              <td>{cellText(row.status)}</td>
              <td>{cellText(row['仲裁说明'])}</td>
              <td className="row-actions">
                <button className="link" type="button" onClick={() => void openDetail(row.id)}>详情</button>
                <button className="link" type="button" onClick={() => void call(`${ENDPOINT}/${row.id}/run`, '执行迁移失败')}>执行迁移</button>
                <button className="link" type="button" onClick={() => void call(`${ENDPOINT}/${row.id}/retry`, '重试失败记录失败')}>重试失败</button>
                <button className="link" type="button" onClick={() => void call(`${ENDPOINT}/${row.id}/rollback`, '执行回滚失败')}>执行回滚</button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td className="empty-state" colSpan={8}>暂无迁移批次，可先按版本号登记</td></tr>
          )}
        </tbody>
      </table>

      {detail && (
        <div className="detail-block">
          <div className="panel">
            <h3>迁移详情：{cellText(detail['批次号'])}（{cellText(detail.status)}）</h3>
            <div className="detail-grid">
              <span>版本号：{cellText(detail['版本号'])}</span>
              <span>兼容性标识：{cellText(detail['兼容性标识'])}</span>
              <span>旧查询定义：{cellText(detail['旧查询定义'])}</span>
              <span>新查询定义：{cellText(detail['新查询定义'])}</span>
              <span>旧字段清单：{cellText(detail['旧字段清单'])}</span>
              <span>仲裁说明：{cellText(detail['仲裁说明'])}</span>
            </div>
            <h3>新字段清单</h3>
            <div className="chip-row">
              {newFields.length === 0 && <span className="muted">暂无新字段</span>}
              {newFields.map((field) => <span key={String(field)} className="chip">{String(field)}</span>)}
            </div>
            {failedList.length > 0 && (
              <p className="error-text">失败记录序号：{failedList.map(String).join('、')}，可修正后重试</p>
            )}
          </div>

          <SnapshotTable title="旧结果快照" records={detail['旧结果快照']} />
          <SnapshotTable title="迁移结果数据集" records={detail['迁移结果']} />

          <div className="panel">
            <h3>迁移明细（逐项复核，{details.length} 条）</h3>
            {details.length === 0 ? (
              <p className="muted">尚未执行迁移</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr><th>序号</th><th>状态</th><th>旧数据</th><th>迁移数据</th><th>说明</th></tr>
                </thead>
                <tbody>
                  {details.map((item, index) => {
                    const entry = item as Record<string, unknown>
                    return (
                      <tr key={index}>
                        <td>{cellText(entry['序号'])}</td>
                        <td>{cellText(entry['状态'])}</td>
                        <td>{cellText(entry['旧数据'])}</td>
                        <td>{cellText(entry['迁移数据'])}</td>
                        <td>{cellText(entry['说明'])}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      <footer className="page-foot">
        <span>共 {total} 条迁移批次记录</span>
        {notice && <span className="ok-text">{notice}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
