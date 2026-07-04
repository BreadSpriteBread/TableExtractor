// Session-persistent extraction cart, deduplicated by document_id.
import { createContext, useContext, useEffect, useMemo, useState } from 'react'

const CartContext = createContext(null)
const STORAGE_KEY = 'extraction-cart'

function loadCart() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    const items = raw ? JSON.parse(raw) : []
    return Array.isArray(items) ? items : []
  } catch {
    return []
  }
}

export function CartProvider({ children }) {
  const [items, setItems] = useState(loadCart)

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(items))
    } catch { /* storage unavailable (private mode) — cart stays in memory */ }
  }, [items])

  const value = useMemo(() => ({
    items,
    count: items.length,
    has: (documentId) => items.some((i) => i.document_id === documentId),
    add: (docs) => {
      const list = Array.isArray(docs) ? docs : [docs]
      setItems((prev) => {
        const known = new Set(prev.map((i) => i.document_id))
        const fresh = []
        for (const d of list) {
          if (!d?.document_id || known.has(d.document_id)) continue
          known.add(d.document_id)
          fresh.push({ document_id: d.document_id, filename: d.filename, source: d.source })
        }
        return fresh.length ? [...prev, ...fresh] : prev
      })
    },
    remove: (documentId) =>
      setItems((prev) => prev.filter((i) => i.document_id !== documentId)),
    clear: () => setItems([]),
  }), [items])

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>
}

export function useCart() {
  const ctx = useContext(CartContext)
  if (!ctx) throw new Error('useCart must be used within CartProvider')
  return ctx
}
