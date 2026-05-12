import { Alert } from 'antd'

const DemoBanner = ({ message }) => (
  <Alert message={message} type="info" showIcon banner
    style={{ marginBottom: 16, borderRadius: 8 }} />
)

export default DemoBanner
