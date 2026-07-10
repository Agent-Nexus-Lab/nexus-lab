const api = require('../../utils/api')

Page({
  data: {
    loading: false,
    errorMessage: '',
    deletedNotice: '',
    summaryCard: null,
    memories: [],
    hasMemories: false,
    queryRewriteStatus: '等待后端返回 memory_used / memory_summary 后确认',
    debugText: ''
  },

  onShow() {
    this.loadMemory()
  },

  async loadMemory(options = {}) {
    this.setData({
      loading: true,
      errorMessage: '',
      deletedNotice: options.keepDeletedNotice ? this.data.deletedNotice : ''
    })

    try {
      const res = await api.getMemory({ status: 'active', page_size: 50 })
      if (!res || res.code !== 0 || !res.data) {
        throw new Error((res && res.message) || '偏好记忆读取失败')
      }

      const rawItems = Array.isArray(res.data.items) ? res.data.items : []
      const memories = rawItems.map((item) => this.normalizeMemory(item))
      const summaryCard = this.pickSummaryCard(memories)
      this.setData({
        loading: false,
        summaryCard,
        memories,
        hasMemories: memories.length > 0,
        queryRewriteStatus: summaryCard
          ? '当前记忆会作为 active memory 进入下一轮推荐理解'
          : '暂无 active memory_summary；后端可能仍只返回标签/事件级记忆',
        debugText: this.formatDebug(res.data)
      })
    } catch (error) {
      this.setData({
        loading: false,
        errorMessage: error.message || '偏好记忆读取失败',
        summaryCard: null,
        memories: [],
        hasMemories: false,
        queryRewriteStatus: '暂时无法确认是否进入下一轮 query rewrite',
        debugText: ''
      })
    }
  },

  normalizeMemory(item) {
    const structured = item.structured_content && typeof item.structured_content === 'object'
      ? item.structured_content
      : {}
    const sourceRefs = structured.source_refs || structured.sourceRefs || item.source_ref || ''
    const sourceRefsText = Array.isArray(sourceRefs) ? sourceRefs.join('、') : String(sourceRefs || '暂无来源摘要')
    const strength = structured.memory_strength != null
      ? structured.memory_strength
      : (structured.strength != null ? structured.strength : item.confidence)
    const cleanupReason = structured.cleanup_reason || structured.cleanupReason || '用户可随时删除；过期或负反馈会降低使用优先级'
    const expiresAfterTurns = structured.expires_after_turns || structured.expiresAfterTurns || ''
    return {
      ...item,
      title: this.formatMemoryTitle(item),
      content: item.content || '暂无记忆内容',
      memory_strength_text: this.formatStrength(strength),
      source_refs_text: sourceRefsText,
      updated_at_text: this.formatDate(item.updated_at),
      expires_text: expiresAfterTurns ? `${expiresAfterTurns} 轮后衰减` : this.formatExpires(item.expires_at),
      cleanup_reason: cleanupReason,
      deleting: false
    }
  },

  pickSummaryCard(memories) {
    const summary = memories.find((item) => item.memory_type === 'memory_summary')
    if (summary) return summary
    const first = memories[0]
    if (!first) return null
    return {
      ...first,
      title: '当前 active memory 摘要',
      content: first.content
    }
  },

  formatMemoryTitle(item) {
    const names = {
      memory_summary: '偏好记忆摘要',
      liked_tag: '喜欢的标签',
      disliked_tag: '不感兴趣标签',
      liked_event: '喜欢的活动',
      disliked_event: '不感兴趣活动',
      negative_keyword: '排除关键词',
      positive_preference: '正向偏好',
      negative_preference: '负向偏好'
    }
    return names[item.memory_type] || item.memory_type || '偏好记忆'
  },

  formatStrength(value) {
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) return '待评估'
    return `${Math.round(Math.max(0, Math.min(numeric, 1)) * 100)}%`
  },

  formatExpires(value) {
    if (!value) return '未设置过期时间'
    return `有效至 ${this.formatDate(value)}`
  },

  formatDate(value) {
    if (!value) return '暂无记录'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hour = String(date.getHours()).padStart(2, '0')
    const minute = String(date.getMinutes()).padStart(2, '0')
    return `${month}-${day} ${hour}:${minute}`
  },

  formatDebug(debug) {
    if (!api.ENABLE_DEBUG_VIEW || !debug) return ''
    try {
      return JSON.stringify(debug, null, 2)
    } catch (error) {
      return String(debug)
    }
  },

  async deleteMemory(event) {
    const memoryId = event.currentTarget.dataset.id
    const index = event.currentTarget.dataset.index
    if (!memoryId) return

    wx.showModal({
      title: '删除偏好记忆',
      content: '删除后，这条记忆将停止用于下一轮推荐理解。',
      confirmText: '删除',
      confirmColor: '#dc2626',
      success: async (modalRes) => {
        if (!modalRes.confirm) return
        await this.performDelete(memoryId, index)
      }
    })
  },

  async performDelete(memoryId, index) {
    const path = `memories[${index}]`
    this.setData({ [`${path}.deleting`]: true })
    try {
      const res = await api.deleteMemory(memoryId)
      if (res && res.code != null && res.code !== 0) {
        throw new Error(res.message || '删除失败')
      }
      this.setData({ deletedNotice: '已停止用于下一轮推荐理解' })
      wx.showToast({ title: '已删除记忆', icon: 'none' })
      this.loadMemory({ keepDeletedNotice: true })
    } catch (error) {
      this.setData({ [`${path}.deleting`]: false })
      wx.showToast({
        title: error.message || '删除失败，请稍后再试',
        icon: 'none'
      })
    }
  },

  goPlan() {
    wx.navigateTo({ url: '/pages/plan/plan' })
  }
})
