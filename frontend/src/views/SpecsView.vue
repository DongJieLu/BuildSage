<template>
  <div class="specs-view">
    <div class="page-head">
      <div>
        <h2>规格库</h2>
        <p class="sub">结构化参数来自公开规格页抽取 + 人工整理；攻略文档用于深度问答链路。</p>
      </div>
      <el-radio-group v-model="tab" size="small">
        <el-radio-button value="specs">硬件规格</el-radio-button>
        <el-radio-button value="docs">攻略文档</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 硬件规格 -->
    <template v-if="tab === 'specs'">
      <div class="toolbar">
        <el-radio-group v-model="category" size="small" @change="loadSpecs">
          <el-radio-button v-for="c in categories" :key="c.key" :value="c.key">{{ c.label }}</el-radio-button>
        </el-radio-group>
        <el-input
          v-model="keyword"
          style="width: 260px"
          placeholder="搜索型号，如 4070 / 14900K"
          clearable
          @keyup.enter="loadSpecs"
          @clear="loadSpecs"
        />
        <span class="count">{{ items.length }} 条</span>
      </div>
      <el-table :data="items" height="calc(100vh - 260px)" size="small" stripe>
        <el-table-column prop="name" label="型号" min-width="230" />
        <template v-for="col in columns" :key="col.prop">
          <el-table-column :prop="col.prop" :label="col.label" width="110" />
        </template>
        <el-table-column prop="source" label="来源" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.source === 'manual' ? 'warning' : 'info'">
              {{ row.source === 'manual' ? '人工整理' : '公开规格页' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <!-- 攻略文档 -->
    <template v-else>
      <div class="toolbar">
        <el-upload :show-file-list="false" :before-upload="onUpload" accept=".md,.txt,.pdf,.docx">
          <el-button type="primary">上传攻略文档</el-button>
        </el-upload>
        <span class="count">{{ docs.length }} 篇</span>
      </div>
      <el-table :data="docs" height="calc(100vh - 260px)" size="small" stripe>
        <el-table-column prop="doc_id" label="ID" width="70" />
        <el-table-column prop="file_name" label="文件名" min-width="300" />
        <el-table-column prop="file_type" label="类型" width="90" />
        <el-table-column prop="chunk_count" label="分块数" width="90" />
        <el-table-column prop="created_at" label="入库时间" width="180" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="danger" @click="removeDoc(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listSpecs, listSources, ingestFile, deleteSource } from '../api'

const tab = ref('specs')
const categories = [
  { key: 'cpu', label: 'CPU' },
  { key: 'gpu', label: '显卡' },
  { key: 'motherboard', label: '主板' },
  { key: 'memory', label: '内存' },
  { key: 'psu', label: '电源' },
]
const COLUMNS = {
  cpu: [
    { prop: 'socket', label: '插槽' },
    { prop: 'cores', label: '核心' },
    { prop: 'tdp_w', label: 'TDP(W)' },
    { prop: 'memory_types', label: '内存' },
  ],
  gpu: [
    { prop: 'vram_gb', label: '显存(GB)' },
    { prop: 'vram_type', label: '显存类型' },
    { prop: 'tdp_w', label: 'TDP(W)' },
    { prop: 'pcie_gen', label: 'PCIe' },
  ],
  motherboard: [
    { prop: 'socket', label: '插槽' },
    { prop: 'chipset', label: '芯片组' },
    { prop: 'memory_types', label: '内存' },
    { prop: 'form_factor', label: '板型' },
  ],
  memory: [
    { prop: 'mem_type', label: '类型' },
    { prop: 'capacity_gb', label: '容量(GB)' },
    { prop: 'speed_mhz', label: '频率' },
    { prop: 'modules', label: '条数' },
  ],
  psu: [
    { prop: 'rated_w', label: '额定(W)' },
    { prop: 'certification', label: '认证' },
    { prop: 'modularity', label: '模组' },
  ],
}

const category = ref('cpu')
const keyword = ref('')
const items = ref([])
const docs = ref([])

const columns = computed(() => COLUMNS[category.value] || [])

async function loadSpecs() {
  try {
    const data = await listSpecs(category.value, keyword.value, 200)
    items.value = data.items || []
  } catch (e) {
    ElMessage.error(`规格查询失败：${e.message}`)
  }
}

async function loadDocs() {
  try {
    const data = await listSources()
    docs.value = data.documents || []
  } catch (e) {
    ElMessage.error(`文档列表失败：${e.message}`)
  }
}

async function onUpload(file) {
  try {
    const r = await ingestFile(file, 'guide')
    ElMessage.success(`已入库：${file.name}（${r.chunk_count} 个分块）`)
    loadDocs()
  } catch (e) {
    ElMessage.error(`入库失败：${e.message}`)
  }
  return false
}

async function removeDoc(row) {
  try {
    await ElMessageBox.confirm(`确认删除「${row.file_name}」及其向量？`, '删除文档', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteSource(row.doc_id)
    ElMessage.success('已删除')
    loadDocs()
  } catch (e) {
    ElMessage.error(`删除失败：${e.message}`)
  }
}

onMounted(() => {
  loadSpecs()
  loadDocs()
})
</script>

<style scoped>
.specs-view {
  height: 100%;
  background: #fff;
  border-radius: 16px;
  padding: 20px 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
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
.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
}
.count {
  font-size: 13px;
  color: #a1a1a6;
}
</style>
