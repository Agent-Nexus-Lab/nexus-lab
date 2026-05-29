const PLAN_REQUEST_STORAGE_KEY = 'planDayRequest'
const PLAN_RESULT_STORAGE_KEY = 'planRunResult'

const api = require('../../utils/api')

const POLL_MESSAGES = [
  '正在拼命检索校园活动...',
  '正在筛选时间和校区...',
  '正在匹配你的兴趣标签...',
  '正在整理活动卡片...'
]

Page({
  data: {
    activeStep: 0,
    currentMessage: POLL_MESSAGES[0],
    progress: 18,
    steps: [
      { text: '读取生成任务 run_id' },
      { text: '轮询 plan_run 状态' },
      { text: '等待 completed 结果' },
      { text: '整理结果页数据' }
    ]
  },

  timer: null,

  onLoad() {
    const request = wx.getStorageSync(PLAN_REQUEST_STORAGE_KEY)
    if (!request) {
      wx.showToast({
        title: '请先输入日程需求',
        icon: 'none'
      })
      wx.redirectTo({
        url: '/pages/plan/plan'
      })
      return
    }

    let tick = 0
    this.timer = setInterval(async () => {
      tick += 1
      const activeStep = Math.min(tick, POLL_MESSAGES.length - 1)
      this.setData({
        activeStep,
        currentMessage: POLL_MESSAGES[activeStep],
        progress: Math.min(18 + tick * 26, 100)
      })

      try {
        const res = await api.getRunStatus(request.run_id)
        console.log('GET /api/agent/runs response:', res)

        if (res.code !== 0) {
          throw new Error(res.message || '查询生成状态失败')
        }

        if (res.data && res.data.status === 'completed') {
          this.finishRealRun(res.data, request)
          return
        }

        if (res.data && res.data.status === 'failed') {
          throw new Error(res.data.error_message || '生成任务失败')
        }
      } catch (error) {
        this.failRun(error)
        return
      }

      if (tick >= 8) {
        this.failRun(new Error('轮询超时，请确认后端是否从 queued/running 进入 completed 或 failed'))
      }
    }, 900)
  },

  onUnload() {
    this.clearTimer()
  },

  clearTimer() {
    if (!this.timer) return
    clearInterval(this.timer)
    this.timer = null
  },

  finishRealRun(runData, request) {
    this.clearTimer()
    wx.setStorageSync(PLAN_RESULT_STORAGE_KEY, {
      ...runData,
      date_scope: runData.date_scope || request.planDayPayload.date_scope,
      request_text: request.planDayPayload.request_text,
      items: Array.isArray(runData.items) ? runData.items : []
    })
    wx.redirectTo({
      url: '/pages/result/result'
    })
  },

  failRun(error) {
    console.error('轮询后端失败:', error)
    this.clearTimer()
    wx.showModal({
      title: '获取结果失败',
      content: `${error.message || '请检查后端服务是否在线'}`,
      showCancel: false,
      success: () => {
        wx.redirectTo({
          url: '/pages/plan/plan'
        })
      }
    })
  }
})
