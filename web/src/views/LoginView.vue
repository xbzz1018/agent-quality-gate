<script setup lang="ts">
import { ShieldCheck } from '@lucide/vue'
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { apiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function submit() {
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    await router.replace(String(route.query.redirect ?? '/'))
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="login-brand">
        <div class="brand-mark brand-mark--large"><ShieldCheck :size="22" /></div>
        <div>
          <strong>Agent Quality Harness</strong>
          <span>智能体评测、可观测与发布门禁</span>
        </div>
      </div>
      <div class="login-heading">
        <h1>登录控制台</h1>
        <p>使用管理员创建的本地账号继续</p>
      </div>
      <ElForm label-position="top" @submit.prevent="submit">
        <ElFormItem label="用户名">
          <ElInput v-model="form.username" size="large" autocomplete="username" autofocus />
        </ElFormItem>
        <ElFormItem label="密码">
          <ElInput
            v-model="form.password"
            type="password"
            size="large"
            autocomplete="current-password"
            show-password
            @keyup.enter="submit"
          />
        </ElFormItem>
        <ElButton
          class="login-submit"
          type="primary"
          size="large"
          :loading="loading"
          :disabled="!form.username || !form.password"
          @click="submit"
        >
          登录
        </ElButton>
      </ElForm>
      <div class="login-foot">管理员账号由 <span class="mono">aqh admin bootstrap</span> 创建</div>
    </section>
  </main>
</template>
