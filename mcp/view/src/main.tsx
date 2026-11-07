import { createRoot } from 'react-dom/client'
import { HostProvider } from './host'
import { View } from './View'
import './tokens.css'

createRoot(document.getElementById('root')!).render(<HostProvider><View /></HostProvider>)
