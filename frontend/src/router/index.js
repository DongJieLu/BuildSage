import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'chat', component: () => import('../views/ChatView.vue') },
  { path: '/builder', name: 'builder', component: () => import('../views/BuilderView.vue') },
  { path: '/specs', name: 'specs', component: () => import('../views/SpecsView.vue') },
  { path: '/stats', name: 'stats', component: () => import('../views/StatsView.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
