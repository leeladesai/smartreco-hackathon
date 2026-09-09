export interface AdminUser {
  id: number;
  email: string;
  role: string;
  telegram_chat_id: string | null;
  created_at: string;
}

export interface UsersListResponse {
  users: AdminUser[];
  has_more: boolean;
}
