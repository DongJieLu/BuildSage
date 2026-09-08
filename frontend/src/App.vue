<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">BuildSage</div>
      <el-menu :default-active="activeMenu" router class="menu">
        <el-menu-item index="/">
          <el-icon><ChatDotRound /></el-icon>
          <span>对话</span>
        </el-menu-item>
        <el-menu-item index="/knowledge">
          <el-icon><Folder /></el-icon>
          <span>知识库</span>
        </el-menu-item>
        <el-menu-item index="/stats">
          <el-icon><DataAnalysis /></el-icon>
          <span>统计看板</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { ChatDotRound, Folder, DataAnalysis } from '@element-plus/icons-vue'

const route = useRoute()
const activeMenu = computed(() => route.path)
</script>

<style scoped>
.layout {
  height: 100vh;
  background: #f5f5f7;
}
.aside {
  background: #f5f5f7;
  border-right: 1px solid #e5e5e7;
  display: flex;
  flex-direction: column;
}
.logo {
  height: 64px;
  line-height: 64px;
  padding: 0 24px;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.3px;
  color: #1d1d1f;
}
.menu {
  border-right: none;
  background: transparent;
  padding: 8px 12px;
  --el-menu-bg-color: transparent;
  --el-menu-text-color: #3d3d3f;
  --el-menu-hover-bg-color: #e8e8ed;
  --el-menu-hover-text-color: #1d1d1f;
  --el-menu-active-color: #1d1d1f;
  --el-menu-item-height: 44px;
}
.menu :deep(.el-menu-item) {
  border-radius: 10px;
  margin-bottom: 4px;
  transition: background-color 0.2s ease;
}
.menu :deep(.el-menu-item.is-active) {
  background: #e8e8ed;
  font-weight: 600;
}
.main {
  padding: 24px;
  overflow: hidden;
}
</style>
