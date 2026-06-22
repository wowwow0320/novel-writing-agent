import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Dashboard } from './pages/Dashboard'
import { StoryWorkspace } from './pages/StoryWorkspace'
import { installClientActionLogger } from './clientActionLogger'

export default function App() {
  useEffect(() => installClientActionLogger(), [])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/story/:storyId" element={<StoryWorkspace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
