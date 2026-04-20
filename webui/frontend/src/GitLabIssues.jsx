// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useState, useEffect } from 'react'

const LABEL_COLORS = {
  'auto-detected': { bg: 'bg-blue-500/20', text: 'text-blue-300', border: 'border-blue-500/30' },
  'needs-approval': { bg: 'bg-yellow-500/20', text: 'text-yellow-300', border: 'border-yellow-500/30' },
  'approved': { bg: 'bg-green-500/20', text: 'text-green-300', border: 'border-green-500/30' },
  'auto-remediated': { bg: 'bg-purple-500/20', text: 'text-purple-300', border: 'border-purple-500/30' },
  'rejected': { bg: 'bg-red-500/20', text: 'text-red-300', border: 'border-red-500/30' },
}

export default function GitLabIssues() {
  const [issues, setIssues] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchIssues = async () => {
      try {
        const res = await fetch('/api/gitlab-issues')
        if (res.ok) setIssues(await res.json())
      } catch {}
      setLoading(false)
    }
    fetchIssues()
    const interval = setInterval(fetchIssues, 30000)
    return () => clearInterval(interval)
  }, [])

  if (loading) return <div className="text-gray-500 text-xs text-center py-4">Loading issues...</div>
  if (issues.length === 0) return <div className="text-gray-500 text-xs text-center py-4">No open issues</div>

  return (
    <div className="space-y-2 max-h-64 overflow-y-auto">
      {issues.map(issue => (
        <a key={issue.iid} href={issue.web_url} target="_blank" rel="noopener noreferrer"
           className="block bg-gray-900/60 rounded-lg p-3 border border-gray-700/30 hover:border-orange-500/30 transition-all group">
          <div className="flex items-start gap-2">
            <span className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${issue.state === 'opened' ? 'bg-green-400' : 'bg-gray-500'}`} />
            <div className="flex-1 min-w-0">
              <div className="text-xs text-gray-300 group-hover:text-white transition-colors truncate">
                #{issue.iid} {issue.title}
              </div>
              <div className="flex gap-1 mt-1 flex-wrap">
                {(issue.labels || []).map(label => {
                  const style = LABEL_COLORS[label] || { bg: 'bg-gray-500/20', text: 'text-gray-400', border: 'border-gray-500/30' }
                  return (
                    <span key={label} className={`text-[10px] px-1.5 py-0.5 rounded-full ${style.bg} ${style.text} border ${style.border}`}>
                      {label}
                    </span>
                  )
                })}
                <span className="text-[10px] text-gray-600 ml-auto">
                  {new Date(issue.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>
          </div>
        </a>
      ))}
    </div>
  )
}
