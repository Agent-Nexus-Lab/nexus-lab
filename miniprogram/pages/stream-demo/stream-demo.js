const api = require('../../utils/api')

Page({
  data: {
    endpoint: '/agent/stream-demo',
    testing: false,
    statusText: '等待验证',
    chunks: []
  },

  onEndpointInput(event) {
    this.setData({
      endpoint: event.detail.value || ''
    })
  },

  async startTest() {
    if (this.data.testing) return

    const endpoint = this.data.endpoint || '/agent/stream-demo'
    this.setData({
      testing: true,
      statusText: '正在请求流式测试接口',
      chunks: []
    })

    try {
      await api.streamRuntimeDemo({
        url: endpoint,
        data: {
          request_text: 'stream demo',
          timestamp: Date.now()
        },
        onChunk: (chunkText) => {
          const chunks = this.data.chunks.concat(chunkText || '[empty chunk]')
          this.setData({
            chunks,
            statusText: `已收到 ${chunks.length} 个 chunk`
          })
        }
      })

      this.setData({
        testing: false,
        statusText: this.data.chunks.length > 0 ? '验证完成' : '请求完成，但没有收到 chunk'
      })
    } catch (error) {
      this.setData({
        testing: false,
        statusText: error.message || '流式验证失败'
      })
    }
  }
})
