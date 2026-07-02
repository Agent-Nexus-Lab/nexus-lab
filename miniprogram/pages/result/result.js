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
    },
    hasItems: false,
    debugText: ''
  },

  resultContext: null,

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
    const planId = result.plan_id || result.id || ''
    const runId = result.run_id || ''
    this.resultContext = { plan_id: planId, run_id: runId }

    this.setData({
      result: {
        ...result,
        plan_id: planId,
        run_id: runId,
        title: result.title || '暂无推荐结果',
        summary: result.summary || '这次没有拿到可展示的活动卡片，可以返回后重新生成。',
        date_scope: result.date_scope || '',
        request_text: result.request_text || '暂无输入记录',
        items: items.map((item) => {
          const sourceUrl = item.source_url || ''
          const eventId = item.event_id || item.id || ''
          const planItemId = item.plan_item_id || ''
          return {
            ...item,
            event_id: eventId,
            plan_id: item.plan_id || planId,
            plan_item_id: planItemId,
            run_id: item.run_id || runId,
            feedback_key: planItemId || eventId || `${item.display_order || 0}-${item.title || ''}`,
            feedback_type: '',
            feedback_pending: false,
            source_clicked: false,
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

  buildFeedbackPayload(item, feedbackType) {
    return {
      event_id: item.event_id || '',
      plan_id: item.plan_id || (this.resultContext && this.resultContext.plan_id) || '',
      plan_item_id: item.plan_item_id || '',
      run_id: item.run_id || (this.resultContext && this.resultContext.run_id) || '',
      feedback_type: feedbackType,
      feedback_source: 'result_card',
      metadata: {
        feedback_type: feedbackType,
        title: item.title,
        tags: item.tags || [],
        source_url: item.source_url,
        display_order: item.display_order
      }
    }
  },

  async postFeedback(item, feedbackType) {
    const payload = this.buildFeedbackPayload(item, feedbackType)
    console.log('POST /api/feedback/event payload:', payload)
    const res = await api.feedbackEvent(payload)
    if (res && res.code != null && res.code !== 0) {
      throw new Error(res.message || '反馈提交失败')
    }
    return res
  },

  async submitFeedback(event) {
    const index = event.currentTarget.dataset.index
    const feedbackType = event.currentTarget.dataset.type
    const path = `result.items[${index}]`
    const item = this.data.result.items[index]
    if (!item || item.feedback_pending) return

    const previousType = item.feedback_type || ''
    if (previousType === feedbackType) return
    const nextType = feedbackType

    this.setData({
      [`${path}.feedback_type`]: nextType,
      [`${path}.feedback_pending`]: true
    })

    try {
      await this.postFeedback(item, feedbackType)
      this.setData({
        [`${path}.feedback_pending`]: false
      })
      wx.showToast({
        title: feedbackType === 'like' ? '已记录，下次会参考' : '已记录，下次会减少类似推荐',
        icon: 'none'
      })
    } catch (error) {
      console.error('反馈提交失败:', error)
      this.setData({
        [`${path}.feedback_type`]: previousType,
        [`${path}.feedback_pending`]: false
      })
      wx.showToast({
        title: '反馈提交失败，请稍后再试',
        icon: 'none'
      })
    }
  },

  openSource(event) {
    const index = event.currentTarget.dataset.index
    const item = this.data.result.items[index]
    if (!item || !this.isHttpUrl(item.source_url)) {
      wx.showToast({
        title: '暂无可打开来源',
        icon: 'none'
      })
      return
    }

    const path = `result.items[${index}]`
    this.setData({ [`${path}.source_clicked`]: true })
    this.postFeedback(item, 'clicked_source').catch((error) => {
      console.warn('clicked_source 反馈提交失败:', error)
    })

    wx.navigateTo({
      url: `/pages/source/source?url=${encodeURIComponent(item.source_url)}`
    })
  },

  goHistory() {
    wx.navigateTo({
      url: '/pages/history/history'
    })
  },

  goPlan() {
    wx.redirectTo({
      url: '/pages/plan/plan'
    })
  }
})
