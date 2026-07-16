Page({
  data: {
    url: ''
  },

  onLoad(options) {
    const url = decodeURIComponent(options.url || '')
    if (!/^https?:\/\//i.test(url)) {
      wx.showToast({
        title: '来源链接不可用',
        icon: 'none'
      })
      return
    }
    this.setData({ url })
  }
})
