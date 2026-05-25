const PROFILE_STORAGE_KEY = 'profileDraft'
const PLAN_REQUEST_STORAGE_KEY = 'planDayRequest'

const api = require('../../utils/api')

Page({
  data: {
    profile: null,
    hasProfile: false,
    dateScopeOptions: [
      { label: '今天', value: 'today' },
      { label: '明天', value: 'tomorrow' },
      { label: '本周', value: 'this_week' }
    ],
    date_scope: 'today',
    request_text: '今晚想安排点 AI 相关但别太累的活动'
  },

  onLoad() {
    this.loadProfileDraft()
  },

  onShow() {
    this.loadProfileDraft()
  },

  loadProfileDraft() {
    const draft = wx.getStorageSync(PROFILE_STORAGE_KEY)
    if (!draft) {
      this.setData({
        profile: null,
        hasProfile: false
      })
      return
    }

    this.setData({
      profile: {
        ...draft,
        interest_tagsText: (draft.interest_tags || []).join('、') || '未选择',
        activity_style_tagsText: (draft.activity_style_tags || []).join('、') || '未选择'
      },
      hasProfile: true
    })
  },

  selectDateScope(event) {
    this.setData({ date_scope: event.currentTarget.dataset.value })
  },

  onRequestInput(event) {
    this.setData({ request_text: event.detail.value })
  },

  goProfile() {
    wx.navigateTo({
      url: '/pages/profile/profile'
    })
  },

  async generatePlan() {
    const profilePayload = wx.getStorageSync(PROFILE_STORAGE_KEY) || null
    const planDayPayload = {
      request_text: this.data.request_text.trim(),
      date_scope: this.data.date_scope
    }

    console.log('profilePayload for POST /api/profile:', profilePayload)
    console.log('planDayPayload for POST /api/agent/plan-day:', planDayPayload)

    if (!profilePayload) {
      wx.showToast({
        title: '请先保存偏好',
        icon: 'none'
      })
      return
    }

    if (!planDayPayload.request_text) {
      wx.showToast({
        title: '请输入日程需求',
        icon: 'none'
      })
      return
    }

    wx.showLoading({
      title: '连接后端中',
      mask: true
    })

    try {
      const profileRes = await api.saveProfile(profilePayload)
      console.log('POST /api/profile response:', profileRes)

      const planRes = await api.planDay(planDayPayload)
      console.log('POST /api/agent/plan-day response:', planRes)

      if (planRes.code !== 0 || !planRes.data || !planRes.data.run_id) {
        throw new Error(planRes.message || '生成任务创建失败')
      }

      wx.setStorageSync(PLAN_REQUEST_STORAGE_KEY, {
        profilePayload,
        planDayPayload,
        run_id: planRes.data.run_id,
        status: planRes.data.status,
        api_base_url: api.API_BASE_URL,
        created_at: new Date().toISOString()
      })

      wx.hideLoading()
      wx.navigateTo({
        url: '/pages/loading/loading'
      })
    } catch (error) {
      console.error('生成日程接口调用失败:', error)
      wx.hideLoading()
      wx.showModal({
        title: '连接后端失败',
        content: `${error.message || '请检查 cpolar 链接、后端服务和小程序网络设置'}`,
        showCancel: false
      })
    }
  }
})
