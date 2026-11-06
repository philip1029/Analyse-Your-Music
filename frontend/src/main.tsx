import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { FavoritesProvider } from './Favorites.tsx'
import { SelectionProvider } from './Selection.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <FavoritesProvider>
      <SelectionProvider>
        <App />
      </SelectionProvider>
    </FavoritesProvider>
  </StrictMode>,
)
