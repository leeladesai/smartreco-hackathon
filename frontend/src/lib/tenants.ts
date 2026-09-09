import type { WidgetResponse } from "./widgets";

export interface TenantSummary {
  id: number;
  name: string;
  status: string;
  created_at: string;
  widget_count: number;
}

export interface TenantDetail extends TenantSummary {
  widgets: WidgetResponse[];
}

export interface TenantsListResponse {
  tenants: TenantSummary[];
  has_more: boolean;
}

export interface TenantCreateResponse {
  id: number;
  name: string;
  status: string;
}
