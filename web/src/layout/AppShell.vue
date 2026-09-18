<script setup lang="ts">
import {
  Activity,
  BarChart3,
  BookOpenCheck,
  Boxes,
  Building2,
  ChevronDown,
  ChevronRight,
  CircleDollarSign,
  Database,
  FileSearch,
  KeyRound,
  LogOut,
  Menu,
  PlaySquare,
  Workflow,
  ScrollText,
  Settings,
  ShieldCheck,
  Target,
  Users,
  X,
} from '@lucide/vue'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const mobileOpen = ref(false)

const navGroups = computed(() => [
  {
    label: '评测平台',
    items: [
      { label: '质量总览', path: '/', icon: Activity },
      { label: '被测目标', path: '/targets', icon: Target },
      { label: '评测数据集', path: '/datasets', icon: Database },
      { label: '评测运行', path: '/runs', icon: PlaySquare },
      { label: '场景运行', path: '/scenarios', icon: Workflow },
    ],
  },
  {
    label: '分析与门禁',
    items: [
      { label: '版本对比', path: '/runs?view=comparison', icon: BarChart3 },
      { label: 'Trace 与回放', path: '/trace', icon: FileSearch },
      { label: '发布门禁', path: '/gate-audits', icon: ShieldCheck },
      { label: '用量与成本', path: '/usage', icon: CircleDollarSign },
    ],
  },
  {
    label: '系统管理',
    items: [
      { label: '组织与成员', path: '/admin/members', icon: Users },
      { label: '角色与权限', path: '/admin/roles', icon: KeyRound },
      { label: '凭据与审计', path: '/admin/service-accounts', icon: ScrollText },
      { label: '系统设置', path: '/admin/settings', icon: Settings },
    ],
  },
  {
    label: '安全与连接',
    items: [
      { label: 'Skills 安全', path: '/skills', icon: BookOpenCheck },
      { label: '系统连接', path: '/pending/connections', icon: Boxes, pending: true },
    ],
  },
])

const routeLabels: Record<string, string> = {
  overview: '质量总览',
  targets: '被测目标',
  datasets: '评测数据集',
  runs: '评测运行',
  scenarios: '场景运行',
  'run-detail': '运行详情',
  comparison: '版本对比',
  gate: '发布门禁',
  usage: '用量与成本',
  trace: 'Trace 与回放',
  'gate-audits': '门禁审计',
  admin: '系统管理',
  skills: 'Skills 安全',
  pending: '增强能力',
}
const currentLabel = computed(() => routeLabels[String(route.name)] ?? 'Agent Quality Harness')

function activePath(path: string) {
  const [clean, query] = path.split('?')
  if (clean === '/') return route.path === '/'
  if (query) {
    const view = new URLSearchParams(query).get('view')
    return route.query.view === view || route.name === view
  }
  if (clean === '/runs') return route.path.startsWith('/runs') && !route.query.view
  return route.path.startsWith(clean)
}

async function switchOrganization(value: number) {
  await auth.switchOrganization(value)
  await router.replace('/')
  window.location.reload()
}

async function logout() {
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <div class="app-shell">
    <button class="mobile-nav-button icon-button" title="打开导航" @click="mobileOpen = true">
      <Menu :size="19" />
    </button>
    <div v-if="mobileOpen" class="mobile-scrim" @click="mobileOpen = false" />
    <aside class="sidebar" :class="{ 'sidebar--open': mobileOpen }">
      <div class="brand-row">
        <div class="brand-mark"><ShieldCheck :size="19" /></div>
        <div class="brand-copy">
          <div class="brand-name">Agent Quality Harness</div>
          <div class="brand-subtitle">Evaluation & Release Gates</div>
        </div>
        <button class="mobile-close icon-button" title="关闭导航" @click="mobileOpen = false">
          <X :size="18" />
        </button>
      </div>
      <nav class="sidebar-nav" aria-label="主导航">
        <section v-for="group in navGroups" :key="group.label" class="nav-group">
          <div class="nav-group-label">{{ group.label }}</div>
          <RouterLink
            v-for="item in group.items"
            :key="item.label"
            :to="item.path"
            class="nav-item"
            :class="{ 'nav-item--active': activePath(item.path) }"
            @click="mobileOpen = false"
          >
            <component :is="item.icon" :size="17" />
            <span>{{ item.label }}</span>
            <span v-if="'pending' in item && item.pending" class="pending-dot" title="Pending" />
          </RouterLink>
        </section>
      </nav>
      <ElDropdown trigger="click" placement="top-start">
        <button class="sidebar-user">
          <span class="user-avatar">{{ auth.user?.display_name.slice(0, 1) }}</span>
          <span class="sidebar-user-copy">
            <strong>{{ auth.user?.display_name }}</strong>
            <small>{{ auth.user?.username }}</small>
          </span>
          <ChevronRight :size="15" />
        </button>
        <template #dropdown>
          <ElDropdownMenu>
            <ElDropdownItem @click="router.push('/admin/sessions')">会话管理</ElDropdownItem>
            <ElDropdownItem divided @click="logout"><LogOut :size="14" /> 退出登录</ElDropdownItem>
          </ElDropdownMenu>
        </template>
      </ElDropdown>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <button class="topbar-home" @click="router.push('/')">Agent Quality Harness</button>
        <ChevronRight :size="15" />
        <strong>{{ currentLabel }}</strong>
        <div class="topbar-tools">
          <div class="organization-switcher">
            <Building2 :size="16" />
            <ElSelect
              :model-value="auth.organizationId"
              size="small"
              aria-label="当前组织"
              @change="switchOrganization"
            >
              <ElOption
                v-for="organization in auth.organizations"
                :key="organization.id"
                :label="organization.name"
                :value="organization.id"
              />
            </ElSelect>
            <ChevronDown :size="14" />
          </div>
          <span class="status-pulse" />
          <span class="api-label">API 实时数据</span>
        </div>
      </header>
      <main class="page-scroll">
        <RouterView :key="auth.organizationId ?? 0" />
      </main>
    </div>
  </div>
</template>
