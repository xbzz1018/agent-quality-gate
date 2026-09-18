import { createRouter, createWebHistory } from 'vue-router'

import AppShell from '@/layout/AppShell.vue'
import { useAuthStore } from '@/stores/auth'
import { pinia } from '@/stores'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    {
      path: '/',
      component: AppShell,
      children: [
        { path: '', name: 'overview', component: () => import('@/views/OverviewView.vue') },
        { path: 'targets', name: 'targets', component: () => import('@/views/TargetsView.vue') },
        { path: 'datasets', name: 'datasets', component: () => import('@/views/DatasetsView.vue') },
        { path: 'runs', name: 'runs', component: () => import('@/views/RunsView.vue') },
        {
          path: 'scenarios',
          name: 'scenarios',
          component: () => import('@/views/ScenariosView.vue'),
        },
        { path: 'runs/:id', name: 'run-detail', component: () => import('@/views/RunDetailView.vue') },
        {
          path: 'runs/:id/comparison',
          name: 'comparison',
          component: () => import('@/views/ComparisonView.vue'),
        },
        { path: 'runs/:id/gate', name: 'gate', component: () => import('@/views/GateView.vue') },
        { path: 'usage', name: 'usage', component: () => import('@/views/UsageView.vue') },
        { path: 'trace', name: 'trace', component: () => import('@/views/TraceSearchView.vue') },
        {
          path: 'gate-audits',
          name: 'gate-audits',
          component: () => import('@/views/GateAuditView.vue'),
        },
        {
          path: 'admin/:section?',
          name: 'admin',
          component: () => import('@/views/AdminView.vue'),
        },
        {
          path: 'skills',
          name: 'skills',
          component: () => import('@/views/SkillsView.vue'),
        },
        {
          path: 'pending/:area',
          name: 'pending',
          component: () => import('@/views/PendingView.vue'),
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore(pinia)
  if (to.name === 'login' && !auth.initialized && !auth.authenticated) return
  await auth.initialize()
  if (to.name !== 'login' && !auth.authenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.authenticated) return { name: 'overview' }
})

window.addEventListener('aqh:auth-expired', () => {
  const auth = useAuthStore(pinia)
  auth.clear()
  router.replace({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
})

export default router
