<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">
        <span class="logo-mark">BS</span>
        <span class="logo-text">装机参谋</span>
      </div>
      <el-menu :default-active="activeMenu" router class="menu">
        <el-menu-item index="/">
          <el-icon><ChatDotRound /></el-icon>
          <span>对话问答</span>
        </el-menu-item>
        <el-menu-item index="/builder">
          <el-icon><SetUp /></el-icon>
          <span>装机配置器</span>
        </el-menu-item>
        <el-menu-item index="/specs">
          <el-icon><Cpu /></el-icon>
          <span>规格库</span>
        </el-menu-item>
        <el-menu-item index="/stats">
          <el-icon><DataAnalysis /></el-icon>
          <span>统计看板</span>
        </el-menu-item>
      </el-menu>
      <div class="aside-foot">
        <div class="foot-line">LangChain 1.x · LangGraph</div>
        <div class="foot-line dim">结构化 + 非结构化混合 RAG</div>
      </div>
    </el-aside>
    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { ChatDotRound, SetUp, Cpu, DataAnalysis } from '@element-plus/icons-vue'

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
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
}
.logo-mark {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: #1d1d1f;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: 0.5px;
}
.logo-text {
  font-size: 16px;
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
.aside-foot {
  margin-top: auto;
  padding: 16px 20px 20px;
}
.foot-line {
  font-size: 11px;
  color: #86868b;
  line-height: 1.7;
}
.foot-line.dim {
  color: #a1a1a6;
}
.main {
  padding: 24px;
  overflow: hidden;
}
</style>
