import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

import { chromium } from 'playwright'

const baseUrl = process.env.AQH_WEB_URL ?? 'http://127.0.0.1:5173'
const username = process.env.AQH_QA_USERNAME
const password = process.env.AQH_QA_PASSWORD
const displayName = process.env.AQH_QA_DISPLAY_NAME ?? username
const runId = Number(process.env.AQH_QA_RUN_ID)
const characterizationRunId = Number(process.env.AQH_QA_CHARACTERIZATION_RUN_ID)
const agUiRunId = Number(process.env.AQH_QA_AG_UI_RUN_ID)
const multiSkillRunId = Number(process.env.AQH_QA_MULTI_SKILL_RUN_ID)
const switchOrganization = process.env.AQH_QA_SWITCH_ORGANIZATION
if (!username || !password || !runId) {
  throw new Error('AQH_QA_USERNAME, AQH_QA_PASSWORD and AQH_QA_RUN_ID are required')
}

const outputDir = resolve(process.cwd(), '../.tmp/visual-qa-auth')
await mkdir(outputDir, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const errors = []

async function openPage(viewport) {
  const context = await browser.newContext({ viewport, locale: 'zh-CN' })
  const page = await context.newPage()
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() === 'error') {
      const location = message.location()
      errors.push(`console: ${message.text()} @ ${location.url || 'unknown'}`)
    }
  })
  return { context, page }
}

async function login(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle' })
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.getByRole('heading', { name: '质量总览' }).waitFor()
}

async function assertNoHorizontalOverflow(page, label) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }))
  if (dimensions.content > dimensions.viewport + 1) {
    throw new Error(`${label} horizontal overflow: ${dimensions.content} > ${dimensions.viewport}`)
  }
}

try {
  const desktop = await openPage({ width: 1440, height: 1000 })
  await login(desktop.page)
  await desktop.page.locator('.chart-frame canvas').waitFor()
  await assertNoHorizontalOverflow(desktop.page, 'overview desktop')
  await desktop.page.screenshot({ path: resolve(outputDir, 'overview-desktop.png'), fullPage: true })

  if (switchOrganization) {
    await desktop.page.locator('.organization-switcher .el-select__wrapper').click()
    await desktop.page.getByRole('option', { name: switchOrganization }).click()
    await desktop.page.waitForTimeout(1200)
    await desktop.page.getByRole('heading', { name: '质量总览' }).waitFor()
    await desktop.page.locator('.organization-switcher .el-select__wrapper').click()
    await desktop.page.getByRole('option', { name: 'Default Organization' }).click()
    await desktop.page.waitForTimeout(1200)
    await desktop.page.getByRole('heading', { name: '质量总览' }).waitFor()
  }

  await desktop.page.goto(`${baseUrl}/runs/${runId}`, { waitUntil: 'networkidle' })
  await desktop.page.getByRole('heading', { name: `评测运行 #${runId}` }).waitFor()
  await desktop.page.getByRole('tab', { name: '实际输出' }).click()
  await assertNoHorizontalOverflow(desktop.page, 'run detail desktop')
  await desktop.page.screenshot({ path: resolve(outputDir, 'run-detail-desktop.png'), fullPage: true })

  await desktop.page.goto(`${baseUrl}/runs/${runId}/comparison`, { waitUntil: 'networkidle' })
  await desktop.page.getByRole('heading', { name: 'Baseline / Candidate 对比' }).waitFor()
  await desktop.page.locator('canvas').waitFor()
  await desktop.page.screenshot({ path: resolve(outputDir, 'comparison-desktop.png'), fullPage: true })

  await desktop.page.goto(`${baseUrl}/usage`, { waitUntil: 'networkidle' })
  await desktop.page.getByRole('heading', { name: '用量与成本' }).waitFor()
  await desktop.page.locator('.chart-frame canvas').waitFor()
  await desktop.page.screenshot({ path: resolve(outputDir, 'usage-desktop.png'), fullPage: true })

  await desktop.page.goto(`${baseUrl}/gate-audits`, { waitUntil: 'networkidle' })
  await desktop.page.getByRole('heading', { name: '发布门禁审计' }).waitFor()
  await desktop.page.screenshot({ path: resolve(outputDir, 'gate-audit-desktop.png'), fullPage: true })

  await desktop.page.goto(`${baseUrl}/skills`, { waitUntil: 'networkidle' })
  await desktop.page.getByRole('heading', { name: 'Skills 安全' }).waitFor()
  await desktop.page.getByRole('tab', { name: '绑定验证' }).click()
  await desktop.page.getByText('原子绑定与冲突检查').waitFor()
  await desktop.page.getByRole('tab', { name: '覆盖矩阵' }).click()
  await desktop.page.getByText('冻结数据集 Skill Coverage').waitFor()
  await desktop.page.getByRole('tab', { name: 'Rego Policy' }).click()
  await assertNoHorizontalOverflow(desktop.page, 'skills desktop')
  await desktop.page.screenshot({ path: resolve(outputDir, 'skills-desktop.png'), fullPage: true })

  if (characterizationRunId) {
    await desktop.page.goto(`${baseUrl}/runs/${characterizationRunId}/comparison`, { waitUntil: 'networkidle' })
    await desktop.page.getByText('需要 Baseline 才能进行版本对比').waitFor()
    await desktop.page.goto(`${baseUrl}/runs/${characterizationRunId}/gate`, { waitUntil: 'networkidle' })
    await desktop.page.getByText('需要 Baseline 才能执行发布门禁').waitFor()
  }

  if (agUiRunId) {
    await desktop.page.goto(`${baseUrl}/runs/${agUiRunId}`, { waitUntil: 'networkidle' })
    await desktop.page.getByRole('heading', { name: `评测运行 #${agUiRunId}` }).waitFor()
    await desktop.page.getByText('Candidate only', { exact: true }).waitFor()
    await desktop.page.getByRole('tab', { name: '实际输出' }).click()
    await assertNoHorizontalOverflow(desktop.page, 'AG-UI run desktop')
    await desktop.page.screenshot({ path: resolve(outputDir, 'ag-ui-run-desktop.png'), fullPage: true })
  }

  if (multiSkillRunId) {
    await desktop.page.goto(`${baseUrl}/runs/${multiSkillRunId}`, { waitUntil: 'networkidle' })
    await desktop.page.getByRole('heading', { name: `评测运行 #${multiSkillRunId}` }).waitFor()
    await desktop.page.screenshot({ path: resolve(outputDir, 'multi-skill-run-desktop.png'), fullPage: true })
    await desktop.page.goto(`${baseUrl}/runs/${multiSkillRunId}/gate`, { waitUntil: 'networkidle' })
    await desktop.page.locator('.gate-word').getByText('SHIP', { exact: true }).waitFor()
    await desktop.page.screenshot({ path: resolve(outputDir, 'multi-skill-gate-desktop.png'), fullPage: true })
  }

  await desktop.page.goto(`${baseUrl}/admin/members`, { waitUntil: 'networkidle' })
  await desktop.page.getByRole('heading', { name: '系统管理' }).waitFor()
  await desktop.page.getByRole('cell', { name: displayName, exact: false }).waitFor()
  await desktop.page.screenshot({ path: resolve(outputDir, 'admin-desktop.png'), fullPage: true })
  await desktop.context.close()

  const mobile = await openPage({ width: 390, height: 844 })
  await login(mobile.page)
  await mobile.page.goto(`${baseUrl}/runs/${runId}`, { waitUntil: 'networkidle' })
  await mobile.page.getByTitle('打开导航').click()
  await mobile.page.locator('.sidebar--open').waitFor()
  await mobile.page.waitForTimeout(250)
  await mobile.page.screenshot({ path: resolve(outputDir, 'run-detail-mobile-nav.png'), fullPage: true })
  await mobile.page.getByTitle('关闭导航').click()
  await mobile.page.waitForTimeout(250)
  await assertNoHorizontalOverflow(mobile.page, 'run detail mobile')
  await mobile.page.screenshot({ path: resolve(outputDir, 'run-detail-mobile.png'), fullPage: true })
  await mobile.page.goto(`${baseUrl}/skills`, { waitUntil: 'networkidle' })
  await mobile.page.getByRole('heading', { name: 'Skills 安全' }).waitFor()
  await assertNoHorizontalOverflow(mobile.page, 'skills mobile')
  await mobile.page.screenshot({ path: resolve(outputDir, 'skills-mobile.png'), fullPage: true })
  await mobile.context.close()

  if (errors.length) throw new Error(`browser errors:\n${errors.join('\n')}`)
  console.log(JSON.stringify({ runId, screenshots: outputDir, browserErrors: 0 }))
} finally {
  await browser.close()
}
