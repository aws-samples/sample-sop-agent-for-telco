import { useState } from 'react';
import { FloatButton, Input, Button, Space } from 'antd';
import { RobotOutlined, SendOutlined, AudioOutlined, CloseOutlined, MinusOutlined, FullscreenOutlined } from '@ant-design/icons';
import { Rnd } from 'react-rnd';
import ReactMarkdown from 'react-markdown';
import { agentAPI } from '../services/api';

const { TextArea } = Input;

const PageAgent = ({ pageContext, pageName, sampleQuestions = [], nodeContext = null }) => {
  const [visible, setVisible] = useState(false);
  const [message, setMessage] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [size, setSize] = useState({ width: 600, height: 600 });
  const [position, setPosition] = useState({ 
    x: Math.max(0, (window.innerWidth - 600) / 2), 
    y: Math.max(50, (window.innerHeight - 600) / 2 - 50) 
  });

  // Normalize pageContext - support both pageContext object and pageName string
  const normalizedContext = pageContext || {
    title: pageName || 'AI Assistant',
    description: `I can help you with ${pageName || 'your questions'}.`
  };

  // Build context description including node context if available
  const getContextDescription = () => {
    let description = normalizedContext.description;
    if (nodeContext && nodeContext.nodeId) {
      description += ` Currently viewing: ${nodeContext.nodeId} (${nodeContext.nodeType || 'device'}) at Level ${nodeContext.level || 'unknown'}.`;
    }
    return description;
  };

  // Default sample questions if none provided
  const defaultQuestions = [
    `What insights can you provide about ${normalizedContext.title}?`,
    'What are the key metrics I should focus on?',
    'Are there any issues I should be aware of?'
  ];
  const questions = sampleQuestions.length > 0 ? sampleQuestions : defaultQuestions;

  // Map page context to agent ID
  const getAgentId = (pageTitle) => {
    const agentMap = {
      'Topology Context': 'topology',
      'Network Overview': 'network',
      'Performance Metrics': 'performance',
      'Anomaly Detection': 'anomaly',
      'Vendor Analysis': 'vendor',
      'Capacity Planning': 'capacity',
      'ML and GNN Insights': 'ml',
      'ML and GNN Insights Context': 'ml',
      'Agentic Advisor': 'advisor',
      'Data Harmonization': 'harmonization',
      'Graph Topology': 'topology',
      'Edge Agents': 'network'
    };
    return agentMap[pageTitle] || 'advisor';
  };

  // Helper to get user-friendly error message
  const getErrorMessage = (error) => {
    const msg = error.message || '';
    if (msg.includes('timed out')) {
      return 'The AI agent is taking longer than expected. Please try a simpler question.';
    }
    if (msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('fetch')) {
      return 'Unable to connect to the AI agent. Please check your network connection.';
    }
    if (msg.includes('HTTP error: 504')) {
      return 'The AI agent timed out. Please try a simpler or more specific question.';
    }
    if (msg.includes('HTTP error: 5')) {
      return 'The AI agent encountered a server error. Please try again in a moment.';
    }
    if (msg.includes('HTTP error: 4')) {
      return 'Request error. Please try rephrasing your question.';
    }
    // Show the actual error for debugging
    console.error('Agent error details:', msg);
    return `Sorry, I encountered an error: ${msg || 'Unknown error'}. Please try again.`;
  };

  const handleSendMessage = async () => {
    if (!message.trim()) return;

    const userMessage = { role: 'user', content: message };
    setChatHistory(prev => [...prev, userMessage]);
    setMessage('');
    setLoading(true);

    try {
      const agentId = getAgentId(normalizedContext.title);
      // Build context including node context if available
      const chatContext = {
        page: normalizedContext.title,
        timestamp: new Date().toISOString()
      };
      if (nodeContext && nodeContext.nodeId) {
        chatContext.currentNode = {
          nodeId: nodeContext.nodeId,
          nodeType: nodeContext.nodeType,
          level: nodeContext.level,
          navigationPath: nodeContext.navigationPath
        };
      }
      const response = await agentAPI.chat(agentId, message, chatContext);

      const aiResponse = {
        role: 'assistant',
        content: response.response || 'Sorry, I encountered an error. Please try again.'
      };
      setChatHistory(prev => [...prev, aiResponse]);
    } catch (error) {
      console.error('Agent error:', error);
      const errorResponse = {
        role: 'assistant',
        content: getErrorMessage(error)
      };
      setChatHistory(prev => [...prev, errorResponse]);
    } finally {
      setLoading(false);
    }
  };

  const handleQuestionClick = async (question) => {
    setMessage(question);
    
    // Automatically send the question
    const userMessage = { role: 'user', content: question };
    setChatHistory(prev => [...prev, userMessage]);
    setLoading(true);

    try {
      const agentId = getAgentId(normalizedContext.title);
      // Build context including node context if available
      const chatContext = {
        page: normalizedContext.title,
        timestamp: new Date().toISOString()
      };
      if (nodeContext && nodeContext.nodeId) {
        chatContext.currentNode = {
          nodeId: nodeContext.nodeId,
          nodeType: nodeContext.nodeType,
          level: nodeContext.level,
          navigationPath: nodeContext.navigationPath
        };
      }
      const response = await agentAPI.chat(agentId, question, chatContext);

      const aiResponse = {
        role: 'assistant',
        content: response.response || 'Sorry, I encountered an error. Please try again.'
      };
      setChatHistory(prev => [...prev, aiResponse]);
    } catch (error) {
      console.error('Agent error:', error);
      const errorResponse = {
        role: 'assistant',
        content: getErrorMessage(error)
      };
      setChatHistory(prev => [...prev, errorResponse]);
    } finally {
      setLoading(false);
      setMessage('');
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const toggleFullscreen = () => {
    if (size.width === window.innerWidth && size.height === window.innerHeight) {
      setSize({ width: 600, height: 600 });
      setPosition({ 
        x: Math.max(0, (window.innerWidth - 600) / 2), 
        y: Math.max(50, (window.innerHeight - 600) / 2 - 50) 
      });
    } else {
      setSize({ width: window.innerWidth, height: window.innerHeight });
      setPosition({ x: 0, y: 0 });
    }
  };

  return (
    <>
      <FloatButton
        icon={<RobotOutlined />}
        type="primary"
        style={{
          right: 24,
          bottom: 24,
          width: 60,
          height: 60,
        }}
        onClick={() => {
          // Recalculate center position each time so it always appears centered on viewport
          setPosition({
            x: Math.max(0, (window.innerWidth - size.width) / 2),
            y: Math.max(50, (window.innerHeight - size.height) / 2 - 50)
          });
          setVisible(true);
        }}
        tooltip="Open AI Assistant (Enter)"
      />

      {visible && (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', zIndex: 1000, pointerEvents: 'none' }}>
        <Rnd
          size={size}
          position={position}
          onDragStop={(e, d) => setPosition({ x: d.x, y: d.y })}
          onResizeStop={(e, direction, ref, delta, position) => {
            setSize({
              width: ref.offsetWidth,
              height: ref.offsetHeight,
            });
            setPosition(position);
          }}
          minWidth={400}
          minHeight={400}
          bounds="parent"
          dragHandleClassName="drag-handle"
          style={{
            zIndex: 1000,
            display: 'flex',
            flexDirection: 'column',
            background: '#fff',
            borderRadius: 8,
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            overflow: 'hidden',
            pointerEvents: 'auto'
          }}
        >
          {/* Title Bar */}
          <div 
            className="drag-handle"
            style={{ 
              display: 'flex', 
              justifyContent: 'space-between', 
              alignItems: 'center',
              padding: '12px 16px',
              background: '#fff',
              borderBottom: '1px solid #e8e8e8',
              cursor: 'move',
              userSelect: 'none'
            }}
          >
            <Space>
              <RobotOutlined style={{ color: '#1890ff' }} />
              <span style={{ fontWeight: 500 }}>{normalizedContext.title}</span>
            </Space>
            <Space>
              <Button
                type="text"
                size="small"
                icon={<MinusOutlined />}
                onClick={() => setMinimized(!minimized)}
                style={{ cursor: 'pointer' }}
              />
              <Button
                type="text"
                size="small"
                icon={<FullscreenOutlined />}
                onClick={toggleFullscreen}
                style={{ cursor: 'pointer' }}
              />
              <Button
                type="text"
                size="small"
                icon={<CloseOutlined />}
                onClick={() => setVisible(false)}
                style={{ cursor: 'pointer' }}
              />
            </Space>
          </div>

          {!minimized && (
            <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100% - 49px)' }}>
              {/* Context Header */}
              <div style={{ 
                padding: '16px 24px', 
                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                color: 'white'
              }}>
                <div style={{ fontSize: 16, fontWeight: 'bold', marginBottom: 8 }}>
                  {normalizedContext.title}
                </div>
                <div style={{ fontSize: 12, opacity: 0.9 }}>
                  {getContextDescription()}
                </div>
              </div>

              {/* Quick Suggestions */}
              {chatHistory.length === 0 && (
                <div style={{ padding: '16px 24px', background: '#f5f5f5' }}>
                  <div style={{ 
                    fontSize: 12, 
                    fontWeight: 'bold', 
                    marginBottom: 12,
                    color: '#1890ff',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8
                  }}>
                    <RobotOutlined />
                    Quick suggestions
                  </div>
                  <Space direction="vertical" style={{ width: '100%' }} size={8}>
                    {questions.map((question, index) => (
                      <Button
                        key={index}
                        type="default"
                        size="small"
                        block
                        style={{ 
                          textAlign: 'left',
                          height: 'auto',
                          padding: '8px 12px',
                          whiteSpace: 'normal',
                          borderRadius: 16
                        }}
                        onClick={() => handleQuestionClick(question)}
                      >
                        {question}
                      </Button>
                    ))}
                  </Space>
                </div>
              )}

              {/* Chat History */}
              <div style={{ 
                flex: 1, 
                overflowY: 'auto', 
                padding: '16px 24px',
                background: '#fafafa',
                userSelect: 'text',
                cursor: 'text'
              }}>
                {chatHistory.map((msg, index) => (
                  <div
                    key={index}
                    style={{
                      marginBottom: 16,
                      display: 'flex',
                      justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start'
                    }}
                  >
                    <div
                      style={{
                        maxWidth: '80%',
                        padding: '10px 14px',
                        borderRadius: 12,
                        background: msg.role === 'user' ? '#1890ff' : '#fff',
                        color: msg.role === 'user' ? '#fff' : '#000',
                        boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
                        fontSize: 14,
                        lineHeight: 1.5
                      }}
                    >
                      {msg.role === 'assistant' ? (
                        <ReactMarkdown
                          components={{
                            p: ({node, ...props}) => <p style={{ margin: '0.5em 0' }} {...props} />,
                            ul: ({node, ...props}) => <ul style={{ margin: '0.5em 0', paddingLeft: '1.5em' }} {...props} />,
                            ol: ({node, ...props}) => <ol style={{ margin: '0.5em 0', paddingLeft: '1.5em' }} {...props} />,
                            li: ({node, ...props}) => <li style={{ margin: '0.25em 0' }} {...props} />,
                            code: ({node, inline, ...props}) => 
                              inline ? 
                                <code style={{ background: '#f0f0f0', padding: '2px 6px', borderRadius: 4, fontSize: '0.9em' }} {...props} /> :
                                <code style={{ display: 'block', background: '#f0f0f0', padding: '8px 12px', borderRadius: 4, fontSize: '0.9em', overflowX: 'auto' }} {...props} />,
                            h1: ({node, ...props}) => <h1 style={{ fontSize: '1.5em', fontWeight: 'bold', margin: '0.5em 0' }} {...props} />,
                            h2: ({node, ...props}) => <h2 style={{ fontSize: '1.3em', fontWeight: 'bold', margin: '0.5em 0' }} {...props} />,
                            h3: ({node, ...props}) => <h3 style={{ fontSize: '1.1em', fontWeight: 'bold', margin: '0.5em 0' }} {...props} />,
                            strong: ({node, ...props}) => <strong style={{ fontWeight: 600 }} {...props} />,
                          }}
                        >
                          {msg.content}
                        </ReactMarkdown>
                      ) : (
                        msg.content
                      )}
                    </div>
                  </div>
                ))}
                {loading && (
                  <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: 16 }}>
                    <div style={{
                      padding: '10px 14px',
                      borderRadius: 12,
                      background: '#fff',
                      boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
                    }}>
                      <Space>
                        <span>Thinking</span>
                        <span className="loading-dots">...</span>
                      </Space>
                    </div>
                  </div>
                )}
              </div>

              {/* Input Area */}
              <div style={{ 
                padding: '16px 24px', 
                borderTop: '1px solid #e8e8e8',
                background: '#fff'
              }}>
                <Space.Compact style={{ width: '100%' }}>
                  <TextArea
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    onKeyDown={handleKeyPress}
                    placeholder="Type your message or use voice input..."
                    autoSize={{ minRows: 1, maxRows: 3 }}
                    style={{ resize: 'none' }}
                  />
                  <Button
                    type="text"
                    icon={<AudioOutlined />}
                    style={{ height: 'auto' }}
                  />
                  <Button
                    type="primary"
                    icon={<SendOutlined />}
                    onClick={handleSendMessage}
                    loading={loading}
                    style={{ height: 'auto' }}
                  />
                </Space.Compact>
              </div>
            </div>
          )}
        </Rnd>
        </div>
      )}

      <style>{`
        @keyframes blink {
          0%, 20% { opacity: 0; }
          40% { opacity: 1; }
          60%, 100% { opacity: 0; }
        }
        .loading-dots {
          animation: blink 1.4s infinite;
        }
      `}</style>
    </>
  );
};

export default PageAgent;
