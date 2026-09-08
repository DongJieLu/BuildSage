// 会话 id：每个浏览器实例持有一个持久 session_id，用于后端多轮上下文。
// 清空对话时重置，等价于开启一个全新会话。
const KEY = 'buildsage_session_id'

export function getSessionId() {
  let id = localStorage.getItem(KEY)
  if (!id) {
    id = crypto.randomUUID
      ? crypto.randomUUID()
      : `sess-${Date.now()}-${Math.random().toString(16).slice(2)}`
    localStorage.setItem(KEY, id)
  }
  return id
}

export function resetSessionId() {
  localStorage.removeItem(KEY)
}
