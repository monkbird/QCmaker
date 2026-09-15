import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './liquid-glass.css'
import './icon-alignment.css'
import './admin.css'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
