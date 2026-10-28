import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import { useAuth } from './lib/auth'
import Login from './pages/Login'

const Overview = lazy(() => import('./pages/Overview'))
const Products = lazy(() => import('./pages/Products'))
const Explorer = lazy(() => import('./pages/Explorer'))
const MarketsRegions = lazy(() => import('./pages/MarketsRegions'))
const Opportunities = lazy(() => import('./pages/Opportunities'))
const Accounts = lazy(() => import('./pages/Accounts'))
const ClientWorkspace = lazy(() => import('./pages/ClientWorkspace'))
const Integrations = lazy(() => import('./pages/Integrations'))
const Markets = lazy(() => import('./pages/Markets'))
const Companies = lazy(() => import('./pages/Companies'))
const Analyst = lazy(() => import('./pages/Analyst'))
const Brief = lazy(() => import('./pages/Brief'))
const Reports = lazy(() => import('./pages/Reports'))
const Pipeline = lazy(() => import('./pages/Pipeline'))
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
  return can('admin') ? children : <Navigate to="/" replace />
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
          <Route index element={<Overview />} />
          <Route path="products" element={<Products />} />
          <Route path="explorer" element={<Explorer />} />
          <Route path="markets" element={<MarketsRegions />} />
          <Route path="opportunities" element={<Opportunities />} />
          <Route path="accounts" element={<Accounts />} />
          <Route path="client" element={<ClientWorkspace />} />
          <Route path="integrations" element={<Integrations />} />
          <Route path="p/:productId">
            <Route index element={<Navigate to="markets" replace />} />
            <Route path="markets" element={<Markets />} />
            <Route path="companies" element={<Companies />} />
            <Route path="analyst" element={<Analyst />} />
            <Route path="brief" element={<Brief />} />
          </Route>
          <Route path="pipeline" element={<Pipeline />} />
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
