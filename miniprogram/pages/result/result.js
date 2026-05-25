const MOCK_RESULT_STORAGE_KEY = 'mockPlanResult'

Page({
  data: {
    result: {
      title: '暂无结果',
      summary: '请先生成一次日程。',
      date_scope: '',
      request_text: '',
      items: []
    }
  },

  onLoad() {
    const result = wx.getStorageSync(MOCK_RESULT_STORAGE_KEY)
    if (!result) {
      wx.showToast({
        title: '暂无生成结果',
        icon: 'none'
      })
      return
    }

    this.setData({
      result: {
        ...result,
        items: (result.items || []).map((item) => ({
          ...item,
          time_text: this.formatTimeRange(item.start_time, item.end_time)
        }))
      }
    })
  },

  formatTimeRange(start, end) {
    return `${this.formatClock(start)} - ${this.formatClock(end)}`
  },

  formatClock(value) {
    if (!value) return '时间待确认'
    const match = value.match(/T(\d{2}:\d{2})/)
    return match ? match[1] : value
  },

  goPlan() {
    wx.redirectTo({
      url: '/pages/plan/plan'
    })
  }
})
