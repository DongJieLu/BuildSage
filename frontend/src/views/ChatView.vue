<template>
  <div class="chat-view">
    <div class="chat-toolbar">
      <el-select v-model="category" style="width: 140px" placeholder="知识方向">
        <el-option v-for="c in categoryOptions" :key="c.value" :label="c.label" :value="c.value" />
      </el-select>
      <el-button :disabled="streaming" @click="clearChat">清空对话</el-button>
    </div>

    <div ref="scrollRef" class="chat-scroll">
      <el-empty v-if="!messages.length" description="输入问题开始对话" />
      <div v-for="(m, i) in messages" :key="i" class="msg-row" :class="m.role">
        <div class="bubble">
          <div class="bubble-text">{{ m.content }}</div>
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
        placeholder="输入你的问题，回车发送"
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

const CATEGORIES = ['ai', 'java', 'test', 'ops', 'bigdata']
const categoryOptions = [
  { label: '全部', value: '' },
  ...CATEGORIES.map((c) => ({ label: c, value: c })),
]

const category = ref('')
const question = ref('')
const messages = ref([])
const streaming = ref(false)
const scrollRef = ref(null)

async function send() {
  const q = question.value.trim()
  if (!q || streaming.value) return
  question.value = ''
  messages.value.push({ role: 'user', content: q })
  const ai = { role: 'assistant', content: '', citations: [] }
  messages.value.push(ai)
  streaming.value = true
  try {
    await chatStream(q, category.value || null, getSessionId(), (evt) => {
      if (evt.type === 'token') {
        ai.content += evt.content || ''
      } else if (evt.type === 'citation') {
        ai.citations = evt.citations || []
      } else if (evt.type === 'done') {
        if (!ai.content) ai.content = '（无输出）'
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
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f2;
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
.msg-row.assistant {
  justify-content: flex-start;
}
.bubble {
  max-width: 78%;
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
