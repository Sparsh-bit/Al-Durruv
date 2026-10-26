import { Compass } from 'lucide-react'
import { Link } from 'react-router'
import { Card, EmptyState } from '../components/ui'

export default function NotFound() {
  return (
    <Card>
      <EmptyState
        icon={<Compass className="size-6" />}
        title="Page not found"
        action={<Link to="/products" className="text-sm font-medium text-brand-700 hover:underline">Go to the product catalogue</Link>}
      >
        The page you opened does not exist or has moved.
      </EmptyState>
    </Card>
  )
}
