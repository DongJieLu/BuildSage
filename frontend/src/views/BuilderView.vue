<template>
  <div class="builder-view">
    <div class="page-head">
      <div>
        <h2>装机配置器</h2>
        <p class="sub">选择配件后一键核验 —— 走的是纯规则引擎（R1~R5），结论可溯源、不依赖 LLM 判断。</p>
      </div>
      <el-button type="primary" :loading="checking" @click="check">校验兼容性</el-button>
    </div>

    <div class="picker-grid">
      <div v-for="cat in categories" :key="cat.key" class="picker-card">
        <div class="picker-label">
          <span class="cat-name">{{ cat.label }}</span>
          <span class="cat-count">{{ options[cat.key].length }} 款</span>
        </div>
        <el-select
          v-model="selected[cat.key]"
          filterable
          clearable
          style="width: 100%"
          :placeholder="`选择${cat.label}`"
        >
          <el-option v-for="o in options[cat.key]" :key="o.name" :label="o.name" :value="o.name">
            <span class="opt-name">{{ o.name }}</span>
            <span class="opt-meta">{{ metaOf(cat.key, o) }}</span>
          </el-option>
        </el-select>
      </div>
      <div class="picker-card">
        <div class="picker-label">
          <span class="cat-name">机箱显卡限长</span>
          <span class="cat-count">可选</span>
        </div>
        <el-input v-model="caseLimit" placeholder="例如 355（毫米）" />
      </div>
    </div>

    <div v-if="result" class="result-panel">
      <div class="result-head">
        <span class="result-title">核验结果</span>
        <span class="route-badge" :class="verdictClass">{{ verdictText }}</span>
        <span v-if="latency" class="latency">{{ latency }} ms</span>
      </div>
      <div class="check-list">
        <div v-for="(c, i) in result.checks" :key="i" class="check-row" :class="c.status">
          <span class="check-icon">{{ c.icon }}</span>
          <span class="check-text"><b v-if="c.rule">{{ c.rule }}</b> {{ c.text }}</span>
        </div>
        <div v-if="result.conclusion" class="conclusion">{{ result.conclusion }}</div>
      </div>
    </div>
    <el-empty v-else-if="!checking" description="选择配件后点击「校验兼容性」" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { listSpecs, chat } from '../api'
import { getSessionId } from '../utils/session'

const categories = [
  { key: 'cpu', label: 'CPU' },
  { key: 'gpu', label: '显卡' },
  { key: 'motherboard', label: '主板' },
  { key: 'memory', label: '内存' },
  { key: 'psu', label: '电源' },
]

const options = ref({ cpu: [], gpu: [], motherboard: [], memory: [], psu: [] })
const selected = ref({ cpu: '', gpu: '', motherboard: '', memory: '', psu: '' })
const caseLimit = ref('')
const checking = ref(false)
const result = ref(null)
const latency = ref(0)
const verdictClass = ref('pass')
const verdictText = ref('')

const CHECK_ICONS = { '✅': 'pass', '❌': 'conflict', '💡': 'warn', '➖': 'skip' }

function metaOf(key, o) {
  if (key === 'cpu') return `${o.socket || '-'} · ${o.tdp_w || '-'}W · ${o.cores || '-'}核`
  if (key === 'gpu') return `${o.vram_gb || '-'}GB ${o.vram_type || ''} · ${o.tdp_w || '-'}W`
  if (key === 'motherboard') return `${o.socket || '-'} · ${o.memory_types || '-'} · ${o.form_factor || '-'}`
  if (key === 'memory') return `${o.mem_type || '-'} · ${o.capacity_gb || '-'}GB · ${o.speed_mhz || '-'}MHz`
  if (key === 'psu') return `${o.rated_w || '-'}W · ${o.certification || '-'}`
  return ''
}

async function loadOptions() {
  for (const c of categories) {
    try {
      const data = await listSpecs(c.key, '', 300)
      options.value[c.key] = data.items || []
    } catch {
      options.value[c.key] = []
    }
  }
}

function buildQuestion() {
  const parts = []
  if (selected.value.cpu) parts.push(selected.value.cpu)
  if (selected.value.gpu) parts.push(selected.value.gpu)
  if (selected.value.motherboard) parts.push(`主板 ${selected.value.motherboard}`)
  if (selected.value.memory) parts.push(`内存 ${selected.value.memory}`)
  if (selected.value.psu) parts.push(`电源 ${selected.value.psu}`)
  if (caseLimit.value) parts.push(`机箱显卡限长 ${caseLimit.value} 毫米`)
  return `帮我检查这套配置是否兼容：${parts.join('，')}`
}

async function check() {
  if (!selected.value.cpu && !selected.value.gpu && !selected.value.motherboard && !selected.value.psu) {
    return
  }
  checking.value = true
  result.value = null
  try {
    const data = await chat(buildQuestion(), null, getSessionId())
    latency.value = data.latency_ms || 0
    const lines = (data.answer || '').split('\n').map((l) => l.trim()).filter(Boolean)
    const checks = []
    let conclusion = ''
    const icons = Object.keys(CHECK_ICONS)
    for (const line of lines) {
      const icon = icons.find((i) => line.startsWith(i))
      if (icon) {
        const body = line.slice(icon.length).trim()
        const rm = body.match(/^(R[1-5])\s+(.*)$/)
        checks.push({ icon, status: CHECK_ICONS[icon], rule: rm ? rm[1] : '', text: rm ? rm[2] : body })
      } else if (line.startsWith('**结论')) {
        conclusion = line.replace(/\*\*/g, '')
      }
    }
    result.value = { checks, conclusion }
    if (conclusion.includes('存在冲突')) {
      verdictClass.value = 'conflict'
      verdictText.value = '存在冲突'
    } else if (conclusion.includes('信息不足')) {
      verdictClass.value = 'unknown'
      verdictText.value = '信息不足'
    } else if (conclusion.includes('提示')) {
      verdictClass.value = 'compat'
      verdictText.value = '可用有提示'
    } else {
      verdictClass.value = 'pass'
      verdictText.value = '配置兼容'
    }
  } catch (e) {
    result.value = { checks: [], conclusion: `校验失败：${e.message}` }
  } finally {
    checking.value = false
  }
}

onMounted(loadOptions)
</script>

<style scoped>
.builder-view {
  height: 100%;
  overflow-y: auto;
  background: #fff;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
}
.page-head h2 {
  margin: 0 0 6px;
  font-size: 20px;
  color: #1d1d1f;
}
.sub {
  margin: 0;
  font-size: 13px;
  color: #86868b;
}
.picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}
.picker-card {
  background: #f5f5f7;
  border-radius: 12px;
  padding: 14px 16px;
}
.picker-label {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
}
.cat-name {
  font-weight: 600;
  font-size: 14px;
  color: #1d1d1f;
}
.cat-count {
  font-size: 12px;
  color: #a1a1a6;
}
.opt-name {
  float: left;
}
.opt-meta {
  float: right;
  color: #a1a1a6;
  font-size: 12px;
  margin-left: 16px;
}
.result-panel {
  margin-top: 24px;
  background: #f5f5f7;
  border-radius: 14px;
  padding: 18px 20px;
}
.result-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.result-title {
  font-weight: 700;
  color: #1d1d1f;
}
.route-badge {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 999px;
  font-weight: 600;
}
.route-badge.pass {
  background: #e7f6ec;
  color: #0f7b3f;
}
.route-badge.compat {
  background: #fef3e2;
  color: #b45309;
}
.route-badge.conflict {
  background: #fdecec;
  color: #b91c1c;
}
.route-badge.unknown {
  background: #f0f0f2;
  color: #6e6e73;
}
.latency {
  font-size: 12px;
  color: #a1a1a6;
}
.check-row {
  display: flex;
  gap: 8px;
  padding: 6px 0;
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
.conclusion {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e5e5e7;
  font-weight: 700;
  color: #1d1d1f;
}
</style>
