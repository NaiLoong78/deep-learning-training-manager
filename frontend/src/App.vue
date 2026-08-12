<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorMessage } from './api'
import ParameterEditor from './components/ParameterEditor.vue'
import MetricChart from './components/MetricChart.vue'
import type { Inspection, Job, MetricRow, Project } from './types'

const active = ref<'create' | 'runs' | 'about'>('create')
const step = ref(0)
const loading = ref(false)
const path = ref('')
const inspection = ref<Inspection>()
const project = ref<Project>()
const values = ref<Record<string, unknown>>({})
const experimentName = ref(`实验-${new Date().toLocaleString('zh-CN', { hour12: false }).replaceAll('/', '-').replaceAll(':', '')}`)
const jobs = ref<Job[]>([])
const selectedJob = ref<Job>()
const logs = ref<string[]>([])
const metrics = ref<MetricRow[]>([])
const logEl = ref<HTMLDivElement>()
const runtime = reactive({ learning_rate: 0.001, epochs: 100 })
let socket: WebSocket | undefined
let pollTimer: number | undefined

const running = computed(() => ['RUNNING', 'STARTING', 'STOPPING'].includes(selectedJob.value?.status || ''))
const statusText: Record<string, string> = {
  CREATED: '已创建', STARTING: '正在启动', RUNNING: '训练中', STOPPING: '正在停止',
  STOPPED: '已停止', COMPLETED: '已完成', FAILED: '失败', INTERRUPTED: '已中断'
}

async function choosePath() {
  loading.value = true
  try {
    const desktopApi = (window as typeof window & { pywebview?: { api?: { select_directory?: () => Promise<string> } } }).pywebview?.api
    const selected = desktopApi?.select_directory ? await desktopApi.select_directory() : (await api.chooseDirectory()).path
    if (selected) { path.value = selected; await inspect() }
  } catch (error) { ElMessage.error(errorMessage(error)) }
  finally { loading.value = false }
}

async function inspect() {
  if (!path.value.trim()) return ElMessage.warning('请先选择或填写项目文件夹')
  loading.value = true
  try {
    inspection.value = await api.inspectProject(path.value.trim())
    values.value = Object.fromEntries(inspection.value.adapter.parameters.map(p => [p.key, p.default]))
    step.value = 1
    ElMessage.success('项目检查完成')
  } catch (error) { ElMessage.error(errorMessage(error)) }
  finally { loading.value = false }
}

async function register() {
  if (!inspection.value) return
  loading.value = true
  try {
    project.value = await api.registerProject(inspection.value)
    step.value = 2
    ElMessage.success('项目已注册，可以创建实验')
  } catch (error) { ElMessage.error(errorMessage(error)) }
  finally { loading.value = false }
}

async function start() {
  if (!project.value || !experimentName.value.trim()) return
  loading.value = true
  try {
    const check = await api.preflightProject(project.value.id, values.value)
    if (!check.ok) {
      const errors = check.issues.filter(item => item.level === 'error').map(item => `• ${item.message}`).join('\n')
      await ElMessageBox.alert(errors || '启动前检查未通过', '暂时无法启动训练', {
        type: 'error', confirmButtonText: '返回修改参数'
      })
      return
    }
    if (check.changes.length) {
      const suggestions = check.changes
        .map(item => `${item.parameter}：${String(item.original)} → ${String(item.suggested)}\n${item.reason}`)
        .join('\n\n')
      await ElMessageBox.confirm(suggestions, '启动前检查发现路径建议', {
        type: 'warning', confirmButtonText: '应用修正并启动', cancelButtonText: '取消启动'
      })
      values.value = check.values
    }
    const experiment = await api.createExperiment(project.value.id, experimentName.value.trim(), values.value)
    const job = await api.startExperiment(experiment.id)
    await loadJobs()
    await openJob(job)
    active.value = 'runs'
    ElMessage.success('训练任务已启动')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
  finally { loading.value = false }
}

async function loadJobs() {
  try { jobs.value = await api.listJobs() } catch { /* 首页首次启动可以为空 */ }
}

async function openJob(job: Job) {
  selectedJob.value = job
  active.value = 'runs'
  const [logData, metricData] = await Promise.all([api.getLogs(job.id), api.getMetrics(job.id)])
  logs.value = logData.lines
  metrics.value = metricData
  connect(job.id)
  scrollLogs()
}

function connect(jobId: number) {
  socket?.close()
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${protocol}://${location.host}/api/ws/jobs/${jobId}`)
  socket.onmessage = async event => {
    const message = JSON.parse(event.data)
    if (message.type === 'log') { logs.value.push(message.line); if (logs.value.length > 2000) logs.value.shift(); scrollLogs() }
    if (message.type === 'metric') metrics.value = await api.getMetrics(jobId)
    if (message.type === 'status' && selectedJob.value) { selectedJob.value.status = message.status; await loadJobs() }
  }
}

function scrollLogs() { nextTick(() => { if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight }) }

async function stop() {
  if (!selectedJob.value) return
  try {
    await ElMessageBox.confirm('平台会先请求训练程序优雅退出，5 秒后仍未退出才终止进程。', '停止训练', { type: 'warning' })
    await api.stopJob(selectedJob.value.id)
    selectedJob.value.status = 'STOPPING'
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(errorMessage(error))
  }
}

async function applyRuntime() {
  if (!selectedJob.value) return
  try {
    await api.updateControl(selectedJob.value.id, { learning_rate: runtime.learning_rate, epochs: runtime.epochs })
    ElMessage.success('控制指令已写入；训练项目需要实现控制协议才会应用')
  } catch (error) { ElMessage.error(errorMessage(error)) }
}

function resetCreate() {
  step.value = 0; path.value = ''; inspection.value = undefined; project.value = undefined; values.value = {}
  experimentName.value = `实验-${Date.now()}`; active.value = 'create'
}

onMounted(async () => {
  await loadJobs()
  pollTimer = window.setInterval(async () => {
    await loadJobs()
    if (selectedJob.value) {
      const fresh = jobs.value.find(j => j.id === selectedJob.value?.id)
      if (fresh) selectedJob.value = fresh
    }
  }, 4000)
})
onBeforeUnmount(() => { socket?.close(); if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">训</div><div><strong>训练管理器</strong><span>本地训练工具</span></div></div>
      <nav>
        <button :class="{ active: active === 'create' }" @click="active = 'create'"><span>＋</span>新建训练</button>
        <button :class="{ active: active === 'runs' }" @click="active = 'runs'; loadJobs()"><span>◉</span>任务中心<i v-if="jobs.length">{{ jobs.length }}</i></button>
        <button :class="{ active: active === 'about' }" @click="active = 'about'"><span>◇</span>接入说明</button>
      </nav>
      <div class="sidebar-foot"><span class="online-dot" />服务运行正常<small>桌面版 v0.2</small></div>
    </aside>

    <main>
      <header><div><p class="eyebrow">本地训练工作台</p><h1>{{ active === 'create' ? '创建训练实验' : active === 'runs' ? '训练任务中心' : '通用项目接入' }}</h1></div><button class="ghost-button" @click="resetCreate">新建实验</button></header>

      <section v-if="active === 'create'" class="content">
        <div class="stepper">
          <div v-for="(label, index) in ['选择项目', '检查项目', '配置参数']" :key="label" :class="{ done: step >= index, current: step === index }"><b>{{ step > index ? '✓' : index + 1 }}</b><span>{{ label }}</span></div>
        </div>

        <article v-if="step === 0" class="hero-card">
          <div class="hero-icon">项目</div>
          <p class="eyebrow">项目接入</p><h2>选择深度学习项目文件夹</h2>
          <p class="lead">平台会静态检查训练入口、框架和 argparse 参数，不执行也不修改你的项目源码。</p>
          <div class="path-row"><el-input v-model="path" size="large" placeholder="例如 C:\projects\my-model" @keyup.enter="inspect" /><el-button size="large" :loading="loading" @click="choosePath">选择文件夹</el-button><el-button type="primary" size="large" :loading="loading" @click="inspect">检查项目</el-button></div>
          <div class="capabilities"><span>✓ argparse 自动识别</span><span>✓ YAML / JSON 配置发现</span><span>✓ 显式适配器</span><span>✓ 不修改源码</span></div>
        </article>

        <template v-else-if="step === 1 && inspection">
          <div class="section-title"><div><p class="eyebrow">静态检查</p><h2>项目检查结果</h2></div><el-button @click="step = 0">重新选择</el-button></div>
          <article class="project-summary">
            <div class="project-avatar">{{ inspection.framework.slice(0, 2).toUpperCase() }}</div>
            <div><h3>{{ inspection.name }}</h3><p>{{ inspection.path }}</p></div>
            <div class="summary-facts"><span><small>框架</small>{{ inspection.framework }}</span><span><small>训练入口</small>{{ inspection.entrypoint }}</span><span><small>识别方式</small>{{ inspection.adapter.mode === 'automatic' ? '自动识别' : '显式适配' }}</span><span><small>参数数目</small>{{ inspection.adapter.parameters.length }}</span></div>
          </article>
          <el-alert v-for="warning in inspection.warnings" :key="warning" :title="warning" type="warning" :closable="false" show-icon />
          <article class="panel environment-panel">
            <div class="panel-head"><div><h3>训练运行环境</h3><p>请使用该深度学习项目自己的 Python 环境，确保其中已经安装 torch、tensorflow 等项目依赖。</p></div></div>
            <el-form label-position="top"><el-form-item label="Python 解释器路径"><el-input v-model="inspection.adapter.python" size="large" placeholder="例如 C:\envs\my-project\Scripts\python.exe" /></el-form-item></el-form>
          </article>
          <article class="panel"><div class="panel-head"><div><h3>发现的训练参数</h3><p>这里只预览参数；注册后可以编辑。</p></div></div><ParameterEditor :parameters="inspection.adapter.parameters" :model-value="values" disabled /></article>
          <div class="action-bar"><span>确认入口和参数正确后再注册项目</span><el-button type="primary" size="large" :loading="loading" @click="register">注册并配置参数 →</el-button></div>
        </template>

        <template v-else-if="step === 2 && project">
          <div class="section-title"><div><p class="eyebrow">实验配置</p><h2>配置训练实验</h2></div><el-tag type="success">{{ project.framework }}</el-tag></div>
          <article class="panel"><div class="panel-head"><div><h3>实验信息</h3><p>配置会生成独立快照，不会覆盖原项目配置。</p></div></div><el-form label-position="top"><el-form-item label="实验名称"><el-input v-model="experimentName" size="large" maxlength="100" /></el-form-item></el-form></article>
          <article class="panel"><div class="panel-head"><div><h3>训练参数</h3><p>灰色字段是只读源码常量；创建 .dl-manager.json 后才能安全修改。</p></div></div><ParameterEditor :parameters="project.adapter.parameters" v-model="values" /></article>
          <div class="action-bar"><span>启动时会创建独立进程并实时采集日志</span><el-button type="primary" size="large" :loading="loading" @click="start">▶ 启动训练</el-button></div>
        </template>
      </section>

      <section v-else-if="active === 'runs'" class="content run-layout">
        <aside class="job-list panel"><div class="panel-head"><div><h3>训练任务</h3><p>{{ jobs.length }} 条记录</p></div><el-button text @click="loadJobs">刷新</el-button></div><button v-for="job in jobs" :key="job.id" :class="{ active: selectedJob?.id === job.id }" @click="openJob(job)"><span class="status-dot" :class="job.status.toLowerCase()" /><div><strong>{{ job.experiment_name || `实验 #${job.experiment_id}` }}</strong><small>{{ job.project_name }} · #{{ job.id }}</small></div><em>{{ statusText[job.status] || job.status }}</em></button><el-empty v-if="!jobs.length" description="还没有训练任务" :image-size="64" /></aside>
        <div v-if="selectedJob" class="job-detail">
          <article class="run-header panel"><div><p class="eyebrow">任务 #{{ selectedJob.id }}</p><h2>{{ selectedJob.experiment_name }}</h2><p>{{ selectedJob.project_name }} · PID {{ selectedJob.pid || '—' }}</p></div><div class="run-actions"><el-tag size="large" :type="selectedJob.status === 'RUNNING' ? 'success' : selectedJob.status === 'FAILED' ? 'danger' : 'info'">{{ statusText[selectedJob.status] || selectedJob.status }}</el-tag><el-button v-if="running" type="danger" plain @click="stop">停止训练</el-button></div></article>
          <article class="panel chart-panel"><div class="panel-head"><div><h3>训练指标</h3><p>自动解析协议指标和常见 loss / accuracy 日志</p></div></div><MetricChart :rows="metrics" /></article>
          <article v-if="running" class="panel runtime-panel"><div><h3>运行时控制</h3><p>项目需读取环境变量 DL_MANAGER_CONTROL_FILE 指向的控制文件。</p></div><el-input-number v-model="runtime.learning_rate" :step="0.0001" :min="0.000001" /><el-input-number v-model="runtime.epochs" :step="1" :min="1" /><el-button type="primary" @click="applyRuntime">应用指令</el-button></article>
          <article class="panel log-panel"><div class="panel-head"><div><h3>实时日志</h3><p>{{ logs.length }} 行 · 自动滚动</p></div><el-button text @click="logs = []">清屏</el-button></div><div ref="logEl" class="terminal"><div v-for="(line, index) in logs" :key="index"><span>{{ String(index + 1).padStart(4, '0') }}</span>{{ line }}</div><p v-if="!logs.length">等待训练输出…</p></div></article>
        </div>
        <article v-else class="panel empty-detail"><el-empty description="选择左侧任务查看日志和指标" /></article>
      </section>

      <section v-else class="content about-grid">
        <article class="panel"><p class="eyebrow">自动识别</p><h2>零配置自动识别</h2><p>项目包含 train.py、main.py 或名称中带 train 的 Python 文件时，平台通过静态语法树读取 argparse 参数。不会 import 或执行项目代码。</p><pre>python train.py --epochs 50 --learning-rate 0.001</pre></article>
        <article class="panel"><p class="eyebrow">显式适配</p><h2>复杂项目精确接入</h2><p>在项目根目录添加 <code>.dl-manager.json</code>，声明入口、参数、启动命令和指标前缀。适用于 Hydra、自定义配置和多脚本项目。</p><pre>{
  "entrypoint": "train.py",
  "framework": "PyTorch",
  "parameters": [ ... ]
}</pre></article>
        <article class="panel wide"><p class="eyebrow">指标协议</p><h2>实时指标协议</h2><p>训练程序向标准输出打印以下格式，页面就会实时生成曲线。普通日志无需改动。</p><pre>print('@@METRIC@@' + json.dumps({
  "epoch": epoch,
  "step": step,
  "train/loss": loss,
  "validation/accuracy": accuracy
}))</pre></article>
      </section>
    </main>
  </div>
</template>
