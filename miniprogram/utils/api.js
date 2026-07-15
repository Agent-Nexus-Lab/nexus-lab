// 联调地址：昕宇公网 IP -> FastAPI :8000。
// 微信开发者工具里需要勾选“不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书”。
const API_BASE_URL = 'http://1.117.75.184:8000/api'
const ENABLE_DEBUG_VIEW = true

function request({ url, method = 'GET', data, retries = 2 }) {
  return new Promise((resolve, reject) => {
    const attempt = (remaining) => {
      wx.request({
        url: `${API_BASE_URL}${url}`,
        method,
        data,
        header: {
          Authorization: 'Bearer dev-openid',
          'content-type': 'application/json'
        },
        success(res) {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(res.data)
            return
          }
          if (remaining > 0 && (res.statusCode === 429 || res.statusCode >= 500)) {
            setTimeout(() => attempt(remaining - 1), 400 * (retries - remaining + 1))
            return
          }
          const message = res.data && res.data.message
            ? res.data.message
            : `HTTP ${res.statusCode}`
          reject(new Error(message))
        },
        fail(error) {
          if (remaining > 0) {
            setTimeout(() => attempt(remaining - 1), 400 * (retries - remaining + 1))
            return
          }
          reject(error)
        }
      })
    }
    attempt(retries)
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

function getPlans({ page = 1, page_size = 20 } = {}) {
  return request({
    url: `/plans?page=${encodeURIComponent(page)}&page_size=${encodeURIComponent(page_size)}`,
    method: 'GET'
  })
}

function getMemory({ status = 'active', memory_scope = '', page = 1, page_size = 20 } = {}) {
  const params = [
    'status=' + encodeURIComponent(status),
    'page=' + encodeURIComponent(page),
    'page_size=' + encodeURIComponent(page_size)
  ]
  if (memory_scope) params.push('memory_scope=' + encodeURIComponent(memory_scope))
  return request({
    url: '/memory?' + params.join('&'),
    method: 'GET'
  })
}

function deleteMemory(memoryId) {
  return request({
    url: '/memory/' + encodeURIComponent(memoryId),
    method: 'DELETE'
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

function requestChunkedStream({ url, data = {}, onChunk }) {
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

function streamRuntimeDemo({ url = '/agent/stream-demo', data = {}, onChunk }) {
  return requestChunkedStream({ url, data, onChunk })
}

function streamPlanDay(planDayPayload, onChunk) {
  return requestChunkedStream({
    url: '/agent/stream-plan-day',
    data: planDayPayload,
    onChunk
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
  getPlans,
  getMemory,
  deleteMemory,
  streamRuntimeDemo,
  streamPlanDay
}
