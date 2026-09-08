from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from legm.config.models import (
    LeagueConfig,
    LeagueInfo,
    Position,
    ProjectionConfig,
    RosterConfig,
    ScoringConfig,
)
from legm.data.models import Base, Player, SeasonStat
from legm.draft.models import PlayerCard
from legm.draft.state import new_draft


@pytest.fixture
def yahoo_scoring() -> ScoringConfig:
    return ScoringConfig(PTS=1, REB=1.2, AST=1.5, STL=3, BLK=3, TOV=-1)


@pytest.fixture
def default_config(yahoo_scoring: ScoringConfig) -> LeagueConfig:
    return LeagueConfig(
        league=LeagueInfo(num_teams=8),
        roster=RosterConfig(
            slots=["PG", "SG", "G", "SF", "PF", "F", "C", "C", "UTIL", "UTIL"],
            bench=3,
            il=1,
            eligibility={
                "G": [Position.PG, Position.SG],
                "F": [Position.SF, Position.PF],
                "UTIL": list(Position),
            },
        ),
        scoring=yahoo_scoring,
        projection=ProjectionConfig(season_weights=[0.65, 0.35], gp_cap=72),
    )


@pytest.fixture
def tiny_config(yahoo_scoring: ScoringConfig) -> LeagueConfig:
    """2 teams, starters PG, C, UTIL. PG-eligible: 2 slots -> 4th best; C: 2 slots -> 4th best;
    SG/SF/PF: 1 slot (UTIL) -> 2nd best; overall: 6th best."""
    return LeagueConfig(
        league=LeagueInfo(num_teams=2),
        roster=RosterConfig(
            slots=["PG", "C", "UTIL"],
            bench=1,
            il=0,
            eligibility={"UTIL": list(Position)},
        ),
        scoring=yahoo_scoring,
        projection=ProjectionConfig(season_weights=[0.65, 0.35], gp_cap=72),
    )


@pytest.fixture
def tiny_pool() -> pd.DataFrame:
    """12 synthetic players with season FP and positions."""
    rows = [
        (1, 1200.0, (Position.PG,)),
        (2, 1100.0, (Position.PG,)),
        (3, 1000.0, (Position.PG, Position.SG)),
        (4, 900.0, (Position.SG,)),
        (5, 850.0, (Position.C,)),
        (6, 800.0, (Position.C,)),
        (7, 750.0, (Position.PF, Position.C)),
        (8, 700.0, (Position.C,)),
        (9, 650.0, (Position.SF,)),
        (10, 600.0, (Position.PG,)),
        (11, 550.0, (Position.PF,)),
        (12, 500.0, (Position.SF, Position.PF)),
    ]
    frame = pd.DataFrame(rows, columns=["PLAYER_ID", "SEASON_FP", "POSITIONS"]).set_index("PLAYER_ID")
    return frame

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        yield s


def _stat(pid, season, gp, mpg, pts, reb, ast, stl, blk, tov):
    return SeasonStat(
        player_id=pid, season=season, gp=gp, mpg=mpg, pts=pts, reb=reb, ast=ast, stl=stl, blk=blk, tov=tov,
        fgm=0, fga=0, ftm=0, fta=0, fg3m=0,
    )


@pytest.fixture
def seeded_session(session):
    """Four players: a PG star, a C, a G-F wing, an F with no recent games."""
    players = [
        Player(nba_id=1, name="Star Guard", normalized_name="star guard", team="AAA", age=27, nba_position="G"),
        Player(nba_id=2, name="Big Center", normalized_name="big center", team="BBB", age=30, nba_position="C"),
        Player(nba_id=3, name="Wing Player Jr.", normalized_name="wing player", team="CCC", age=24, nba_position="G-F"),
        Player(nba_id=4, name="Old Forward", normalized_name="old forward", team="DDD", age=35, nba_position="F"),
    ]
    session.add_all(players)
    session.add_all(
        [
            _stat(1, "2025-26", 70, 34, 28, 5, 8, 1.5, 0.5, 3),
            _stat(1, "2024-25", 65, 33, 26, 5, 7, 1.2, 0.4, 3),
            _stat(2, "2025-26", 75, 30, 20, 12, 3, 0.8, 2.0, 2),
            _stat(3, "2025-26", 60, 28, 15, 4, 3, 1.0, 0.5, 1.5),
            _stat(4, "2024-25", 50, 20, 10, 5, 2, 0.5, 0.5, 1),
        ]
    )
    session.flush()
    return session

# Cycle of position sets that gives a realistic mix (guards heavy, some multi).
_POS_CYCLE = [
    (Position.PG, Position.SG),
    (Position.C,),
    (Position.SF, Position.PF),
    (Position.SG, Position.SF),
    (Position.PG,),
    (Position.PF, Position.C),
    (Position.SG,),
    (Position.SF,),
    (Position.PF,),
    (Position.C, Position.PF),
]


def make_pool(n: int = 130, with_adp: bool = True) -> dict[int, PlayerCard]:
    pool = {}
    for i in range(n):
        pid = 1000 + i
        fpg = 60.0 - i * 0.35
        gp = 70.0
        season_fp = fpg * gp
        pool[pid] = PlayerCard(
            player_id=pid,
            name=f"Player {i:03d}",
            positions=_POS_CYCLE[i % len(_POS_CYCLE)],
            team="T%02d" % (i % 30),
            gp=gp,
            fpg=fpg,
            season_fp=season_fp,
            vorp=season_fp - 1500.0,
            # ADP mostly tracks VORP but with a few deliberate inversions.
            adp=(float(i + 1) if i % 7 else float(i + 4)) if with_adp and i < 100 else None,
        )
    return pool


@pytest.fixture
def pool():
    return make_pool()


@pytest.fixture
def draft(default_config, pool):
    return new_draft(default_config, pool, user_team_index=2, draft_id="test")
