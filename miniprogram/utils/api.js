// 联调地址：昕宇公网 IP -> FastAPI :8000。
// 微信开发者工具里需要勾选“不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书”。
const API_BASE_URL = 'http://1.117.75.184:8000/api'
const ENABLE_DEBUG_VIEW = true

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

function feedbackEvent(feedbackPayload) {
  return request({
    url: '/feedback/event',
    method: 'POST',
    data: feedbackPayload
  })
}

function getDataHealth() {
  return request({
    url: '/admin/data-health',
    method: 'GET'
  })
}

function decodeChunk(data) {
  if (!data) return ''
  if (typeof data === 'string') return data
  const bytes = new Uint8Array(data)
  let binary = ''
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index])
  }
  try {
    return decodeURIComponent(escape(binary))
  } catch (error) {
    return binary
  }
}

function streamRuntimeDemo({ url = '/agent/stream-demo', data = {}, onChunk }) {
  return new Promise((resolve, reject) => {
    const task = wx.request({
      url: `${API_BASE_URL}${url}`,
      method: 'POST',
      data,
      enableChunked: true,
      responseType: 'arraybuffer',
      header: {
        Authorization: 'Bearer dev-openid',
        'content-type': 'application/json'
      },
      success(res) {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`HTTP ${res.statusCode}`))
          return
        }
        resolve(res)
      },
      fail(error) {
        reject(error)
      }
    })

    if (!task || typeof task.onChunkReceived !== 'function') {
      reject(new Error('当前微信基础库不支持 onChunkReceived'))
      return
    }

    task.onChunkReceived((response) => {
      if (typeof onChunk === 'function') {
        onChunk(decodeChunk(response.data))
      }
    })
  })
}

module.exports = {
  API_BASE_URL,
  ENABLE_DEBUG_VIEW,
  saveProfile,
  planDay,
  getRunStatus,
  feedbackEvent,
  getDataHealth,
  streamRuntimeDemo
}
