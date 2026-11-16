import { useEffect, useState } from 'react'

import { fetchJson } from '@/api/client'

type VersionContract = {
  版本号: string
  状态: string
  兼容性标识: string
  灰度比例: string
  新字段清单: string[]
  来源批次: string
  仲裁说明: string
}

type VersionFieldRow = {
  版本号: string
  状态: string
  兼容性标识: string
  新字段清单: string[]
  发布时间: string
}

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
  数据版本契约?: VersionContract | null
  版本字段清单?: VersionFieldRow[]
}

const fallbackCards = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
const fallbackModules = [{"name": "服务注册", "created": 0, "pending": 0, "abnormal": 0}, {"name": "查询编排", "created": 0, "pending": 0, "abnormal": 0}, {"name": "接口限流", "created": 0, "pending": 0, "abnormal": 0}, {"name": "鉴权管理", "created": 0, "pending": 0, "abnormal": 0}, {"name": "服务监控", "created": 0, "pending": 0, "abnormal": 0}, {"name": "消费方登记", "created": 0, "pending": 0, "abnormal": 0}, {"name": "版本管理", "created": 0, "pending": 0, "abnormal": 0}, {"name": "结果缓存", "created": 0, "pending": 0, "abnormal": 0}, {"name": "响应转换", "created": 0, "pending": 0, "abnormal": 0}, {"name": "网关路由", "created": 0, "pending": 0, "abnormal": 0}, {"name": "接口文档", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据源配置", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据查询", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据清洗", "created": 0, "pending": 0, "abnormal": 0}, {"name": "调用日志", "created": 0, "pending": 0, "abnormal": 0}, {"name": "模拟数据", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据备份", "created": 0, "pending": 0, "abnormal": 0}, {"name": "事件通知", "created": 0, "pending": 0, "abnormal": 0}]

export default function Overview() {
  const [cards, setCards] = useState<Overview['cards']>(fallbackCards)
  const [moduleRows, setModuleRows] = useState<Overview['modules']>(fallbackModules)
  const [contract, setContract] = useState<VersionContract | null>(null)
  const [versionFields, setVersionFields] = useState<VersionFieldRow[]>([])

  useEffect(() => {
    fetchJson<Overview>('/api/overview')
      .then((payload) => {
        setCards(payload.cards)
        setModuleRows(payload.modules)
        setContract(payload['数据版本契约'] ?? null)
        setVersionFields(payload['版本字段清单'] ?? [])
      })
      .catch(() => undefined)
  }, [])

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <h2>运营概览</h2>
          <p className="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
        </div>
      </header>
      <div className="stat-row">
        {cards.map((card) => (
          <article key={card.label} className="stat-card">
            <span className="stat-label">{card.label}</span>
            <strong className="stat-value">{card.value}</strong>
          </article>
        ))}
      </div>

      <div className="panel">
        <h3>数据版本契约</h3>
        {contract ? (
          <>
            <div className="detail-grid">
              <span>当前版本：{contract['版本号']}</span>
              <span>状态：{contract['状态']}</span>
              <span>兼容性标识：{contract['兼容性标识']}</span>
              <span>灰度比例：{contract['灰度比例']}</span>
              <span>来源批次：{contract['来源批次'] || '—'}</span>
              <span>仲裁说明：{contract['仲裁说明'] || '—'}</span>
            </div>
            <div className="chip-row">
              {(contract['新字段清单'] ?? []).map((field) => (
                <span key={field} className="chip">{field}</span>
              ))}
            </div>
          </>
        ) : (
          <p className="muted">暂无生效中的数据版本契约</p>
        )}
      </div>

      <div className="panel">
        <h3>版本字段清单（含旧版本）</h3>
        <table className="data-table">
          <thead>
            <tr><th>版本号</th><th>状态</th><th>兼容性标识</th><th>新字段清单</th><th>发布时间</th></tr>
          </thead>
          <tbody>
            {versionFields.map((row) => (
              <tr key={row['版本号']}>
                <td>{row['版本号']}</td>
                <td>{row['状态']}</td>
                <td>{row['兼容性标识'] ?? '—'}</td>
                <td>{(row['新字段清单'] ?? []).join('、') || '—'}</td>
                <td>{row['发布时间'] ?? '—'}</td>
              </tr>
            ))}
            {versionFields.length === 0 && (
              <tr><td className="empty-state" colSpan={5}>暂无版本记录</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <table className="data-table">
        <thead>
          <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
        </thead>
        <tbody>
          {moduleRows.map((row) => (
            <tr key={row.name}>
              <td>{row.name}</td>
              <td>{row.created}</td>
              <td>{row.pending}</td>
              <td>{row.abnormal}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
