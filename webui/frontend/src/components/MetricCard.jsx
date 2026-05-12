import { Card, Statistic } from 'antd'
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'

const MetricCard = ({ title, value, suffix, delta, precision = 0, loading = false, icon }) => {
  const isPositive = delta > 0
  const deltaColor = isPositive ? '#27700E' : '#D13212'

  return (
    <Card 
      className="metric-card" 
      loading={loading}
      bordered={false}
      style={{
        background: '#FFFFFF',
        borderRadius: '8px',
        boxShadow: '0 1px 4px rgba(0, 0, 0, 0.08)',
        border: '1px solid #E5E5E8',
        height: '100%',
      }}
      bodyStyle={{
        padding: '20px',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <div style={{
            fontSize: '13px',
            color: '#545B64',
            fontWeight: 500,
            marginBottom: '8px',
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
            fontFamily: '"Amazon Ember", "Helvetica Neue", Helvetica, Arial, sans-serif',
          }}>
            {title}
          </div>
          <Statistic
            value={value}
            precision={precision}
            suffix={suffix}
            valueStyle={{
              fontSize: '28px',
              fontWeight: 300,
              color: '#000000',
              fontFamily: '"Amazon Ember", "Helvetica Neue", Helvetica, Arial, sans-serif',
            }}
          />
          {delta !== undefined && (
            <div style={{
              marginTop: '8px',
              fontSize: '13px',
              fontWeight: 500,
              color: deltaColor,
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}>
              {isPositive ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              <span>{Math.abs(delta)}% vs last period</span>
            </div>
          )}
        </div>
        {icon && (
          <div style={{
            fontSize: '32px',
            color: '#FF9900',
            opacity: 0.6,
          }}>
            {icon}
          </div>
        )}
      </div>
    </Card>
  )
}

export default MetricCard
