import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Renders an SOP (markdown) the way an engineer reads it: headings, numbered
// steps, tables and code blocks. react-markdown does not render raw HTML, so SOP
// content (including Bedrock-generated SOPs) cannot inject markup.
const SopMarkdown = ({ content }) => (
  <div className="sop-markdown" style={{ maxHeight: '65vh', overflow: 'auto', fontSize: 13 }}>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{content || ''}</ReactMarkdown>
  </div>
)

export default SopMarkdown
