import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, setAccessToken, setOrganization } from '@/services/api'
import type { AuthUser, Organization } from '@/types/api'

const ORGANIZATION_KEY = 'aqh.organization-id'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const organizations = ref<Organization[]>([])
  const organizationId = ref<number | null>(null)
  const initialized = ref(false)
  const authenticated = computed(() => user.value !== null)
  const currentOrganization = computed(
    () => organizations.value.find((item) => item.id === organizationId.value) ?? null,
  )
  const can = (permission: string) =>
    user.value?.platform_admin === true || user.value?.permissions.includes(permission) === true

  async function applyLogin(result: Awaited<ReturnType<typeof api.login>>) {
    setAccessToken(result.access_token)
    organizations.value = result.organizations
    const saved = Number(localStorage.getItem(ORGANIZATION_KEY))
    const selected = result.organizations.some((item) => item.id === saved)
      ? saved
      : (result.organizations[0]?.id ?? null)
    organizationId.value = selected
    setOrganization(selected)
    user.value = await api.me()
  }

  async function login(username: string, password: string) {
    await applyLogin(await api.login(username, password))
  }

  async function initialize() {
    if (initialized.value) return
    try {
      await applyLogin(await api.refresh())
    } catch {
      clear()
    } finally {
      initialized.value = true
    }
  }

  async function switchOrganization(id: number) {
    organizationId.value = id
    localStorage.setItem(ORGANIZATION_KEY, String(id))
    setOrganization(id)
    user.value = await api.me()
  }

  async function logout() {
    try {
      await api.logout()
    } finally {
      clear()
    }
  }

  function clear() {
    user.value = null
    organizations.value = []
    organizationId.value = null
    setAccessToken(null)
    setOrganization(null)
  }

  return {
    user,
    organizations,
    organizationId,
    initialized,
    authenticated,
    currentOrganization,
    can,
    login,
    initialize,
    switchOrganization,
    logout,
    clear,
  }
})
