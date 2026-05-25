// 联调地址：昕宇的 cpolar -> FastAPI localhost:8000
// 微信开发者工具里需要勾选“不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书”。
const API_BASE_URL = 'https://473128a5.r21.vip.cpolar.cn/api'

function request({ url, method = 'GET', data }) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${API_BASE_URL}${url}`,
      method,
      data,
      header: {
        Authorization: 'Bearer dev-openid',
        'content-type': 'application/json'
      },
      success(res) {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`HTTP ${res.statusCode}`))
          return
        }
        resolve(res.data)
      },
      fail(error) {
        reject(error)
      }
    })
  })
}

function saveProfile(profilePayload) {
  return request({
    url: '/profile',
    method: 'POST',
    data: profilePayload
  })
}

function planDay(planDayPayload) {
  return request({
    url: '/agent/plan-day',
    method: 'POST',
    data: planDayPayload
  })
}

function getRunStatus(runId) {
  return request({
    url: `/agent/runs/${runId}`,
    method: 'GET'
  })
}

module.exports = {
  API_BASE_URL,
  saveProfile,
  planDay,
  getRunStatus
}
