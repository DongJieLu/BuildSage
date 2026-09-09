import axios from 'axios'
import { getSessionId } from '../utils/session'

// 统一响应包 { code, data, msg }；code===0 表示成功。
const http = axios.create({
  baseURL: '/api/v1',
  timeout: 180000,
})

async function unwrap(promise) {
  const { data } = await promise
  if (data.code !== 0) {
    throw new Error(data.msg || '请求失败')
  }
  return data.data
}

// 非流式问答
export function chat(question, category, sessionId) {
  return unwrap(http.post('/chat', { question, category, session_id: sessionId }))
}

// 流式问答：POST + fetch + ReadableStream 手动解析 SSE。
// 事件类型：route / token / citation / done / error
export async function chatStream(question, category, sessionId, onEvent) {
  const resp = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, category, session_id: sessionId }),
  })
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => '')
    throw new Error(`流式请求失败 (${resp.status})：${text}`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, idx).trim()
      buffer = buffer.slice(idx + 2)
      if (!raw.startsWith('data:')) continue
      const payload = raw.slice(5).trim()
      if (!payload) continue
      let evt
      try {
        evt = JSON.parse(payload)
      } catch {
        continue
      }
      onEvent(evt)
    }
  }
}

// 文档入库（multipart）
export function ingestFile(file, category) {
  const form = new FormData()
  form.append('file', file)
  form.append('category', category)
  return unwrap(http.post('/ingest', form))
}

// 文档列表
export function listSources(category) {
  return unwrap(http.get('/sources', { params: { category: category || undefined } }))
}

// 删除文档
export function deleteSource(docId) {
  return unwrap(http.delete(`/sources/${docId}`))
}

// 规格库查询（category: cpu|gpu|motherboard|memory|psu）
export function listSpecs(category, q, limit = 100) {
  return unwrap(http.get('/specs', { params: { category, q: q || undefined, limit } }))
}

// 统计
export function getStats(days) {
  return unwrap(http.get('/stats', { params: { days } }))
}

// 健康检查
export function health() {
  return unwrap(http.get('/health'))
}

export { getSessionId }
