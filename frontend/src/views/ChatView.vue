<template>
  <div class="chat-view">
    <div class="chat-toolbar">
      <el-select v-model="category" style="width: 150px" placeholder="知识方向">
        <el-option v-for="c in categoryOptions" :key="c.value" :label="c.label" :value="c.value" />
      </el-select>
      <div class="examples">
        <el-tag
          v-for="ex in examples"
          :key="ex"
          class="example-tag"
          effect="plain"
          @click="askExample(ex)"
        >{{ ex }}</el-tag>
      </div>
      <el-button :disabled="streaming" @click="clearChat">清空对话</el-button>
    </div>

    <div ref="scrollRef" class="chat-scroll">
      <el-empty v-if="!messages.length" description="问我硬件参数、装机兼容性，或选购建议" />
      <div v-for="(m, i) in messages" :key="i" class="msg-row" :class="m.role">
        <div class="bubble">
          <!-- 路由徽章：标注走了哪条通道 -->
          <div v-if="m.role === 'assistant' && m.intent" class="meta-row">
            <span class="route-badge" :class="m.intent">{{ intentLabel(m.intent) }}</span>
            <span v-if="m.strategy" class="strategy">{{ m.strategy }}</span>
            <span v-if="m.latency" class="latency">{{ m.latency }} ms</span>
            <span v-if="m.cacheHit" class="latency">缓存命中</span>
          </div>

          <!-- 参数卡片 -->
          <div v-if="m.role === 'assistant' && m.intent === 'param' && m.card" class="spec-card">
            <div class="spec-name">{{ m.card.name }}</div>
            <div v-for="row in m.card.rows" :key="row.label" class="spec-row">
              <span class="spec-label">{{ row.label }}</span>
              <span class="spec-value">{{ row.value }}</span>
            </div>
          </div>

          <!-- 兼容核验单 -->
          <div v-else-if="m.role === 'assistant' && m.intent === 'compat' && m.checks.length" class="check-list">
            <div v-for="(c, ci) in m.checks" :key="ci" class="check-row" :class="c.status">
              <span class="check-icon">{{ c.icon }}</span>
              <span class="check-text">
                <b v-if="c.rule">{{ c.rule }}</b> {{ c.text }}
              </span>
            </div>
            <div v-if="m.conclusion" class="conclusion">{{ m.conclusion }}</div>
          </div>

          <!-- 普通文本（流式 / rag / 拒答） -->
          <div v-if="m.content" class="bubble-text">{{ m.content }}</div>
          <div v-if="m.progress" class="progress-line">
            <span class="dot" />{{ m.progress }}
          </div>

          <el-collapse
            v-if="m.role === 'assistant' && m.citations && m.citations.length"
            class="citations"
          >
            <el-collapse-item :title="`引用来源（${m.citations.length}）`">
              <div v-for="(c, ci) in m.citations" :key="ci" class="citation-item">
                <div class="citation-head">
                  [{{ ci + 1 }}] {{ c.doc_name || '未知文档' }}<template v-if="c.title"> — {{ c.title }}</template>
                </div>
                <div class="citation-text">{{ c.text }}</div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </div>

    <div class="chat-input">
      <el-input
        v-model="question"
        placeholder="例如：RTX 4070 的 TDP 是多少 / 14900K 配 650W 电源行吗 / 5000 元怎么配"
        :disabled="streaming"
        @keyup.enter="send"
      />
      <el-button type="primary" :loading="streaming" @click="send">发送</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'
import { chatStream } from '../api'
import { getSessionId, resetSessionId } from '../utils/session'

const categoryOptions = [
  { label: '全部', value: '' },
  { label: '选购攻略', value: 'guide' },
]
const examples = ['RTX 4070 的 TDP 是多少', 'i9-14900K 配 650W 电源够吗', '5000 元装机怎么配']

const category = ref('')
const question = ref('')
const messages = ref([])
const streaming = ref(false)
const scrollRef = ref(null)

const INTENT_LABELS = {
  param: '参数直查',
  compat: '兼容校验',
  rag: '深度问答',
  reject: '拒答',
}
function intentLabel(i) {
  return INTENT_LABELS[i] || i
}

const CHECK_ICONS = { '✅': 'pass', '❌': 'conflict', '💡': 'warn', '➖': 'skip' }

function parseParamCard(text) {
  // 形如：**GeForce RTX 4070**\n- TDP: 200\n- 显存容量: 12
  const lines = (text || '').split('\n').map((l) => l.trim()).filter(Boolean)
  if (!lines.length || !lines[0].startsWith('**')) return null
  const name = lines[0].replace(/\*\*/g, '')
  const rows = []
  for (const line of lines.slice(1)) {
    const m = line.match(/^-\s*([^:：]+)[:：]\s*(.+)$/)
    if (m) rows.push({ label: m[1].trim(), value: m[2].trim() })
  }
  return rows.length ? { name, rows } : null
}

function parseChecks(text) {
  const lines = (text || '').split('\n').map((l) => l.trim()).filter(Boolean)
  const checks = []
  let conclusion = ''
  for (const line of lines) {
    const icon = line.slice(0, 2)
    if (CHECK_ICONS[icon]) {
      const body = line.slice(2).trim()
      const rm = body.match(/^(R[1-5])\s+(.*)$/)
      checks.push({
        icon,
        status: CHECK_ICONS[icon],
        rule: rm ? rm[1] : '',
        text: rm ? rm[2] : body,
      })
    } else if (line.startsWith('**结论')) {
      conclusion = line.replace(/\*\*/g, '')
    }
  }
  return { checks, conclusion }
}

async function send() {
  const q = question.value.trim()
  if (!q || streaming.value) return
  question.value = ''
  messages.value.push({ role: 'user', content: q })
  const ai = {
    role: 'assistant', content: '', citations: [], intent: '', strategy: '',
    latency: 0, cacheHit: false, card: null, checks: [], conclusion: '', progress: '',
  }
  messages.value.push(ai)
  streaming.value = true
  try {
    await chatStream(q, category.value || null, getSessionId(), (evt) => {
      if (evt.type === 'route') {
        ai.intent = evt.intent || ''
        ai.strategy = evt.strategy || ''
      } else if (evt.type === 'progress') {
        ai.progress = progressLabel(evt.stage)
      } else if (evt.type === 'token') {
        ai.progress = ''
        ai.content += evt.content || ''
      } else if (evt.type === 'citation') {
        ai.citations = evt.citations || []
      } else if (evt.type === 'done') {
        ai.latency = evt.latency_ms || 0
        ai.cacheHit = !!evt.cache_hit
        ai.progress = ''
        if (!ai.content) ai.content = '（无输出）'
        if (ai.intent === 'param') {
          const card = parseParamCard(ai.content)
          if (card) {
            ai.card = card
            ai.content = ''
          }
        } else if (ai.intent === 'compat') {
          const { checks, conclusion } = parseChecks(ai.content)
          if (checks.length) {
            ai.checks = checks
            ai.conclusion = conclusion
            ai.content = ''
          }
        }
      } else if (evt.type === 'error') {
        ai.content = `服务出错：${evt.message || '未知错误'}`
      }
    })
  } catch (e) {
    ai.content = `请求失败：${e.message}`
  } finally {
    streaming.value = false
  }
}

function progressLabel(stage) {
  return {
    slot_extraction: '正在识别型号…',
    config_extraction: '正在解析配置清单…',
    retrieval: '正在检索攻略文档并重排…',
  }[stage] || '处理中…'
}

function askExample(ex) {
  question.value = ex
  send()
}

function clearChat() {
  messages.value = []
  resetSessionId()
}

watch(
  messages,
  async () => {
    await nextTick()
    if (scrollRef.value) {
      scrollRef.value.scrollTop = scrollRef.value.scrollHeight
    }
  },
  { deep: true },
)
</script>

<style scoped>
.chat-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
.chat-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid #f0f0f2;
  flex-wrap: wrap;
}
.examples {
  display: flex;
  gap: 8px;
  flex: 1;
  flex-wrap: wrap;
}
.example-tag {
  cursor: pointer;
}
.example-tag:hover {
  border-color: #1d1d1f;
  color: #1d1d1f;
}
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}
.msg-row {
  display: flex;
  margin-bottom: 20px;
}
.msg-row.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 82%;
}
.meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.route-badge {
  font-size: 12px;
  padding: 2px 9px;
  border-radius: 999px;
  font-weight: 600;
}
.route-badge.param {
  background: #e8f0fe;
  color: #1a56db;
}
.route-badge.compat {
  background: #fef3e2;
  color: #b45309;
}
.route-badge.rag {
  background: #e7f6ec;
  color: #0f7b3f;
}
.route-badge.reject {
  background: #f0f0f2;
  color: #6e6e73;
}
.strategy,
.latency {
  font-size: 12px;
  color: #a1a1a6;
}
.bubble-text {
  white-space: pre-wrap;
  word-break: break-word;
  padding: 12px 16px;
  border-radius: 16px;
  line-height: 1.65;
  font-size: 15px;
}
.msg-row.user .bubble-text {
  background: #1d1d1f;
  color: #fff;
  border-bottom-right-radius: 6px;
}
.msg-row.assistant .bubble-text {
  background: #f5f5f7;
  color: #1d1d1f;
  border-bottom-left-radius: 6px;
}
/* 参数卡片 */
.spec-card {
  background: #f5f5f7;
  border-radius: 14px;
  padding: 16px 18px;
  border-bottom-left-radius: 6px;
}
.spec-name {
  font-size: 15px;
  font-weight: 700;
  margin-bottom: 10px;
  color: #1d1d1f;
}
.spec-row {
  display: flex;
  justify-content: space-between;
  padding: 5px 0;
  border-bottom: 1px dashed #e5e5e7;
  font-size: 14px;
}
.spec-row:last-child {
  border-bottom: none;
}
.spec-label {
  color: #6e6e73;
}
.spec-value {
  color: #1d1d1f;
  font-weight: 600;
}
/* 兼容核验单 */
.check-list {
  background: #f5f5f7;
  border-radius: 14px;
  padding: 14px 16px;
  border-bottom-left-radius: 6px;
}
.check-row {
  display: flex;
  gap: 8px;
  padding: 5px 0;
  font-size: 14px;
  line-height: 1.6;
}
.check-row.conflict .check-text {
  color: #b91c1c;
}
.check-row.warn .check-text {
  color: #b45309;
}
.check-row.skip .check-text {
  color: #a1a1a6;
}
.check-icon {
  flex-shrink: 0;
}
.conclusion {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #e5e5e7;
  font-weight: 700;
  font-size: 14px;
  color: #1d1d1f;
}
.progress-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #86868b;
  padding: 8px 0;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #1d1d1f;
  animation: pulse 1s infinite ease-in-out;
}
@keyframes pulse {
  0%, 100% { opacity: 0.25; }
  50% { opacity: 1; }
}
.citations {
  margin-top: 8px;
  background: #fff;
  border: 1px solid #e5e5e7;
  border-radius: 12px;
}
.citation-item {
  margin-bottom: 10px;
}
.citation-head {
  font-weight: 600;
  margin-bottom: 4px;
  color: #1d1d1f;
}
.citation-text {
  color: #6e6e73;
  font-size: 13px;
  background: #f5f5f7;
  padding: 10px;
  border-radius: 8px;
  white-space: pre-wrap;
}
.chat-input {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid #f0f0f2;
  background: #fff;
}
.chat-input .el-input {
  flex: 1;
}
</style>
