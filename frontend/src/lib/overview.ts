export interface OverviewResponse {
  totals: {
    users: number;
    catalog_items: number;
    events: number;
    recommendations: number;
  };
  event_type_counts: Record<string, number>;
  feedback: { up: number; down: number };
}

export interface ActivityEvent {
  id: number;
  visitor_id: string;
  event_type: string;
  catalog_item_id: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ActivityResponse {
  events: ActivityEvent[];
  has_more: boolean;
}
