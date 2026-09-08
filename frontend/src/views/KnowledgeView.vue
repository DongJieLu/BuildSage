<template>
  <div class="knowledge-view">
    <el-card shadow="never" class="card">
      <template #header>上传文档</template>
      <el-upload
        :auto-upload="false"
        :limit="1"
        :on-change="onFileChange"
        :on-remove="() => (file = null)"
        accept=".pdf,.docx,.txt,.md"
      >
        <el-button>选择文件（PDF / DOCX / TXT / MD）</el-button>
      </el-upload>
      <div class="upload-row">
        <el-select v-model="uploadCategory" style="width: 140px" placeholder="知识方向">
          <el-option v-for="c in CATEGORIES" :key="c" :label="c" :value="c" />
        </el-select>
        <el-button type="primary" :loading="uploading" :disabled="!file" @click="doUpload">
          上传入库
        </el-button>
      </div>
      <div v-if="uploadResult" class="result">{{ uploadResult }}</div>
    </el-card>

    <el-card shadow="never" class="card">
      <template #header>
        <div class="list-header">
          <span>文档列表</span>
          <div class="list-actions">
            <el-select v-model="filterCategory" style="width: 140px" @change="loadDocs">
              <el-option v-for="c in filterOptions" :key="c.value" :label="c.label" :value="c.value" />
            </el-select>
            <el-button @click="loadDocs">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="docs" v-loading="loadingDocs" border stripe>
        <el-table-column prop="doc_id" label="doc_id" width="80" />
        <el-table-column prop="file_name" label="文件名" min-width="180" />
        <el-table-column prop="category" label="方向" width="90" />
        <el-table-column prop="file_type" label="类型" width="80" />
        <el-table-column prop="chunk_count" label="分块数" width="90" />
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="danger" @click="doDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ingestFile, listSources, deleteSource } from '../api'

const CATEGORIES = ['ai', 'java', 'test', 'ops', 'bigdata']
const filterOptions = [
  { label: '全部', value: '' },
  ...CATEGORIES.map((c) => ({ label: c, value: c })),
]

const uploadCategory = ref('ai')
const filterCategory = ref('')
const file = ref(null)
const uploading = ref(false)
const uploadResult = ref('')
const docs = ref([])
const loadingDocs = ref(false)

function onFileChange(uploadFile) {
  file.value = uploadFile.raw
}

async function doUpload() {
  if (!file.value) return
  uploading.value = true
  uploadResult.value = ''
  try {
    const r = await ingestFile(file.value, uploadCategory.value)
    uploadResult.value = `入库成功：doc_id=${r.doc_id}，分块 ${r.chunk_count} 个`
    ElMessage.success('入库成功')
    file.value = null
    loadDocs()
  } catch (e) {
    uploadResult.value = `入库失败：${e.message}`
    ElMessage.error(`入库失败：${e.message}`)
  } finally {
    uploading.value = false
  }
}

async function loadDocs() {
  loadingDocs.value = true
  try {
    const r = await listSources(filterCategory.value || null)
    docs.value = r.documents || []
  } catch (e) {
    ElMessage.error(`加载失败：${e.message}`)
  } finally {
    loadingDocs.value = false
  }
}

async function doDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除文档「${row.file_name}」(doc_id=${row.doc_id})？`,
      '删除确认',
      { type: 'warning' },
    )
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

onMounted(loadDocs)
</script>

<style scoped>
.knowledge-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.card {
  border-radius: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
.upload-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}
.result {
  margin-top: 12px;
  color: #6e6e73;
}
.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.list-actions {
  display: flex;
  gap: 12px;
}
</style>
