// Cart behaviour: add/remove/clear, dedup by document_id, session persistence.
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { CartProvider, useCart } from './CartContext'

const DOC_A = { document_id: 'sha256:aaa', filename: 'a.pdf', source: 'upload' }
const DOC_B = { document_id: 'sha256:bbb', filename: 'b.pdf', source: 'saudi_exchange' }

function Harness() {
  const cart = useCart()
  return (
    <div>
      <span data-testid="count">{cart.count}</span>
      <ul>
        {cart.items.map((i) => <li key={i.document_id}>{i.filename}</li>)}
      </ul>
      <button onClick={() => cart.add(DOC_A)}>addA</button>
      <button onClick={() => cart.add([DOC_A, DOC_B])}>addBoth</button>
      <button onClick={() => cart.remove(DOC_A.document_id)}>removeA</button>
      <button onClick={() => cart.clear()}>clear</button>
    </div>
  )
}

const setup = () => {
  render(<CartProvider><Harness /></CartProvider>)
  return userEvent.setup()
}

describe('cart', () => {
  it('adds documents and updates the count', async () => {
    const user = setup()
    await user.click(screen.getByText('addA'))
    expect(screen.getByTestId('count')).toHaveTextContent('1')
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
  })

  it('deduplicates by document_id', async () => {
    const user = setup()
    await user.click(screen.getByText('addA'))
    await user.click(screen.getByText('addA'))
    await user.click(screen.getByText('addBoth'))  // A again + B
    expect(screen.getByTestId('count')).toHaveTextContent('2')
    expect(screen.getAllByText('a.pdf')).toHaveLength(1)
  })

  it('removes a single item', async () => {
    const user = setup()
    await user.click(screen.getByText('addBoth'))
    await user.click(screen.getByText('removeA'))
    expect(screen.getByTestId('count')).toHaveTextContent('1')
    expect(screen.queryByText('a.pdf')).not.toBeInTheDocument()
    expect(screen.getByText('b.pdf')).toBeInTheDocument()
  })

  it('clears all items', async () => {
    const user = setup()
    await user.click(screen.getByText('addBoth'))
    await user.click(screen.getByText('clear'))
    expect(screen.getByTestId('count')).toHaveTextContent('0')
  })

  it('persists to sessionStorage and restores on remount', async () => {
    const user = setup()
    await user.click(screen.getByText('addBoth'))
    expect(JSON.parse(sessionStorage.getItem('extraction-cart'))).toHaveLength(2)

    // fresh mount (same session) restores the cart
    render(<CartProvider><Harness /></CartProvider>)
    const counts = screen.getAllByTestId('count')
    expect(counts[counts.length - 1]).toHaveTextContent('2')
  })

  it('ignores malformed stored carts', () => {
    sessionStorage.setItem('extraction-cart', '{not json')
    setup()
    expect(screen.getByTestId('count')).toHaveTextContent('0')
  })
})
