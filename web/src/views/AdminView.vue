<script setup lang="ts">
import { Copy, KeyRound, Plus, RotateCcw, Trash2 } from '@lucide/vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '@/components/EmptyState.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api, apiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type {
  ApiKeyRecord,
  AuditLog,
  Member,
  Organization,
  Permission,
  Role,
  ServiceAccount,
  SystemSetting,
} from '@/types/api'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const section = computed(() => String(route.params.section ?? 'members'))
const loading = ref(false)
const members = ref<Member[]>([])
const roles = ref<Role[]>([])
const permissions = ref<Permission[]>([])
const accounts = ref<ServiceAccount[]>([])
const keys = ref<Record<number, ApiKeyRecord[]>>({})
const audits = ref<AuditLog[]>([])
const settings = ref<SystemSetting[]>([])
const sessions = ref<Array<Record<string, unknown>>>([])
const organizations = ref<Organization[]>([])
const dialog = ref('')
const createdKey = ref('')
const settingScope = ref<'organization' | 'platform'>('organization')

const memberForm = reactive({
  username: '',
  display_name: '',
  email: '',
  password: '',
  role_ids: [] as number[],
})
const roleForm = reactive({ name: '', description: '', permission_codes: [] as string[] })
const accountForm = reactive({ name: '', description: '' })
const organizationForm = reactive({ slug: '', name: '' })
const settingForm = reactive({ key: 'timezone', value: '{\n  "name": "Asia/Shanghai"\n}' })

const tabs = [
  { value: 'members', label: '组织与成员' },
  { value: 'roles', label: '角色与权限' },
  { value: 'service-accounts', label: 'Service Account / API Key' },
  { value: 'audit', label: '审计日志' },
  { value: 'sessions', label: '会话' },
  { value: 'settings', label: '系统设置' },
  { value: 'organizations', label: '组织管理' },
]

async function load() {
  loading.value = true
  try {
    if (section.value === 'members') [members.value, roles.value] = await Promise.all([api.members(), api.roles()])
    if (section.value === 'roles') [roles.value, permissions.value] = await Promise.all([api.roles(), api.permissions()])
    if (section.value === 'service-accounts') {
      accounts.value = await api.serviceAccounts()
      keys.value = Object.fromEntries(await Promise.all(accounts.value.map(async (account) => [account.id, await api.apiKeys(account.id)])))
    }
    if (section.value === 'audit') audits.value = await api.auditLogs()
    if (section.value === 'settings') {
      settings.value =
        settingScope.value === 'platform' ? await api.platformSettings() : await api.settings()
    }
    if (section.value === 'sessions') sessions.value = await api.adminSessions()
    if (section.value === 'organizations') organizations.value = await api.organizations()
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
}

async function createMember() {
  try {
    await api.createMember({ ...memberForm, email: memberForm.email || null })
    ElMessage.success('成员已创建')
    dialog.value = ''
    Object.assign(memberForm, { username: '', display_name: '', email: '', password: '', role_ids: [] })
    await load()
  } catch (error) { ElMessage.error(apiError(error)) }
}

async function toggleMember(row: Member) {
  try {
    await api.updateMember(row.membership_id, { active: !row.active })
    await load()
  } catch (error) { ElMessage.error(apiError(error)) }
}

async function createRole() {
  try {
    await api.createRole(roleForm)
    ElMessage.success('自定义角色已创建')
    dialog.value = ''
    Object.assign(roleForm, { name: '', description: '', permission_codes: [] })
    await load()
  } catch (error) { ElMessage.error(apiError(error)) }
}

async function createAccount() {
  try {
    await api.createServiceAccount(accountForm)
    ElMessage.success('Service Account 已创建')
    dialog.value = ''
    Object.assign(accountForm, { name: '', description: '' })
    await load()
  } catch (error) { ElMessage.error(apiError(error)) }
}

async function createKey(account: ServiceAccount) {
  const name = await ElMessageBox.prompt('输入 Key 名称；明文只显示一次', '创建 API Key', { inputValue: 'quality-gate' })
  try {
    const key = await api.createApiKey(account.id, { name: name.value })
    createdKey.value = key.api_key ?? ''
    dialog.value = 'created-key'
    await load()
  } catch (error) { ElMessage.error(apiError(error)) }
}

async function revokeKey(key: ApiKeyRecord) {
  await ElMessageBox.confirm(`撤销 ${key.prefix} 后无法恢复，继续？`, '撤销 API Key', { type: 'warning' })
  try {
    await api.revokeApiKey(key.id)
    await load()
  } catch (error) { ElMessage.error(apiError(error)) }
}

async function saveSetting() {
  try {
    const value = JSON.parse(settingForm.value) as Record<string, unknown>
    if (settingScope.value === 'platform') await api.putPlatformSetting(settingForm.key, value)
    else await api.putSetting(settingForm.key, value)
    ElMessage.success('设置已保存')
    dialog.value = ''
    await load()
  } catch (error) { ElMessage.error(apiError(error)) }
}

async function createOrganization() {
  try {
    await api.createOrganization(organizationForm)
    ElMessage.success('组织已创建并播种系统角色')
    dialog.value = ''
    Object.assign(organizationForm, { slug: '', name: '' })
    await load()
  } catch (error) { ElMessage.error(apiError(error)) }
}

async function revokeSession(id: number) {
  try {
    await api.revokeAdminSession(id)
    await load()
  } catch (error) { ElMessage.error(apiError(error)) }
}

async function copyKey() {
  await navigator.clipboard.writeText(createdKey.value)
  ElMessage.success('API Key 已复制')
}

watch(section, load)
onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div><h1 class="page-title">系统管理</h1><p class="page-subtitle">当前组织的成员、权限、凭据、会话和安全设置</p></div>
      <ElButton :loading="loading" @click="load"><RotateCcw :size="15" /> 刷新</ElButton>
    </div>
    <ElSegmented class="admin-tabs" :model-value="section" :options="tabs" @change="(value: string | number | boolean) => router.push(`/admin/${String(value)}`)" />

    <section v-if="section === 'members'" class="panel">
      <div class="panel-header"><h2 class="panel-title">组织成员</h2><ElButton type="primary" @click="dialog = 'member'"><Plus :size="15" /> 创建用户</ElButton></div>
      <ElTable :data="members" v-loading="loading">
        <ElTableColumn prop="display_name" label="用户" min-width="180"><template #default="{ row }"><strong>{{ row.display_name }}</strong><div class="muted">{{ row.username }}</div></template></ElTableColumn>
        <ElTableColumn prop="email" label="邮箱" min-width="210"><template #default="{ row }">{{ row.email ?? '—' }}</template></ElTableColumn>
        <ElTableColumn label="角色" min-width="240"><template #default="{ row }"><ElTag v-for="name in row.role_names" :key="name" size="small">{{ name }}</ElTag></template></ElTableColumn>
        <ElTableColumn label="状态" width="100"><template #default="{ row }"><StatusTag :value="row.active ? 'active' : 'disabled'" /></template></ElTableColumn>
        <ElTableColumn label="操作" width="110"><template #default="{ row }"><ElButton link @click="toggleMember(row)">{{ row.active ? '停用' : '启用' }}</ElButton></template></ElTableColumn>
      </ElTable>
    </section>

    <section v-else-if="section === 'roles'" class="panel">
      <div class="panel-header"><h2 class="panel-title">角色与权限</h2><ElButton type="primary" @click="dialog = 'role'"><Plus :size="15" /> 自定义角色</ElButton></div>
      <ElTable :data="roles" v-loading="loading">
        <ElTableColumn prop="name" label="角色" min-width="180"><template #default="{ row }"><strong>{{ row.name }}</strong><ElTag v-if="row.system" size="small" type="info">系统</ElTag></template></ElTableColumn>
        <ElTableColumn prop="description" label="说明" min-width="220" />
        <ElTableColumn label="权限" min-width="420"><template #default="{ row }"><span class="permission-list">{{ row.permission_codes.join(' · ') }}</span></template></ElTableColumn>
      </ElTable>
    </section>

    <section v-else-if="section === 'service-accounts'" class="section-stack">
      <div class="panel">
        <div class="panel-header"><h2 class="panel-title">Service Account / API Key</h2><ElButton type="primary" @click="dialog = 'account'"><Plus :size="15" /> 新建账号</ElButton></div>
        <EmptyState v-if="!accounts.length" title="暂无 Service Account" description="为 Gate CLI 和 CI 创建组织级机器身份。" />
        <div v-for="account in accounts" :key="account.id" class="account-block">
          <div class="account-heading"><div><strong>{{ account.name }}</strong><span>{{ account.description }}</span></div><ElButton @click="createKey(account)"><KeyRound :size="14" /> 创建 Key</ElButton></div>
          <ElTable :data="keys[account.id] ?? []">
            <ElTableColumn prop="name" label="Key" min-width="160" />
            <ElTableColumn prop="prefix" label="前缀" min-width="150" />
            <ElTableColumn label="最后使用" min-width="180"><template #default="{ row }">{{ row.last_used_at ? new Date(row.last_used_at).toLocaleString('zh-CN') : '从未使用' }}</template></ElTableColumn>
            <ElTableColumn label="状态" width="100"><template #default="{ row }"><StatusTag :value="row.revoked_at ? 'revoked' : 'active'" /></template></ElTableColumn>
            <ElTableColumn label="操作" width="90"><template #default="{ row }"><ElButton link type="danger" :disabled="!!row.revoked_at" @click="revokeKey(row)"><Trash2 :size="14" /></ElButton></template></ElTableColumn>
          </ElTable>
        </div>
      </div>
    </section>

    <section v-else-if="section === 'audit'" class="panel">
      <div class="panel-header"><h2 class="panel-title">审计日志</h2></div>
      <ElTable :data="audits" v-loading="loading">
        <ElTableColumn prop="action" label="动作" min-width="220" />
        <ElTableColumn prop="actor_type" label="主体" width="140" />
        <ElTableColumn label="资源" min-width="180"><template #default="{ row }">{{ row.resource_type ?? '—' }} {{ row.resource_id ?? '' }}</template></ElTableColumn>
        <ElTableColumn label="结果" width="110"><template #default="{ row }"><StatusTag :value="row.outcome" /></template></ElTableColumn>
        <ElTableColumn label="时间" min-width="190"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template></ElTableColumn>
      </ElTable>
    </section>

    <section v-else-if="section === 'sessions'" class="panel">
      <div class="panel-header"><h2 class="panel-title">当前用户会话</h2></div>
      <ElTable :data="sessions" v-loading="loading">
        <ElTableColumn prop="id" label="Session" width="100" />
        <ElTableColumn prop="display_name" label="用户" min-width="160" />
        <ElTableColumn prop="ip_address" label="IP" min-width="150" />
        <ElTableColumn prop="user_agent" label="User Agent" min-width="300" show-overflow-tooltip />
        <ElTableColumn label="过期时间" min-width="190"><template #default="{ row }">{{ new Date(String(row.expires_at)).toLocaleString('zh-CN') }}</template></ElTableColumn>
        <ElTableColumn label="状态" width="100"><template #default="{ row }"><StatusTag :value="row.revoked_at ? 'revoked' : 'active'" /></template></ElTableColumn>
        <ElTableColumn label="操作" width="90"><template #default="{ row }"><ElButton link type="danger" :disabled="!!row.revoked_at" @click="revokeSession(Number(row.id))">撤销</ElButton></template></ElTableColumn>
      </ElTable>
    </section>

    <section v-else-if="section === 'settings'" class="panel">
      <div class="panel-header"><div class="toolbar"><h2 class="panel-title">系统设置</h2><ElSegmented v-if="auth.user?.platform_admin" v-model="settingScope" :options="[{ label: '组织级', value: 'organization' }, { label: '平台级', value: 'platform' }]" @change="load" /></div><ElButton type="primary" @click="dialog = 'setting'"><Plus :size="15" /> 设置键</ElButton></div>
      <ElTable :data="settings" v-loading="loading">
        <ElTableColumn prop="key" label="键" min-width="260" />
        <ElTableColumn label="值" min-width="420"><template #default="{ row }"><span class="mono">{{ JSON.stringify(row.value) }}</span></template></ElTableColumn>
        <ElTableColumn label="更新时间" min-width="190"><template #default="{ row }">{{ new Date(row.updated_at).toLocaleString('zh-CN') }}</template></ElTableColumn>
      </ElTable>
    </section>

    <section v-else-if="section === 'organizations'" class="panel">
      <div class="panel-header"><h2 class="panel-title">组织管理</h2><ElButton v-if="auth.user?.platform_admin" type="primary" @click="dialog = 'organization'"><Plus :size="15" /> 创建组织</ElButton></div>
      <ElTable :data="organizations" v-loading="loading">
        <ElTableColumn prop="name" label="组织" min-width="220" />
        <ElTableColumn prop="slug" label="Slug" min-width="180" />
        <ElTableColumn label="状态" width="120"><template #default="{ row }"><StatusTag :value="row.active ? 'active' : 'disabled'" /></template></ElTableColumn>
      </ElTable>
    </section>

    <ElDialog v-model="dialog" :show-close="dialog !== 'created-key'" :close-on-click-modal="dialog !== 'created-key'" width="560px">
      <template #header><strong>{{ dialog === 'member' ? '创建组织成员' : dialog === 'role' ? '创建自定义角色' : dialog === 'account' ? '创建 Service Account' : dialog === 'setting' ? '更新设置' : dialog === 'organization' ? '创建组织' : 'API Key 仅显示一次' }}</strong></template>
      <ElForm v-if="dialog === 'member'" label-position="top">
        <div class="form-grid"><ElFormItem label="用户名"><ElInput v-model="memberForm.username" /></ElFormItem><ElFormItem label="显示名"><ElInput v-model="memberForm.display_name" /></ElFormItem></div>
        <ElFormItem label="邮箱"><ElInput v-model="memberForm.email" /></ElFormItem>
        <ElFormItem label="初始密码"><ElInput v-model="memberForm.password" type="password" show-password /></ElFormItem>
        <ElFormItem label="角色"><ElSelect v-model="memberForm.role_ids" multiple><ElOption v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" /></ElSelect></ElFormItem>
      </ElForm>
      <ElForm v-else-if="dialog === 'role'" label-position="top">
        <ElFormItem label="角色名称"><ElInput v-model="roleForm.name" /></ElFormItem>
        <ElFormItem label="说明"><ElInput v-model="roleForm.description" /></ElFormItem>
        <ElFormItem label="权限"><ElSelect v-model="roleForm.permission_codes" multiple filterable><ElOption v-for="permission in permissions" :key="permission.code" :label="`${permission.code} · ${permission.name}`" :value="permission.code" /></ElSelect></ElFormItem>
      </ElForm>
      <ElForm v-else-if="dialog === 'account'" label-position="top"><ElFormItem label="名称"><ElInput v-model="accountForm.name" /></ElFormItem><ElFormItem label="说明"><ElInput v-model="accountForm.description" /></ElFormItem></ElForm>
      <ElForm v-else-if="dialog === 'setting'" label-position="top"><ElFormItem label="允许的设置键"><ElSelect v-model="settingForm.key"><template v-if="settingScope === 'organization'"><ElOption label="时区" value="timezone" /><ElOption label="数据保留期" value="retention.days" /><ElOption label="默认 GatePolicy" value="evaluation.default_gate_policy_id" /><ElOption label="默认 PricingSnapshot" value="evaluation.default_pricing_snapshot_id" /><ElOption label="会话限制" value="security.session_limit" /></template><template v-else><ElOption label="默认时区" value="timezone.default" /><ElOption label="默认数据保留期" value="retention.default_days" /><ElOption label="Access Token 分钟" value="security.access_token_minutes" /><ElOption label="Refresh Session 天数" value="security.refresh_session_days" /></template></ElSelect></ElFormItem><ElFormItem label="JSON 值"><ElInput v-model="settingForm.value" type="textarea" :rows="7" /></ElFormItem></ElForm>
      <ElForm v-else-if="dialog === 'organization'" label-position="top"><ElFormItem label="名称"><ElInput v-model="organizationForm.name" /></ElFormItem><ElFormItem label="Slug"><ElInput v-model="organizationForm.slug" placeholder="quality-team" /></ElFormItem></ElForm>
      <div v-else-if="dialog === 'created-key'" class="key-once"><p>关闭后无法再次查看完整密钥。</p><pre class="json-block">{{ createdKey }}</pre><ElButton @click="copyKey"><Copy :size="15" /> 复制</ElButton></div>
      <template #footer>
        <ElButton v-if="dialog !== 'created-key'" @click="dialog = ''">取消</ElButton>
        <ElButton v-if="dialog === 'member'" type="primary" @click="createMember">创建用户</ElButton>
        <ElButton v-else-if="dialog === 'role'" type="primary" @click="createRole">创建角色</ElButton>
        <ElButton v-else-if="dialog === 'account'" type="primary" @click="createAccount">创建账号</ElButton>
        <ElButton v-else-if="dialog === 'setting'" type="primary" @click="saveSetting">保存</ElButton>
        <ElButton v-else-if="dialog === 'organization'" type="primary" @click="createOrganization">创建组织</ElButton>
        <ElButton v-else-if="dialog === 'created-key'" type="primary" @click="dialog = ''; createdKey = ''">我已保存</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.permission-list { color: #475467; font-size: 12px; line-height: 20px; }
.account-block + .account-block { border-top: 1px solid var(--border); }
.account-heading { min-height: 66px; padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.account-heading > div { display: grid; gap: 3px; }
.account-heading span { color: var(--muted); font-size: 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.key-once { display: grid; gap: 12px; }
.key-once p { margin: 0; color: var(--danger); font-size: 13px; }
:deep(.el-tag + .el-tag) { margin-left: 6px; }
@media (max-width: 620px) { .form-grid { grid-template-columns: 1fr; } }
</style>
