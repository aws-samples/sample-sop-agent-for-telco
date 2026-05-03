import axios from 'axios'

const API = axios.create({ baseURL: '/api', timeout: 60000 })

// ── Real ANRA endpoints ──
export const getAlarms = () => API.get('/alarms').then(r => r.data)
export const getNodes = () => API.get('/nodes').then(r => r.data)
export const getTopology = () => API.get('/topology').then(r => r.data)
export const getSops = () => API.get('/sops').then(r => r.data)
export const getSop = (path) => API.get(`/sops/${path}`).then(r => r.data)
export const getExecutions = () => API.get('/executions').then(r => r.data)
export const getApprovals = () => API.get('/approvals').then(r => r.data)
export const postApprove = (name, action) => API.post('/approve', { alarm_name: name, action }).then(r => r.data)
export const postChat = (msg) => API.post('/chat', { message: msg }).then(r => r.data)
export const getMetrics = (params) => API.get('/metrics', { params }).then(r => r.data)
export const getHealth = () => axios.get('/health').then(r => r.data)

// ── Synthetic data for demo pages ──
// These return mock data matching Sigit's API response format

export const getNetworkOverview = () => Promise.resolve({ total_components: 0, health_score: 0 })
export const getNetworkTrends = () => Promise.resolve([])
export const getActiveAnomalies = () => Promise.resolve([])
export const getDashboardOverview = () => Promise.resolve({})
export const getGrafanaComprehensiveMetrics = () => Promise.resolve({})
export const getOutpostsGrafanaMetrics = () => Promise.resolve({})
export const getSJC38GrafanaMetrics = () => Promise.resolve({})
export const getAnomalyStats = (days = 30) => Promise.resolve({
  total_anomalies: 47, critical: 3, major: 8, minor: 15, warning: 21,
  by_layer: { hardware: 5, os: 8, kubernetes: 14, application: 20 },
  trend: Array.from({ length: days }, (_, i) => ({
    date: new Date(Date.now() - (days - i) * 86400000).toISOString().slice(0, 10),
    count: Math.floor(Math.random() * 5) + 1,
  })),
})
export const getVendorAnalysis = () => Promise.resolve({
  vendors: [
    { name: 'Nokia', score: 92, latency: 4.2, throughput: 850, reliability: 99.7 },
    { name: 'Ericsson', score: 89, latency: 5.1, throughput: 780, reliability: 99.5 },
    { name: 'Samsung', score: 87, latency: 4.8, throughput: 810, reliability: 99.3 },
  ],
})
export const getCapacityStats = () => Promise.resolve({
  cpu: { current: 62, growth: '+3.2%', days_to_threshold: 45 },
  memory: { current: 71, growth: '+2.1%', days_to_threshold: 38 },
  storage: { current: 45, growth: '+1.5%', days_to_threshold: 90 },
})
export const getCapacityForecast = () => Promise.resolve({
  forecast: Array.from({ length: 30 }, (_, i) => ({
    day: i + 1, cpu: 62 + i * 0.5, memory: 71 + i * 0.3, storage: 45 + i * 0.2,
  })),
})
export const getMLModelDetails = () => Promise.resolve({})
export const getMLStats = () => Promise.resolve({
  models_active: 6, predictions_today: 1247, accuracy_avg: 91.7,
})
export const getGNNInsights = () => Promise.resolve({})
export const getHarmonizationStats = () => Promise.resolve({})

// Topology APIs (Sigit's format — redirected to ANRA)
export const getTopologyHierarchy = () => getTopology()
export const getNodeDetails = (id) => API.get(`/nodes/${id}`).then(r => r.data)
export const getActiveTickets = () => Promise.resolve([])
export const getActiveChanges = () => Promise.resolve([])

// Edge events → ANRA alarms
export const getEdgeEvents = () => getAlarms()

// Agent API (for PageAgent component)
export const agentAPI = {
  listAgents: () => Promise.resolve([{ id: 'anra', name: 'ANRA Advisor' }]),
  chat: async (_agentId, message) => {
    const r = await postChat(message)
    return { response: r.response }
  },
  executeTool: () => Promise.resolve({}),
  recommendAgent: () => Promise.resolve({ agent: 'anra' }),
}

export default API
