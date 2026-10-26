import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import { useAuth } from './lib/auth'
import Login from './pages/Login'

const Products = lazy(() => import('./pages/Products'))
const Markets = lazy(() => import('./pages/Markets'))
const Companies = lazy(() => import('./pages/Companies'))
const Analyst = lazy(() => import('./pages/Analyst'))
const Brief = lazy(() => import('./pages/Brief'))
const Reports = lazy(() => import('./pages/Reports'))
const ReportView = lazy(() => import('./pages/ReportView'))
const Logistics = lazy(() => import('./pages/Logistics'))
const Admin = lazy(() => import('./pages/Admin'))
const NotFound = lazy(() => import('./pages/NotFound'))

function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <FullPageSpinner />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { can } = useAuth()
  return can('admin') ? children : <Navigate to="/products" replace />
}

function FullPageSpinner() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <Spinner className="size-7" />
    </div>
  )
}

export default function App() {
  return (
    <Suspense fallback={<FullPageSpinner />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <Protected>
              <Layout />
            </Protected>
          }
        >
          <Route index element={<Navigate to="/products" replace />} />
          <Route path="products" element={<Products />} />
          <Route path="p/:productId">
            <Route index element={<Navigate to="markets" replace />} />
            <Route path="markets" element={<Markets />} />
            <Route path="companies" element={<Companies />} />
            <Route path="analyst" element={<Analyst />} />
            <Route path="brief" element={<Brief />} />
          </Route>
          <Route path="reports" element={<Reports />} />
          <Route path="reports/:reportId" element={<ReportView />} />
          <Route path="logistics" element={<Logistics />} />
          <Route
            path="admin"
            element={
              <AdminOnly>
                <Admin />
              </AdminOnly>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
