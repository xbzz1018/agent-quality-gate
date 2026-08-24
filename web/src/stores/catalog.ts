import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '@/services/api'
import type { AgentVersion, Dataset, GatePolicy, PricingSnapshot, Target } from '@/types/api'

export const useCatalogStore = defineStore('catalog', () => {
  const targets = ref<Target[]>([])
  const datasets = ref<Dataset[]>([])
  const policies = ref<GatePolicy[]>([])
  const pricing = ref<PricingSnapshot[]>([])
  const versionsByTarget = ref<Record<number, AgentVersion[]>>({})
  const loading = ref(false)

  const versions = computed(() => Object.values(versionsByTarget.value).flat())

  async function refresh() {
    loading.value = true
    try {
      const [targetRows, datasetRows, policyRows, pricingRows] = await Promise.all([
        api.targets(),
        api.datasets(),
        api.policies(),
        api.pricing(),
      ])
      targets.value = targetRows.items
      datasets.value = datasetRows.items
      policies.value = policyRows
      pricing.value = pricingRows
      const entries = await Promise.all(
        targetRows.items.map(async (target) => [target.id, await api.versions(target.id)] as const),
      )
      versionsByTarget.value = Object.fromEntries(entries)
    } finally {
      loading.value = false
    }
  }

  return { targets, datasets, policies, pricing, versionsByTarget, versions, loading, refresh }
})
