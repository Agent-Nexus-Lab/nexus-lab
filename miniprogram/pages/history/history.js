const api = require('../../utils/api')

Page({
  data: {
    histories: [],
    loading: false,
    errorMessage: ''
  },

  onShow() {
    this.loadHistory()
  },

  async loadHistory() {
    this.setData({ loading: true, errorMessage: '' })
    try {
      const response = await api.getPlans({ page: 1, page_size: 20 })
      if (!response || response.code !== 0 || !response.data) {
        throw new Error((response && response.message) || '历史规划读取失败')
      }
      const items = Array.isArray(response.data.items) ? response.data.items : []
      this.setData({
        loading: false,
        histories: items.map((item) => ({
          ...item,
          status: 'completed',
          created_at_text: this.formatDate(item.created_at),
          date_scope_text: this.formatDateScope(item.date_scope)
        }))
      })
    } catch (error) {
      this.setData({
        loading: false,
        histories: [],
        errorMessage: error.message || '历史规划读取失败'
      })
    }
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
    const map = { today: '今天', tomorrow: '明天', this_week: '本周' }
    return map[value] || value || '未指定'
  },

  goPlan() {
    wx.redirectTo({ url: '/pages/plan/plan' })
  }
})
