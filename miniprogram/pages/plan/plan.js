const PROFILE_STORAGE_KEY = 'profileDraft'
const PLAN_REQUEST_STORAGE_KEY = 'planDayRequest'

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

  generatePlan() {
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

    wx.setStorageSync(PLAN_REQUEST_STORAGE_KEY, {
      profilePayload,
      planDayPayload,
      created_at: new Date().toISOString()
    })

    wx.navigateTo({
      url: '/pages/loading/loading'
    })
  }
})
