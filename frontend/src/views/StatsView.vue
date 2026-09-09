<template>
  <div class="stats-view">
    <div class="stats-toolbar">
      <span class="label">统计天数</span>
      <el-slider v-model="days" :min="1" :max="30" style="width: 240px" @change="loadStats" />
      <el-button @click="loadStats">刷新统计</el-button>
    </div>

    <el-alert v-if="summary" :title="summary" type="info" :closable="false" class="summary" />

    <el-row :gutter="16">
      <el-col :span="12">
        <div ref="intentRef" class="chart"></div>
      </el-col>
      <el-col :span="12">
        <div ref="strategyRef" class="chart"></div>
      </el-col>
    </el-row>
    <el-row :gutter="16">
      <el-col :span="24">
        <div ref="dailyRef" class="chart"></div>
      </el-col>
    </el-row>

    <el-card shadow="never" class="card">
      <template #header>热点问题 Top10（近 30 天）</template>
      <el-table :data="hotQuestions" border stripe>
        <el-table-column prop="question" label="问题" min-width="300" />
        <el-table-column prop="count" label="提问次数" width="120" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getStats } from '../api'

const days = ref(7)
const summary = ref('')
const hotQuestions = ref([])
const intentRef = ref(null)
const strategyRef = ref(null)
const dailyRef = ref(null)

let charts = []

function renderBar(el, data, name) {
  const chart = echarts.init(el)
  const items = Object.entries(data || {})
  chart.setOption({
    title: { text: name, left: 'center', textStyle: { fontSize: 14, fontWeight: 600, color: '#1d1d1f' } },
    tooltip: {},
    grid: { left: 40, right: 20, top: 50, bottom: 40 },
    xAxis: {
      type: 'category',
      data: items.map(([k]) => k),
      axisLine: { lineStyle: { color: '#d2d2d7' } },
      axisLabel: { color: '#6e6e73' },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#f0f0f2' } },
      axisLabel: { color: '#6e6e73' },
    },
    series: [
      {
        type: 'bar',
        data: items.map(([, v]) => v),
        barMaxWidth: 40,
        itemStyle: { color: '#1d1d1f', borderRadius: [4, 4, 0, 0] },
      },
    ],
  })
  return chart
}

function renderLine(el, daily) {
  const chart = echarts.init(el)
  const items = daily || []
  chart.setOption({
    title: { text: '日均延迟', left: 'center', textStyle: { fontSize: 14, fontWeight: 600, color: '#1d1d1f' } },
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 50, bottom: 40 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: items.map((d) => d.date),
      axisLine: { lineStyle: { color: '#d2d2d7' } },
      axisLabel: { color: '#6e6e73' },
    },
    yAxis: {
      type: 'value',
      name: 'ms',
      splitLine: { lineStyle: { color: '#f0f0f2' } },
      axisLabel: { color: '#6e6e73' },
    },
    series: [
      {
        name: '平均延迟(ms)',
        type: 'line',
        smooth: true,
        data: items.map((d) => d.avg_latency_ms),
        lineStyle: { color: '#1d1d1f', width: 2 },
        itemStyle: { color: '#1d1d1f' },
        areaStyle: { color: 'rgba(29, 29, 31, 0.06)' },
      },
    ],
  })
  return chart
}

function disposeCharts() {
  charts.forEach((c) => c.dispose())
  charts = []
}

async function loadStats() {
  try {
    const data = await getStats(days.value)
    const specTotal = Object.values(data.spec_scale || {}).reduce((a, b) => a + b, 0)
    summary.value = `近 ${days.value} 天共 ${data.total} 条问答 · 平均延迟 ${data.avg_latency_ms} ms · 规格库 ${specTotal} 个型号`
    hotQuestions.value = data.hot_questions || []
    await nextTick()
    disposeCharts()
    charts = [
      renderBar(intentRef.value, data.intent_distribution, '意图分布'),
      renderBar(strategyRef.value, data.strategy_distribution, '策略分布'),
      renderLine(dailyRef.value, data.daily),
    ]
  } catch (e) {
    ElMessage.error(`统计加载失败：${e.message}`)
  }
}

function handleResize() {
  charts.forEach((c) => c.resize())
}

onMounted(() => {
  loadStats()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  disposeCharts()
})
</script>

<style scoped>
.stats-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.stats-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #fff;
  padding: 16px 20px;
  border-radius: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
.label {
  color: #6e6e73;
}
.summary {
  border-radius: 12px;
}
.chart {
  height: 320px;
  background: #fff;
  border-radius: 16px;
  margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
.card {
  border-radius: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
</style>
