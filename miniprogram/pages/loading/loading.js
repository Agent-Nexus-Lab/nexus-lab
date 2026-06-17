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
  load_profile: 0,
  load_memory: 0,
  search_events: 1,
  searching_events: 1,
  tool_service_boundary: 1,
  build_schedule: 2,
  arranging_schedule: 2,
  runtime_orchestration: 2,
  rewrite_plan: 3,
  save_plan: 3,
  saving_plan: 3,
  memory_feedback_loop: 3,
  feedback_loop: 3
}

Page({
  data: {
    viewState: 'running',
    runStatus: 'queued',
    statusLabel: '任务已入队',
    currentMessage: '正在理解你的需求...',
    progress: 18,
    activeStep: 0,
    errorMessage: '',
    debugText: '',
    steps: [
      { text: '正在理解需求' },
      { text: '正在检索活动' },
      { text: '正在编排日程' },
      { text: '正在整理结果' }
    ]
  },

  timer: null,
  pollCount: 0,
  request: null,

  onLoad() {
    this.request = wx.getStorageSync(PLAN_REQUEST_STORAGE_KEY)
    if (!this.request || !this.request.run_id) {
      wx.showToast({
        title: '请先输入日程需求',
        icon: 'none'
      })
      wx.redirectTo({
        url: '/pages/plan/plan'
      })
      return
    }

    this.pollRunStatus()
  },

  onUnload() {
    this.clearTimer()
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

  updateRunningState(runData) {
    const activeStep = STAGE_INDEX[runData.stage] == null ? -1 : STAGE_INDEX[runData.stage]
    const messages = [
      '正在理解你的需求...',
      '正在检索校园活动...',
      '正在编排你的日程...',
      '正在整理推荐结果...'
    ]
    const currentMessage = activeStep === -1
      ? (runData.status === 'queued' ? '任务已入队，等待 Agent 处理...' : 'Agent 正在运行...')
      : messages[activeStep]

    this.setData({
      viewState: 'running',
      runStatus: runData.status,
      statusLabel: runData.status === 'queued' ? '任务已入队' : 'Agent 正在运行',
      currentMessage,
      activeStep,
      progress: activeStep === -1 ? 32 : Math.min(28 + activeStep * 20, 88),
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
      progress: 100
    })

    const result = {
      ...runData,
      date_scope: runData.date_scope || this.request.planDayPayload.date_scope,
      request_text: this.request.planDayPayload.request_text,
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
    console.error('轮询后端失败:', message, debug)
    this.clearTimer()
    this.setData({
      viewState: 'failed',
      runStatus: 'failed',
      statusLabel: '生成失败',
      currentMessage: '这次没有成功生成日程',
      errorMessage: message,
      debugText: this.formatDebug(debug),
      progress: 100
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

  formatDebug(debug) {
    if (!api.ENABLE_DEBUG_VIEW || !debug) return ''
    try {
      const normalized = typeof debug === 'string' ? JSON.parse(debug) : debug
      return JSON.stringify(normalized, null, 2)
    } catch (error) {
      return String(debug)
    }
  }
})
