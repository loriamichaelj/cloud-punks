import { Navigate, Route, Routes } from 'react-router';
import { Layout } from './components/Layout';
import { DEMO_TOOLS } from './config';
import { BasketPage } from './routes/Basket';
import { Catalog } from './routes/Catalog';
import { CheckoutPage } from './routes/Checkout';
import { DemoPage } from './routes/Demo';
import { NotFound } from './routes/NotFound';
import { OrderPage } from './routes/Order';
import { OrdersPage } from './routes/Orders';
import { ProductPage } from './routes/Product';

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Catalog />} />
        <Route path="products/:sku" element={<ProductPage />} />
        <Route path="basket" element={<BasketPage />} />
        <Route path="checkout" element={<CheckoutPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="orders/:id" element={<OrderPage />} />
        {DEMO_TOOLS ? <Route path="demo" element={<DemoPage />} /> : null}
        <Route path="home" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
