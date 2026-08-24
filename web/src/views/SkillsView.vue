<script setup lang="ts">
import { Link2, Plus, RefreshCw, ScanSearch, ShieldCheck } from '@lucide/vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import EmptyState from '@/components/EmptyState.vue'
import StatusTag from '@/components/StatusTag.vue'
import { api, apiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type {
  GatePolicy,
  PolicyBundle,
  SkillPackage,
  SkillScan,
  SkillVersion,
} from '@/types/api'
import { formatDate, pretty } from '@/utils/format'

const auth = useAuthStore()
const tab = ref('catalog')
const loading = ref(false)
const packages = ref<SkillPackage[]>([])
const versions = ref<SkillVersion[]>([])
const scans = ref<SkillScan[]>([])
const policies = ref<PolicyBundle[]>([])
const gatePolicies = ref<GatePolicy[]>([])
const selectedPackageId = ref<number | null>(null)
const selectedVersionId = ref<number | null>(null)
const importVisible = ref(false)
const policyVisible = ref(false)
const gatePolicyVisible = ref(false)
const runId = ref<number | null>(null)
const regression = ref<Record<string, unknown> | null>(null)
const attachAgentVersionId = ref<number | null>(null)

const importForm = reactive({
  name: '',
  version: '1.0.0',
  description: '',
  source_ref: '',
  path: 'SKILL.md',
  content: '',
})
const policyForm = reactive({
  name: '',
  version: '1',
  package_path: '',
  entrypoint: 'decision',
  rego: '',
})
const gatePolicyForm = reactive({
  name: '',
  version: '1',
  policy_bundle_id: null as number | null,
})

const selectedVersion = computed(() =>
  versions.value.find((item) => item.id === selectedVersionId.value),
)

async function loadCatalog() {
  loading.value = true
  try {
    const [skillsPage, policyPage, gatePolicyRows] = await Promise.all([
      api.skills(),
      api.policyBundles(),
      api.policies(),
    ])
    packages.value = skillsPage.items
    policies.value = policyPage.items
    gatePolicies.value = gatePolicyRows
    if (!selectedPackageId.value && packages.value.length) {
      await selectPackage(packages.value[0].id)
    }
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
}

async function selectPackage(id: number) {
  selectedPackageId.value = id
  try {
    versions.value = await api.skillVersions(id)
    selectedVersionId.value = versions.value[0]?.id ?? null
    await loadScans()
  } catch (error) {
    ElMessage.error(apiError(error))
  }
}

async function loadScans() {
  scans.value = selectedVersionId.value ? await api.skillScans(selectedVersionId.value) : []
}

async function importPackage() {
  try {
    const result = await api.importSkill({
      name: importForm.name,
      version: importForm.version,
      description: importForm.description,
      source_ref: importForm.source_ref || null,
      manifest: { permissions: {} },
      files: [{ path: importForm.path, content: importForm.content }],
    })
    importVisible.value = false
    ElMessage.success('Skill 版本已冻结')
    await loadCatalog()
    await selectPackage(result.package.id)
  } catch (error) {
    ElMessage.error(apiError(error))
  }
}

async function scanSelected() {
  if (!selectedVersionId.value) return
  try {
    const result = await api.scanSkill(selectedVersionId.value)
    ElMessage.success(`扫描完成：${result.status.toUpperCase()}`)
    await loadScans()
  } catch (error) {
    ElMessage.error(apiError(error))
  }
}

async function attachSelected() {
  if (!selectedVersionId.value || !attachAgentVersionId.value) return
  try {
    await api.attachSkill(attachAgentVersionId.value, selectedVersionId.value)
    ElMessage.success('Skill 已绑定到 Agent Version')
  } catch (error) {
    ElMessage.error(apiError(error))
  }
}

async function loadRegression() {
  if (!runId.value) return
  try {
    regression.value = await api.skillRegression(runId.value)
  } catch (error) {
    regression.value = null
    ElMessage.error(apiError(error))
  }
}

function openPolicyDialog() {
  const organizationId = auth.organizationId ?? 0
  policyForm.package_path = `aqh.org_${organizationId}.release.v_1`
  policyForm.rego = [
    `package ${policyForm.package_path}`,
    '',
    'decision := {"decision": "ship", "reasons": []}',
  ].join('\n')
  policyVisible.value = true
}

async function createPolicy() {
  try {
    const result = await api.createPolicyBundle({
      ...policyForm,
      data: {},
    })
    policyVisible.value = false
    await loadCatalog()
    if (result.status === 'validated') ElMessage.success('Rego 已由 OPA 验证')
    else ElMessage.warning('Policy 已保存，但验证失败')
  } catch (error) {
    ElMessage.error(apiError(error))
  }
}

async function createGatePolicy() {
  if (!gatePolicyForm.policy_bundle_id) return
  try {
    await api.createGatePolicy({
      name: gatePolicyForm.name,
      version: gatePolicyForm.version,
      policy_bundle_id: gatePolicyForm.policy_bundle_id,
      thresholds: {},
      active: true,
    })
    gatePolicyVisible.value = false
    ElMessage.success('GatePolicy 已绑定 validated Bundle')
    await loadCatalog()
  } catch (error) {
    ElMessage.error(apiError(error))
  }
}

function bundleFor(policy: GatePolicy) {
  return policies.value.find((item) => item.id === policy.policy_bundle_id)
}

onMounted(loadCatalog)
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-header">
      <div>
        <h1 class="page-title">Skills 安全</h1>
        <p class="page-subtitle">不可变版本、确定性扫描、跨版本回归与 Rego 发布策略</p>
      </div>
      <div class="page-actions">
        <ElButton @click="loadCatalog"><RefreshCw :size="15" />刷新</ElButton>
        <ElButton @click="openPolicyDialog"><ShieldCheck :size="15" />新建 Policy</ElButton>
        <ElButton type="primary" @click="importVisible = true"><Plus :size="15" />导入 Skill</ElButton>
      </div>
    </div>

    <ElTabs v-model="tab" class="security-tabs">
      <ElTabPane label="Skill 清单" name="catalog">
        <div class="skills-layout">
          <section class="panel package-list">
            <div class="panel-header"><h2 class="panel-title">Packages</h2><span class="muted">{{ packages.length }}</span></div>
            <button
              v-for="item in packages"
              :key="item.id"
              class="package-row"
              :class="{ 'package-row--active': selectedPackageId === item.id }"
              @click="selectPackage(item.id)"
            >
              <strong>{{ item.name }}</strong><span>{{ item.description || '无描述' }}</span>
            </button>
            <EmptyState v-if="!packages.length" title="尚未导入 Skill" description="导入结构化文本文件后，平台会冻结版本与 SHA-256。" />
          </section>
          <section class="panel">
            <div class="panel-header"><h2 class="panel-title">不可变版本</h2><ElButton size="small" :disabled="!selectedVersionId" @click="scanSelected"><ScanSearch :size="14" />执行扫描</ElButton></div>
            <ElTable :data="versions" @current-change="(row: SkillVersion) => { selectedVersionId = row?.id; loadScans() }">
              <ElTableColumn prop="version" label="版本" width="110" />
              <ElTableColumn label="SHA-256" min-width="250"><template #default="{ row }"><span class="mono hash">{{ row.sha256 }}</span></template></ElTableColumn>
              <ElTableColumn label="冻结时间" width="170"><template #default="{ row }">{{ formatDate(row.frozen_at) }}</template></ElTableColumn>
            </ElTable>
            <div v-if="selectedVersion" class="attach-bar">
              <span>绑定到 Agent Version</span>
              <ElInputNumber v-model="attachAgentVersionId" :min="1" controls-position="right" placeholder="Version ID" />
              <ElButton @click="attachSelected"><Link2 :size="14" />绑定</ElButton>
            </div>
          </section>
        </div>
      </ElTabPane>

      <ElTabPane label="扫描发现" name="scans">
        <section class="panel">
          <div class="panel-header"><h2 class="panel-title">扫描历史与发现</h2><span class="mono">{{ selectedVersion?.sha256 ?? '选择一个 Skill 版本' }}</span></div>
          <ElTable :data="scans.flatMap((scan) => scan.findings.map((finding) => ({ ...finding, scan })))">
            <ElTableColumn label="状态" width="90"><template #default="{ row }"><StatusTag :value="row.severity" /></template></ElTableColumn>
            <ElTableColumn prop="rule_id" label="规则" min-width="210"><template #default="{ row }"><span class="mono">{{ row.rule_id }}</span></template></ElTableColumn>
            <ElTableColumn label="位置" min-width="170"><template #default="{ row }">{{ row.path }}:{{ row.line }}</template></ElTableColumn>
            <ElTableColumn prop="message" label="说明" min-width="280" />
            <ElTableColumn label="扫描器" width="150"><template #default="{ row }">{{ row.scan.scanner_version }}</template></ElTableColumn>
          </ElTable>
          <EmptyState v-if="!scans.length" title="尚无扫描结果" description="选择 Skill 版本并执行确定性安全扫描。" />
        </section>
      </ElTabPane>

      <ElTabPane label="版本回归" name="regression">
        <section class="panel regression-panel">
          <div class="panel-header"><h2 class="panel-title">Baseline / Candidate Skill 回归</h2></div>
          <div class="regression-query"><ElInputNumber v-model="runId" :min="1" controls-position="right" /><ElButton type="primary" @click="loadRegression">查询 Run</ElButton></div>
          <pre v-if="regression" class="json-block regression-json">{{ pretty(regression) }}</pre>
          <EmptyState v-else title="输入 EvalRun ID" description="平台只比较该运行清单中冻结的 Baseline 与 Candidate Skill 扫描摘要。" />
        </section>
      </ElTabPane>

      <ElTabPane label="Rego Policy" name="policy">
        <section class="panel">
          <div class="panel-header"><h2 class="panel-title">Policy Bundles</h2><ElButton size="small" @click="gatePolicyVisible = true">绑定 GatePolicy</ElButton></div>
          <ElTable :data="policies">
            <ElTableColumn prop="name" label="名称" min-width="170" />
            <ElTableColumn prop="version" label="版本" width="90" />
            <ElTableColumn label="状态" width="110"><template #default="{ row }"><StatusTag :value="row.status === 'validated' ? 'pass' : 'block'" /></template></ElTableColumn>
            <ElTableColumn prop="package_path" label="Package" min-width="240"><template #default="{ row }"><span class="mono">{{ row.package_path }}</span></template></ElTableColumn>
            <ElTableColumn label="SHA-256" min-width="230"><template #default="{ row }"><span class="mono hash">{{ row.sha256 }}</span></template></ElTableColumn>
          </ElTable>
          <EmptyState v-if="!policies.length" title="尚无 Policy Bundle" description="创建 Rego 后由 OPA 编译验证，只有 validated 版本可绑定 GatePolicy。" />
        </section>
        <section class="panel gate-policy-list">
          <div class="panel-header"><h2 class="panel-title">Gate Policies</h2><span class="muted">执行绑定</span></div>
          <ElTable :data="gatePolicies">
            <ElTableColumn prop="name" label="名称" min-width="170" />
            <ElTableColumn prop="version" label="版本" width="90" />
            <ElTableColumn label="Bundle" min-width="190"><template #default="{ row }">{{ bundleFor(row)?.name ?? 'Built-in only' }}</template></ElTableColumn>
            <ElTableColumn label="Bundle SHA" min-width="230"><template #default="{ row }"><span class="mono hash">{{ bundleFor(row)?.sha256 ?? '—' }}</span></template></ElTableColumn>
            <ElTableColumn label="状态" width="90"><template #default="{ row }"><StatusTag :value="row.active ? 'pass' : 'inactive'" /></template></ElTableColumn>
          </ElTable>
        </section>
      </ElTabPane>
    </ElTabs>

    <ElDialog v-model="importVisible" title="导入 Skill 版本" width="min(620px, 94vw)">
      <ElForm label-position="top">
        <div class="form-grid"><ElFormItem label="Package 名称"><ElInput v-model="importForm.name" /></ElFormItem><ElFormItem label="版本"><ElInput v-model="importForm.version" /></ElFormItem></div>
        <ElFormItem label="描述"><ElInput v-model="importForm.description" /></ElFormItem>
        <ElFormItem label="来源（非敏感引用）"><ElInput v-model="importForm.source_ref" /></ElFormItem>
        <ElFormItem label="文件路径"><ElInput v-model="importForm.path" /></ElFormItem>
        <ElFormItem label="UTF-8 文本内容"><ElInput v-model="importForm.content" type="textarea" :rows="9" /></ElFormItem>
      </ElForm>
      <template #footer><ElButton @click="importVisible = false">取消</ElButton><ElButton type="primary" @click="importPackage">冻结版本</ElButton></template>
    </ElDialog>

    <ElDialog v-model="policyVisible" title="新建 Rego Policy Bundle" width="min(760px, 94vw)">
      <ElForm label-position="top">
        <div class="form-grid"><ElFormItem label="名称"><ElInput v-model="policyForm.name" /></ElFormItem><ElFormItem label="版本"><ElInput v-model="policyForm.version" /></ElFormItem></div>
        <div class="form-grid"><ElFormItem label="Package"><ElInput v-model="policyForm.package_path" /></ElFormItem><ElFormItem label="Entrypoint"><ElInput v-model="policyForm.entrypoint" /></ElFormItem></div>
        <ElFormItem label="Rego"><ElInput v-model="policyForm.rego" type="textarea" :rows="13" class="code-input" /></ElFormItem>
      </ElForm>
      <template #footer><ElButton @click="policyVisible = false">取消</ElButton><ElButton type="primary" @click="createPolicy">提交并验证</ElButton></template>
    </ElDialog>

    <ElDialog v-model="gatePolicyVisible" title="绑定 GatePolicy" width="min(560px, 94vw)">
      <ElForm label-position="top">
        <div class="form-grid"><ElFormItem label="名称"><ElInput v-model="gatePolicyForm.name" /></ElFormItem><ElFormItem label="版本"><ElInput v-model="gatePolicyForm.version" /></ElFormItem></div>
        <ElFormItem label="Validated Policy Bundle"><ElSelect v-model="gatePolicyForm.policy_bundle_id" style="width: 100%"><ElOption v-for="bundle in policies.filter((item) => item.status === 'validated')" :key="bundle.id" :label="`${bundle.name} · ${bundle.version} · ${bundle.sha256.slice(0, 12)}`" :value="bundle.id" /></ElSelect></ElFormItem>
      </ElForm>
      <template #footer><ElButton @click="gatePolicyVisible = false">取消</ElButton><ElButton type="primary" :disabled="!gatePolicyForm.name || !gatePolicyForm.policy_bundle_id" @click="createGatePolicy">创建并绑定</ElButton></template>
    </ElDialog>
  </div>
</template>

<style scoped>
.security-tabs { --el-tabs-header-height: 42px; }
.skills-layout { display: grid; grid-template-columns: minmax(240px, .34fr) minmax(560px, 1fr); gap: 14px; }
.package-list { overflow: hidden; }
.package-row { width: 100%; min-height: 62px; display: grid; gap: 3px; padding: 11px 16px; border: 0; border-bottom: 1px solid var(--border); background: white; color: var(--text); text-align: left; cursor: pointer; }
.package-row:hover, .package-row--active { background: var(--accent-soft); }
.package-row--active { box-shadow: inset 3px 0 var(--accent); }
.package-row strong { font-size: 13px; }
.package-row span { overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.hash { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attach-bar, .regression-query { display: flex; align-items: center; gap: 9px; padding: 12px 16px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; }
.attach-bar .el-input-number { width: 160px; margin-left: auto; }
.regression-panel { min-height: 430px; }
.regression-query { border-top: 0; border-bottom: 1px solid var(--border); }
.regression-json { margin: 16px; max-height: 480px; }
.gate-policy-list { margin-top: 14px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.code-input :deep(textarea) { font-family: "Cascadia Code", Consolas, monospace; font-size: 12px; }
@media (max-width: 950px) { .skills-layout { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .form-grid { grid-template-columns: 1fr; gap: 0; } .attach-bar { align-items: stretch; flex-direction: column; } .attach-bar .el-input-number { width: 100%; margin-left: 0; } }
</style>
