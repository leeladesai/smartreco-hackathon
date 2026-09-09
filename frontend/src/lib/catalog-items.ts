export interface CatalogItem {
  id: number;
  title: string;
  description: string;
  story: string | null;
  provider: string;
  category: string;
  price: string;
  specs: Record<string, string>;
  use_case_tags: string[];
  source_url: string | null;
  vector_synced: boolean;
  ingestion_adapter: string;
  review_status: string;
  sync_stale: boolean;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SpecRow {
  label: string;
  value: string;
}

export interface ItemFormValues {
  title: string;
  description: string;
  story: string;
  provider: string;
  category: string;
  price: string;
  specs: SpecRow[];
  use_case_tags: string;
  source_url: string;
}

export function emptyItemForm(): ItemFormValues {
  return {
    title: "",
    description: "",
    story: "",
    provider: "",
    category: "",
    price: "",
    specs: [],
    use_case_tags: "",
    source_url: "",
  };
}

export function itemToForm(item: CatalogItem): ItemFormValues {
  return {
    title: item.title,
    description: item.description,
    story: item.story ?? "",
    provider: item.provider,
    category: item.category,
    price: item.price,
    specs: Object.entries(item.specs ?? {}).map(([label, value]) => ({ label, value })),
    use_case_tags: item.use_case_tags.join(", "),
    source_url: item.source_url ?? "",
  };
}

export function formToPayload(form: ItemFormValues) {
  const specs: Record<string, string> = {};
  for (const row of form.specs) {
    const label = row.label.trim();
    const value = row.value.trim();
    if (label && value) specs[label] = value;
  }
  return {
    title: form.title.trim(),
    description: form.description.trim(),
    story: form.story.trim() || null,
    provider: form.provider.trim(),
    category: form.category.trim(),
    price: form.price.trim(),
    specs,
    use_case_tags: form.use_case_tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean),
    source_url: form.source_url.trim() || null,
  };
}

export interface BulkImportRowResult {
  row: number;
  title: string | null;
  status: string;
  errors: string[];
}

export interface BulkImportResponse {
  inserted: number;
  skipped_duplicate: number;
  invalid: number;
  rows: BulkImportRowResult[];
}
