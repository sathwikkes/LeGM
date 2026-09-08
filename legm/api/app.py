"""FastAPI application. Run with `legm serve` or `uvicorn legm.api.app:app --reload`.

No `from __future__ import annotations` here: FastAPI must see the real
Annotated[..., Depends(...)] objects, which are closure-local.
"""

import os
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from legm.api.auth import (
    AuthError,
    AuthSettings,
    LoginIn,
    RegisterIn,
    TokenOut,
    UserOut,
    authenticate,
    create_token,
    decode_token,
    register_user,
    user_out,
)
from legm.agent.chat import DEFAULT_MODEL, LLMUnavailable, llm_available, run_chat
from legm.agent.tools import TOOL_FUNCTIONS, ToolContext
from legm.api.feedback import get_preferences, record_feedback, to_preferences
from legm.api.recommend import SurvivalCache, compare_out, opponents_out, recommend, survival_out
from legm.api.schemas import (
    AvailableOut,
    ChatIn,
    ChatOut,
    CompareOut,
    ImportPicksIn,
    ImportReportOut,
    LLMStatusOut,
    CreateDraftIn,
    DraftOut,
    DraftSummaryOut,
    FeedbackIn,
    LeagueOut,
    OpponentsOut,
    PickIn,
    PlayerOut,
    PreferencesIn,
    PreferencesOut,
    RecommendationsOut,
    SimulateIn,
    SurvivalOut,
)
from legm.api.store import DraftExists, DraftNotFound, DraftStore
from legm.api.views import available_out, draft_out, league_out, player_out_from_row, summary_out
from legm.api.ws import DraftHub
from legm.config import load_league_config
from legm.config.models import LeagueConfig
from legm.data.db import init_db, make_engine, session_scope
from legm.draft.models import DraftState
from legm.data.models import User, UserPreference
from legm.draft.pool import load_pool, pool_shortfall
from legm.draft.simulate import simulate
from legm.draft.state import DraftError, make_pick, new_draft, undo
from legm.draft.strategies import make_strategy
from legm.engine.rankings import rank_players
from legm.integrations import apply_external_picks, parse_picks_text


class Settings:
    def __init__(
        self,
        config_path: str | os.PathLike[str] | None = None,
        database_url: str | None = None,
        cors_origins: list[str] | None = None,
        auth: AuthSettings | None = None,
        cors_origin_regex: str | None = None,
    ):
        self.config_path = config_path
        self.database_url = database_url
        self.auth = auth or AuthSettings()
        raw = cors_origins or os.environ.get("LEGM_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        # Browsers send the Origin header without a path, so a trailing slash would never match.
        self.cors_origins = [o.strip().rstrip("/") for o in raw if o.strip()]
        # Optional pattern, e.g. https://.*\.vercel\.app to allow every preview deployment.
        self.cors_origin_regex = cors_origin_regex or os.environ.get("LEGM_CORS_ORIGIN_REGEX") or None


def create_app(settings: Settings | None = None, llm_client=None) -> FastAPI:
    """llm_client: optional Anthropic-compatible client (tests inject a stub)."""
    settings = settings or Settings()
    app = FastAPI(title="LeGM API", version="0.5.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    league: LeagueConfig = load_league_config(settings.config_path)
    engine: Engine = make_engine(settings.database_url)
    init_db(engine)
    store = DraftStore(engine)
    hub = DraftHub()
    survival_cache = SurvivalCache()
    auth = settings.auth
    app.state.league = league
    app.state.engine = engine
    app.state.store = store
    app.state.hub = hub

    # ---- auth ---------------------------------------------------------------

    def load_user(user_id: int) -> User:
        with session_scope(engine) as s:
            user = s.get(User, user_id)
            if user is None or not user.is_active:
                raise AuthError(401, "account not found")
            return user

    def current_user(request: Request) -> User:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="not authenticated", headers={"WWW-Authenticate": "Bearer"})
        try:
            return load_user(decode_token(header[7:].strip(), auth))
        except AuthError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail, headers={"WWW-Authenticate": "Bearer"}) from exc

    UserDep = Annotated[User, Depends(current_user)]

    @app.post("/api/auth/register", response_model=TokenOut, status_code=201)
    def register(body: RegisterIn) -> TokenOut:
        try:
            with session_scope(engine) as s:
                user = register_user(s, body, auth)
                token = create_token(user, auth)
                return TokenOut(access_token=token, user=user_out(user))
        except AuthError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    @app.post("/api/auth/login", response_model=TokenOut)
    def login(body: LoginIn) -> TokenOut:
        try:
            with session_scope(engine) as s:
                user = authenticate(s, body.email, body.password)
                return TokenOut(access_token=create_token(user, auth), user=user_out(user))
        except AuthError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    @app.get("/api/auth/me", response_model=UserOut)
    def me(user: UserDep) -> UserOut:
        return user_out(user)

    @app.get("/api/auth/config")
    def auth_config() -> dict:
        return {"invite_required": auth.invite_code is not None}

    def prefs_for(user: User):
        with session_scope(engine) as s:
            return to_preferences(get_preferences(s, user.id))

    # ---- draft access helpers ---------------------------------------------------

    def hub_key(user: User, draft_id: str) -> str:
        return f"{user.id}:{draft_id}"

    def get_state(draft_id: str, user: UserDep) -> DraftState:
        try:
            return store.get(user.id, draft_id)
        except DraftNotFound:
            raise HTTPException(status_code=404, detail=f"draft {draft_id!r} not found") from None

    StateDep = Annotated[DraftState, Depends(get_state)]

    async def mutate(user: User, draft_id: str, fn) -> DraftOut:
        get_state(draft_id, user)
        try:
            state = await run_in_threadpool(store.update, user.id, draft_id, fn)
        except DraftError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        out = draft_out(state)
        await hub.broadcast(hub_key(user, draft_id), {"type": "draft", "draft": out.model_dump(mode="json")})
        return out

    # ---- meta ---------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {"name": "LeGM API", "version": app.version, "health": "/api/health", "docs": "/docs"}

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/league", response_model=LeagueOut)
    def get_league() -> LeagueOut:
        return league_out(league)

    # ---- players ------------------------------------------------------------

    @app.get("/api/players", response_model=list[PlayerOut])
    def list_players(
        top: Annotated[int, Query(ge=1, le=1000)] = 200,
        q: str | None = None,
        position: str | None = None,
        include_inactive: bool = False,
    ) -> list[PlayerOut]:
        from legm.data.names import normalize_name

        with session_scope(engine) as session:
            ranked = rank_players(session, league, include_inactive=include_inactive)
        if q:
            nq = normalize_name(q)
            ranked = ranked[ranked["NAME"].map(lambda n: nq in normalize_name(n))]
        if position:
            pos = position.upper()
            ranked = ranked[ranked["POSITIONS"].map(lambda s: pos in s.split(","))]
        return [player_out_from_row(int(pid), r) for pid, r in ranked.head(top).iterrows()]

    @app.get("/api/players/{player_id}", response_model=PlayerOut)
    def get_player(player_id: int) -> PlayerOut:
        with session_scope(engine) as session:
            ranked = rank_players(session, league, include_inactive=True)
        if player_id not in ranked.index:
            raise HTTPException(status_code=404, detail="player not found")
        return player_out_from_row(player_id, ranked.loc[player_id])

    # ---- drafts -------------------------------------------------------------

    @app.get("/api/drafts", response_model=list[DraftSummaryOut])
    def list_drafts_(user: UserDep) -> list[DraftSummaryOut]:
        return [summary_out(store.get(user.id, d)) for d, _ in store.ids(user.id)]

    @app.post("/api/drafts", response_model=DraftOut, status_code=201)
    async def create_draft(body: CreateDraftIn, user: UserDep) -> DraftOut:

        def build() -> DraftState:
            with session_scope(engine) as session:
                pool = load_pool(session, league, include_inactive=body.include_inactive)
            if not pool:
                raise ValueError("player pool is empty; run `legm ingest` first")
            # Only validate an explicit override: raising the team count is the new
            # way to outgrow the pool. Config-sized drafts keep their old behaviour.
            if body.num_teams is not None and (short := pool_shortfall(pool, league, body.num_teams)):
                raise ValueError(f"{short}; run `legm ingest` or lower the team count")
            return new_draft(
                league,
                pool,
                user_team_index=body.user_slot - 1,
                team_names=body.team_names,
                draft_id=body.name,
                num_teams=body.num_teams,
            )

        try:
            state = await run_in_threadpool(build)
            store.create(user.id, state)
        except DraftExists:
            raise HTTPException(status_code=409, detail=f"draft {body.name!r} already exists") from None
        except (DraftError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return draft_out(state)

    @app.get("/api/drafts/{draft_id}", response_model=DraftOut)
    def get_draft(state: StateDep) -> DraftOut:
        return draft_out(state)

    @app.delete("/api/drafts/{draft_id}", status_code=204)
    def delete_draft(draft_id: str, user: UserDep) -> None:
        try:
            store.delete(user.id, draft_id)
        except DraftNotFound:
            raise HTTPException(status_code=404, detail="draft not found") from None

    @app.get("/api/drafts/{draft_id}/available", response_model=AvailableOut)
    def get_available(
        state: StateDep,
        user: UserDep,
        q: str | None = None,
        position: str | None = None,
        team: int | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AvailableOut:
        _, surv = survival_cache.get_or_compute(user.id, state, state.league)
        return available_out(
            state, team_index=team, query=q, position=position, limit=limit, offset=offset, p_return=surv.probabilities
        )

    @app.get("/api/drafts/{draft_id}/recommendations", response_model=RecommendationsOut)
    async def get_recommendations(
        state: StateDep, user: UserDep, top: Annotated[int, Query(ge=1, le=20)] = 3, team: int | None = None
    ) -> RecommendationsOut:
        return await run_in_threadpool(recommend, state, state.league, survival_cache, user.id, prefs_for(user), team, top)

    @app.get("/api/drafts/{draft_id}/survival", response_model=SurvivalOut)
    async def get_survival(state: StateDep, user: UserDep) -> SurvivalOut:
        return await run_in_threadpool(survival_out, state, state.league, survival_cache, user.id)

    @app.get("/api/drafts/{draft_id}/opponents", response_model=OpponentsOut)
    async def get_opponents(state: StateDep, user: UserDep, top: Annotated[int, Query(ge=1, le=10)] = 4) -> OpponentsOut:
        return await run_in_threadpool(opponents_out, state, state.league, survival_cache, user.id, top)

    @app.get("/api/drafts/{draft_id}/compare", response_model=CompareOut)
    async def get_compare(state: StateDep, user: UserDep, ids: str) -> CompareOut:
        try:
            player_ids = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=422, detail="ids must be comma-separated integers") from None
        if not 2 <= len(player_ids) <= 5:
            raise HTTPException(status_code=422, detail="compare 2 to 5 players")
        return await run_in_threadpool(compare_out, state, state.league, survival_cache, user.id, player_ids, prefs_for(user))

    @app.post("/api/drafts/{draft_id}/feedback", response_model=PreferencesOut)
    async def post_feedback(state: StateDep, user: UserDep, body: FeedbackIn, draft_id: str) -> PreferencesOut:
        if body.player_id not in state.pool:
            raise HTTPException(status_code=404, detail="player not in this draft's pool")
        if body.vote == 0:
            raise HTTPException(status_code=422, detail="vote must be +1 or -1")
        comp = await run_in_threadpool(compare_out, state, state.league, survival_cache, user.id, [body.player_id, body.player_id], prefs_for(user))
        components = comp.players[0].components
        card = state.pool[body.player_id]
        with session_scope(engine) as s:
            pref = record_feedback(s, user.id, draft_id, body.player_id, body.vote, components, card.age)
            return PreferencesOut(**pref.as_dict())

    @app.get("/api/preferences", response_model=PreferencesOut)
    def get_prefs(user: UserDep) -> PreferencesOut:
        with session_scope(engine) as s:
            return PreferencesOut(**get_preferences(s, user.id).as_dict())

    @app.put("/api/preferences", response_model=PreferencesOut)
    def put_prefs(user: UserDep, body: PreferencesIn) -> PreferencesOut:
        with session_scope(engine) as s:
            pref = get_preferences(s, user.id)
            for f in UserPreference.FIELDS:
                setattr(pref, f, max(-1.0, min(1.0, float(getattr(body, f)))))
            s.flush()
            return PreferencesOut(**pref.as_dict())

    @app.post("/api/drafts/{draft_id}/picks", response_model=DraftOut)
    async def post_pick(draft_id: str, body: PickIn, user: UserDep) -> DraftOut:
        return await mutate(user, draft_id, lambda s: make_pick(s, body.player_id))

    @app.post("/api/drafts/{draft_id}/undo", response_model=DraftOut)
    async def post_undo(draft_id: str, user: UserDep) -> DraftOut:
        return await mutate(user, draft_id, undo)

    @app.post("/api/drafts/{draft_id}/simulate", response_model=DraftOut)
    async def post_simulate(draft_id: str, body: SimulateIn, user: UserDep) -> DraftOut:
        strategy = make_strategy(body.strategy, body.jitter)  # ValueError -> 422 below
        return await mutate(
            user,
            draft_id,
            lambda s: simulate(s, default=strategy, seed=body.seed, stop_before_user=body.until_user),
        )

    # ---- LLM assistant (Phase 7) ---------------------------------------------------

    @app.get("/api/llm/status", response_model=LLMStatusOut)
    def llm_status() -> LLMStatusOut:
        return LLMStatusOut(
            available=llm_client is not None or llm_available(),
            model=os.environ.get("LEGM_LLM_MODEL", DEFAULT_MODEL),
            tools=sorted(TOOL_FUNCTIONS),
        )

    @app.post("/api/drafts/{draft_id}/chat", response_model=ChatOut)
    async def post_chat(state: StateDep, user: UserDep, body: ChatIn) -> ChatOut:
        ctx = ToolContext(state=state, league=state.league, cache=survival_cache, owner_id=user.id, prefs=prefs_for(user))
        try:
            result = await run_in_threadpool(run_chat, ctx, [m.model_dump() for m in body.messages], llm_client)
        except LLMUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ChatOut(reply=result.reply, tool_calls=result.tool_calls, model=result.model, stop_reason=result.stop_reason, usage=result.usage)

    # ---- external pick import (Phase 8) ---------------------------------------------

    @app.post("/api/drafts/{draft_id}/import-picks", response_model=ImportReportOut)
    async def import_picks(draft_id: str, user: UserDep, body: ImportPicksIn) -> ImportReportOut:
        get_state(draft_id, user)
        try:
            picks = parse_picks_text(body.content, body.format)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=f"could not parse picks: {exc}") from exc
        reports: list = []

        def apply(s: DraftState) -> DraftState:
            new_state, report = apply_external_picks(s, picks)
            reports.append(report)
            return new_state

        out = await mutate(user, draft_id, apply)
        report = reports[0]
        return ImportReportOut(
            applied=report.applied_count,
            skipped=[{"pick_number": p.pick_number, "player_name": p.player_name, "reason": r} for p, r in report.skipped],
            draft=out,
        )

    # ---- websocket ----------------------------------------------------------

    @app.websocket("/ws/drafts/{draft_id}")
    async def draft_socket(ws: WebSocket, draft_id: str, token: str = "") -> None:
        try:
            user = load_user(decode_token(token, auth))
            state = store.get(user.id, draft_id)
        except AuthError:
            await ws.close(code=4401)
            return
        except DraftNotFound:
            await ws.close(code=4404)
            return
        key = hub_key(user, draft_id)
        await hub.connect(key, ws)
        try:
            await ws.send_json({"type": "draft", "draft": draft_out(state).model_dump(mode="json")})
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            await hub.disconnect(key, ws)

    @app.exception_handler(ValueError)
    async def value_error_handler(_, exc: ValueError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=422, content={"detail": str(exc)})

    return app


app = create_app()
