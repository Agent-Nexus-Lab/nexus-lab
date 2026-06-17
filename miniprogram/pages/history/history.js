const PLAN_HISTORY_STORAGE_KEY = 'planHistoryDraft'

Page({
  data: {
    histories: []
  },

  onShow() {
    const histories = wx.getStorageSync(PLAN_HISTORY_STORAGE_KEY) || []
    this.setData({
      histories: histories.map((item) => ({
        ...item,
        created_at_text: this.formatDate(item.created_at),
        date_scope_text: this.formatDateScope(item.date_scope)
      }))
    })
  },

  formatDate(value) {
    if (!value) return '时间待确认'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hour = String(date.getHours()).padStart(2, '0')
    const minute = String(date.getMinutes()).padStart(2, '0')
    return `${month}-${day} ${hour}:${minute}`
  },

  formatDateScope(value) {
    const map = {
      today: '今天',
      tomorrow: '明天',
      this_week: '本周'
    }
    return map[value] || value || '未指定'
  },

  goPlan() {
    wx.redirectTo({
      url: '/pages/plan/plan'
    })
  }
})
