export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_URL = API_URL.replace(/^http/, "ws");
const TOKEN_KEY = "legm_token";

export function getToken(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
export function setToken(token: string | null) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export type User = { id: number; email: string; display_name: string };
export type TokenOut = { access_token: string; token_type: string; user: User };

export type Player = {
  player_id: number;
  name: string;
  positions: string[];
  team: string | null;
  gp: number;
  fpg: number;
  season_fp: number;
  vorp: number;
  adp: number | null;
};

export type AvailablePlayer = Player & {
  pool_vorp: number;
  legal_for_user: boolean;
  fills_open_slot: boolean;
  p_return: number | null;
  injury_status: string | null;
  confidence: number;
};

export type Pick = { pick_number: number; round: number; team_index: number; team_name: string; player: Player; made_at: string };
export type Slot = { slot: string; kind: "start" | "bench" | "il"; player: Player | null };
export type Roster = {
  team_index: number;
  name: string;
  is_user: boolean;
  slots: Slot[];
  open_positions: string[];
  open_bench: number;
  player_count: number;
};
export type Clock = {
  current_pick: number;
  current_round: number | null;
  team_on_the_clock: number | null;
  team_name_on_the_clock: string | null;
  is_user_turn: boolean;
  user_next_pick: number | null;
  picks_before_user: number | null;
  is_complete: boolean;
  total_picks: number;
};
export type Draft = {
  draft_id: string;
  created_at: string;
  config: { num_teams: number; rounds: number; user_team_index: number; team_names: string[]; draft_type: string; slots: string[] };
  clock: Clock;
  picks: Pick[];
  rosters: Roster[];
  replacement_levels: Record<string, number>;
};
export type DraftSummary = {
  draft_id: string;
  created_at: string;
  picks_made: number;
  total_picks: number;
  num_teams: number;
  user_team_index: number;
  is_complete: boolean;
};
export type Available = { players: AvailablePlayer[]; replacement_levels: Record<string, number>; total: number };

export type Components = {
  score: number | null;
  value: number;
  pool_vorp: number;
  vorp: number;
  season_fp: number;
  fpg: number;
  gp: number;
  gp_norm: number;
  fit: number;
  open_positions_filled: string[];
  scarcity: number;
  upside: number;
  adp: number | null;
  adp_value: number;
  injury_status: string | null;
  injury_risk: number;
  confidence: number;
  p_return: number;
};
export type Recommendation = { rank: number; player: Player; score: number; components: Components; reasons: string[] };
export type Recommendations = {
  for_team: number;
  is_user_turn: boolean;
  until_pick: number | null;
  n_sims: number;
  scarcity: Record<string, number>;
  recommendations: Recommendation[];
};
export type Opponent = {
  team_index: number;
  team_name: string;
  pick_number: number;
  open_positions: string[];
  open_bench: number;
  roster: Player[];
  likely_targets: { player: Player; probability: number }[];
};
export type Opponents = { until_pick: number | null; opponents: Opponent[] };
export type ComparePlayer = { player: Player; drafted: boolean; legal_for_user: boolean; components: Components };
export type Compare = { players: ComparePlayer[]; until_pick: number | null };
export type Preferences = {
  risk_tolerance: number;
  rookie_preference: number;
  upside_preference: number;
  injury_aversion: number;
  veteran_preference: number;
  adp_sensitivity: number;
};
export type ChatMessage = { role: "user" | "assistant"; content: string };
export type ChatOut = { reply: string; tool_calls: { name: string; input: Record<string, unknown> }[]; model: string; stop_reason: string | null };
export type LLMStatus = { available: boolean; model: string; tools: string[] };
export type League = {
  name: string;
  num_teams: number;
  max_teams: number;
  draft_type: string;
  format: string;
  slots: string[];
  bench: number;
  il: number;
  scoring: Record<string, number>;
};
export type ImportReport = { applied: number; skipped: { pick_number: number; player_name: string; reason: string }[]; draft: Draft };

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export const AUTH_EVENT = "legm:unauthorized";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    if (res.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event(AUTH_EVENT));
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  // auth
  register: (body: { email: string; password: string; display_name: string; invite_code?: string }) =>
    request<TokenOut>("/api/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (body: { email: string; password: string }) => request<TokenOut>("/api/auth/login", { method: "POST", body: JSON.stringify(body) }),
  me: () => request<User>("/api/auth/me"),
  authConfig: () => request<{ invite_required: boolean }>("/api/auth/config"),
  // data
  league: () => request<League>("/api/league"),
  players: (params: { top?: number; q?: string; position?: string; include_inactive?: boolean } = {}) =>
    request<Player[]>(`/api/players${qs(params)}`),
  // drafts
  drafts: () => request<DraftSummary[]>("/api/drafts"),
  createDraft: (body: { name: string; user_slot: number; num_teams?: number; team_names?: string[] | null }) =>
    request<Draft>("/api/drafts", { method: "POST", body: JSON.stringify(body) }),
  draft: (id: string) => request<Draft>(`/api/drafts/${id}`),
  deleteDraft: (id: string) => request<void>(`/api/drafts/${id}`, { method: "DELETE" }),
  available: (id: string, params: { q?: string; position?: string; limit?: number; offset?: number } = {}) =>
    request<Available>(`/api/drafts/${id}/available${qs(params)}`),
  recommendations: (id: string, top = 3) => request<Recommendations>(`/api/drafts/${id}/recommendations${qs({ top })}`),
  opponents: (id: string) => request<Opponents>(`/api/drafts/${id}/opponents`),
  compare: (id: string, ids: number[]) => request<Compare>(`/api/drafts/${id}/compare${qs({ ids: ids.join(",") })}`),
  feedback: (id: string, player_id: number, vote: 1 | -1) =>
    request<Preferences>(`/api/drafts/${id}/feedback`, { method: "POST", body: JSON.stringify({ player_id, vote }) }),
  preferences: () => request<Preferences>("/api/preferences"),
  pick: (id: string, player_id: number) => request<Draft>(`/api/drafts/${id}/picks`, { method: "POST", body: JSON.stringify({ player_id }) }),
  undo: (id: string) => request<Draft>(`/api/drafts/${id}/undo`, { method: "POST" }),
  simulate: (id: string, body: { strategy?: string; jitter?: number; seed?: number | null; until_user?: boolean }) =>
    request<Draft>(`/api/drafts/${id}/simulate`, { method: "POST", body: JSON.stringify(body) }),
  importPicks: (id: string, format: "csv" | "json", content: string) =>
    request<ImportReport>(`/api/drafts/${id}/import-picks`, { method: "POST", body: JSON.stringify({ format, content }) }),
  // assistant
  llmStatus: () => request<LLMStatus>("/api/llm/status"),
  chat: (id: string, messages: ChatMessage[]) => request<ChatOut>(`/api/drafts/${id}/chat`, { method: "POST", body: JSON.stringify({ messages }) }),
};

export const fmt = {
  n0: (v: number | null | undefined) => (v == null ? "" : Math.round(v).toLocaleString()),
  n1: (v: number | null | undefined) => (v == null ? "" : v.toFixed(1)),
  pct: (v: number | null | undefined) => (v == null ? "" : `${Math.round(v * 100)}%`),
  pos: (p: string[]) => p.join("/") || "UTIL",
  lastName: (name: string) => name.split(" ").slice(1).join(" ") || name,
};
