"""Every modelling assumption in one place.

Change a number here, re-run `make all`, and every table and chart follows.
"""
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"
DB_PATH = WORK / "darkstore.duckdb"
RESULTS = ROOT / "results"
IMG = ROOT / "docs" / "img"
CONFIG_DIR = ROOT / "config"
SQL_DIR = ROOT / "sql"

SEED = 42


@dataclass(frozen=True)
class Layout:
    """A single-floor dark store with parallel pick aisles.

    Racks run front-to-back. Each pick aisle has a rack on both sides. A cross
    aisle runs along the front (where the pack station is) and along the back.
    All lengths are metres.
    """
    n_aisles: int = 10            # pick aisles
    bays_per_side: int = 15       # bays along one rack face
    bay_width: float = 1.0        # width of one bay along the aisle
    levels: int = 6               # shelf levels per bay (1 = floor)
    slots_per_bay_level: int = 2  # SKUs side by side on one shelf of one bay
    aisle_width: float = 1.0      # clear walking width of a pick aisle
    rack_depth: float = 0.5       # depth of one rack face
    cross_aisle_width: float = 1.5
    golden_levels: tuple = (2, 3, 4)  # waist-to-shoulder height: fastest to pick

    @property
    def aisle_pitch(self) -> float:
        # centre of one aisle to centre of the next: aisle + one rack each side
        return self.aisle_width + 2 * self.rack_depth

    @property
    def aisle_length(self) -> float:
        return self.bays_per_side * self.bay_width

    @property
    def depth(self) -> float:
        """Distance from the front cross-aisle centreline to the back one."""
        return self.aisle_length + self.cross_aisle_width

    @property
    def width(self) -> float:
        return self.n_aisles * self.aisle_pitch

    @property
    def depot_x(self) -> float:
        """Pack station sits on the front cross aisle, centred."""
        return self.width / 2

    @property
    def n_slots(self) -> int:
        return self.n_aisles * 2 * self.bays_per_side * self.levels * self.slots_per_bay_level

    @property
    def floor_area_m2(self) -> float:
        return self.width * (self.aisle_length + 2 * self.cross_aisle_width)


@dataclass(frozen=True)
class PickTimes:
    """Standard times for one picker with a trolley and totes (seconds)."""
    walk_speed_mps: float = 1.0       # walking with a trolley, incl. turns
    order_setup_s: float = 20.0       # read pick list on handheld, take totes
    line_pick_golden_s: float = 7.0   # locate, scan, pick one line at waist height
    line_pick_other_s: float = 11.0   # same, but bending to floor level or reaching top
    order_dropoff_s: float = 15.0     # drop totes at pack station, close task


@dataclass(frozen=True)
class Store:
    orders_per_day: int = 2000        # typical mid-size Indian dark store
    assortment_max_skus: int = 3000   # SKUs the store carries (<= layout slots)
    units_per_line: int = 1           # Instacart has no quantities; assume 1 unit


@dataclass(frozen=True)
class Replenishment:
    history_days: int = 56            # demand history used to set parameters
    sim_days: int = 91                # ~3 months of simulated operation
    lead_time_days: int = 1           # DC order placed end of day t lands end of day t+1
    review_period_days: int = 1       # stock reviewed once a day
    max_cover_days: float = 2.0       # max = min + this many days of mean demand
    service_levels: tuple = (0.80, 0.85, 0.90, 0.95, 0.97, 0.99, 0.995)
    naive_min_units: tuple = (2, 3, 4, 6, 8, 12, 20)  # same min for every SKU; max = 2 x min
    cover_min_days: tuple = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0)  # min = days of mean demand, no safety stock
    chosen_service_level: float = 0.95  # policy used for the KPI log


@dataclass(frozen=True)
class Capacity:
    wait_target_min: float = 2.0      # an order should start picking within this
    wait_target_share: float = 0.90   # ...for at least this share of orders
    max_pickers_on_floor: int = 16    # beyond this, 10 aisles congest (~1.5 pickers per aisle)
    pack_stations: int = 6
    pack_time_s: float = 60.0         # bag, seal, label, hand to rider
    des_days: int = 28                # four simulated weeks per SimPy check
    des_rounds: int = 4               # rounds of "add a picker where the SimPy check fails"


@dataclass(frozen=True)
class Slotting:
    eval_orders: int = 5000           # held-out orders used to compare layouts
    affinity_orders: int = 400_000    # orders sampled to count co-picks
    bootstrap: int = 2000


@dataclass(frozen=True)
class Config:
    layout: Layout = field(default_factory=Layout)
    pick: PickTimes = field(default_factory=PickTimes)
    store: Store = field(default_factory=Store)
    repl: Replenishment = field(default_factory=Replenishment)
    cap: Capacity = field(default_factory=Capacity)
    slot: Slotting = field(default_factory=Slotting)


CFG = Config()
