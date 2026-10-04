import { Navigate, Route, Routes } from 'react-router';
import { Layout } from './components/Layout';
import { DEMO_TOOLS } from './config';
import { AccountPage } from './routes/Account';
import { CollectionPage } from './routes/Collection';
import { DemoPage } from './routes/Demo';
import { ItemPage } from './routes/Item';
import { NotFound } from './routes/NotFound';
import { OrderPage } from './routes/Order';

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<CollectionPage tab="items" />} />
        <Route path="activity" element={<CollectionPage tab="activity" />} />
        <Route path="cloudpunks/:id" element={<ItemPage />} />
        <Route path="account" element={<AccountPage />} />
        <Route path="orders" element={<Navigate to="/account?tab=orders" replace />} />
        <Route path="orders/:id" element={<OrderPage />} />
        {DEMO_TOOLS ? <Route path="demo" element={<DemoPage />} /> : null}
        <Route path="home" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
