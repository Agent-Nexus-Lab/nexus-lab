const PLAN_REQUEST_STORAGE_KEY = 'planDayRequest'
const PLAN_RESULT_STORAGE_KEY = 'planRunResult'
const PLAN_HISTORY_STORAGE_KEY = 'planHistoryDraft'

const api = require('../../utils/api')

const POLL_INTERVAL_MS = 800
const MAX_POLL_COUNT = 60
const STAGE_INDEX = {
  intent_parsing: 0,
  intent_parser: 0,
  understanding_request: 0,
  parse_intent: 0,
  load_profile: 1,
  read_memory: 1,
  load_memory: 1,
  search_events: 2,
  searching_events: 2,
  filter_and_score: 2,
  tool_service_boundary: 2,
  build_schedule: 3,
  arranging_schedule: 3,
  runtime_orchestration: 3,
  rewrite_plan: 4,
  rewrite_summary_and_reasons: 4,
  save_plan: 4,
  saving_plan: 4,
  cache_hit: 4,
  memory_feedback_loop: 4,
  feedback_loop: 4
}

const STAGE_MESSAGES = {
  intent_parsing: '正在理解你的需求',
  intent_parser: '正在理解你的需求',
  understanding_request: '正在理解你的需求',
  parse_intent: '正在理解你的需求',
  load_profile: '正在读取你的画像',
  read_memory: '正在读取你的偏好记忆',
  load_memory: '正在读取你的偏好记忆',
  search_events: '正在检索可参加的校园活动',
  searching_events: '正在检索可参加的校园活动',
  filter_and_score: '正在根据时间、地点和偏好排序',
  build_schedule: '正在编排你的日程',
  arranging_schedule: '正在编排你的日程',
  rewrite_plan: '正在整理推荐理由',
  rewrite_summary_and_reasons: '正在整理推荐理由',
  save_plan: '正在保存规划结果',
  saving_plan: '正在保存规划结果',
  cache_hit: '命中缓存，正在返回上次可复用结果'
}

Page({
  data: {
    viewState: 'running',
    runStatus: 'queued',
    statusLabel: '任务已入队',
    currentMessage: '正在理解你的需求...',
    progress: 18,
    progressText: '18%',
    activeStep: 0,
    errorMessage: '',
    failureDetails: [],
    rewriteNotice: '',
    debugText: '',
    dataHealth: null,
    dataHealthError: '',
    steps: [
      { text: '正在理解需求' },
      { text: '正在读取记忆' },
      { text: '正在检索活动' },
      { text: '正在编排日程' },
      { text: '正在整理推荐理由' }
    ]
  },

  timer: null,
  pollCount: 0,
  request: null,
  streamBuffer: '',
  streamCompleted: false,

  onLoad() {
    this.request = wx.getStorageSync(PLAN_REQUEST_STORAGE_KEY)
    const hasRunId = this.request && this.request.run_id
    const hasPlanPayload = this.request && this.request.planDayPayload
    if (!hasRunId && !hasPlanPayload) {
      wx.showToast({
        title: '请先输入日程需求',
        icon: 'none'
      })
      wx.redirectTo({
        url: '/pages/plan/plan'
      })
      return
    }

    this.loadDataHealth()
    if (hasRunId) {
      this.pollRunStatus()
      return
    }

    if (this.request.stream_first !== false && typeof api.streamPlanDay === 'function') {
      this.startStreamPlan()
      return
    }

    this.createRunAndPoll()
  },

  onUnload() {
    this.clearTimer()
  },

  async startStreamPlan() {
    this.streamBuffer = ''
    this.streamCompleted = false
    this.updateRunningState({
      status: 'running',
      stage: 'intent_parsing',
      stage_message: '正在连接实时生成通道',
      progress: 12
    })

    try {
      await api.streamPlanDay(
        {
          ...this.request.planDayPayload,
          include_debug: api.ENABLE_DEBUG_VIEW
        },
        (chunkText) => this.handleStreamChunk(chunkText)
      )
      this.flushStreamBuffer()
      if (!this.streamCompleted) {
        throw new Error('流式接口结束但未返回 completed')
      }
    } catch (error) {
      if (this.streamCompleted) return
      console.warn('流式生成不可用，切换轮询:', error)
      await this.createRunAndPoll(error)
    }
  },

  async createRunAndPoll(streamError) {
    const fallbackDebug = streamError
      ? { stream_fallback_reason: streamError.message || String(streamError) }
      : null
    this.setData({
      viewState: 'running',
      runStatus: 'queued',
      statusLabel: streamError ? '切换轮询' : '创建任务',
      currentMessage: streamError ? '实时通道暂不可用，正在切换稳定轮询...' : '正在创建生成任务...',
      activeStep: 0,
      progress: 18,
      progressText: '18%',
      debugText: this.formatDebug(fallbackDebug)
    })

    try {
      const planRes = await api.planDay(this.request.planDayPayload)
      console.log('POST /api/agent/plan-day response:', planRes)
      if (planRes.code !== 0 || !planRes.data || !planRes.data.run_id) {
        throw new Error(planRes.message || '生成任务创建失败')
      }

      this.request = {
        ...this.request,
        run_id: planRes.data.run_id,
        status: planRes.data.status,
        stream_fallback_reason: fallbackDebug && fallbackDebug.stream_fallback_reason
      }
      wx.setStorageSync(PLAN_REQUEST_STORAGE_KEY, this.request)
      this.pollRunStatus()
    } catch (error) {
      this.failRun(error.message || '生成任务创建失败', {
        ...(fallbackDebug || {}),
        error: error.message || String(error)
      })
    }
  },

  async pollRunStatus() {
    this.clearTimer()
    this.pollCount += 1

    try {
      const res = await api.getRunStatus(this.request.run_id)
      console.log('GET /api/agent/runs response:', res)

      if (!res || res.code !== 0 || !res.data) {
        throw new Error((res && res.message) || '查询生成状态失败')
      }

      const runData = res.data
      if (runData.status === 'completed') {
        this.finishRealRun(runData)
        return
      }

      if (runData.status === 'failed') {
        this.failRun(runData.error_message || '生成任务失败', runData.debug)
        return
      }

      if (runData.status !== 'queued' && runData.status !== 'running') {
        throw new Error(`未知运行状态：${runData.status || '空'}`)
      }

      this.updateRunningState(runData)

      if (this.pollCount >= MAX_POLL_COUNT) {
        this.failRun('轮询超时，请确认后端是否从 queued/running 进入 completed 或 failed', runData.debug)
        return
      }

      this.timer = setTimeout(() => {
        this.pollRunStatus()
      }, POLL_INTERVAL_MS)
    } catch (error) {
      this.failRun(error.message || '请检查后端服务是否在线')
    }
  },

  handleStreamChunk(chunkText) {
    console.log('POST /api/agent/stream-plan-day chunk:', chunkText)
    const events = this.extractStreamEvents(chunkText)
    if (events.length === 0 && String(chunkText || '').trim()) {
      this.updateRunningState({
        status: 'running',
        stage_message: String(chunkText).trim(),
        progress: this.data.progress
      })
      return
    }
    events.forEach((event) => this.processStreamEvent(event))
  },

  flushStreamBuffer() {
    const text = this.streamBuffer.trim()
    if (!text) return
    this.streamBuffer = ''
    const event = this.parseStreamLine(text)
    if (event) this.processStreamEvent(event)
  },

  extractStreamEvents(chunkText) {
    this.streamBuffer += String(chunkText || '')
    const lines = this.streamBuffer.split(/\r?\n/)
    this.streamBuffer = lines.pop() || ''
    const events = []

    lines.forEach((line) => {
      const event = this.parseStreamLine(line)
      if (event) events.push(event)
    })

    const buffered = this.streamBuffer.trim()
    if (buffered.startsWith('{') && buffered.endsWith('}')) {
      const event = this.parseStreamLine(buffered)
      if (event) {
        events.push(event)
        this.streamBuffer = ''
      }
    }

    return events
  },

  parseStreamLine(line) {
    let text = String(line || '').trim()
    if (!text || text.startsWith(':') || text.startsWith('event:')) return null
    if (text.startsWith('data:')) text = text.slice(5).trim()
    if (!text) return null
    if (text === '[DONE]') return { stream_done: true }

    try {
      return JSON.parse(text)
    } catch (error) {
      return { status: 'running', stage_message: text }
    }
  },

  processStreamEvent(event) {
    let payload = event && event.code != null && event.data ? event.data : event
    if (event && event.data && typeof event.data === 'object' && (event.type || event.event)) {
      payload = { ...event.data, type: event.type, event: event.event }
    }
    if (!payload || typeof payload !== 'object' || payload.stream_done) return

    if (payload.run_id) {
      this.request = { ...this.request, run_id: payload.run_id }
      wx.setStorageSync(PLAN_REQUEST_STORAGE_KEY, this.request)
    }

    const status = payload.status || payload.event || payload.type
    if (status === 'completed' || status === 'result' || payload.done === true) {
      this.streamCompleted = true
      this.finishRealRun(this.normalizeStreamResult(payload))
      return
    }

    if (status === 'failed' || status === 'error') {
      this.streamCompleted = true
      this.failRun(payload.error_message || payload.message || '流式生成失败', payload.debug || payload)
      return
    }

    this.updateRunningState({
      ...payload,
      status: payload.status || 'running',
      stage: payload.stage || payload.current_stage,
      stage_message: payload.stage_message || payload.message || payload.text,
      progress: payload.progress
    })
  },

  normalizeStreamResult(payload) {
    const result = payload.data || payload.result || payload.plan || payload
    return {
      ...result,
      status: 'completed',
      run_id: result.run_id || payload.run_id || this.request.run_id || '',
      plan_id: result.plan_id || payload.plan_id || '',
      debug: result.debug || payload.debug
    }
  },

  updateRunningState(runData) {
    const stage = runData.stage || ''
    const cacheHit = this.isCacheHit(runData)
    const activeStep = cacheHit ? STAGE_INDEX.cache_hit : (STAGE_INDEX[stage] == null ? -1 : STAGE_INDEX[stage])
    const currentMessage = runData.stage_message ||
      (cacheHit ? STAGE_MESSAGES.cache_hit : STAGE_MESSAGES[stage]) ||
      (runData.status === 'queued' ? '任务已入队，等待 Agent 处理...' : 'Agent 正在运行...')
    const nextProgress = this.normalizeProgress(runData.progress, activeStep, cacheHit)

    this.setData({
      viewState: 'running',
      runStatus: runData.status,
      statusLabel: cacheHit ? '命中缓存' : (runData.status === 'queued' ? '任务已入队' : 'Agent 正在运行'),
      currentMessage,
      activeStep,
      progress: nextProgress,
      progressText: `${nextProgress}%`,
      rewriteNotice: this.extractRewriteNotice(runData.debug),
      debugText: this.formatDebug(runData.debug)
    })
  },

  finishRealRun(runData) {
    this.clearTimer()
    this.setData({
      viewState: 'completed',
      runStatus: 'completed',
      statusLabel: '生成完成',
      currentMessage: '日程已生成',
      activeStep: this.data.steps.length - 1,
      progress: 100,
      progressText: '100%'
    })

    const planDayPayload = this.request.planDayPayload || {}
    const result = {
      ...runData,
      date_scope: runData.date_scope || planDayPayload.date_scope,
      request_text: planDayPayload.request_text || runData.request_text || '',
      items: Array.isArray(runData.items) ? runData.items : []
    }

    wx.setStorageSync(PLAN_RESULT_STORAGE_KEY, result)
    this.saveHistoryDraft(result)

    this.timer = setTimeout(() => {
      wx.redirectTo({
        url: '/pages/result/result'
      })
    }, 180)
  },

  saveHistoryDraft(result) {
    const history = wx.getStorageSync(PLAN_HISTORY_STORAGE_KEY) || []
    const items = Array.isArray(result.items) ? result.items : []
    const planId = result.plan_id || result.id || ''
    const runId = result.run_id || this.request.run_id || ''
    const nextItem = {
      plan_id: planId,
      run_id: runId,
      title: result.title || '暂无标题',
      summary: result.summary || '',
      date_scope: result.date_scope || '',
      request_text: result.request_text || '',
      item_count: items.length,
      status: result.status || 'completed',
      created_at: new Date().toISOString()
    }
    const filtered = history.filter((item) => {
      if (planId && item.plan_id === planId) return false
      if (runId && item.run_id === runId) return false
      return true
    })
    wx.setStorageSync(PLAN_HISTORY_STORAGE_KEY, [nextItem, ...filtered].slice(0, 20))
  },

  failRun(message, debug) {
    console.error('生成失败:', message, debug)
    const debugReason = this.extractDebugReason(debug)
    const rewriteNotice = this.extractRewriteNotice(debug)
    this.clearTimer()
    this.setData({
      viewState: 'failed',
      runStatus: 'failed',
      statusLabel: '生成失败',
      currentMessage: '这次没有成功生成日程',
      errorMessage: debugReason ? `${message}：${debugReason}` : message,
      failureDetails: this.extractFailureDetails(debug),
      rewriteNotice,
      debugText: this.formatDebug(debug),
      progress: 100,
      progressText: '100%'
    })
  },

  goPlan() {
    wx.redirectTo({
      url: '/pages/plan/plan'
    })
  },

  clearTimer() {
    if (!this.timer) return
    clearTimeout(this.timer)
    this.timer = null
  },

  async loadDataHealth() {
    if (!api.ENABLE_DEBUG_VIEW || typeof api.getDataHealth !== 'function') return
    try {
      const res = await api.getDataHealth()
      if (!res || res.code !== 0 || !res.data) {
        throw new Error((res && res.message) || '数据健康状态获取失败')
      }
      this.setData({
        dataHealth: this.normalizeDataHealth(res.data),
        dataHealthError: ''
      })
    } catch (error) {
      this.setData({
        dataHealth: null,
        dataHealthError: error.message || '数据健康状态获取失败'
      })
    }
  },

  normalizeDataHealth(data) {
    const sources = data.sources_breakdown || {}
    return {
      ...data,
      healthLabel: data.is_healthy ? '健康' : '需关注',
      statusClass: data.is_healthy ? 'healthy' : 'warning',
      lastCollectionText: this.formatDateTime(data.last_collection_time),
      sourceSummary: Object.keys(sources).length > 0
        ? Object.keys(sources).map((key) => `${key} ${sources[key]}`).join(' / ')
        : '暂无来源统计',
      collectionLogs: this.normalizeCollectionLogs(data.collection_logs || data.collectionLogs),
      alerts: Array.isArray(data.alerts) ? data.alerts : []
    }
  },

  normalizeCollectionLogs(logs) {
    if (!Array.isArray(logs) || logs.length === 0) {
      return [{
        id: 'empty',
        timeText: '暂无',
        result: '暂无采集日志记录',
        source: 'collection_logs 未返回'
      }]
    }
    return logs.slice(0, 3).map((log, index) => ({
      id: log.id || log.log_id || `${index}`,
      timeText: this.formatDateTime(log.created_at || log.collection_time || log.time),
      result: log.result || log.status || 'unknown',
      source: log.source_name || log.source || log.account || '未知来源'
    }))
  },

  formatDateTime(value) {
    if (!value) return '暂无记录'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hour = String(date.getHours()).padStart(2, '0')
    const minute = String(date.getMinutes()).padStart(2, '0')
    return `${month}-${day} ${hour}:${minute}`
  },

  formatDebug(debug) {
    if (!api.ENABLE_DEBUG_VIEW || !debug) return ''
    try {
      const normalized = typeof debug === 'string' ? JSON.parse(debug) : debug
      return JSON.stringify(normalized, null, 2)
    } catch (error) {
      return String(debug)
    }
  },

  isCacheHit(runData) {
    const debug = this.parseDebugObject(runData.debug) || {}
    const cache = debug.cache && typeof debug.cache === 'object' ? debug.cache : {}
    return runData.cache_hit === true || debug.cache_hit === true || cache.cache_hit === true
  },

  normalizeProgress(progress, activeStep, cacheHit) {
    if (typeof progress === 'number' && Number.isFinite(progress)) {
      const percent = progress >= 0 && progress <= 1 ? progress * 100 : progress
      return Math.round(Math.max(8, Math.min(percent, 96)))
    }
    if (cacheHit) return 92
    if (activeStep === -1) return 32
    return Math.min(22 + activeStep * 17, 88)
  },

  extractDebugReason(debug) {
    const normalized = this.parseDebugObject(debug)
    if (!normalized) return typeof debug === 'string' ? debug : ''
    return normalized.rejection_reason ||
      normalized.error_message ||
      normalized.error ||
      normalized.stream_fallback_reason ||
      normalized.rewrite_error ||
      ''
  },

  extractFailureDetails(debug) {
    const normalized = this.parseDebugObject(debug)
    if (!normalized) return []
    const rejections = normalized.rejections || normalized.debug_rejections || normalized.rejection_reasons
    if (!Array.isArray(rejections)) return []
    return rejections.map((item, index) => {
      if (typeof item === 'string') return { id: `${index}`, text: item }
      return {
        id: item.id || item.code || `${index}`,
        text: item.reason || item.message || item.error || JSON.stringify(item)
      }
    }).filter((item) => item.text)
  },

  extractRewriteNotice(debug) {
    const normalized = this.parseDebugObject(debug)
    if (!normalized) return ''
    const llmRewrite = normalized.llm_rewrite && typeof normalized.llm_rewrite === 'object'
      ? normalized.llm_rewrite
      : {}
    const rewriteError = normalized.rewrite_error || llmRewrite.error
    if (!rewriteError && normalized.used_fallback !== true && llmRewrite.used_fallback !== true) return ''
    const timeout = normalized.timeout_seconds || llmRewrite.timeout_seconds
    const promptVersion = normalized.prompt_version || llmRewrite.prompt_version
    const parts = ['推荐文案已降级为模板生成']
    if (rewriteError) parts.push(`原因：${rewriteError}`)
    if (timeout) parts.push(`超时：${timeout}s`)
    if (promptVersion) parts.push(`prompt：${promptVersion}`)
    return parts.join('，')
  },

  parseDebugObject(debug) {
    if (!debug) return null
    if (typeof debug === 'object') return debug
    if (typeof debug !== 'string') return null
    try {
      return JSON.parse(debug)
    } catch (error) {
      return null
    }
  }
})
