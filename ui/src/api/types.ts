// Types come from the committed OpenAPI snapshots (`make ui-types`). The generated order status
// is a plain string in the spec; the UI narrows it to the three values the state machine has.

import type { components as ProductComponents } from './generated/product-service';
import type { components as InventoryComponents } from './generated/inventory-service';
import type { components as OrderComponents } from './generated/order-service';
import type { components as NotificationComponents } from './generated/notification-service';
import type { OrderStatus } from '../lib/polling';

type OrderSchemas = OrderComponents['schemas'];

export type Product = ProductComponents['schemas']['ProductOut'];
export type ProductPage = ProductComponents['schemas']['ProductPageOut'];
export type Category = ProductComponents['schemas']['CategoryOut'];
export type CategoryList = ProductComponents['schemas']['CategoryListOut'];

export type Stock = InventoryComponents['schemas']['StockOut'];
export type Availability = InventoryComponents['schemas']['AvailabilityOut'];
export type AvailabilityLine = InventoryComponents['schemas']['LineOut'];

export type Order = Omit<OrderSchemas['OrderOut'], 'status'> & { status: OrderStatus };
export type OrderPage = Omit<OrderSchemas['OrderPageOut'], 'items'> & { items: Order[] };
export type OrderCreate = OrderSchemas['OrderCreate'];

// The CloudPunks market (DESIGN.md section 16.4).
export type Listing = OrderSchemas['ListingOut'];
export type ListingPage = OrderSchemas['ListingPageOut'];
export type Bid = OrderSchemas['BidOut'];
export type BidPage = OrderSchemas['BidPageOut'];
export type ActivityEntry = OrderSchemas['ActivityOut'];
export type ActivityPage = OrderSchemas['ActivityPageOut'];

export type Notification = NotificationComponents['schemas']['NotificationOut'];
export type NotificationList = NotificationComponents['schemas']['NotificationList'];
