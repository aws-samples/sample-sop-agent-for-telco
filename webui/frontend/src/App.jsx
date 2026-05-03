import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import DashboardLayout from './components/DashboardLayout'
import Dashboard from './pages/Dashboard'
import Alarms from './pages/Alarms'
import SOPs from './pages/SOPs'
import Topology from './pages/Topology'
import AskAnra from './pages/AskAnra'

function App() {
  return (
    <AuthProvider>
      <DashboardLayout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/alarms" element={<Alarms />} />
          <Route path="/sops" element={<SOPs />} />
          <Route path="/topology" element={<Topology />} />
          <Route path="/ask" element={<AskAnra />} />
        </Routes>
      </DashboardLayout>
    </AuthProvider>
  )
}

export default App
