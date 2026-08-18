import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { AuthProvider } from './context/AuthContext'
import { DemoProvider } from './context/DemoContext'
import DashboardLayout from './components/DashboardLayout'
import MissionControl from './pages/MissionControl'
import AnraPage from './pages/AnraPage'
import AndaPage from './pages/AndaPage'
import AnpaPage from './pages/AnpaPage'
import Approvals from './pages/Approvals'
import Incident from './pages/Incident'
import Alarms from './pages/Alarms'
import SOPs from './pages/SOPs'
import Topology from './pages/Topology'
import Incidents from './pages/Incidents'
import AskAnra from './pages/AskAnra'

function App() {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#1890ff', borderRadius: 6 } }}>
      <BrowserRouter>
        <AuthProvider>
          <DemoProvider>
          <DashboardLayout>
            <Routes>
              <Route path="/" element={<MissionControl />} />
              <Route path="/anra" element={<AnraPage />} />
              <Route path="/anda" element={<AndaPage />} />
              <Route path="/anpa" element={<AnpaPage />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/incidents" element={<Incidents />} />
              <Route path="/incidents/:id" element={<Incident />} />
              <Route path="/alarms" element={<Alarms />} />
              <Route path="/sops" element={<SOPs />} />
              <Route path="/topology" element={<Topology />} />
              <Route path="/ask" element={<AskAnra />} />
            </Routes>
          </DashboardLayout>
          </DemoProvider>
        </AuthProvider>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
