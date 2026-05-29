const PLAN_RESULT_STORAGE_KEY = 'planRunResult'

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
    const result = wx.getStorageSync(PLAN_RESULT_STORAGE_KEY)
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
          tags: Array.isArray(item.tags) ? item.tags : [],
          title: item.title || '未命名活动',
          summary: item.summary || '暂无简介',
          location: item.location || '地点待确认',
          campus: item.campus || '校区待确认',
          organizer: item.organizer || '主办方待确认',
          source_url: item.source_url || '暂无来源链接',
          reason_text: item.reason_text || '暂无推荐理由',
          display_order: item.display_order || 0,
          quality_score: item.quality_score == null ? '待评估' : item.quality_score,
          time_text: this.formatTimeRange(item.start_time, item.end_time)
        }))
      }
    })
  },

  formatTimeRange(start, end) {
    const startText = this.formatClock(start)
    const endText = this.formatClock(end)
    if (startText === '时间待确认' && endText === '时间待确认') return '时间待确认'
    return `${startText} - ${endText}`
  },

  formatClock(value) {
    if (!value) return '时间待确认'
    const text = String(value)
    const match = text.match(/[T\s](\d{2}:\d{2})/) || text.match(/^(\d{2}:\d{2})/)
    return match ? match[1] : value
  },

  goPlan() {
    wx.redirectTo({
      url: '/pages/plan/plan'
    })
  }
})
