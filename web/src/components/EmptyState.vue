<script setup lang="ts">
import { Inbox } from '@lucide/vue'

defineProps<{ title: string; description?: string }>()
</script>

<template>
  <div class="empty-state">
    <Inbox :size="28" aria-hidden="true" />
    <strong>{{ title }}</strong>
    <span v-if="description">{{ description }}</span>
    <slot />
  </div>
</template>
