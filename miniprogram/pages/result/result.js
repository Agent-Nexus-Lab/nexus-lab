const PLAN_RESULT_STORAGE_KEY = 'planRunResult'
const api = require('../../utils/api')

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

    const items = Array.isArray(result.items) ? result.items : []

    this.setData({
      result: {
        ...result,
        title: result.title || '暂无推荐结果',
        summary: result.summary || '这次没有拿到可展示的活动卡片，可以返回后重新生成。',
        date_scope: result.date_scope || '',
        request_text: result.request_text || '暂无输入记录',
        items: items.map((item) => {
          const sourceUrl = item.source_url || ''
          return {
            ...item,
            tags: Array.isArray(item.tags) ? item.tags : [],
            title: item.title || '未命名活动',
            summary: item.summary || '暂无简介',
            location: item.location || '地点待确认',
            campus: item.campus || '校区待确认',
            organizer: item.organizer || '主办方待确认',
            source_url: sourceUrl || '暂无来源链接',
            has_source_url: this.isHttpUrl(sourceUrl),
            reason_text: item.reason_text || '暂无推荐理由',
            display_order: item.display_order || 0,
            quality_score: item.quality_score == null ? '待评估' : item.quality_score,
            time_text: this.formatTimeRange(item.start_time, item.end_time)
          }
        })
      },
      hasItems: items.length > 0,
      debugText: this.formatDebug(result.debug)
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

  formatDebug(debug) {
    if (!api.ENABLE_DEBUG_VIEW || !debug) return ''
    try {
      const normalized = typeof debug === 'string' ? JSON.parse(debug) : debug
      return JSON.stringify(normalized, null, 2)
    } catch (error) {
      return String(debug)
    }
  },

  isHttpUrl(value) {
    return /^https?:\/\//i.test(String(value || ''))
  },

  copySourceUrl(event) {
    const url = event.currentTarget.dataset.url
    if (!url) return
    wx.setClipboardData({
      data: url,
      success: () => {
        wx.showToast({
          title: '来源链接已复制',
          icon: 'none'
        })
      }
    })
  },

  goPlan() {
    wx.redirectTo({
      url: '/pages/plan/plan'
    })
  }
})
