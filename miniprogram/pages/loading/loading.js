const PLAN_REQUEST_STORAGE_KEY = 'planDayRequest'
const MOCK_RESULT_STORAGE_KEY = 'mockPlanResult'

const api = require('../../utils/api')

const POLL_MESSAGES = [
  '正在拼命检索校园活动...',
  '正在筛选时间和校区...',
  '正在匹配你的兴趣标签...',
  '正在整理活动卡片...'
]

function buildMockResult(request) {
  return {
    run_id: 'run_mock_001',
    status: 'completed',
    plan_id: 'plan_mock_ai_evening',
    title: '今晚 AI 轻量活动安排',
    summary: '今晚为你找到 3 个偏轻松的 AI 相关活动，优先考虑江湾校区与晚间时间。',
    date_scope: request.planDayPayload.date_scope,
    request_text: request.planDayPayload.request_text,
    items: [
      {
        event_id: 'evt_001',
        title: 'AI 讲座：大模型在产业中的应用',
        summary: '邀请业界专家分享大模型落地案例，适合对 AI 应用感兴趣的同学。',
        start_time: '2026-05-21T19:00:00+08:00',
        end_time: '2026-05-21T20:30:00+08:00',
        location: '江湾校区教学楼 A205',
        campus: '江湾',
        organizer: '计算机学院',
        tags: ['AI', '讲座', '产业'],
        source_url: 'https://www.example.edu.cn/events/123',
        reason_text: '主题匹配你的 AI 兴趣，时间在晚间，地点也符合你的校区偏好。',
        display_order: 1,
        quality_score: 0.86
      },
      {
        event_id: 'evt_002',
        title: 'AI 创业沙龙：从实验室到产品',
        summary: '小型圆桌讨论，聊聊如何把 AI 研究变成可用的产品。',
        start_time: '2026-05-21T20:40:00+08:00',
        end_time: '2026-05-21T21:30:00+08:00',
        location: '江湾校区创新创业空间 1 楼',
        campus: '江湾',
        organizer: '创新创业中心',
        tags: ['AI', '创业', '沙龙'],
        source_url: 'https://www.example.edu.cn/events/456',
        reason_text: '同时匹配 AI 和创业两个标签，活动形式更轻松，适合作为讲座后的延伸选择。',
        display_order: 2,
        quality_score: 0.82
      },
      {
        event_id: 'evt_003',
        title: '技术读书会：AI Agent 产品案例讨论',
        summary: '围绕 AI Agent 产品案例做轻量分享和自由讨论。',
        start_time: '2026-05-22T18:30:00+08:00',
        end_time: '2026-05-22T20:00:00+08:00',
        location: '邯郸校区学生创新中心 204',
        campus: '邯郸',
        organizer: '产品与技术社',
        tags: ['AI', '产品', '社交'],
        source_url: 'https://www.example.edu.cn/events/789',
        reason_text: '如果你愿意扩大到明天或邯郸校区，这是一个更偏交流和产品视角的备选。',
        display_order: 3,
        quality_score: 0.78
      }
    ],
    started_at: '2026-05-21T20:00:01+08:00',
    ended_at: '2026-05-21T20:00:05+08:00',
    error_message: null
  }
}

Page({
  data: {
    activeStep: 0,
    currentMessage: POLL_MESSAGES[0],
    progress: 18,
    steps: [
      { text: '读取生成任务 run_id' },
      { text: '请求后端运行状态' },
      { text: '等待活动卡片返回' },
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
        this.failRun(new Error('轮询超时，请确认后端是否返回 completed'))
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

  finishMockRun(request) {
    this.clearTimer()
    wx.setStorageSync(MOCK_RESULT_STORAGE_KEY, buildMockResult(request))
    wx.redirectTo({
      url: '/pages/result/result'
    })
  },

  finishRealRun(runData, request) {
    this.clearTimer()
    wx.setStorageSync(MOCK_RESULT_STORAGE_KEY, {
      ...runData,
      request_text: request.planDayPayload.request_text,
      items: runData.items || []
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
