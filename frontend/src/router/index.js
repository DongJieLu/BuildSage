import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'chat', component: () => import('../views/ChatView.vue') },
  { path: '/knowledge', name: 'knowledge', component: () => import('../views/KnowledgeView.vue') },
  { path: '/stats', name: 'stats', component: () => import('../views/StatsView.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
