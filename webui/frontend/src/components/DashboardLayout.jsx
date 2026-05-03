import { useState } from 'react'
import { Layout, Menu, Tooltip, Modal, Form, Input, Button, message, Divider } from 'antd'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { DashboardOutlined, AlertOutlined, RobotOutlined, ApartmentOutlined, SyncOutlined, LogoutOutlined, UserOutlined, LockOutlined, CrownOutlined } from '@ant-design/icons'

const PAGE_TITLES = {
  '/': 'Dashboard',
  '/alarms': 'Alarms & remediation',
  '/sops': 'SOPs',
  '/topology': 'Topology',
  '/ask': 'Ask ANRA',
}

const { Header, Sider, Content } = Layout

const DashboardLayout = ({ children }) => {
  const [collapsed, setCollapsed] = useState(false)
  const [profileModalOpen, setProfileModalOpen] = useState(false)
  const [changingPassword, setChangingPassword] = useState(false)
  const [form] = Form.useForm()
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout, changePassword } = useAuth()
  const pageTitle = PAGE_TITLES[location.pathname] || 'ANRA'

  const handleChangePassword = async (values) => {
    setChangingPassword(true)
    const result = await changePassword(values.oldPassword, values.newPassword)
    setChangingPassword(false)
    if (result.success) {
      message.success('Password changed successfully')
      form.resetFields()
      setProfileModalOpen(false)
    } else {
      message.error(result.error || 'Failed to change password')
    }
  }

  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: 'Dashboard' },
    { key: '/alarms', icon: <AlertOutlined />, label: 'Alarms' },
    { key: '/sops', icon: <SyncOutlined />, label: 'SOPs' },
    { key: '/topology', icon: <ApartmentOutlined />, label: 'Topology' },
    { key: '/ask', icon: <RobotOutlined />, label: 'Ask ANRA' },
  ]

  const handleMenuClick = ({ key }) => {
    navigate(key)
  }

  return (
    <Layout className="dashboard-layout aws-builder-theme">
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={240}
        collapsedWidth={64}
        style={{
          overflow: 'auto',
          height: '100vh',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          background: '#232F3E',
          boxShadow: '2px 0 8px rgba(0,0,0,0.15)',
        }}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: collapsed ? 'center' : 'flex-start',
            color: '#FFFFFF',
            fontSize: collapsed ? 20 : 16,
            fontWeight: 400,
            padding: collapsed ? '0' : '0 20px',
            background: '#161E2D',
            borderBottom: '1px solid rgba(255,255,255,0.1)',
            fontFamily: '"Amazon Ember", "Helvetica Neue", Helvetica, Arial, sans-serif',
          }}
        >
          {collapsed ? 'C' : 'ANRA'}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={handleMenuClick}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#FFFFFF',
            fontFamily: '"Amazon Ember", "Helvetica Neue", Helvetica, Arial, sans-serif',
            fontSize: '14px',
            fontWeight: 400,
          }}
          theme="dark"
        />
        <div
          style={{
            position: 'absolute',
            bottom: 48,
            left: 0,
            right: 0,
            borderTop: '1px solid rgba(255,255,255,0.1)',
            padding: collapsed ? '12px 0' : '12px 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: collapsed ? 'center' : 'space-between',
            gap: 8,
          }}
        >
          <Tooltip title={collapsed ? `${user?.email} — click to manage profile` : 'Manage profile'} placement="right">
            <div
              onClick={() => setProfileModalOpen(true)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                overflow: 'hidden',
                cursor: 'pointer',
                flex: 1,
                minWidth: 0,
              }}
            >
              <UserOutlined style={{ color: '#aaa', flexShrink: 0 }} />
              {!collapsed && (
                <span style={{
                  color: '#ccc',
                  fontSize: 12,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {user?.email}
                </span>
              )}
            </div>
          </Tooltip>
          {!collapsed && (
            <Tooltip title="Logout" placement="right">
              <LogoutOutlined
                onClick={logout}
                style={{
                  color: '#aaa',
                  fontSize: 16,
                  cursor: 'pointer',
                  flexShrink: 0,
                  transition: 'color 0.2s',
                }}
                onMouseEnter={e => e.currentTarget.style.color = '#ff4d4f'}
                onMouseLeave={e => e.currentTarget.style.color = '#aaa'}
              />
            </Tooltip>
          )}
        </div>

        {/* Profile modal */}
        <Modal
          title={null}
          open={profileModalOpen}
          onCancel={() => { setProfileModalOpen(false); form.resetFields() }}
          footer={null}
          width={420}
        >
          {/* Profile header */}
          <div style={{ textAlign: 'center', padding: '24px 0 16px' }}>
            <div style={{
              width: 64, height: 64, borderRadius: '50%',
              background: '#232F3E', display: 'flex', alignItems: 'center',
              justifyContent: 'center', margin: '0 auto 12px',
            }}>
              <UserOutlined style={{ fontSize: 28, color: '#fff' }} />
            </div>
            <div style={{ fontWeight: 600, fontSize: 16, color: '#000' }}>{user?.email}</div>
            <div style={{ marginTop: 6 }}>
              {user?.isAdmin
                ? <span style={{ background: '#fff3cd', color: '#856404', padding: '2px 10px', borderRadius: 12, fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}><CrownOutlined /> Admin</span>
                : <span style={{ background: '#e8f4fd', color: '#0c5460', padding: '2px 10px', borderRadius: 12, fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}><UserOutlined /> User</span>
              }
            </div>
          </div>

          <Divider style={{ margin: '0 0 20px' }}>Change Password</Divider>

          <Form form={form} layout="vertical" onFinish={handleChangePassword}>
            <Form.Item
              name="oldPassword"
              label="Current password"
              rules={[{ required: true, message: 'Enter your current password' }]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="Current password" />
            </Form.Item>
            <Form.Item
              name="newPassword"
              label="New password"
              rules={[
                { required: true, message: 'Enter a new password' },
                { min: 8, message: 'Password must be at least 8 characters' },
              ]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="New password" />
            </Form.Item>
            <Form.Item
              name="confirmPassword"
              label="Confirm new password"
              dependencies={['newPassword']}
              rules={[
                { required: true, message: 'Confirm your new password' },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue('newPassword') === value) return Promise.resolve()
                    return Promise.reject(new Error('Passwords do not match'))
                  },
                }),
              ]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="Confirm new password" />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" htmlType="submit" loading={changingPassword} block>
                Update password
              </Button>
            </Form.Item>
          </Form>

          <Divider />
          <Button
            danger
            block
            icon={<LogoutOutlined />}
            onClick={() => { setProfileModalOpen(false); logout() }}
          >
            Logout
          </Button>
        </Modal>
      </Sider>
      <Layout style={{ marginLeft: collapsed ? 64 : 240, transition: 'margin-left 0.2s' }}>
        <Header
          style={{
            padding: '0 32px',
            background: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
            height: 64,
            lineHeight: '64px',
            position: 'sticky',
            top: 0,
            zIndex: 10,
          }}
        >
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 2,
            }}
          >
            <h1
              style={{
                margin: 0,
                fontSize: 20,
                fontWeight: 500,
                color: '#000000',
                fontFamily: '"Amazon Ember", "Helvetica Neue", Helvetica, Arial, sans-serif',
                lineHeight: 1.3,
              }}
            >
              {pageTitle}
            </h1>
            <span
              style={{
                fontSize: 13,
                color: '#545B64',
                fontWeight: 400,
                fontFamily: '"Amazon Ember", "Helvetica Neue", Helvetica, Arial, sans-serif',
              }}
            >
              Autonomous Network Remediation Agent
            </span>
          </div>
          <div style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
            <span style={{ 
              color: '#545B64', 
              fontSize: 14,
              fontFamily: '"Amazon Ember", "Helvetica Neue", Helvetica, Arial, sans-serif',
            }}>
              {new Date().toLocaleString('en-US', { 
                month: 'short', 
                day: 'numeric', 
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
              })}
            </span>
          </div>
        </Header>
        <Content
          style={{
            margin: 0,
            padding: '24px 32px',
            minHeight: 'calc(100vh - 64px)',
            background: '#F8F8FA',
          }}
        >
          {children}
        </Content>
      </Layout>
    </Layout>
  )
}

export default DashboardLayout
