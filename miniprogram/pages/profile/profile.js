const PROFILE_STORAGE_KEY = 'profileDraft'

Page({
  data: {
    campusOptions: ['江湾', '邯郸', '枫林', '张江', '其他'],
    identityOptions: ['本科生', '硕士生', '博士生', '教职工', '其他'],
    interestOptions: ['AI', '创业', '学术', '职业', '技术', '人文', '艺术', '体育', '公益', '社交'],
    timeOptions: ['工作日白天', '工作日晚上', '周末上午', '周末下午', '周末晚上'],
    styleOptions: ['轻松', '互动', '实践', '理论', '正式', '自由'],
    interestChips: [],
    timeChips: [],
    styleChips: [],
    campus: '江湾',
    identity: '本科生',
    interest_tags: ['AI'],
    selectedAvailableTimes: ['工作日晚上'],
    activity_style_tags: ['轻松'],
    raw_preference_text: ''
  },

  onLoad() {
    const draft = wx.getStorageSync(PROFILE_STORAGE_KEY)
    if (!draft) {
      this.refreshChips()
      return
    }

    this.setData({
      campus: draft.campus || '江湾',
      identity: draft.identity || '本科生',
      interest_tags: draft.interest_tags || [],
      selectedAvailableTimes: draft.available_time ? draft.available_time.split('、') : [],
      activity_style_tags: draft.activity_style_tags || [],
      raw_preference_text: draft.raw_preference_text || ''
    }, () => {
      this.refreshChips()
    })
  },

  selectCampus(event) {
    this.setData({ campus: event.currentTarget.dataset.value })
  },

  selectIdentity(event) {
    this.setData({ identity: event.currentTarget.dataset.value })
  },

  toggleArrayField(event) {
    const { field, value } = event.currentTarget.dataset
    const current = this.data[field] || []
    const next = current.indexOf(value) > -1
      ? current.filter((item) => item !== value)
      : current.concat(value)

    this.setData({ [field]: next })
    this.refreshChips(field, next)
  },

  onRawPreferenceInput(event) {
    this.setData({ raw_preference_text: event.detail.value })
  },

  buildProfilePayload() {
    const {
      campus,
      identity,
      interest_tags,
      selectedAvailableTimes,
      activity_style_tags,
      raw_preference_text
    } = this.data

    return {
      nickname: '微信用户',
      campus,
      identity,
      raw_preference_text,
      interest_tags,
      preferred_campuses: campus ? [campus] : [],
      available_time: selectedAvailableTimes.join('、'),
      activity_style_tags,
      profile_summary: ''
    }
  },

  refreshChips(changedField, changedValue) {
    const interestTags = changedField === 'interest_tags' ? changedValue : this.data.interest_tags
    const availableTimes = changedField === 'selectedAvailableTimes' ? changedValue : this.data.selectedAvailableTimes
    const styleTags = changedField === 'activity_style_tags' ? changedValue : this.data.activity_style_tags

    this.setData({
      interestChips: this.data.interestOptions.map((label) => ({
        label,
        selected: interestTags.indexOf(label) > -1
      })),
      timeChips: this.data.timeOptions.map((label) => ({
        label,
        selected: availableTimes.indexOf(label) > -1
      })),
      styleChips: this.data.styleOptions.map((label) => ({
        label,
        selected: styleTags.indexOf(label) > -1
      }))
    })
  },

  saveProfile() {
    const profilePayload = this.buildProfilePayload()
    wx.setStorageSync(PROFILE_STORAGE_KEY, profilePayload)
    console.log('profilePayload for POST /api/profile:', profilePayload)

    wx.navigateTo({
      url: '/pages/plan/plan'
    })
  }
})
