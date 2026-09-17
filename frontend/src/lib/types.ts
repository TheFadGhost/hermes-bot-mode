export type Theme = "system" | "light" | "dark";

export type MotionPreference = "system" | "on" | "off";

export type View = "chat" | "memory" | "files" | "activity" | "settings";

export type InfoTab = "overview" | "memory" | "files" | "activity" | "computer";

export type AvatarShape = "blob" | "orb" | "capsule" | "lozenge" | "peak" | "hex" | "cloud" | "drop";

export interface User {
  id: string;
  name?: string;
  username?: string;
  avatar_url?: string | null;
}

export interface Session {
  authenticated: boolean;
  user?: User;
  expires_at?: string | null;
}

export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  avatar_url?: string | null;
  avatar?: AvatarShape | string | null;
  color?: string | null;
  emoji?: string | null;
  model?: string | null;
  is_active?: boolean;
  memory_scope?: "private" | "shared" | "both" | string;
  created_at?: string;
  updated_at?: string;
}

export interface Conversation {
  id: string;
  agent_id: string;
  title?: string | null;
  updated_at?: string;
  created_at?: string;
  message_count?: number;
  kind?: "direct" | "group" | "delegated" | string;
  name?: string | null;
  members?: InboxMember[];
  coordinator_id?: string | null;
  pinned?: boolean;
  archived?: boolean;
}

export interface InboxMember {
  agent_id: string;
  name: string;
  role?: "member" | "coordinator" | string;
  avatar?: AvatarShape | string | null;
  avatar_url?: string | null;
  color?: string | null;
}

export interface InboxTask {
  id: string;
  agent_id?: string | null;
  conversation_id?: string | null;
  origin_conversation_id?: string | null;
  parent_task_id?: string | null;
  request_id?: string | null;
  status?: string;
  phase?: string | null;
  error_message?: string | null;
}

export interface InboxEntry {
  conversation_id: string;
  kind: "direct" | "group" | "delegated" | string;
  agent_id?: string | null;
  name: string;
  members: InboxMember[];
  preview?: string | null;
  updated_at?: string | null;
  unread_count?: number;
  pinned?: boolean;
  archived?: boolean;
  active_tasks?: InboxTask[];
  coordinator_id?: string | null;
}

export type MessageRole = "user" | "assistant" | "system" | "tool";

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  created_at?: string;
  status?: "pending" | "streaming" | "complete" | "error" | string;
  metadata?: Record<string, unknown>;
  author_agent_id?: string | null;
  source_task_id?: string | null;
  request_id?: string | null;
  origin_conversation_id?: string | null;
  reply_to_id?: string | null;
}

export interface MemoryItem {
  id: string;
  content: string;
  scope: "shared" | "private" | string;
  agent_id?: string | null;
  tags?: string[];
  created_at?: string;
  updated_at?: string;
}

export interface LearnedSkill {
  id: string;
  name: string;
  trigger?: string | null;
  instructions?: string | null;
  evidence?: string | null;
  revision?: number | null;
  enabled?: boolean;
  source_task_id?: string | null;
  updated_at?: string;
}

export interface FileAsset {
  id: string;
  name: string;
  content_type?: string | null;
  size?: number | null;
  url?: string | null;
  created_at?: string;
  status?: string;
}

export interface ActivityItem {
  id: string;
  kind?: string;
  title: string;
  detail?: string | null;
  status?: "running" | "complete" | "failed" | "waiting" | string;
  created_at?: string;
  agent_id?: string | null;
  conversation_id?: string | null;
}

export interface RuntimeStatus {
  available: boolean;
  provider?: string;
  model?: string | null;
  reason?: string | null;
}

export interface RuntimeModel {
  id: string;
  name: string;
  efforts?: string[];
}

export interface RuntimeAccount {
  connected: boolean;
  type?: string | null;
  plan?: string | null;
  models?: RuntimeModel[];
}

export interface RuntimeLogin {
  verificationUrl: string;
  userCode: string;
  loginId: string;
}

export interface RuntimeUsage {
  used?: number | null;
  limit?: number | null;
  remaining?: number | null;
  reset_at?: string | null;
  windows?: RuntimeUsageWindow[];
  [key: string]: unknown;
}

export interface RuntimeUsageWindow {
  id?: string;
  used_percent?: number | null;
  remaining_percent?: number | null;
  window_duration_mins?: number | null;
  reset_at?: string | null;
}

export interface ExtensionsStatus {
  connections: { configured: boolean };
  voice: { configured: boolean; model?: string; max_bytes?: number; max_seconds?: number };
  private_input: { available: boolean };
  telegram: { configured: boolean };
}

export interface ConnectionCatalogItem {
  slug: string;
  name: string;
  description?: string;
  connected: boolean;
}

export interface ConnectionAccount {
  id: string;
  toolkit: string;
  name: string;
  status: string;
}

export interface ConnectionsResponse {
  configured: boolean;
  catalog: ConnectionCatalogItem[];
  accounts: ConnectionAccount[];
  next_cursor?: string | null;
}

export type ChatRequestKind = "private_input" | "connection" | "connector_action" | string;
export type ChatRequestStatus = "pending" | "ready" | "executing" | "completed" | "denied" | "expired" | "failed" | "uncertain" | string;

export interface ChatRequest {
  id: string;
  agent_id: string;
  conversation_id: string;
  kind: ChatRequestKind;
  title: string;
  purpose?: string | null;
  status: ChatRequestStatus;
  created_at?: string | number | null;
  expires_at?: string | number | null;
  data: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string | null;
}

export interface PrivateField {
  id: string;
  label: string;
  purpose: string;
  expires_at?: string | number | null;
  one_time: boolean;
}

export interface Teaching {
  id: string;
  agent_id: string;
  name: string;
  trigger: string;
  steps: string[];
  notes?: string | null;
  frame_file_ids?: string[];
  status: "unverified" | "verified" | string;
  revision?: number;
  enabled: boolean;
  created_at?: string | number | null;
  updated_at?: string | number | null;
  last_task_id?: string | null;
}

export interface DesktopStatus {
  available: boolean;
  created?: boolean;
  running?: boolean;
  view_url?: string | null;
  reason?: string | null;
  phase?: "unavailable" | "starting" | "running" | "paused" | "failed" | string;
  control_mode?: "manual" | "bot" | string;
  generation?: number | string | null;
  visible?: boolean;
}

export interface Routine {
  id: string;
  name: string;
  instruction: string;
  time: string;
  timezone: string;
  weekdays: number[];
  enabled: boolean;
  next_due?: string | null;
  last_run_at?: string | null;
}

export interface TaskEnvelope {
  id: string;
  agent_id?: string | null;
  conversation_id: string;
  origin_conversation_id?: string | null;
  parent_task_id?: string | null;
  request_id?: string | null;
  status?: string;
  phase?: string | null;
  error_message?: string | null;
}

export interface OnboardingState {
  complete: boolean;
  steps?: Array<{ id: string; title: string; description: string }>;
}

export interface Approval {
  approval_id: string;
  kind: string;
  description: string;
  status?: "pending" | "approved" | "denied" | string;
  data?: Record<string, unknown>;
}

export interface AgentInput {
  name: string;
  description?: string;
  avatar?: AvatarShape;
  color?: string;
  model?: string;
  memory_scope?: "private" | "shared" | "both";
}

export interface MemoryInput {
  content: string;
  scope: "shared" | "private";
  agent_id?: string;
  tags?: string[];
}

export interface StreamEvent {
  type: string;
  data: Record<string, unknown> | string | null;
}

