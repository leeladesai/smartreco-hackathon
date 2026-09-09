export interface WidgetResponse {
  id: number;
  tenant_id: number;
  name: string;
  status: string;
  allowed_origins: string[];
  first_event_at: string | null;
  feed_url: string | null;
  tracker_verified: boolean;
  catalog_ready: boolean;
  ready: boolean;
  created_at: string;
}

export interface WidgetCreateResponse {
  widget: WidgetResponse;
  api_key: string;
}

export interface ApiKeyResponse {
  api_key: string;
}
