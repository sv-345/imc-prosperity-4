use anyhow::{Context, Result, bail};
use csv::{ReaderBuilder, WriterBuilder};
use rand::distributions::{Distribution, WeightedIndex};
use rand::{Rng, SeedableRng};
use rand_chacha::ChaCha8Rng;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};

// Round 0 (tutorial) days + products.
const ROUND0_DAYS: [i32; 2] = [-2, -1];
const ROUND0_PRODUCTS: [&str; 2] = ["EMERALDS", "TOMATOES"];

// Round 2 days + products. Calibrated from data/round2/*.csv
// (see scripts/round2_calibration/calibrate_round2.py and docs/round2_model.md).
const ROUND2_DAYS: [i32; 3] = [-1, 0, 1];
const ROUND2_PRODUCTS: [&str; 2] = ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"];

// Round 3 days + products. Calibrated from data/round3/*.csv
// (see scripts/round3_calibration/calibrate_round3.py and docs/round3_params.json).
// Day-TTE mapping per IMC wiki: day {0, 1, 2} = TTE {8, 7, 6}/365. Live R3
// starts at TTE = 5/365. 12 products: 2 delta-1 + 10 VEV call vouchers on
// VELVETFRUIT_EXTRACT with strikes {4000, 4500, 5000, 5100, 5200, 5300,
// 5400, 5500, 6000, 6500}.
const ROUND3_DAYS: [i32; 3] = [0, 1, 2];
const ROUND3_PRODUCTS: [&str; 12] = [
    "HYDROGEL_PACK",
    "VELVETFRUIT_EXTRACT",
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
    "VEV_6000",
    "VEV_6500",
];
// R3 voucher strikes in the same order as VEV_* products above.
const VEV_STRIKES: [i32; 10] = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500];
const VEV_ACTIVE_STRIKES: [i32; 6] = [5000, 5100, 5200, 5300, 5400, 5500];
const VEV_PINNED_STRIKES: [i32; 2] = [6000, 6500];

// R3 live-simulation TTE (days). IMC states R3 starts at TTE = 5 days.
const R3_LIVE_TTE_YEARS: f64 = 5.0 / 365.0;

// R3 per-strike bot IV (single sigma per strike, annualized). Source:
// docs/round3_params.json -> VEV.iv_by_strike.by_strike.*.iv_mean. VEV_5400
// is a calibrated kink (lower than neighbors) and is itself a trader
// exploit target, NOT a fit artifact.
const VEV_IV_5000: f64 = 0.2344;
const VEV_IV_5100: f64 = 0.2318;
const VEV_IV_5200: f64 = 0.2343;
const VEV_IV_5300: f64 = 0.2368;
const VEV_IV_5400: f64 = 0.2221; // intentional kink per bot calibration
const VEV_IV_5500: f64 = 0.2409;
// Deep-ITM vouchers: the bot isn't using BSM for these, it's quoting
// near-intrinsic plus a fixed offset. We approximate with a high IV that
// reproduces the observed spread dynamics for sim purposes. Not used for
// trader-side pricing (trader uses intrinsic + buffer).
const VEV_IV_4000: f64 = 0.24; // placeholder — deep ITM, noise-dominated
const VEV_IV_4500: f64 = 0.24; // placeholder — deep ITM, noise-dominated
// Pinned wings have no IV in the sim — books are fixed.

// R3 HYDROGEL_PACK FV params (docs/round3_params.json -> HYDROGEL.fv).
// Observed within-day mid std ≈ 32, tick-to-tick innovation sigma ≈ 2.17.
// Model as AR(1) on levels with phi chosen so equilibrium std matches
// observed: phi = sqrt(1 - (sigma_eps / std_equilibrium)^2).
// The observed diff-ACF1 of -0.13 is a microstructure artifact (bid-ask
// bounce from bot3 presence toggles), NOT an AR(1) signature — a pure
// random walk has diff-ACF1 ≈ 0, which would give std_equilibrium → ∞.
// Using level-phi reproduces level dynamics; bot3 bounce is separately
// simulated in make_hydrogel_book.
const HYDROGEL_FAIR_VALUE: f64 = 9991.0;
const HYDROGEL_INNOV_SIGMA: f64 = 2.17;
const HYDROGEL_EQUIL_STD: f64 = 32.0;

// R3 VELVETFRUIT_EXTRACT FV params.
const VELVET_FAIR_VALUE: f64 = 5250.0;
const VELVET_INNOV_SIGMA: f64 = 1.13;
const VELVET_EQUIL_STD: f64 = 15.6;

// R3 taker arrival rates (per-tick Bernoulli). Source:
// docs/round3_params.json -> {HYDROGEL,VELVET,VEV}.taker.taker_rate_per_tick.
const HYDROGEL_TRADE_ACTIVE_PROB: f64 = 0.0337;
const VELVET_TRADE_ACTIVE_PROB: f64 = 0.0454;
const VELVET_SECOND_TRADE_PROB: f64 = 0.0066;
const HYDROGEL_TRADE_BUY_PROB: f64 = 0.519;
const VELVET_TRADE_BUY_PROB: f64 = 0.569;
// Per-VEV active strike taker rates (approximate; calibrated per-strike from
// R3 trades, see round3_params.json -> VEV.taker_by_strike.*.taker_rate_per_tick).
// Most active strikes 5000-5500 have taker rates ~0.01-0.03; pinned strikes
// have essentially zero taker flow.
const VEV_TRADE_ACTIVE_PROB_ACTIVE: f64 = 0.012;
const VEV_TRADE_ACTIVE_PROB_PINNED: f64 = 0.0;
const VEV_TRADE_BUY_PROB: f64 = 0.50;

// Aliases kept for backward compatibility with code paths that still hard-code
// the round-0 product set (e.g. the strategy runner). The data-generation path
// uses `days_for_round` / `products_for_round` below.
const DAYS: [i32; 2] = ROUND0_DAYS;
const PRODUCTS: [&str; 2] = ROUND0_PRODUCTS;

const DEFAULT_TICKS_PER_DAY: usize = 10_000;
const TIMESTAMP_STEP: i32 = 100;
const TOMATO_HALF_TIE_FLIP_PROB: f64 = 0.0005;
const POSITION_LIMIT: i32 = 80; // Default for R0/R2 delta-1 products. R3 uses per-product limits (see position_limit_for).

/// Per-product position limit. For R3, HYDROGEL_PACK / VELVETFRUIT_EXTRACT
/// have limit 200 and all VEV_* vouchers have 300 (per IMC wiki).
/// For other products (R0/R2), falls back to POSITION_LIMIT = 80.
fn position_limit_for(product: &str) -> i32 {
    match product {
        "HYDROGEL_PACK" | "VELVETFRUIT_EXTRACT" => 200,
        p if p.starts_with("VEV_") => 300,
        _ => POSITION_LIMIT,
    }
}
const EMERALDS_TRADE_ACTIVE_PROB: f64 = 399.0 / 20_000.0;
const TOMATOES_TRADE_ACTIVE_PROB: f64 = 819.0 / 20_000.0;
const TOMATOES_SECOND_TRADE_PROB: f64 = 1.0 / 819.0;
const EMERALDS_TRADE_BUY_PROB: f64 = 195.0 / 399.0;
const TOMATOES_TRADE_BUY_PROB: f64 = 387.0 / 820.0;

// Round 2 taker arrivals (per-tick Bernoulli, IID).
// docs/round2_params.json -> OSM.taker.taker_rate_per_tick = 0.04598
// docs/round2_params.json -> PEP.taker.taker_rate_per_tick = 0.03309
const OSMIUM_TRADE_ACTIVE_PROB: f64 = 0.04598;
const PEPPER_TRADE_ACTIVE_PROB: f64 = 0.03309;
// Multi-trade ticks are rare; matches OSM.taker.multi_trade_tick_frac = 0.013.
const OSMIUM_SECOND_TRADE_PROB: f64 = 0.013;
const PEPPER_SECOND_TRADE_PROB: f64 = 0.005;
// docs/round2_params.json -> side_buy_frac
const OSMIUM_TRADE_BUY_PROB: f64 = 0.490;
const PEPPER_TRADE_BUY_PROB: f64 = 0.506;

// Round 2 fair-value anchors (per docs/round2_params.json).
const OSMIUM_FAIR_VALUE: i32 = 10001;           // OSM.fv.fair_value
const PEPPER_DRIFT_PER_TICK: f64 = 0.10000;     // PEP.fv.drift_per_tick
// per_day_start rounded to integer thousands; matches 10999.98 / 12000.01 / 12999.92.
const PEPPER_START_DAY_NEG1: f64 = 11_000.0;
const PEPPER_START_DAY_0:    f64 = 12_000.0;
const PEPPER_START_DAY_POS1: f64 = 13_000.0;

const STRATEGY_RUN_TIMEOUT_MS: u64 = 900;
// Bot 3 offsets: 2/3 passive, 1/3 aggressive, 50/50 within each group
// (old weighted offsets removed — calibration proved uniform with passive/aggressive structure)

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Round {
    Round0,
    Round2,
    Round3,
}

impl Round {
    fn days(self) -> &'static [i32] {
        match self {
            Round::Round0 => &ROUND0_DAYS,
            Round::Round2 => &ROUND2_DAYS,
            Round::Round3 => &ROUND3_DAYS,
        }
    }

    fn products(self) -> &'static [&'static str] {
        match self {
            Round::Round0 => &ROUND0_PRODUCTS,
            Round::Round2 => &ROUND2_PRODUCTS,
            Round::Round3 => &ROUND3_PRODUCTS,
        }
    }

    fn dir_name(self) -> &'static str {
        match self {
            Round::Round0 => "round0",
            Round::Round2 => "round2",
            Round::Round3 => "round3",
        }
    }

    fn number(self) -> i32 {
        match self {
            Round::Round0 => 0,
            Round::Round2 => 2,
            Round::Round3 => 3,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FvMode {
    Replay,
    Simulate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum TradeMode {
    ReplayTimes,
    Simulate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum TomatoSupport {
    Continuous,
    Half,
    Quarter,
}

#[derive(Clone, Debug)]
struct Config {
    output_dir: PathBuf,
    actual_dir: PathBuf,
    fv_mode: FvMode,
    trade_mode: TradeMode,
    tomato_support: TomatoSupport,
    seed: u64,
    strategy_path: Option<PathBuf>,
    python_bin: String,
    sessions: usize,
    write_session_limit: usize,
    ticks_per_day: usize,
    round: Round,
}

#[derive(Clone, Debug)]
struct ReplayData {
    tomato_latent_state_by_day: HashMap<i32, Vec<TomatoLatentState>>,
    trade_counts_by_key: HashMap<(i32, String), Vec<usize>>,
}

#[derive(Clone, Copy, Debug)]
enum HalfTieOrientation {
    Inward,
    Outward,
}

impl HalfTieOrientation {
    fn flip(self) -> Self {
        match self {
            HalfTieOrientation::Inward => HalfTieOrientation::Outward,
            HalfTieOrientation::Outward => HalfTieOrientation::Inward,
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct TomatoLatentState {
    fair: f64,
    half_tie_orientation: HalfTieOrientation,
}

#[derive(Clone, Debug)]
struct DayOutput {
    day: i32,
    price_rows: Vec<PriceRow>,
    trade_rows: Vec<TradeRow>,
    trace_rows: Vec<TraceRow>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LevelOwner {
    Bot,
    Strategy,
}

#[derive(Clone, Debug)]
struct Level {
    price: i32,
    quantity: i32,
    owner: LevelOwner,
}

#[derive(Clone, Debug)]
struct SimBook {
    bids: Vec<Level>,
    asks: Vec<Level>,
}

#[derive(Clone, Debug)]
struct Fill {
    symbol: String,
    price: i32,
    quantity: i32,
    buyer: Option<String>,
    seller: Option<String>,
    timestamp: i32,
}

#[derive(Clone, Debug, Default)]
struct ProductLedger {
    position: i32,
    cash: f64,
}

#[derive(Clone, Copy, Debug, Default)]
struct RunningLinearFit {
    n: f64,
    sum_x: f64,
    sum_y: f64,
    sum_xx: f64,
    sum_yy: f64,
    sum_xy: f64,
}

impl RunningLinearFit {
    fn update(&mut self, x: f64, y: f64) {
        self.n += 1.0;
        self.sum_x += x;
        self.sum_y += y;
        self.sum_xx += x * x;
        self.sum_yy += y * y;
        self.sum_xy += x * y;
    }

    fn slope_per_step(&self) -> f64 {
        let denom = self.n * self.sum_xx - self.sum_x * self.sum_x;
        if denom.abs() < 1e-12 {
            0.0
        } else {
            (self.n * self.sum_xy - self.sum_x * self.sum_y) / denom
        }
    }

    fn r_squared(&self) -> f64 {
        let x_var = self.n * self.sum_xx - self.sum_x * self.sum_x;
        let y_var = self.n * self.sum_yy - self.sum_y * self.sum_y;
        if x_var.abs() < 1e-12 || y_var.abs() < 1e-12 {
            0.0
        } else {
            let cov = self.n * self.sum_xy - self.sum_x * self.sum_y;
            (cov * cov) / (x_var * y_var)
        }
    }
}

#[derive(Clone, Debug, Serialize)]
struct SessionSummary {
    session_id: usize,
    total_pnl: f64,
    emerald_pnl: f64,
    tomato_pnl: f64,
    emerald_position: i32,
    tomato_position: i32,
    emerald_cash: f64,
    tomato_cash: f64,
    total_slope_per_step: f64,
    total_r2: f64,
    emerald_slope_per_step: f64,
    emerald_r2: f64,
    tomato_slope_per_step: f64,
    tomato_r2: f64,
    /// Added for round 2: JSON-encoded dict of per-product stats keyed by
    /// product name. Shape: {"PRODUCT": {"pnl": f64, "cash": f64,
    /// "position": i32, "slope_per_step": f64, "r_squared": f64}, ...}.
    /// The Python dashboard builder prefers this over the legacy scalar
    /// columns when it's non-empty, so round-0 runs still emit the legacy
    /// columns populated and round-2 runs emit OSM/PEP via this field.
    product_stats_json: String,
}

#[derive(Clone, Debug, Serialize)]
struct RunSummary {
    session_id: usize,
    day: i32,
    total_pnl: f64,
    emerald_pnl: f64,
    tomato_pnl: f64,
    total_slope_per_step: f64,
    total_r2: f64,
    emerald_slope_per_step: f64,
    emerald_r2: f64,
    tomato_slope_per_step: f64,
    tomato_r2: f64,
    /// See SessionSummary.product_stats_json.
    product_stats_json: String,
}

#[derive(Clone, Debug, Serialize, Default)]
struct ProductStats {
    pnl: f64,
    cash: f64,
    position: i32,
    slope_per_step: f64,
    r_squared: f64,
}

#[derive(Clone, Debug)]
struct SessionOutput {
    session_id: usize,
    summary: SessionSummary,
    run_summaries: Vec<RunSummary>,
    day_outputs: Vec<DayOutput>,
}

#[derive(Clone, Debug)]
struct Book {
    bids: Vec<(i32, i32)>,
    asks: Vec<(i32, i32)>,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
struct InputPriceRow {
    day: i32,
    timestamp: i32,
    product: String,
    bid_price_1: Option<i32>,
    bid_volume_1: Option<i32>,
    bid_price_2: Option<i32>,
    bid_volume_2: Option<i32>,
    bid_price_3: Option<i32>,
    bid_volume_3: Option<i32>,
    ask_price_1: Option<i32>,
    ask_volume_1: Option<i32>,
    ask_price_2: Option<i32>,
    ask_volume_2: Option<i32>,
    ask_price_3: Option<i32>,
    ask_volume_3: Option<i32>,
    mid_price: f64,
    profit_and_loss: f64,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
struct InputTradeRow {
    timestamp: i32,
    buyer: Option<String>,
    seller: Option<String>,
    symbol: String,
    currency: String,
    price: f64,
    quantity: i32,
}

#[derive(Clone, Debug, Serialize)]
struct PriceRow {
    day: i32,
    timestamp: i32,
    product: String,
    bid_price_1: Option<i32>,
    bid_volume_1: Option<i32>,
    bid_price_2: Option<i32>,
    bid_volume_2: Option<i32>,
    bid_price_3: Option<i32>,
    bid_volume_3: Option<i32>,
    ask_price_1: Option<i32>,
    ask_volume_1: Option<i32>,
    ask_price_2: Option<i32>,
    ask_volume_2: Option<i32>,
    ask_price_3: Option<i32>,
    ask_volume_3: Option<i32>,
    mid_price: f64,
    profit_and_loss: f64,
}

#[derive(Clone, Debug, Serialize)]
struct TradeRow {
    timestamp: i32,
    buyer: Option<String>,
    seller: Option<String>,
    symbol: String,
    currency: String,
    price: f64,
    quantity: i32,
}

#[derive(Clone, Debug, Serialize)]
struct TraceRow {
    day: i32,
    timestamp: i32,
    product: String,
    fair_value: f64,
    position: i32,
    cash: f64,
    mtm_pnl: f64,
}

#[derive(Debug, Serialize)]
struct WorkerTrade {
    symbol: String,
    price: i32,
    quantity: i32,
    buyer: Option<String>,
    seller: Option<String>,
    timestamp: i32,
}

#[derive(Debug, Serialize)]
struct WorkerOrderDepth {
    buy_orders: HashMap<String, i32>,
    sell_orders: HashMap<String, i32>,
}

#[derive(Debug, Serialize)]
struct WorkerRequest {
    #[serde(rename = "type")]
    request_type: String,
    timestamp: i32,
    timeout_ms: u64,
    trader_data: String,
    order_depths: HashMap<String, WorkerOrderDepth>,
    own_trades: HashMap<String, Vec<WorkerTrade>>,
    market_trades: HashMap<String, Vec<WorkerTrade>>,
    position: HashMap<String, i32>,
}

#[allow(dead_code)]
#[derive(Clone, Debug, Deserialize)]
struct WorkerOrder {
    symbol: String,
    price: i32,
    quantity: i32,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
struct WorkerResponse {
    orders: Option<HashMap<String, Vec<WorkerOrder>>>,
    conversions: Option<i32>,
    trader_data: Option<String>,
    stdout: Option<String>,
    error: Option<String>,
}

impl Config {
    fn from_args() -> Result<Self> {
        let mut config = Config {
            output_dir: PathBuf::from("../tmp/rust_simulator_output"),
            actual_dir: PathBuf::from("../data/round0"),
            fv_mode: FvMode::Replay,
            trade_mode: TradeMode::ReplayTimes,
            tomato_support: TomatoSupport::Continuous,
            seed: 20_260_401,
            strategy_path: None,
            python_bin: "python3".to_string(),
            sessions: 1,
            write_session_limit: 0,
            ticks_per_day: DEFAULT_TICKS_PER_DAY,
            round: Round::Round0,
        };

        // If --actual-dir is explicitly passed it wins. Otherwise we re-derive
        // the default from --round after argument parsing completes.
        let mut actual_dir_explicit = false;
        let mut args = env::args().skip(1);
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--output" => {
                    config.output_dir =
                        PathBuf::from(args.next().context("missing value for --output")?);
                }
                "--actual-dir" => {
                    config.actual_dir =
                        PathBuf::from(args.next().context("missing value for --actual-dir")?);
                    actual_dir_explicit = true;
                }
                "--round" => {
                    let value = args.next().context("missing value for --round")?;
                    config.round = match value.as_str() {
                        "0" => Round::Round0,
                        "2" => Round::Round2,
                        "3" => Round::Round3,
                        other => bail!("unsupported --round {} (expected 0, 2, or 3)", other),
                    };
                }
                "--fv-mode" => {
                    let value = args.next().context("missing value for --fv-mode")?;
                    config.fv_mode = match value.as_str() {
                        "replay" => FvMode::Replay,
                        "simulate" => FvMode::Simulate,
                        other => bail!("unsupported --fv-mode {}", other),
                    };
                }
                "--trade-mode" => {
                    let value = args.next().context("missing value for --trade-mode")?;
                    config.trade_mode = match value.as_str() {
                        "replay-times" => TradeMode::ReplayTimes,
                        "simulate" => TradeMode::Simulate,
                        other => bail!("unsupported --trade-mode {}", other),
                    };
                }
                "--tomato-support" => {
                    let value = args.next().context("missing value for --tomato-support")?;
                    config.tomato_support = match value.as_str() {
                        "continuous" => TomatoSupport::Continuous,
                        "0.5" | "half" => TomatoSupport::Half,
                        "0.25" | "quarter" => TomatoSupport::Quarter,
                        other => bail!("unsupported --tomato-support {}", other),
                    };
                }
                "--seed" => {
                    config.seed = args
                        .next()
                        .context("missing value for --seed")?
                        .parse()
                        .context("invalid --seed")?;
                }
                "--strategy" => {
                    config.strategy_path = Some(PathBuf::from(
                        args.next().context("missing value for --strategy")?,
                    ));
                }
                "--python-bin" => {
                    config.python_bin = args.next().context("missing value for --python-bin")?;
                }
                "--sessions" => {
                    config.sessions = args
                        .next()
                        .context("missing value for --sessions")?
                        .parse()
                        .context("invalid --sessions")?;
                }
                "--write-session-limit" => {
                    config.write_session_limit = args
                        .next()
                        .context("missing value for --write-session-limit")?
                        .parse()
                        .context("invalid --write-session-limit")?;
                }
                "--ticks-per-day" => {
                    config.ticks_per_day = args
                        .next()
                        .context("missing value for --ticks-per-day")?
                        .parse()
                        .context("invalid --ticks-per-day")?;
                }
                other => bail!("unknown argument {}", other),
            }
        }

        if !actual_dir_explicit {
            config.actual_dir =
                PathBuf::from(format!("../data/{}", config.round.dir_name()));
        }

        Ok(config)
    }
}

fn main() -> Result<()> {
    let config = Config::from_args()?;
    let replay_data = ReplayData::load(&config)?;

    if config.strategy_path.is_some() {
        let outputs = run_backtests(&config, &replay_data)?;
        write_backtest_outputs(&config, &outputs)?;
        write_run_log(&config)?;
        return Ok(());
    }

    let outputs = config
        .round
        .days()
        .par_iter()
        .map(|day| generate_day(*day, &config, &replay_data))
        .collect::<Result<Vec<_>>>()?;

    write_outputs(&config, &outputs)?;
    write_run_log(&config)?;
    Ok(())
}

impl ReplayData {
    fn load(config: &Config) -> Result<Self> {
        let mut tomato_latent_state_by_day = HashMap::new();
        let mut trade_counts_by_key = HashMap::new();
        let days = config.round.days();
        let products = config.round.products();

        // TOMATOES latent state is only meaningful for Round 0 (see
        // estimate_tomato_latent_state). Round 2 uses deterministic per-tick
        // fairs for PEP and a constant for OSM, so no latent state is needed.
        if config.fv_mode == FvMode::Replay && config.round == Round::Round0 {
            for day in days.iter().copied() {
                let prices = load_price_rows(&config.actual_dir, day)?;
                let mut rows: Vec<_> = prices
                    .into_iter()
                    .filter(|row| row.product == "TOMATOES")
                    .collect();
                rows.sort_by_key(|row| row.timestamp);
                let latent_state_estimate = rows
                    .iter()
                    .map(estimate_tomato_latent_state)
                    .collect::<Vec<_>>();
                tomato_latent_state_by_day.insert(day, latent_state_estimate);
            }
        }

        if config.trade_mode == TradeMode::ReplayTimes {
            for day in days.iter().copied() {
                let trades = load_trade_rows(&config.actual_dir, day)?;
                for product in products.iter().copied() {
                    let mut counts = vec![0usize; DEFAULT_TICKS_PER_DAY];
                    for trade in trades.iter().filter(|row| row.symbol == product) {
                        let index = usize::try_from(trade.timestamp / TIMESTAMP_STEP)
                            .context("negative timestamp while loading replay trades")?;
                        if index < counts.len() {
                            counts[index] += 1;
                        }
                    }
                    trade_counts_by_key.insert((day, product.to_string()), counts);
                }
            }
        }

        Ok(Self {
            tomato_latent_state_by_day,
            trade_counts_by_key,
        })
    }
}

fn generate_day(day: i32, config: &Config, replay: &ReplayData) -> Result<DayOutput> {
    let mut rng = ChaCha8Rng::seed_from_u64(seed_for_day(config.seed, day));
    let n_products = config.round.products().len();
    let mut price_rows = Vec::with_capacity(config.ticks_per_day * n_products);
    let mut trade_rows = Vec::new();

    match config.round {
        Round::Round0 => {
            let tomato_latent_state = match config.fv_mode {
                FvMode::Replay => replay
                    .tomato_latent_state_by_day
                    .get(&day)
                    .cloned()
                    .context("missing replay tomato latent state estimate")?,
                FvMode::Simulate => simulate_tomato_fair(
                    day,
                    config.tomato_support,
                    config.ticks_per_day,
                    &mut rng,
                ),
            };

            let emerald_trade_counts =
                trade_counts_for("EMERALDS", day, config, replay, &mut rng)?;
            let tomato_trade_counts =
                trade_counts_for("TOMATOES", day, config, replay, &mut rng)?;

            for tick in 0..config.ticks_per_day {
                let timestamp = (tick as i32) * TIMESTAMP_STEP;
                let emerald_book = make_emerald_book(&mut rng);
                let tomato_book = make_tomato_book(tomato_latent_state[tick], &mut rng);

                price_rows.push(book_to_price_row(day, timestamp, "EMERALDS", &emerald_book));
                price_rows.push(book_to_price_row(day, timestamp, "TOMATOES", &tomato_book));

                for _ in 0..emerald_trade_counts[tick] {
                    trade_rows.extend(sample_trade_rows(
                        timestamp,
                        "EMERALDS",
                        &emerald_book,
                        &mut rng,
                    ));
                }
                for _ in 0..tomato_trade_counts[tick] {
                    trade_rows.extend(sample_trade_rows(
                        timestamp,
                        "TOMATOES",
                        &tomato_book,
                        &mut rng,
                    ));
                }
            }
        }
        Round::Round2 => {
            let osm_trade_counts =
                trade_counts_for("ASH_COATED_OSMIUM", day, config, replay, &mut rng)?;
            let pep_trade_counts =
                trade_counts_for("INTARIAN_PEPPER_ROOT", day, config, replay, &mut rng)?;

            for tick in 0..config.ticks_per_day {
                let timestamp = (tick as i32) * TIMESTAMP_STEP;
                let osm_book = make_osmium_book(&mut rng);
                let pep_book = make_pepper_book(pepper_latent_fair(day, tick), &mut rng);

                price_rows.push(book_to_price_row(
                    day,
                    timestamp,
                    "ASH_COATED_OSMIUM",
                    &osm_book,
                ));
                price_rows.push(book_to_price_row(
                    day,
                    timestamp,
                    "INTARIAN_PEPPER_ROOT",
                    &pep_book,
                ));

                for _ in 0..osm_trade_counts[tick] {
                    trade_rows.extend(sample_trade_rows(
                        timestamp,
                        "ASH_COATED_OSMIUM",
                        &osm_book,
                        &mut rng,
                    ));
                }
                for _ in 0..pep_trade_counts[tick] {
                    trade_rows.extend(sample_trade_rows(
                        timestamp,
                        "INTARIAN_PEPPER_ROOT",
                        &pep_book,
                        &mut rng,
                    ));
                }
            }
        }
        Round::Round3 => {
            // Simulate underlying price paths for HYDROGEL and VELVETFRUIT.
            // Vouchers are derived from VELVET's path tick-by-tick via BSM.
            let hydrogel_path = simulate_delta1_path(
                HYDROGEL_FAIR_VALUE,
                HYDROGEL_INNOV_SIGMA,
                HYDROGEL_EQUIL_STD,
                config.ticks_per_day,
                &mut rng,
            );
            let velvet_path = simulate_delta1_path(
                VELVET_FAIR_VALUE,
                VELVET_INNOV_SIGMA,
                VELVET_EQUIL_STD,
                config.ticks_per_day,
                &mut rng,
            );

            // Per-product trade counts (VEV pinned strikes have zero activity).
            let mut trade_counts_map: HashMap<String, Vec<usize>> = HashMap::new();
            for product in ROUND3_PRODUCTS {
                trade_counts_map.insert(
                    product.to_string(),
                    trade_counts_for(product, day, config, replay, &mut rng)?,
                );
            }

            for tick in 0..config.ticks_per_day {
                let timestamp = (tick as i32) * TIMESTAMP_STEP;
                let hydrogel_book = make_hydrogel_book(hydrogel_path[tick], &mut rng);
                let velvet_book = make_velvet_book(velvet_path[tick], &mut rng);

                price_rows.push(book_to_price_row(day, timestamp, "HYDROGEL_PACK", &hydrogel_book));
                price_rows.push(book_to_price_row(day, timestamp, "VELVETFRUIT_EXTRACT", &velvet_book));

                // Vouchers anchored on VELVET fair with per-strike single IV and
                // the R3 live TTE (5 days). During data generation this is the
                // only mode (replay-FV mode not supported for R3).
                for &k in VEV_STRIKES.iter() {
                    let product = vev_product_name(k);
                    let book = make_vev_book(k, velvet_path[tick], R3_LIVE_TTE_YEARS, &mut rng);
                    price_rows.push(book_to_price_row(day, timestamp, product, &book));

                    let count = trade_counts_map
                        .get(product)
                        .map(|v| v[tick])
                        .unwrap_or(0);
                    for _ in 0..count {
                        trade_rows.extend(sample_trade_rows(timestamp, product, &book, &mut rng));
                    }
                }

                let hy_count = trade_counts_map
                    .get("HYDROGEL_PACK")
                    .map(|v| v[tick])
                    .unwrap_or(0);
                let ve_count = trade_counts_map
                    .get("VELVETFRUIT_EXTRACT")
                    .map(|v| v[tick])
                    .unwrap_or(0);
                for _ in 0..hy_count {
                    trade_rows.extend(sample_trade_rows(timestamp, "HYDROGEL_PACK", &hydrogel_book, &mut rng));
                }
                for _ in 0..ve_count {
                    trade_rows.extend(sample_trade_rows(timestamp, "VELVETFRUIT_EXTRACT", &velvet_book, &mut rng));
                }
            }
        }
    }

    price_rows.sort_by(|a, b| {
        a.timestamp
            .cmp(&b.timestamp)
            .then(a.product.cmp(&b.product))
    });
    trade_rows.sort_by(|a, b| a.timestamp.cmp(&b.timestamp).then(a.symbol.cmp(&b.symbol)));

    Ok(DayOutput {
        day,
        price_rows,
        trade_rows,
        trace_rows: Vec::new(),
    })
}

fn write_outputs(config: &Config, outputs: &[DayOutput]) -> Result<()> {
    let round_dir = config.output_dir.join(config.round.dir_name());
    fs::create_dir_all(&round_dir)
        .with_context(|| format!("failed to create {}", round_dir.display()))?;
    let round_num = config.round.number();

    for output in outputs {
        let price_path =
            round_dir.join(format!("prices_round_{}_day_{}.csv", round_num, output.day));
        let trade_path =
            round_dir.join(format!("trades_round_{}_day_{}.csv", round_num, output.day));

        let mut price_writer = WriterBuilder::new()
            .delimiter(b';')
            .from_path(&price_path)
            .with_context(|| format!("failed to open {}", price_path.display()))?;
        for row in &output.price_rows {
            price_writer.serialize(row)?;
        }
        price_writer.flush()?;

        let mut trade_writer = WriterBuilder::new()
            .delimiter(b';')
            .from_path(&trade_path)
            .with_context(|| format!("failed to open {}", trade_path.display()))?;
        for row in &output.trade_rows {
            trade_writer.serialize(row)?;
        }
        trade_writer.flush()?;
    }

    Ok(())
}

struct StrategyWorker {
    child: Child,
    stdin: BufWriter<ChildStdin>,
    stdout: BufReader<ChildStdout>,
}

impl StrategyWorker {
    fn spawn(config: &Config) -> Result<Self> {
        let strategy_path = config
            .strategy_path
            .as_ref()
            .context("missing strategy path")?
            .canonicalize()
            .with_context(|| "failed to canonicalize strategy path")?;
        let project_root = env::var("PROSPERITY4MCBT_ROOT")
            .map(PathBuf::from)
            .or_else(|_| {
                env::current_dir().map(|cwd| {
                    cwd.parent()
                        .map(Path::to_path_buf)
                        .unwrap_or(cwd)
                })
            })
            .context("failed to resolve project root for python strategy worker")?;
        let worker_path = project_root.join("scripts/python_strategy_worker.py");
        if !worker_path.is_file() {
            bail!(
                "python strategy worker not found at {}",
                worker_path.display()
            );
        }

        let mut child = Command::new(&config.python_bin)
            .arg(worker_path)
            .arg(strategy_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .context("failed to spawn python strategy worker")?;

        let stdin = BufWriter::new(child.stdin.take().context("missing worker stdin")?);
        let stdout = BufReader::new(child.stdout.take().context("missing worker stdout")?);

        Ok(Self {
            child,
            stdin,
            stdout,
        })
    }

    fn reset(&mut self) -> Result<()> {
        let payload = serde_json::json!({ "type": "reset" });
        self.send(&payload)?;
        let response = self.read_response()?;
        if let Some(error) = response.error {
            bail!("python worker reset failed: {}", error);
        }
        Ok(())
    }

    fn run(&mut self, request: &WorkerRequest) -> Result<WorkerResponse> {
        self.send(request)?;
        let response = self.read_response()?;
        if let Some(error) = &response.error {
            bail!("python worker failed: {}", error);
        }
        Ok(response)
    }

    fn send<T: Serialize>(&mut self, payload: &T) -> Result<()> {
        serde_json::to_writer(&mut self.stdin, payload)?;
        self.stdin.write_all(b"\n")?;
        self.stdin.flush()?;
        Ok(())
    }

    fn read_response(&mut self) -> Result<WorkerResponse> {
        let mut line = String::new();
        let bytes = self.stdout.read_line(&mut line)?;
        if bytes == 0 {
            bail!("python worker exited unexpectedly");
        }
        let response = serde_json::from_str::<WorkerResponse>(line.trim())
            .context("failed to decode python worker response")?;
        Ok(response)
    }
}

impl Drop for StrategyWorker {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn run_backtests(config: &Config, replay: &ReplayData) -> Result<Vec<SessionOutput>> {
    let mut outputs = (0..config.sessions)
        .into_par_iter()
        .map(|session_id| {
            let capture = session_id < config.write_session_limit;
            match config.round {
                Round::Round0 => run_backtest_session(session_id, capture, config, replay),
                Round::Round2 => run_backtest_session_r2(session_id, capture, config, replay),
                Round::Round3 => run_backtest_session_r3(session_id, capture, config, replay),
            }
        })
        .collect::<Result<Vec<_>>>()?;
    outputs.sort_by_key(|output| output.session_id);
    Ok(outputs)
}

fn monte_carlo_session_day(session_id: usize, round: Round) -> i32 {
    let days = round.days();
    days[session_id % days.len()]
}

fn run_backtest_session(
    session_id: usize,
    capture_outputs: bool,
    config: &Config,
    replay: &ReplayData,
) -> Result<SessionOutput> {
    let mut worker = StrategyWorker::spawn(config)?;
    let mut day_outputs = Vec::with_capacity(1);
    let mut emerald_total = 0.0;
    let mut tomato_total = 0.0;
    let mut emerald_cash_total = 0.0;
    let mut tomato_cash_total = 0.0;
    let mut emerald_final_position = 0;
    let mut tomato_final_position = 0;
    let mut total_fit = RunningLinearFit::default();
    let mut emerald_fit = RunningLinearFit::default();
    let mut tomato_fit = RunningLinearFit::default();
    let mut global_step = 0usize;
    let mut run_summaries = Vec::with_capacity(1);
    let session_day = monte_carlo_session_day(session_id, Round::Round0);

    for day in [session_day] {
        worker.reset()?;
        let mut rng = ChaCha8Rng::seed_from_u64(seed_for_session_day(config.seed, session_id, day));
        let tomato_latent_state = match config.fv_mode {
            FvMode::Replay => replay
                .tomato_latent_state_by_day
                .get(&day)
                .cloned()
                .context("missing replay tomato latent state estimate")?,
            FvMode::Simulate => simulate_tomato_fair(day, config.tomato_support, config.ticks_per_day, &mut rng),
        };

        let emerald_trade_counts = trade_counts_for("EMERALDS", day, config, replay, &mut rng)?;
        let tomato_trade_counts = trade_counts_for("TOMATOES", day, config, replay, &mut rng)?;

        let mut ledgers = HashMap::from([
            ("EMERALDS".to_string(), ProductLedger::default()),
            ("TOMATOES".to_string(), ProductLedger::default()),
        ]);
        let mut trader_data = String::new();
        let mut prev_own_trades = empty_trade_map();
        let mut prev_market_trades = empty_trade_map();
        let mut day_total_fit = RunningLinearFit::default();
        let mut day_emerald_fit = RunningLinearFit::default();
        let mut day_tomato_fit = RunningLinearFit::default();
        let mut day_step = 0usize;
        let mut price_rows = if capture_outputs {
            Vec::with_capacity(config.ticks_per_day * PRODUCTS.len())
        } else {
            Vec::new()
        };
        let mut trade_rows = Vec::new();
        let mut trace_rows = Vec::new();

        for tick in 0..config.ticks_per_day {
            let timestamp = (tick as i32) * TIMESTAMP_STEP;
            let emerald_book = make_emerald_book(&mut rng);
            let tomato_book = make_tomato_book(tomato_latent_state[tick], &mut rng);

            if capture_outputs {
                price_rows.push(book_to_price_row(day, timestamp, "EMERALDS", &emerald_book));
                price_rows.push(book_to_price_row(day, timestamp, "TOMATOES", &tomato_book));
            }

            let order_depths = HashMap::from([
                ("EMERALDS".to_string(), book_to_worker_depth(&emerald_book)),
                ("TOMATOES".to_string(), book_to_worker_depth(&tomato_book)),
            ]);
            let position = ledgers
                .iter()
                .map(|(product, ledger)| (product.clone(), ledger.position))
                .collect::<HashMap<_, _>>();
            let request = WorkerRequest {
                request_type: "run".to_string(),
                timestamp,
                timeout_ms: STRATEGY_RUN_TIMEOUT_MS,
                trader_data: trader_data.clone(),
                order_depths,
                own_trades: fills_to_worker_trade_map(&prev_own_trades),
                market_trades: fills_to_worker_trade_map(&prev_market_trades),
                position,
            };
            let response = worker.run(&request)?;
            trader_data = response.trader_data.unwrap_or_default();

            let mut live_books = HashMap::from([
                ("EMERALDS".to_string(), book_to_sim_book(&emerald_book)),
                ("TOMATOES".to_string(), book_to_sim_book(&tomato_book)),
            ]);
            let strategy_orders = normalize_strategy_orders(response.orders.unwrap_or_default());
            let filtered_orders = enforce_strategy_limits(&strategy_orders, &ledgers);

            let mut own_trades_this_tick = empty_trade_map();
            let mut market_trades_this_tick = empty_trade_map();

            for product in PRODUCTS {
                let product_key = product.to_string();
                let orders = filtered_orders
                    .get(product)
                    .cloned()
                    .unwrap_or_default();
                let book = live_books
                    .get_mut(&product_key)
                    .context("missing live book")?;
                let ledger = ledgers.get_mut(&product_key).context("missing ledger")?;
                let fills = execute_strategy_orders(product, timestamp, book, ledger, &orders);
                if capture_outputs {
                    trade_rows.extend(fills.iter().map(fill_to_trade_row));
                }
                own_trades_this_tick.insert(product_key.clone(), fills);
            }

            for (product, count) in [("EMERALDS", emerald_trade_counts[tick]), ("TOMATOES", tomato_trade_counts[tick])] {
                let product_key = product.to_string();
                let book = live_books
                    .get_mut(&product_key)
                    .context("missing live book for taker execution")?;
                let ledger = ledgers.get_mut(&product_key).context("missing ledger for taker execution")?;
                for _ in 0..count {
                    let market_buy = sample_trade_side(product, &mut rng);
                    let fills = execute_taker_trade(product, timestamp, book, ledger, market_buy, &mut rng);
                    for fill in fills {
                        let row = fill_to_trade_row(&fill);
                        if fill_involves_strategy(&fill) {
                            own_trades_this_tick.entry(product_key.clone()).or_default().push(fill);
                        } else {
                            market_trades_this_tick.entry(product_key.clone()).or_default().push(fill);
                        }
                        if capture_outputs {
                            trade_rows.push(row);
                        }
                    }
                }
            }

            if capture_outputs {
                for product in PRODUCTS {
                    let product_key = product.to_string();
                    let ledger = ledgers.get(&product_key).context("missing ledger for trace")?;
                    let fair = if product == "EMERALDS" {
                        10_000.0
                    } else {
                        tomato_latent_state[tick].fair
                    };
                    trace_rows.push(TraceRow {
                        day,
                        timestamp,
                        product: product_key,
                        fair_value: fair,
                        position: ledger.position,
                        cash: ledger.cash,
                        mtm_pnl: ledger.cash + ledger.position as f64 * fair,
                    });
                }
            }

            let emerald_ledger = ledgers.get("EMERALDS").context("missing emerald ledger for fit")?;
            let tomato_ledger = ledgers.get("TOMATOES").context("missing tomato ledger for fit")?;
            let emerald_mtm = emerald_ledger.cash + emerald_ledger.position as f64 * 10_000.0;
            let tomato_mtm =
                tomato_ledger.cash + tomato_ledger.position as f64 * tomato_latent_state[tick].fair;
            let session_x = global_step as f64;
            let day_x = day_step as f64;
            emerald_fit.update(session_x, emerald_mtm);
            tomato_fit.update(session_x, tomato_mtm);
            total_fit.update(session_x, emerald_mtm + tomato_mtm);
            day_emerald_fit.update(day_x, emerald_mtm);
            day_tomato_fit.update(day_x, tomato_mtm);
            day_total_fit.update(day_x, emerald_mtm + tomato_mtm);
            global_step += 1;
            day_step += 1;

            prev_own_trades = own_trades_this_tick;
            prev_market_trades = market_trades_this_tick;
        }

        let emerald_fair = 10_000.0;
        let tomato_fair = tomato_latent_state
            .last()
            .map(|state| state.fair)
            .unwrap_or(5_000.0);
        let emerald_ledger = ledgers.get("EMERALDS").context("missing emerald ledger")?;
        let tomato_ledger = ledgers.get("TOMATOES").context("missing tomato ledger")?;
        let emerald_pnl = emerald_ledger.cash + emerald_ledger.position as f64 * emerald_fair;
        let tomato_pnl = tomato_ledger.cash + tomato_ledger.position as f64 * tomato_fair;

        emerald_total += emerald_pnl;
        tomato_total += tomato_pnl;
        emerald_cash_total += emerald_ledger.cash;
        tomato_cash_total += tomato_ledger.cash;
        emerald_final_position = emerald_ledger.position;
        tomato_final_position = tomato_ledger.position;

        let day_product_stats: HashMap<String, ProductStats> = HashMap::from([
            (
                "EMERALDS".to_string(),
                ProductStats {
                    pnl: emerald_pnl,
                    cash: emerald_ledger.cash,
                    position: emerald_ledger.position,
                    slope_per_step: day_emerald_fit.slope_per_step(),
                    r_squared: day_emerald_fit.r_squared(),
                },
            ),
            (
                "TOMATOES".to_string(),
                ProductStats {
                    pnl: tomato_pnl,
                    cash: tomato_ledger.cash,
                    position: tomato_ledger.position,
                    slope_per_step: day_tomato_fit.slope_per_step(),
                    r_squared: day_tomato_fit.r_squared(),
                },
            ),
        ]);

        run_summaries.push(RunSummary {
            session_id,
            day,
            total_pnl: emerald_pnl + tomato_pnl,
            emerald_pnl,
            tomato_pnl,
            total_slope_per_step: day_total_fit.slope_per_step(),
            total_r2: day_total_fit.r_squared(),
            emerald_slope_per_step: day_emerald_fit.slope_per_step(),
            emerald_r2: day_emerald_fit.r_squared(),
            tomato_slope_per_step: day_tomato_fit.slope_per_step(),
            tomato_r2: day_tomato_fit.r_squared(),
            product_stats_json: serde_json::to_string(&day_product_stats)
                .unwrap_or_else(|_| "{}".to_string()),
        });

        day_outputs.push(DayOutput {
            day,
            price_rows,
            trade_rows,
            trace_rows,
        });
    }

    let session_product_stats: HashMap<String, ProductStats> = HashMap::from([
        (
            "EMERALDS".to_string(),
            ProductStats {
                pnl: emerald_total,
                cash: emerald_cash_total,
                position: emerald_final_position,
                slope_per_step: emerald_fit.slope_per_step(),
                r_squared: emerald_fit.r_squared(),
            },
        ),
        (
            "TOMATOES".to_string(),
            ProductStats {
                pnl: tomato_total,
                cash: tomato_cash_total,
                position: tomato_final_position,
                slope_per_step: tomato_fit.slope_per_step(),
                r_squared: tomato_fit.r_squared(),
            },
        ),
    ]);

    let summary = SessionSummary {
        session_id,
        total_pnl: emerald_total + tomato_total,
        emerald_pnl: emerald_total,
        tomato_pnl: tomato_total,
        emerald_position: emerald_final_position,
        tomato_position: tomato_final_position,
        emerald_cash: emerald_cash_total,
        tomato_cash: tomato_cash_total,
        total_slope_per_step: total_fit.slope_per_step(),
        total_r2: total_fit.r_squared(),
        emerald_slope_per_step: emerald_fit.slope_per_step(),
        emerald_r2: emerald_fit.r_squared(),
        tomato_slope_per_step: tomato_fit.slope_per_step(),
        tomato_r2: tomato_fit.r_squared(),
        product_stats_json: serde_json::to_string(&session_product_stats)
            .unwrap_or_else(|_| "{}".to_string()),
    };

    Ok(SessionOutput {
        session_id,
        summary,
        run_summaries,
        day_outputs,
    })
}

/// Round 2 session runner — structurally parallel to `run_backtest_session`
/// but product-generic (iterates `config.round.products()`), uses R2 book
/// generators, and writes only the generic `product_stats_json` column
/// (legacy emerald/tomato scalar columns are zero).
fn run_backtest_session_r2(
    session_id: usize,
    capture_outputs: bool,
    config: &Config,
    replay: &ReplayData,
) -> Result<SessionOutput> {
    let products: &[&str] = config.round.products();
    let mut worker = StrategyWorker::spawn(config)?;
    let mut day_outputs = Vec::with_capacity(1);
    let mut total_fit = RunningLinearFit::default();
    let mut product_fits: HashMap<String, RunningLinearFit> =
        products.iter().map(|p| (p.to_string(), RunningLinearFit::default())).collect();
    let mut product_totals: HashMap<String, f64> =
        products.iter().map(|p| (p.to_string(), 0.0)).collect();
    let mut product_cash: HashMap<String, f64> =
        products.iter().map(|p| (p.to_string(), 0.0)).collect();
    let mut product_final_pos: HashMap<String, i32> =
        products.iter().map(|p| (p.to_string(), 0)).collect();
    let mut global_step = 0usize;
    let mut run_summaries = Vec::with_capacity(1);
    let session_day = monte_carlo_session_day(session_id, config.round);

    for day in [session_day] {
        worker.reset()?;
        let mut rng = ChaCha8Rng::seed_from_u64(seed_for_session_day(config.seed, session_id, day));

        let mut trade_counts: HashMap<String, Vec<usize>> = HashMap::new();
        for product in products.iter().copied() {
            trade_counts.insert(
                product.to_string(),
                trade_counts_for(product, day, config, replay, &mut rng)?,
            );
        }

        let mut ledgers: HashMap<String, ProductLedger> = products
            .iter()
            .map(|p| (p.to_string(), ProductLedger::default()))
            .collect();
        let mut trader_data = String::new();
        let mut prev_own_trades = empty_trade_map_for(products);
        let mut prev_market_trades = empty_trade_map_for(products);
        let mut day_total_fit = RunningLinearFit::default();
        let mut day_product_fits: HashMap<String, RunningLinearFit> =
            products.iter().map(|p| (p.to_string(), RunningLinearFit::default())).collect();
        let mut day_step = 0usize;
        let mut price_rows = if capture_outputs {
            Vec::with_capacity(config.ticks_per_day * products.len())
        } else {
            Vec::new()
        };
        let mut trade_rows = Vec::new();
        let mut trace_rows = Vec::new();

        for tick in 0..config.ticks_per_day {
            let timestamp = (tick as i32) * TIMESTAMP_STEP;
            // Build per-product books and fair-values for this tick.
            let pep_fair_val = pepper_latent_fair(day, tick);
            let mut books: HashMap<String, Book> = HashMap::new();
            let mut fairs: HashMap<String, f64> = HashMap::new();
            for product in products.iter().copied() {
                let (book, fair) = match product {
                    "ASH_COATED_OSMIUM" => (make_osmium_book(&mut rng), OSMIUM_FAIR_VALUE as f64),
                    "INTARIAN_PEPPER_ROOT" => (make_pepper_book(pep_fair_val, &mut rng), pep_fair_val),
                    other => bail!("round 2 session runner: unsupported product {}", other),
                };
                if capture_outputs {
                    price_rows.push(book_to_price_row(day, timestamp, product, &book));
                }
                books.insert(product.to_string(), book);
                fairs.insert(product.to_string(), fair);
            }

            let order_depths: HashMap<String, WorkerOrderDepth> = books
                .iter()
                .map(|(k, book)| (k.clone(), book_to_worker_depth(book)))
                .collect();
            let position: HashMap<String, i32> = ledgers
                .iter()
                .map(|(product, ledger)| (product.clone(), ledger.position))
                .collect();
            let request = WorkerRequest {
                request_type: "run".to_string(),
                timestamp,
                timeout_ms: STRATEGY_RUN_TIMEOUT_MS,
                trader_data: trader_data.clone(),
                order_depths,
                own_trades: fills_to_worker_trade_map_for(&prev_own_trades, products),
                market_trades: fills_to_worker_trade_map_for(&prev_market_trades, products),
                position,
            };
            let response = worker.run(&request)?;
            trader_data = response.trader_data.unwrap_or_default();

            let mut live_books: HashMap<String, SimBook> = books
                .iter()
                .map(|(k, book)| (k.clone(), book_to_sim_book(book)))
                .collect();
            let strategy_orders = normalize_strategy_orders_for(
                response.orders.unwrap_or_default(),
                products,
            );
            let filtered_orders = enforce_strategy_limits(&strategy_orders, &ledgers);

            let mut own_trades_this_tick = empty_trade_map_for(products);
            let mut market_trades_this_tick = empty_trade_map_for(products);

            // Strategy orders first.
            for product in products.iter().copied() {
                let product_key = product.to_string();
                let orders = filtered_orders.get(product).cloned().unwrap_or_default();
                let book = live_books.get_mut(&product_key).context("missing live book")?;
                let ledger = ledgers.get_mut(&product_key).context("missing ledger")?;
                let fills = execute_strategy_orders(product, timestamp, book, ledger, &orders);
                if capture_outputs {
                    trade_rows.extend(fills.iter().map(fill_to_trade_row));
                }
                own_trades_this_tick.insert(product_key, fills);
            }

            // Bot taker flow.
            for product in products.iter().copied() {
                let product_key = product.to_string();
                let count = trade_counts.get(&product_key).map(|v| v[tick]).unwrap_or(0);
                let book = live_books
                    .get_mut(&product_key)
                    .context("missing live book for taker execution")?;
                let ledger = ledgers
                    .get_mut(&product_key)
                    .context("missing ledger for taker execution")?;
                for _ in 0..count {
                    let market_buy = sample_trade_side(product, &mut rng);
                    let fills = execute_taker_trade(product, timestamp, book, ledger, market_buy, &mut rng);
                    for fill in fills {
                        let row = fill_to_trade_row(&fill);
                        if fill_involves_strategy(&fill) {
                            own_trades_this_tick
                                .entry(product_key.clone())
                                .or_default()
                                .push(fill);
                        } else {
                            market_trades_this_tick
                                .entry(product_key.clone())
                                .or_default()
                                .push(fill);
                        }
                        if capture_outputs {
                            trade_rows.push(row);
                        }
                    }
                }
            }

            if capture_outputs {
                for product in products.iter().copied() {
                    let product_key = product.to_string();
                    let ledger = ledgers.get(&product_key).context("missing ledger for trace")?;
                    let fair = *fairs.get(&product_key).unwrap_or(&0.0);
                    trace_rows.push(TraceRow {
                        day,
                        timestamp,
                        product: product_key,
                        fair_value: fair,
                        position: ledger.position,
                        cash: ledger.cash,
                        mtm_pnl: ledger.cash + ledger.position as f64 * fair,
                    });
                }
            }

            // Update linear fits for stability/R² tracking.
            let mut tick_total_mtm = 0.0;
            for product in products.iter().copied() {
                let product_key = product.to_string();
                let ledger = ledgers.get(&product_key).context("missing ledger for fit")?;
                let fair = *fairs.get(&product_key).unwrap_or(&0.0);
                let mtm = ledger.cash + ledger.position as f64 * fair;
                let session_x = global_step as f64;
                let day_x = day_step as f64;
                product_fits.get_mut(&product_key).unwrap().update(session_x, mtm);
                day_product_fits.get_mut(&product_key).unwrap().update(day_x, mtm);
                tick_total_mtm += mtm;
            }
            let session_x = global_step as f64;
            let day_x = day_step as f64;
            total_fit.update(session_x, tick_total_mtm);
            day_total_fit.update(day_x, tick_total_mtm);
            global_step += 1;
            day_step += 1;

            prev_own_trades = own_trades_this_tick;
            prev_market_trades = market_trades_this_tick;
        }

        // End-of-day: lock per-product PnL using the final-tick fair value.
        let mut day_product_stats: HashMap<String, ProductStats> = HashMap::new();
        let mut day_total_pnl = 0.0;
        for product in products.iter().copied() {
            let product_key = product.to_string();
            let ledger = ledgers.get(&product_key).context("missing ledger for eod")?;
            let fair = match product {
                "ASH_COATED_OSMIUM" => OSMIUM_FAIR_VALUE as f64,
                "INTARIAN_PEPPER_ROOT" => pepper_latent_fair(day, config.ticks_per_day - 1),
                _ => 0.0,
            };
            let pnl = ledger.cash + ledger.position as f64 * fair;
            day_total_pnl += pnl;
            *product_totals.get_mut(&product_key).unwrap() += pnl;
            *product_cash.get_mut(&product_key).unwrap() += ledger.cash;
            *product_final_pos.get_mut(&product_key).unwrap() = ledger.position;
            let fit = day_product_fits.get(&product_key).unwrap();
            day_product_stats.insert(
                product_key.clone(),
                ProductStats {
                    pnl,
                    cash: ledger.cash,
                    position: ledger.position,
                    slope_per_step: fit.slope_per_step(),
                    r_squared: fit.r_squared(),
                },
            );
        }

        run_summaries.push(RunSummary {
            session_id,
            day,
            total_pnl: day_total_pnl,
            emerald_pnl: 0.0,
            tomato_pnl: 0.0,
            total_slope_per_step: day_total_fit.slope_per_step(),
            total_r2: day_total_fit.r_squared(),
            emerald_slope_per_step: 0.0,
            emerald_r2: 0.0,
            tomato_slope_per_step: 0.0,
            tomato_r2: 0.0,
            product_stats_json: serde_json::to_string(&day_product_stats)
                .unwrap_or_else(|_| "{}".to_string()),
        });

        day_outputs.push(DayOutput {
            day,
            price_rows,
            trade_rows,
            trace_rows,
        });
    }

    // Session-level stats.
    let mut session_stats: HashMap<String, ProductStats> = HashMap::new();
    for product in products.iter().copied() {
        let product_key = product.to_string();
        session_stats.insert(
            product_key.clone(),
            ProductStats {
                pnl: *product_totals.get(&product_key).unwrap_or(&0.0),
                cash: *product_cash.get(&product_key).unwrap_or(&0.0),
                position: *product_final_pos.get(&product_key).unwrap_or(&0),
                slope_per_step: product_fits.get(&product_key).unwrap().slope_per_step(),
                r_squared: product_fits.get(&product_key).unwrap().r_squared(),
            },
        );
    }
    let total_pnl: f64 = product_totals.values().sum();

    let summary = SessionSummary {
        session_id,
        total_pnl,
        emerald_pnl: 0.0,
        tomato_pnl: 0.0,
        emerald_position: 0,
        tomato_position: 0,
        emerald_cash: 0.0,
        tomato_cash: 0.0,
        total_slope_per_step: total_fit.slope_per_step(),
        total_r2: total_fit.r_squared(),
        emerald_slope_per_step: 0.0,
        emerald_r2: 0.0,
        tomato_slope_per_step: 0.0,
        tomato_r2: 0.0,
        product_stats_json: serde_json::to_string(&session_stats)
            .unwrap_or_else(|_| "{}".to_string()),
    };

    Ok(SessionOutput {
        session_id,
        summary,
        run_summaries,
        day_outputs,
    })
}

fn write_backtest_outputs(config: &Config, outputs: &[SessionOutput]) -> Result<()> {
    fs::create_dir_all(&config.output_dir)?;
    let summary_path = config.output_dir.join("session_summary.csv");
    let mut writer = WriterBuilder::new()
        .delimiter(b',')
        .from_path(&summary_path)
        .with_context(|| format!("failed to open {}", summary_path.display()))?;
    for output in outputs {
        writer.serialize(&output.summary)?;
    }
    writer.flush()?;

    let run_summary_path = config.output_dir.join("run_summary.csv");
    let mut run_writer = WriterBuilder::new()
        .delimiter(b',')
        .from_path(&run_summary_path)
        .with_context(|| format!("failed to open {}", run_summary_path.display()))?;
    for output in outputs {
        for run_summary in &output.run_summaries {
            run_writer.serialize(run_summary)?;
        }
    }
    run_writer.flush()?;

    let round_num = config.round.number();
    for output in outputs.iter().take(config.write_session_limit) {
        let round_dir = config
            .output_dir
            .join("sessions")
            .join(format!("session_{:05}", output.session_id))
            .join(config.round.dir_name());
        fs::create_dir_all(&round_dir)?;
        for day_output in &output.day_outputs {
            let price_path =
                round_dir.join(format!("prices_round_{}_day_{}.csv", round_num, day_output.day));
            let trade_path =
                round_dir.join(format!("trades_round_{}_day_{}.csv", round_num, day_output.day));
            let trace_path =
                round_dir.join(format!("trace_round_{}_day_{}.csv", round_num, day_output.day));
            let mut price_writer = WriterBuilder::new().delimiter(b';').from_path(&price_path)?;
            for row in &day_output.price_rows {
                price_writer.serialize(row)?;
            }
            price_writer.flush()?;

            let mut trade_writer = WriterBuilder::new().delimiter(b';').from_path(&trade_path)?;
            for row in &day_output.trade_rows {
                trade_writer.serialize(row)?;
            }
            trade_writer.flush()?;

            let mut trace_writer = WriterBuilder::new().delimiter(b';').from_path(&trace_path)?;
            for row in &day_output.trace_rows {
                trace_writer.serialize(row)?;
            }
            trace_writer.flush()?;
        }
    }

    Ok(())
}

fn write_run_log(config: &Config) -> Result<()> {
    let log_path = config.output_dir.join("run.log");
    let contents = format!(
        "seed={}\nfv_mode={:?}\ntrade_mode={:?}\ntomato_support={:?}\nactual_dir={}\nstrategy={}\nsessions={}\nwrite_session_limit={}\n",
        config.seed,
        config.fv_mode,
        config.trade_mode,
        config.tomato_support,
        config.actual_dir.display()
        ,
        config
            .strategy_path
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "".to_string()),
        config.sessions,
        config.write_session_limit,
    );
    fs::create_dir_all(&config.output_dir)?;
    fs::write(&log_path, contents)
        .with_context(|| format!("failed to write {}", log_path.display()))?;
    Ok(())
}

fn seed_for_day(seed: u64, day: i32) -> u64 {
    let mut value = seed ^ (day as i64 as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
    value ^= value >> 33;
    value = value.wrapping_mul(0xFF51_AFD7_ED55_8CCD);
    value ^= value >> 33;
    value
}

fn seed_for_session_day(seed: u64, session_id: usize, day: i32) -> u64 {
    seed_for_day(seed ^ ((session_id as u64).wrapping_mul(0xA24B_AED4_963E_E407)), day)
}

fn empty_trade_map() -> HashMap<String, Vec<Fill>> {
    HashMap::from([
        ("EMERALDS".to_string(), Vec::new()),
        ("TOMATOES".to_string(), Vec::new()),
    ])
}

fn empty_trade_map_for(products: &[&str]) -> HashMap<String, Vec<Fill>> {
    products.iter().map(|p| (p.to_string(), Vec::new())).collect()
}

fn fills_to_worker_trade_map(source: &HashMap<String, Vec<Fill>>) -> HashMap<String, Vec<WorkerTrade>> {
    fills_to_worker_trade_map_for(source, &PRODUCTS)
}

fn fills_to_worker_trade_map_for(
    source: &HashMap<String, Vec<Fill>>,
    products: &[&str],
) -> HashMap<String, Vec<WorkerTrade>> {
    products
        .iter()
        .map(|product| {
            let trades = source
                .get(*product)
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .map(|fill| WorkerTrade {
                    symbol: fill.symbol,
                    price: fill.price,
                    quantity: fill.quantity,
                    buyer: fill.buyer,
                    seller: fill.seller,
                    timestamp: fill.timestamp,
                })
                .collect::<Vec<_>>();
            ((*product).to_string(), trades)
        })
        .collect()
}

fn book_to_worker_depth(book: &Book) -> WorkerOrderDepth {
    let buy_orders = book
        .bids
        .iter()
        .map(|(price, qty)| (price.to_string(), *qty))
        .collect::<HashMap<_, _>>();
    let sell_orders = book
        .asks
        .iter()
        .map(|(price, qty)| (price.to_string(), -*qty))
        .collect::<HashMap<_, _>>();
    WorkerOrderDepth {
        buy_orders,
        sell_orders,
    }
}

fn book_to_sim_book(book: &Book) -> SimBook {
    SimBook {
        bids: book
            .bids
            .iter()
            .map(|(price, quantity)| Level {
                price: *price,
                quantity: *quantity,
                owner: LevelOwner::Bot,
            })
            .collect(),
        asks: book
            .asks
            .iter()
            .map(|(price, quantity)| Level {
                price: *price,
                quantity: *quantity,
                owner: LevelOwner::Bot,
            })
            .collect(),
    }
}

fn normalize_strategy_orders(
    raw: HashMap<String, Vec<WorkerOrder>>,
) -> HashMap<String, Vec<WorkerOrder>> {
    // Legacy helper: normalises for round 0. Kept for the R0 session runner.
    normalize_strategy_orders_for(raw, &PRODUCTS)
}

fn normalize_strategy_orders_for(
    raw: HashMap<String, Vec<WorkerOrder>>,
    products: &[&str],
) -> HashMap<String, Vec<WorkerOrder>> {
    products
        .iter()
        .map(|product| {
            (
                (*product).to_string(),
                raw.get(*product).cloned().unwrap_or_default(),
            )
        })
        .collect()
}

fn enforce_strategy_limits(
    orders: &HashMap<String, Vec<WorkerOrder>>,
    ledgers: &HashMap<String, ProductLedger>,
) -> HashMap<String, Vec<WorkerOrder>> {
    orders
        .iter()
        .map(|(product, product_orders)| {
            let current_position = ledgers.get(product).map(|ledger| ledger.position).unwrap_or(0);
            let total_buy: i32 = product_orders
                .iter()
                .filter(|order| order.quantity > 0)
                .map(|order| order.quantity)
                .sum();
            let total_sell: i32 = product_orders
                .iter()
                .filter(|order| order.quantity < 0)
                .map(|order| -order.quantity)
                .sum();

            let limit = position_limit_for(product);
            let accepted = if current_position + total_buy > limit
                || current_position - total_sell < -limit
            {
                Vec::new()
            } else {
                product_orders.clone()
            };

            (product.clone(), accepted)
        })
        .collect()
}

fn execute_strategy_orders(
    product: &str,
    timestamp: i32,
    book: &mut SimBook,
    ledger: &mut ProductLedger,
    orders: &[WorkerOrder],
) -> Vec<Fill> {
    let mut fills = Vec::new();
    let mut passive_bids: HashMap<i32, i32> = HashMap::new();
    let mut passive_asks: HashMap<i32, i32> = HashMap::new();

    for order in orders {
        if order.quantity > 0 {
            let mut remaining = order.quantity;
            while remaining > 0 {
                let Some(best_ask) = book.asks.first_mut() else {
                    break;
                };
                if best_ask.owner != LevelOwner::Bot || best_ask.price > order.price {
                    break;
                }
                let fill_qty = remaining.min(best_ask.quantity);
                fills.push(Fill {
                    symbol: product.to_string(),
                    price: best_ask.price,
                    quantity: fill_qty,
                    buyer: Some("SUBMISSION".to_string()),
                    seller: Some("BOT".to_string()),
                    timestamp,
                });
                ledger.position += fill_qty;
                ledger.cash -= best_ask.price as f64 * fill_qty as f64;
                remaining -= fill_qty;
                best_ask.quantity -= fill_qty;
                if best_ask.quantity == 0 {
                    book.asks.remove(0);
                }
            }
            if remaining > 0 {
                *passive_bids.entry(order.price).or_insert(0) += remaining;
            }
        } else if order.quantity < 0 {
            let mut remaining = -order.quantity;
            while remaining > 0 {
                let Some(best_bid) = book.bids.first_mut() else {
                    break;
                };
                if best_bid.owner != LevelOwner::Bot || best_bid.price < order.price {
                    break;
                }
                let fill_qty = remaining.min(best_bid.quantity);
                fills.push(Fill {
                    symbol: product.to_string(),
                    price: best_bid.price,
                    quantity: fill_qty,
                    buyer: Some("BOT".to_string()),
                    seller: Some("SUBMISSION".to_string()),
                    timestamp,
                });
                ledger.position -= fill_qty;
                ledger.cash += best_bid.price as f64 * fill_qty as f64;
                remaining -= fill_qty;
                best_bid.quantity -= fill_qty;
                if best_bid.quantity == 0 {
                    book.bids.remove(0);
                }
            }
            if remaining > 0 {
                *passive_asks.entry(order.price).or_insert(0) += remaining;
            }
        }
    }

    for (price, quantity) in passive_bids {
        insert_level(
            &mut book.bids,
            Level {
                price,
                quantity,
                owner: LevelOwner::Strategy,
            },
            true,
        );
    }
    for (price, quantity) in passive_asks {
        insert_level(
            &mut book.asks,
            Level {
                price,
                quantity,
                owner: LevelOwner::Strategy,
            },
            false,
        );
    }

    fills
}

fn execute_taker_trade(
    product: &str,
    timestamp: i32,
    book: &mut SimBook,
    ledger: &mut ProductLedger,
    market_buy: bool,
    rng: &mut ChaCha8Rng,
) -> Vec<Fill> {
    let mut fills = Vec::new();
    let available_volume = if market_buy {
        book.asks.iter().map(|level| level.quantity).sum()
    } else {
        book.bids.iter().map(|level| level.quantity).sum()
    };
    if available_volume <= 0 {
        return fills;
    }

    let mut remaining = sample_trade_quantity_by_side(product, market_buy, available_volume, rng);

    while remaining > 0 {
        let (price, owner, fill_qty) = if market_buy {
            let Some(best_ask) = book.asks.first_mut() else {
                break;
            };
            let fill_qty = remaining.min(best_ask.quantity);
            let price = best_ask.price;
            let owner = best_ask.owner;
            best_ask.quantity -= fill_qty;
            if best_ask.quantity == 0 {
                book.asks.remove(0);
            }
            (price, owner, fill_qty)
        } else {
            let Some(best_bid) = book.bids.first_mut() else {
                break;
            };
            let fill_qty = remaining.min(best_bid.quantity);
            let price = best_bid.price;
            let owner = best_bid.owner;
            best_bid.quantity -= fill_qty;
            if best_bid.quantity == 0 {
                book.bids.remove(0);
            }
            (price, owner, fill_qty)
        };

        if fill_qty <= 0 {
            break;
        }

        let fill = match (market_buy, owner) {
            (true, LevelOwner::Bot) => Fill {
                symbol: product.to_string(),
                price,
                quantity: fill_qty,
                buyer: Some("BOT_TAKER".to_string()),
                seller: Some("BOT_MAKER".to_string()),
                timestamp,
            },
            (true, LevelOwner::Strategy) => {
                ledger.position -= fill_qty;
                ledger.cash += price as f64 * fill_qty as f64;
                Fill {
                    symbol: product.to_string(),
                    price,
                    quantity: fill_qty,
                    buyer: Some("BOT_TAKER".to_string()),
                    seller: Some("SUBMISSION".to_string()),
                    timestamp,
                }
            }
            (false, LevelOwner::Bot) => Fill {
                symbol: product.to_string(),
                price,
                quantity: fill_qty,
                buyer: Some("BOT_MAKER".to_string()),
                seller: Some("BOT_TAKER".to_string()),
                timestamp,
            },
            (false, LevelOwner::Strategy) => {
                ledger.position += fill_qty;
                ledger.cash -= price as f64 * fill_qty as f64;
                Fill {
                    symbol: product.to_string(),
                    price,
                    quantity: fill_qty,
                    buyer: Some("SUBMISSION".to_string()),
                    seller: Some("BOT_TAKER".to_string()),
                    timestamp,
                }
            }
        };
        fills.push(fill);
        remaining -= fill_qty;
    }

    fills
}

fn insert_level(levels: &mut Vec<Level>, level: Level, descending: bool) {
    if let Some(existing) = levels
        .iter_mut()
        .find(|existing| existing.price == level.price && existing.owner == level.owner)
    {
        existing.quantity += level.quantity;
    } else {
        levels.push(level);
    }
    if descending {
        levels.sort_by(|a, b| b.price.cmp(&a.price).then(owner_priority(a.owner).cmp(&owner_priority(b.owner))));
    } else {
        levels.sort_by(|a, b| a.price.cmp(&b.price).then(owner_priority(a.owner).cmp(&owner_priority(b.owner))));
    }
}

fn owner_priority(owner: LevelOwner) -> i32 {
    match owner {
        LevelOwner::Bot => 0,
        LevelOwner::Strategy => 1,
    }
}

fn fill_involves_strategy(fill: &Fill) -> bool {
    fill.buyer.as_deref() == Some("SUBMISSION") || fill.seller.as_deref() == Some("SUBMISSION")
}

fn fill_to_trade_row(fill: &Fill) -> TradeRow {
    TradeRow {
        timestamp: fill.timestamp,
        buyer: fill.buyer.clone(),
        seller: fill.seller.clone(),
        symbol: fill.symbol.clone(),
        currency: "XIRECS".to_string(),
        price: fill.price as f64,
        quantity: fill.quantity,
    }
}

fn sample_trade_side(product: &str, rng: &mut ChaCha8Rng) -> bool {
    let buy_prob = match product {
        "EMERALDS" => EMERALDS_TRADE_BUY_PROB,
        "TOMATOES" => TOMATOES_TRADE_BUY_PROB,
        "ASH_COATED_OSMIUM" => OSMIUM_TRADE_BUY_PROB,
        "INTARIAN_PEPPER_ROOT" => PEPPER_TRADE_BUY_PROB,
        "HYDROGEL_PACK" => HYDROGEL_TRADE_BUY_PROB,
        "VELVETFRUIT_EXTRACT" => VELVET_TRADE_BUY_PROB,
        p if p.starts_with("VEV_") => VEV_TRADE_BUY_PROB,
        _ => 0.5,
    };
    rng.gen_bool(buy_prob)
}

/// Infer the round number from an `actual_dir` path like `.../round0` or
/// `.../round2`. Falls back to 0 so legacy callers keep working.
fn round_num_from_dir(actual_dir: &Path) -> i32 {
    actual_dir
        .file_name()
        .and_then(|s| s.to_str())
        .and_then(|name| name.strip_prefix("round"))
        .and_then(|n| n.parse::<i32>().ok())
        .unwrap_or(0)
}

fn load_price_rows(actual_dir: &Path, day: i32) -> Result<Vec<InputPriceRow>> {
    let round = round_num_from_dir(actual_dir);
    let path = actual_dir.join(format!("prices_round_{}_day_{}.csv", round, day));
    let mut reader = ReaderBuilder::new()
        .delimiter(b';')
        .from_path(&path)
        .with_context(|| format!("failed to read {}", path.display()))?;
    let mut rows = Vec::new();
    for record in reader.deserialize() {
        let row: InputPriceRow = record?;
        rows.push(row);
    }
    Ok(rows)
}

fn load_trade_rows(actual_dir: &Path, day: i32) -> Result<Vec<InputTradeRow>> {
    let round = round_num_from_dir(actual_dir);
    let path = actual_dir.join(format!("trades_round_{}_day_{}.csv", round, day));
    let mut reader = ReaderBuilder::new()
        .delimiter(b';')
        .from_path(&path)
        .with_context(|| format!("failed to read {}", path.display()))?;
    let mut rows = Vec::new();
    for record in reader.deserialize() {
        let row: InputTradeRow = record?;
        rows.push(row);
    }
    Ok(rows)
}

fn infer_observed_fair(row: &InputPriceRow) -> f64 {
    let bids = [row.bid_price_1, row.bid_price_2, row.bid_price_3]
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();
    let asks = [row.ask_price_1, row.ask_price_2, row.ask_price_3]
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();
    let worst_bid = bids.into_iter().min().unwrap_or(0);
    let worst_ask = asks.into_iter().max().unwrap_or(0);
    (worst_bid as f64 + worst_ask as f64) / 2.0
}

fn estimate_tomato_latent_state(row: &InputPriceRow) -> TomatoLatentState {
    let Some((inner_bid, outer_bid, inner_ask, outer_ask)) = tomato_wall_quotes(row) else {
        return TomatoLatentState {
            fair: infer_observed_fair(row),
            half_tie_orientation: HalfTieOrientation::Inward,
        };
    };

    let intervals = [
        interval_from_quote(outer_bid, -8.0),
        interval_from_quote(outer_ask, 8.0),
        interval_from_quote(inner_bid, -6.5),
        interval_from_quote(inner_ask, 6.5),
    ];

    let lower = intervals
        .iter()
        .map(|(lo, _)| *lo)
        .fold(f64::NEG_INFINITY, f64::max);
    let upper = intervals
        .iter()
        .map(|(_, hi)| *hi)
        .fold(f64::INFINITY, f64::min);

    let fair = if lower <= upper {
        (lower + upper) / 2.0
    } else {
        (outer_bid as f64 + outer_ask as f64) / 2.0
    };
    let half_tie_orientation = match outer_ask - outer_bid {
        15 => HalfTieOrientation::Inward,
        17 => HalfTieOrientation::Outward,
        _ => HalfTieOrientation::Inward,
    };

    TomatoLatentState {
        fair,
        half_tie_orientation,
    }
}

fn tomato_wall_quotes(row: &InputPriceRow) -> Option<(i32, i32, i32, i32)> {
    let bid3 = row.bid_price_3.is_some();
    let ask3 = row.ask_price_3.is_some();

    match (bid3, ask3) {
        (false, false) => Some((
            row.bid_price_1?,
            row.bid_price_2?,
            row.ask_price_1?,
            row.ask_price_2?,
        )),
        (true, false) => Some((
            row.bid_price_2?,
            row.bid_price_3?,
            row.ask_price_1?,
            row.ask_price_2?,
        )),
        (false, true) => Some((
            row.bid_price_1?,
            row.bid_price_2?,
            row.ask_price_2?,
            row.ask_price_3?,
        )),
        (true, true) => None,
    }
}

fn interval_from_quote(price: i32, offset: f64) -> (f64, f64) {
    (
        price as f64 - 0.5 - offset,
        price as f64 + 0.5 - offset,
    )
}

fn trade_counts_for(
    product: &str,
    day: i32,
    config: &Config,
    replay: &ReplayData,
    rng: &mut ChaCha8Rng,
) -> Result<Vec<usize>> {
    match config.trade_mode {
        TradeMode::ReplayTimes => replay
            .trade_counts_by_key
            .get(&(day, product.to_string()))
            .cloned()
            .context("missing replay trade count series"),
        TradeMode::Simulate => Ok(simulate_trade_counts(product, config.ticks_per_day, rng)),
    }
}

fn simulate_trade_counts(product: &str, ticks: usize, rng: &mut ChaCha8Rng) -> Vec<usize> {
    let (base_prob, second_trade_prob) = match product {
        "EMERALDS" => (EMERALDS_TRADE_ACTIVE_PROB, 0.0),
        "TOMATOES" => (TOMATOES_TRADE_ACTIVE_PROB, TOMATOES_SECOND_TRADE_PROB),
        "ASH_COATED_OSMIUM" => (OSMIUM_TRADE_ACTIVE_PROB, OSMIUM_SECOND_TRADE_PROB),
        "INTARIAN_PEPPER_ROOT" => (PEPPER_TRADE_ACTIVE_PROB, PEPPER_SECOND_TRADE_PROB),
        "HYDROGEL_PACK" => (HYDROGEL_TRADE_ACTIVE_PROB, 0.0),
        "VELVETFRUIT_EXTRACT" => (VELVET_TRADE_ACTIVE_PROB, VELVET_SECOND_TRADE_PROB),
        "VEV_6000" | "VEV_6500" => (VEV_TRADE_ACTIVE_PROB_PINNED, 0.0),
        p if p.starts_with("VEV_") => (VEV_TRADE_ACTIVE_PROB_ACTIVE, 0.0),
        _ => (0.0, 0.0),
    };
    let mut counts = vec![0usize; ticks];
    for count in &mut counts {
        if rng.gen_bool(base_prob) {
            *count = 1;
            if second_trade_prob > 0.0 && rng.gen_bool(second_trade_prob) {
                *count += 1;
            }
        }
    }
    counts
}

fn simulate_tomato_fair(
    day: i32,
    support: TomatoSupport,
    ticks: usize,
    rng: &mut ChaCha8Rng,
) -> Vec<TomatoLatentState> {
    let start = if day == -1 { 5006.0 } else { 5000.0 };
    let sigma = 0.496;
    let mut states = vec![
        TomatoLatentState {
            fair: 0.0,
            half_tie_orientation: HalfTieOrientation::Inward,
        };
        ticks
    ];
    let mut orientation = if rng.gen_bool(0.5) {
        HalfTieOrientation::Inward
    } else {
        HalfTieOrientation::Outward
    };
    states[0] = TomatoLatentState {
        fair: quantize_tomato_fair(start, support),
        half_tie_orientation: orientation,
    };

    for index in 1..ticks {
        let step = sigma * sample_standard_normal(rng);
        if rng.gen_bool(TOMATO_HALF_TIE_FLIP_PROB) {
            orientation = orientation.flip();
        }
        states[index] = TomatoLatentState {
            fair: quantize_tomato_fair(states[index - 1].fair + step, support),
            half_tie_orientation: orientation,
        };
    }

    states
}

fn quantize_tomato_fair(value: f64, support: TomatoSupport) -> f64 {
    match support {
        TomatoSupport::Continuous => value,
        TomatoSupport::Half => (value * 2.0).round() / 2.0,
        TomatoSupport::Quarter => (value * 4.0).round() / 4.0,
    }
}

fn sample_standard_normal(rng: &mut ChaCha8Rng) -> f64 {
    let u1 = rng.gen_range(f64::EPSILON..1.0);
    let u2 = rng.gen_range(0.0..1.0);
    (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
}

fn make_emerald_book(rng: &mut ChaCha8Rng) -> Book {
    let fair = 10_000;
    let inner_size = rng.gen_range(10..=15);
    let outer_size = rng.gen_range(20..=30);
    let draw: f64 = rng.gen_range(0.0..1.0);

    if draw < 321.0 / 20_000.0 {
        let bot3_size = rng.gen_range(5..=10);
        Book {
            bids: vec![
                (fair, bot3_size),
                (fair - 8, inner_size),
                (fair - 10, outer_size),
            ],
            asks: vec![(fair + 8, inner_size), (fair + 10, outer_size)],
        }
    } else if draw < (321.0 + 333.0) / 20_000.0 {
        let bot3_size = rng.gen_range(5..=10);
        Book {
            bids: vec![(fair - 8, inner_size), (fair - 10, outer_size)],
            asks: vec![
                (fair, bot3_size),
                (fair + 8, inner_size),
                (fair + 10, outer_size),
            ],
        }
    } else {
        Book {
            bids: vec![(fair - 8, inner_size), (fair - 10, outer_size)],
            asks: vec![(fair + 8, inner_size), (fair + 10, outer_size)],
        }
    }
}

fn make_tomato_book(latent_state: TomatoLatentState, rng: &mut ChaCha8Rng) -> Book {
    let outer_size = rng.gen_range(15..=25);
    let inner_size = rng.gen_range(5..=10);
    let (outer_bid, outer_ask) = tomato_outer_quotes(latent_state);
    let (inner_bid, inner_ask) = tomato_inner_quotes(latent_state.fair);
    let draw: f64 = rng.gen_range(0.0..1.0);

    // Bot 3: 6.3% presence, 50/50 bid/ask
    if draw < 0.063 / 2.0 {
        let (bot3_price, bot3_size) = tomato_bot3_bid_quote(latent_state.fair, rng);
        Book {
            bids: vec![
                (bot3_price, bot3_size),
                (inner_bid, inner_size),
                (outer_bid, outer_size),
            ],
            asks: vec![(inner_ask, inner_size), (outer_ask, outer_size)],
        }
    } else if draw < 0.063 {
        let (bot3_price, bot3_size) = tomato_bot3_ask_quote(latent_state.fair, rng);
        Book {
            bids: vec![(inner_bid, inner_size), (outer_bid, outer_size)],
            asks: vec![
                (bot3_price, bot3_size),
                (inner_ask, inner_size),
                (outer_ask, outer_size),
            ],
        }
    } else {
        Book {
            bids: vec![(inner_bid, inner_size), (outer_bid, outer_size)],
            asks: vec![(inner_ask, inner_size), (outer_ask, outer_size)],
        }
    }
}

fn tomato_outer_quotes(latent_state: TomatoLatentState) -> (i32, i32) {
    let bid_target = latent_state.fair - 8.0;
    let ask_target = latent_state.fair + 8.0;

    if is_half_tie(bid_target) && is_half_tie(ask_target) {
        // Bot 1 is deterministic once the latent half-tie orientation bit is
        // part of the shared fair state. Bot 2 ignores this bit because its
        // +/-6.5 targets on half-mid rows land on exact integers.
        match latent_state.half_tie_orientation {
            HalfTieOrientation::Inward => (round_up(bid_target), round_down(ask_target)),
            HalfTieOrientation::Outward => (round_down(bid_target), round_up(ask_target)),
        }
    } else {
        (round_nearest(bid_target), round_nearest(ask_target))
    }
}

fn tomato_inner_quotes(latent_fair: f64) -> (i32, i32) {
    // Calibrated: bid rounds at frac=0.25, ask rounds at frac=0.75
    // bid = floor(FV + 0.75) - 7
    // ask = ceil(FV + 0.25) + 6
    let bid = (latent_fair + 0.75).floor() as i32 - 7;
    let ask = (latent_fair + 0.25).ceil() as i32 + 6;
    (bid, ask)
}

fn tomato_bot3_bid_quote(latent_fair: f64, rng: &mut ChaCha8Rng) -> (i32, i32) {
    // 2/3 passive (offset -2 or -1), 1/3 aggressive (offset 0 or +1)
    // 50/50 within each group
    let passive = rng.gen_bool(2.0 / 3.0);
    let near = rng.gen_bool(0.5);
    let offset = if passive {
        if near { -1 } else { -2 }
    } else {
        if near { 0 } else { 1 }
    };
    let price = round_nearest(latent_fair) + offset;
    let size = if passive {
        rng.gen_range(2..=6)
    } else {
        rng.gen_range(5..=12)
    };
    (price, size)
}

fn tomato_bot3_ask_quote(latent_fair: f64, rng: &mut ChaCha8Rng) -> (i32, i32) {
    // 2/3 passive (offset 0 or +1), 1/3 aggressive (offset -2 or -1)
    // 50/50 within each group
    let passive = rng.gen_bool(2.0 / 3.0);
    let near = rng.gen_bool(0.5);
    let offset = if passive {
        if near { 0 } else { 1 }
    } else {
        if near { -1 } else { -2 }
    };
    let price = round_nearest(latent_fair) + offset;
    let size = if passive {
        rng.gen_range(2..=6)
    } else {
        rng.gen_range(5..=12)
    };
    (price, size)
}

// ============================================================================
// Round 2 — ASH_COATED_OSMIUM and INTARIAN_PEPPER_ROOT
// ----------------------------------------------------------------------------
// All numeric parameters come from docs/round2_params.json (produced by
// scripts/round2_calibration/calibrate_round2.py). Anything hard-coded here
// maps 1:1 to the JSON so the two can be re-synchronised after recalibration.
// ============================================================================

/// Deterministic PEP fair value — docs/round2_params.json -> PEP.fv.
/// Per-day start values are exactly 11000 / 12000 / 13000 within noise.
fn pepper_latent_fair(day: i32, tick: usize) -> f64 {
    let start = match day {
        -1 => PEPPER_START_DAY_NEG1,
        0 => PEPPER_START_DAY_0,
        1 => PEPPER_START_DAY_POS1,
        // Extrapolate linearly for other days so the simulator can be exercised
        // with `--ticks-per-day` / custom day lists without panicking.
        other => PEPPER_START_DAY_0 + (other as f64) * 1_000.0,
    };
    start + PEPPER_DRIFT_PER_TICK * (tick as f64)
}

/// Near-mid noise bot for OSM. Offsets modal at ±4 and falling off inward;
/// see docs/round2_params.json -> OSM.book.bot3_{bid,ask}_offset_hist. 83%
/// passive (same side as the quote), matches bot3_passive_frac.
fn osmium_bot3_quote(is_bid: bool, fair: i32, rng: &mut ChaCha8Rng) -> (i32, i32) {
    let passive = rng.gen_bool(0.83);
    // Modal offset magnitude is 4; taper to 3,2,1 with decreasing weight.
    let offset_mag = match rng.gen_range(0..100) {
        0..=44 => 4,
        45..=74 => 3,
        75..=89 => 2,
        _ => 1,
    };
    let offset = if passive {
        if is_bid { -offset_mag } else { offset_mag }
    } else {
        if is_bid { offset_mag } else { -offset_mag }
    };
    let size = rng.gen_range(2..=15);
    (fair + offset, size)
}

/// OSM book generator — docs/round2_params.json -> OSM.book.
fn make_osmium_book(rng: &mut ChaCha8Rng) -> Book {
    let fair = OSMIUM_FAIR_VALUE;
    let wall_size_bid = rng.gen_range(20..=30);
    let wall_size_ask = rng.gen_range(20..=30);
    let inner_size_bid = rng.gen_range(10..=15);
    let inner_size_ask = rng.gen_range(10..=15);
    let bid_wall = fair - 10;
    let ask_wall = fair + 9;
    let bid_inner = fair - 8;
    let ask_inner = fair + 8;

    // Inner-drop probability: empirical spread mean 16.23 decomposes into
    // (inner-present, spread 16) × 0.92 + (wall-only, spread 19) × 0.08.
    // See scripts/round2_calibration/validate_round2.py.
    let bid_has_inner = !rng.gen_bool(0.08);
    let ask_has_inner = !rng.gen_bool(0.08);

    let has_bid_bot3 = rng.gen_bool(0.04);
    let has_ask_bot3 = rng.gen_bool(0.04);

    let mut bids: Vec<(i32, i32)> = vec![(bid_wall, wall_size_bid)];
    if bid_has_inner {
        bids.push((bid_inner, inner_size_bid));
    }
    let mut asks: Vec<(i32, i32)> = vec![(ask_wall, wall_size_ask)];
    if ask_has_inner {
        asks.push((ask_inner, inner_size_ask));
    }

    if has_bid_bot3 {
        let (p, s) = osmium_bot3_quote(true, fair, rng);
        // Insert as the best bid (front of vector).
        bids.insert(0, (p, s));
    }
    if has_ask_bot3 {
        let (p, s) = osmium_bot3_quote(false, fair, rng);
        asks.insert(0, (p, s));
    }

    // Sort levels so bids are high→low and asks are low→high (the downstream
    // CSV writer takes level 1 as top-of-book).
    bids.sort_by(|a, b| b.0.cmp(&a.0));
    asks.sort_by(|a, b| a.0.cmp(&b.0));

    // Truncate to top-3 levels per side (matching the input schema).
    bids.truncate(3);
    asks.truncate(3);
    Book { bids, asks }
}

/// Near-mid noise bot for PEP. Aggressive fraction is ~70% (passive_frac ≈
/// 0.31) and offsets are modal at ±3/±4 — docs/round2_params.json ->
/// PEP.book.bot3_*_offset_hist.
fn pepper_bot3_quote(is_bid: bool, fair: i32, rng: &mut ChaCha8Rng) -> (i32, i32) {
    let passive = rng.gen_bool(0.31);
    let offset_mag = if rng.gen_bool(0.66) { 4 } else { 3 };
    let offset = if passive {
        if is_bid { -offset_mag } else { offset_mag }
    } else {
        if is_bid { offset_mag } else { -offset_mag }
    };
    let size = rng.gen_range(3..=12);
    (fair + offset, size)
}

/// PEP book generator — docs/round2_params.json -> PEP.book.
fn make_pepper_book(latent_fair: f64, rng: &mut ChaCha8Rng) -> Book {
    let fair = latent_fair.floor() as i32;
    let wall_size_bid = rng.gen_range(15..=25);
    let wall_size_ask = rng.gen_range(15..=25);
    let inner_size_bid = rng.gen_range(8..=12);
    let inner_size_ask = rng.gen_range(8..=12);
    let bid_wall = fair - 10;
    let ask_wall = fair + 10;
    let bid_inner = fair - 6;
    let ask_inner = fair + 7;

    // Inner-drop probability: empirical spread mean 14.12 decomposes into
    // (inner-present, spread 13) × 0.84 + (wall-only, spread 20) × 0.16.
    let bid_has_inner = !rng.gen_bool(0.16);
    let ask_has_inner = !rng.gen_bool(0.16);

    let has_bid_bot3 = rng.gen_bool(0.03);
    let has_ask_bot3 = rng.gen_bool(0.015);

    let mut bids: Vec<(i32, i32)> = vec![(bid_wall, wall_size_bid)];
    if bid_has_inner {
        bids.push((bid_inner, inner_size_bid));
    }
    let mut asks: Vec<(i32, i32)> = vec![(ask_wall, wall_size_ask)];
    if ask_has_inner {
        asks.push((ask_inner, inner_size_ask));
    }

    if has_bid_bot3 {
        let (p, s) = pepper_bot3_quote(true, fair, rng);
        bids.insert(0, (p, s));
    }
    if has_ask_bot3 {
        let (p, s) = pepper_bot3_quote(false, fair, rng);
        asks.insert(0, (p, s));
    }

    bids.sort_by(|a, b| b.0.cmp(&a.0));
    asks.sort_by(|a, b| a.0.cmp(&b.0));
    bids.truncate(3);
    asks.truncate(3);
    Book { bids, asks }
}

fn round_nearest(value: f64) -> i32 {
    value.round() as i32
}

fn round_down(value: f64) -> i32 {
    value.floor() as i32
}

fn round_up(value: f64) -> i32 {
    value.ceil() as i32
}

fn is_half_tie(value: f64) -> bool {
    ((value.fract().abs()) - 0.5).abs() < 1e-9
}

fn book_to_price_row(day: i32, timestamp: i32, product: &str, book: &Book) -> PriceRow {
    let bid1 = book.bids.first().copied();
    let bid2 = book.bids.get(1).copied();
    let bid3 = book.bids.get(2).copied();
    let ask1 = book.asks.first().copied();
    let ask2 = book.asks.get(1).copied();
    let ask3 = book.asks.get(2).copied();
    let mid_price = (book.bids[0].0 as f64 + book.asks[0].0 as f64) / 2.0;

    PriceRow {
        day,
        timestamp,
        product: product.to_string(),
        bid_price_1: bid1.map(|x| x.0),
        bid_volume_1: bid1.map(|x| x.1),
        bid_price_2: bid2.map(|x| x.0),
        bid_volume_2: bid2.map(|x| x.1),
        bid_price_3: bid3.map(|x| x.0),
        bid_volume_3: bid3.map(|x| x.1),
        ask_price_1: ask1.map(|x| x.0),
        ask_volume_1: ask1.map(|x| x.1),
        ask_price_2: ask2.map(|x| x.0),
        ask_volume_2: ask2.map(|x| x.1),
        ask_price_3: ask3.map(|x| x.0),
        ask_volume_3: ask3.map(|x| x.1),
        mid_price,
        profit_and_loss: 0.0,
    }
}

fn sample_trade_rows(timestamp: i32, product: &str, book: &Book, rng: &mut ChaCha8Rng) -> Vec<TradeRow> {
    let market_buy = sample_trade_side(product, rng);
    let available_volume: i32 = if market_buy {
        book.asks.iter().map(|(_, volume)| *volume).sum()
    } else {
        book.bids.iter().map(|(_, volume)| *volume).sum()
    };
    if available_volume <= 0 {
        return Vec::new();
    }

    let quantity = sample_trade_quantity_by_side(product, market_buy, available_volume, rng);

    let mut rows = Vec::new();
    let mut remaining = quantity;
    if market_buy {
        for (price, volume_limit) in &book.asks {
            if remaining <= 0 {
                break;
            }
            let fill_qty = remaining.min(*volume_limit);
            rows.push(TradeRow {
                timestamp,
                buyer: None,
                seller: None,
                symbol: product.to_string(),
                currency: "XIRECS".to_string(),
                price: *price as f64,
                quantity: fill_qty,
            });
            remaining -= fill_qty;
        }
    } else {
        for (price, volume_limit) in &book.bids {
            if remaining <= 0 {
                break;
            }
            let fill_qty = remaining.min(*volume_limit);
            rows.push(TradeRow {
                timestamp,
                buyer: None,
                seller: None,
                symbol: product.to_string(),
                currency: "XIRECS".to_string(),
                price: *price as f64,
                quantity: fill_qty,
            });
            remaining -= fill_qty;
        }
    }

    rows
}

fn sample_trade_quantity_by_side(
    product: &str,
    market_buy: bool,
    volume_limit: i32,
    rng: &mut ChaCha8Rng,
) -> i32 {
    // Round 2 quantity supports come from docs/round2_params.json ->
    // {OSM,PEP}.taker.qty_support. Within the support we use a uniform prior
    // (side-independent) because buy/sell splits in R2 are ~50/50 and the
    // calibration data does not show a clear size-by-side bias.
    let (values, weights): (&[i32], &[u32]) = match (product, market_buy) {
        ("EMERALDS", true) => (&[3, 4, 5, 6, 7, 8], &[32, 30, 34, 36, 29, 34]),
        ("EMERALDS", false) => (&[3, 4, 5, 6, 7, 8], &[28, 33, 40, 49, 30, 24]),
        ("TOMATOES", true) => (&[2, 3, 4, 5, 6], &[99, 85, 101, 100, 2]),
        ("TOMATOES", false) => (&[2, 3, 4, 5], &[110, 125, 101, 97]),
        // Empirical qty histograms from data/round2/trades_round_2_day_*.csv
        // (Counter over 3 days). OSM tails off sharply past qty=6; PEP
        // distribution is roughly flat across [3,7] then tails off at 8.
        ("ASH_COATED_OSMIUM", _) => (
            &[2, 3, 4, 5, 6, 7, 8, 9, 10],
            &[199, 181, 209, 250, 238, 75, 108, 67, 68],
        ),
        ("INTARIAN_PEPPER_ROOT", _) => (&[3, 4, 5, 6, 7, 8], &[222, 181, 186, 180, 183, 44]),
        // R3 hists (docs/round3_params.json -> {HYDROGEL,VELVET,VEV_*}.taker.qty_hist)
        ("HYDROGEL_PACK", _) => (&[2, 3, 4, 5, 6], &[193, 198, 202, 212, 205]),
        ("VELVETFRUIT_EXTRACT", _) => (
            &[3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
            &[190, 189, 223, 212, 224, 233, 23, 29, 10, 11, 13, 9, 6],
        ),
        // VEV active-strike takers: moderate qty range. Pinned strikes never
        // receive trades so this arm is never reached for them.
        (p, _) if p.starts_with("VEV_") => (&[3, 4, 5, 6, 7, 8, 10], &[80, 90, 100, 95, 70, 50, 20]),
        _ => (&[1], &[1]),
    };

    let filtered = values
        .iter()
        .zip(weights.iter())
        .filter(|(value, _)| **value <= volume_limit)
        .map(|(value, weight)| (*value, *weight))
        .collect::<Vec<_>>();

    if filtered.is_empty() {
        return volume_limit.max(1);
    }

    let filtered_values = filtered.iter().map(|(value, _)| *value).collect::<Vec<_>>();
    let filtered_weights = filtered
        .iter()
        .map(|(_, weight)| *weight)
        .collect::<Vec<_>>();
    let chooser = WeightedIndex::new(filtered_weights).expect("valid filtered trade weights");
    filtered_values[chooser.sample(rng)]
}

// ============================================================================
// Round 3 — HYDROGEL_PACK, VELVETFRUIT_EXTRACT, VEV_* vouchers
// ----------------------------------------------------------------------------
// Parameters derived from data/round3/*.csv via
// scripts/round3_calibration/calibrate_round3.py. See
// docs/round3_params.json for provenance.
// ============================================================================

/// Black-Scholes european call with no interest rate.
fn bs_call(s: f64, k: f64, t: f64, sigma: f64) -> f64 {
    if t <= 0.0 || sigma <= 0.0 {
        return (s - k).max(0.0);
    }
    let vol = sigma * t.sqrt();
    let d1 = ((s / k).ln() + 0.5 * sigma * sigma * t) / vol;
    let d2 = d1 - vol;
    s * norm_cdf(d1) - k * norm_cdf(d2)
}

/// Standard normal CDF using Abramowitz & Stegun 7.1.26 (via erf).
fn norm_cdf(x: f64) -> f64 {
    // erf approx (max error ~1.5e-7). Source: A&S 7.1.26.
    let a1 = 0.254829592;
    let a2 = -0.284496736;
    let a3 = 1.421413741;
    let a4 = -1.453152027;
    let a5 = 1.061405429;
    let p = 0.3275911;
    let sign = if x < 0.0 { -1.0 } else { 1.0 };
    let abs_x = x.abs() / 2_f64.sqrt();
    let t = 1.0 / (1.0 + p * abs_x);
    let y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * (-abs_x * abs_x).exp();
    0.5 * (1.0 + sign * y)
}

/// Map a strike (e.g. 5400) to the corresponding product symbol ("VEV_5400").
/// Caller must ensure the strike is one of VEV_STRIKES; otherwise returns
/// an empty string which will trigger downstream unknown-product branches.
fn vev_product_name(strike: i32) -> &'static str {
    match strike {
        4000 => "VEV_4000",
        4500 => "VEV_4500",
        5000 => "VEV_5000",
        5100 => "VEV_5100",
        5200 => "VEV_5200",
        5300 => "VEV_5300",
        5400 => "VEV_5400",
        5500 => "VEV_5500",
        6000 => "VEV_6000",
        6500 => "VEV_6500",
        _ => "",
    }
}

/// Per-strike calibrated IV (flat assumption per strike). Returns 0.0 for
/// pinned strikes (6000, 6500) since the sim uses a fixed pinned book for
/// those, not a BS-derived one.
fn vev_iv_for_strike(strike: i32) -> f64 {
    match strike {
        4000 => VEV_IV_4000,
        4500 => VEV_IV_4500,
        5000 => VEV_IV_5000,
        5100 => VEV_IV_5100,
        5200 => VEV_IV_5200,
        5300 => VEV_IV_5300,
        5400 => VEV_IV_5400,
        5500 => VEV_IV_5500,
        _ => 0.0,
    }
}

/// Mean-reverting latent fair for delta-1 R3 products. AR(1) on level:
/// mid[t+1] = mean + phi * (mid[t] - mean) + innov_sigma * z[t].
///
/// Params:
/// - mean: long-run mean (e.g. HYDROGEL=9991, VELVET=5250)
/// - innov_sigma: per-tick innovation sigma (e.g. HYDROGEL=2.17)
/// - equil_std: target equilibrium standard deviation of the process (e.g.
///   HYDROGEL=32). phi is derived so that equilibrium std matches:
///     Var(x) = innov_sigma^2 / (1 - phi^2) = equil_std^2
///     phi = sqrt(1 - (innov_sigma / equil_std)^2)
///   Clamped to [0.5, 0.9999] to avoid numerical blow-ups.
fn simulate_delta1_path(
    mean: f64,
    innov_sigma: f64,
    equil_std: f64,
    ticks: usize,
    rng: &mut ChaCha8Rng,
) -> Vec<f64> {
    let ratio = innov_sigma / equil_std;
    let phi = (1.0 - ratio * ratio).max(0.25).sqrt().clamp(0.5, 0.9999);
    let mut out = vec![0.0; ticks];
    out[0] = mean;
    for i in 1..ticks {
        let z = sample_standard_normal(rng);
        out[i] = mean + phi * (out[i - 1] - mean) + innov_sigma * z;
    }
    out
}

/// HYDROGEL_PACK book generator. Calibrated from docs/round3_params.json ->
/// HYDROGEL.book. Outer wall at fair±10 with half-tie split to ±10/±11 on
/// half-integer mids, inner at fair±8, occasional bot-3 near-mid quote.
fn make_hydrogel_book(latent_fair: f64, rng: &mut ChaCha8Rng) -> Book {
    // Half-tie orientation — flip rarely; chosen fresh each call.
    let outward = rng.gen_bool(0.5);
    let (bid_outer, ask_outer) = if (latent_fair.fract().abs() - 0.5).abs() < 1e-9 {
        // Half-tie: split outer wall
        if outward {
            ((latent_fair - 10.0).floor() as i32, (latent_fair + 10.0).ceil() as i32)
        } else {
            ((latent_fair - 10.0).ceil() as i32, (latent_fair + 10.0).floor() as i32)
        }
    } else {
        (
            (latent_fair - 10.0).round() as i32,
            (latent_fair + 10.0).round() as i32,
        )
    };
    // Inner at fair±8 (integer by construction when fair is integer; otherwise round)
    let bid_inner = (latent_fair - 8.0).round() as i32;
    let ask_inner = (latent_fair + 8.0).round() as i32;

    // Volumes (U[20,30] outer, U[10,15] inner).
    let outer_size_bid = rng.gen_range(20..=30);
    let outer_size_ask = rng.gen_range(20..=30);
    let inner_size_bid = rng.gen_range(10..=15);
    let inner_size_ask = rng.gen_range(10..=15);

    // Presence: walls ~0.974, inners ~0.94 (per calibration).
    let has_bid_inner = !rng.gen_bool(0.06);
    let has_ask_inner = !rng.gen_bool(0.06);

    // Bot-3: 5.96% bid, 3.30% ask, passive side only.
    let has_bid_bot3 = rng.gen_bool(0.0596);
    let has_ask_bot3 = rng.gen_bool(0.0330);

    let mut bids: Vec<(i32, i32)> = vec![(bid_outer, outer_size_bid)];
    if has_bid_inner {
        bids.push((bid_inner, inner_size_bid));
    }
    let mut asks: Vec<(i32, i32)> = vec![(ask_outer, outer_size_ask)];
    if has_ask_inner {
        asks.push((ask_inner, inner_size_ask));
    }
    if has_bid_bot3 {
        // Passive bid at fair-N where N ∈ {3,4,5,6,7} modal at 7 and 4.
        let offset = match rng.gen_range(0..100) {
            0..=34 => -7,
            35..=64 => -4,
            65..=84 => -6,
            85..=94 => -3,
            _ => -5,
        };
        let p = (latent_fair + offset as f64).round() as i32;
        let s = rng.gen_range(4..=30);
        bids.insert(0, (p, s));
    }
    if has_ask_bot3 {
        let offset = match rng.gen_range(0..100) {
            0..=49 => 4,
            50..=79 => 7,
            80..=94 => 5,
            _ => 6,
        };
        let p = (latent_fair + offset as f64).round() as i32;
        let s = rng.gen_range(4..=30);
        asks.insert(0, (p, s));
    }
    bids.sort_by(|a, b| b.0.cmp(&a.0));
    asks.sort_by(|a, b| a.0.cmp(&b.0));
    bids.truncate(3);
    asks.truncate(3);
    Book { bids, asks }
}

/// VELVETFRUIT_EXTRACT book generator. Effectively a single-level MM with
/// asymmetric quotes: bid at fair-2 or fair-3 (half-tie split), ask at
/// fair+3, sometimes with a second level (bid-3/ask+4). Calibrated from
/// docs/round3_params.json -> VELVET.book.
fn make_velvet_book(latent_fair: f64, rng: &mut ChaCha8Rng) -> Book {
    // Half-tie on bid side: bid = floor(fair-2) → offset -2 or -3.
    // Ask is straightforward round.
    let outward = rng.gen_bool(0.5);
    let bid_top = if (latent_fair.fract().abs() - 0.5).abs() < 1e-9 {
        if outward {
            (latent_fair - 2.5).floor() as i32
        } else {
            (latent_fair - 2.5).ceil() as i32
        }
    } else {
        (latent_fair - 2.5).round() as i32
    };
    let ask_top = (latent_fair + 2.5).round() as i32 + 1; // mostly +3 offset

    let bid_top_size = rng.gen_range(30..=60);
    let ask_top_size = rng.gen_range(30..=60);

    // Secondary level presence ~50%
    let has_bid_level2 = rng.gen_bool(0.5);
    let has_ask_level2 = rng.gen_bool(0.5);

    let mut bids: Vec<(i32, i32)> = vec![(bid_top, bid_top_size)];
    let mut asks: Vec<(i32, i32)> = vec![(ask_top, ask_top_size)];
    if has_bid_level2 {
        bids.push((bid_top - 1, rng.gen_range(25..=65)));
    }
    if has_ask_level2 {
        asks.push((ask_top + 1, rng.gen_range(25..=65)));
    }
    bids.sort_by(|a, b| b.0.cmp(&a.0));
    asks.sort_by(|a, b| a.0.cmp(&b.0));
    bids.truncate(3);
    asks.truncate(3);
    Book { bids, asks }
}

/// VEV voucher book. Delegates to pinned form for 6000/6500 (bid=0/ask=1),
/// otherwise builds a BS-anchored two-level book with per-strike IV.
fn make_vev_book(strike: i32, underlying_fv: f64, tte_years: f64, rng: &mut ChaCha8Rng) -> Book {
    if strike == 6000 || strike == 6500 {
        return make_pinned_vev_book();
    }
    let iv = vev_iv_for_strike(strike);
    let fv = bs_call(underlying_fv, strike as f64, tte_years, iv);
    let fv_int = fv.round() as i32;

    // Spread scales with option price: deeper ITM => wider spread, tighter
    // as we move OTM. Use a simple piecewise mapping calibrated from the
    // observed mean spreads per strike.
    let (outer_off, inner_off) = spread_off_for_strike(strike);
    let outer_off = outer_off as i32;
    let inner_off = inner_off as i32;
    let bid_outer = fv_int - outer_off;
    let ask_outer = fv_int + outer_off;
    let bid_inner = fv_int - inner_off;
    let ask_inner = fv_int + inner_off;

    // Size distributions scale loosely with strike depth.
    let (wall_size_lo, wall_size_hi) = wall_size_for_strike(strike);
    let (inner_size_lo, inner_size_hi) = (wall_size_lo / 2, wall_size_hi / 2 + 1);

    let wall_size_bid = rng.gen_range(wall_size_lo..=wall_size_hi);
    let wall_size_ask = rng.gen_range(wall_size_lo..=wall_size_hi);
    let inner_size_bid = rng.gen_range(inner_size_lo.max(5)..=inner_size_hi.max(10));
    let inner_size_ask = rng.gen_range(inner_size_lo.max(5)..=inner_size_hi.max(10));

    // Inner presence rate ~50-80% depending on strike; collapse to single
    // level for OTM-ish strikes with tighter spreads.
    let inner_present_rate = inner_presence_for_strike(strike);
    let has_bid_inner = inner_off != outer_off && rng.gen_bool(inner_present_rate);
    let has_ask_inner = inner_off != outer_off && rng.gen_bool(inner_present_rate);

    let mut bids: Vec<(i32, i32)> = vec![(bid_outer.max(0), wall_size_bid)];
    if has_bid_inner {
        bids.push((bid_inner.max(0), inner_size_bid));
    }
    let mut asks: Vec<(i32, i32)> = vec![(ask_outer, wall_size_ask)];
    if has_ask_inner {
        asks.push((ask_inner, inner_size_ask));
    }
    bids.sort_by(|a, b| b.0.cmp(&a.0));
    asks.sort_by(|a, b| a.0.cmp(&b.0));
    bids.truncate(3);
    asks.truncate(3);
    Book { bids, asks }
}

/// Pinned wing book for VEV_6000 / VEV_6500. Always bid=0 ask=1 with
/// volume 16 on each side. Observed identically on all 3 historical days.
fn make_pinned_vev_book() -> Book {
    Book {
        bids: vec![(0, 16)],
        asks: vec![(1, 16)],
    }
}

/// Outer/inner offsets for VEV bot quotes, calibrated roughly from observed
/// spreads per strike. Returns (outer_off, inner_off). For strikes where
/// inner is absent, outer_off == inner_off.
fn spread_off_for_strike(strike: i32) -> (i32, i32) {
    match strike {
        4000 => (11, 8),        // spread ~20
        4500 => (8, 6),         // spread ~16
        5000 => (3, 2),         // spread ~6
        5100 => (3, 2),         // spread ~4.3
        5200 => (2, 1),         // spread ~2.9
        5300 => (1, 1),         // spread ~2.1, mostly single-level
        5400 => (1, 1),         // spread ~1.4
        5500 => (1, 1),         // spread ~1.2
        _ => (1, 1),
    }
}

/// Wall-size sampling range per strike. Empirical mean top-level vols per
/// strike land near these bands.
fn wall_size_for_strike(strike: i32) -> (i32, i32) {
    match strike {
        4000 | 4500 => (15, 30),
        5000 | 5100 => (10, 25),
        5200 | 5300 => (15, 30),
        5400 | 5500 => (18, 30),
        _ => (10, 20),
    }
}

/// Probability of a non-pinned VEV having an inner level present alongside
/// the outer wall. Active strikes in the 5000-5200 range show 2-level books
/// frequently; 5300-5500 increasingly collapse to a single level.
fn inner_presence_for_strike(strike: i32) -> f64 {
    match strike {
        4000 | 4500 => 1.0,
        5000 | 5100 => 0.64,
        5200 => 0.25,
        5300 => 0.05,
        _ => 0.02,
    }
}

/// R3 strategy runner. Mirrors run_backtest_session_r2 but:
/// 1. Generates HYDROGEL and VELVETFRUIT fair-value paths per session.
/// 2. Vouchers are re-priced each tick from VELVET's mid using per-strike
///    IV at R3 live TTE (5 days).
/// 3. Hidden-FV liquidation at end-of-day: delta-1 products at final latent
///    fair; vouchers at BSM(final_underlying, K, T=live_tte) using per-strike IV.
fn run_backtest_session_r3(
    session_id: usize,
    capture_outputs: bool,
    config: &Config,
    replay: &ReplayData,
) -> Result<SessionOutput> {
    let products: &[&str] = config.round.products();
    let mut worker = StrategyWorker::spawn(config)?;
    let mut day_outputs = Vec::with_capacity(1);
    let mut total_fit = RunningLinearFit::default();
    let mut product_fits: HashMap<String, RunningLinearFit> =
        products.iter().map(|p| (p.to_string(), RunningLinearFit::default())).collect();
    let mut product_totals: HashMap<String, f64> =
        products.iter().map(|p| (p.to_string(), 0.0)).collect();
    let mut product_cash: HashMap<String, f64> =
        products.iter().map(|p| (p.to_string(), 0.0)).collect();
    let mut product_final_pos: HashMap<String, i32> =
        products.iter().map(|p| (p.to_string(), 0)).collect();
    let mut global_step = 0usize;
    let mut run_summaries = Vec::with_capacity(1);
    let session_day = monte_carlo_session_day(session_id, config.round);

    for day in [session_day] {
        worker.reset()?;
        let mut rng = ChaCha8Rng::seed_from_u64(seed_for_session_day(config.seed, session_id, day));

        // Simulate fair-value paths for the two delta-1 underlyings.
        let hydrogel_path = simulate_delta1_path(
            HYDROGEL_FAIR_VALUE,
            HYDROGEL_INNOV_SIGMA,
            HYDROGEL_EQUIL_STD,
            config.ticks_per_day,
            &mut rng,
        );
        let velvet_path = simulate_delta1_path(
            VELVET_FAIR_VALUE,
            VELVET_INNOV_SIGMA,
            VELVET_EQUIL_STD,
            config.ticks_per_day,
            &mut rng,
        );

        let mut trade_counts: HashMap<String, Vec<usize>> = HashMap::new();
        for product in products.iter().copied() {
            trade_counts.insert(
                product.to_string(),
                trade_counts_for(product, day, config, replay, &mut rng)?,
            );
        }

        let mut ledgers: HashMap<String, ProductLedger> = products
            .iter()
            .map(|p| (p.to_string(), ProductLedger::default()))
            .collect();
        let mut trader_data = String::new();
        let mut prev_own_trades = empty_trade_map_for(products);
        let mut prev_market_trades = empty_trade_map_for(products);
        let mut day_total_fit = RunningLinearFit::default();
        let mut day_product_fits: HashMap<String, RunningLinearFit> =
            products.iter().map(|p| (p.to_string(), RunningLinearFit::default())).collect();
        let mut day_step = 0usize;
        let mut price_rows = if capture_outputs {
            Vec::with_capacity(config.ticks_per_day * products.len())
        } else {
            Vec::new()
        };
        let mut trade_rows = Vec::new();
        let mut trace_rows = Vec::new();

        for tick in 0..config.ticks_per_day {
            let timestamp = (tick as i32) * TIMESTAMP_STEP;
            let hydrogel_fv = hydrogel_path[tick];
            let velvet_fv = velvet_path[tick];

            // Build per-product books and fair values for this tick.
            let mut books: HashMap<String, Book> = HashMap::new();
            let mut fairs: HashMap<String, f64> = HashMap::new();
            for product in products.iter().copied() {
                let (book, fair) = match product {
                    "HYDROGEL_PACK" => (make_hydrogel_book(hydrogel_fv, &mut rng), hydrogel_fv),
                    "VELVETFRUIT_EXTRACT" => (make_velvet_book(velvet_fv, &mut rng), velvet_fv),
                    p if p.starts_with("VEV_") => {
                        let strike: i32 = p[4..].parse().unwrap_or(0);
                        let book = make_vev_book(strike, velvet_fv, R3_LIVE_TTE_YEARS, &mut rng);
                        let fair = bs_call(
                            velvet_fv,
                            strike as f64,
                            R3_LIVE_TTE_YEARS,
                            vev_iv_for_strike(strike),
                        );
                        (book, fair)
                    }
                    other => bail!("round 3 session runner: unsupported product {}", other),
                };
                if capture_outputs {
                    price_rows.push(book_to_price_row(day, timestamp, product, &book));
                }
                books.insert(product.to_string(), book);
                fairs.insert(product.to_string(), fair);
            }

            let order_depths: HashMap<String, WorkerOrderDepth> = books
                .iter()
                .map(|(k, book)| (k.clone(), book_to_worker_depth(book)))
                .collect();
            let position: HashMap<String, i32> = ledgers
                .iter()
                .map(|(product, ledger)| (product.clone(), ledger.position))
                .collect();
            let request = WorkerRequest {
                request_type: "run".to_string(),
                timestamp,
                timeout_ms: STRATEGY_RUN_TIMEOUT_MS,
                trader_data: trader_data.clone(),
                order_depths,
                own_trades: fills_to_worker_trade_map_for(&prev_own_trades, products),
                market_trades: fills_to_worker_trade_map_for(&prev_market_trades, products),
                position,
            };
            let response = worker.run(&request)?;
            trader_data = response.trader_data.unwrap_or_default();

            let mut live_books: HashMap<String, SimBook> = books
                .iter()
                .map(|(k, book)| (k.clone(), book_to_sim_book(book)))
                .collect();
            let strategy_orders = normalize_strategy_orders_for(
                response.orders.unwrap_or_default(),
                products,
            );
            let filtered_orders = enforce_strategy_limits(&strategy_orders, &ledgers);

            let mut own_trades_this_tick = empty_trade_map_for(products);
            let mut market_trades_this_tick = empty_trade_map_for(products);

            for product in products.iter().copied() {
                let product_key = product.to_string();
                let orders = filtered_orders.get(product).cloned().unwrap_or_default();
                let book = live_books.get_mut(&product_key).context("missing live book")?;
                let ledger = ledgers.get_mut(&product_key).context("missing ledger")?;
                let fills = execute_strategy_orders(product, timestamp, book, ledger, &orders);
                if capture_outputs {
                    trade_rows.extend(fills.iter().map(fill_to_trade_row));
                }
                own_trades_this_tick.insert(product_key, fills);
            }

            for product in products.iter().copied() {
                let product_key = product.to_string();
                let count = trade_counts.get(&product_key).map(|v| v[tick]).unwrap_or(0);
                let book = live_books
                    .get_mut(&product_key)
                    .context("missing live book for taker execution")?;
                let ledger = ledgers
                    .get_mut(&product_key)
                    .context("missing ledger for taker execution")?;
                for _ in 0..count {
                    let market_buy = sample_trade_side(product, &mut rng);
                    let fills = execute_taker_trade(product, timestamp, book, ledger, market_buy, &mut rng);
                    for fill in fills {
                        let row = fill_to_trade_row(&fill);
                        if fill_involves_strategy(&fill) {
                            own_trades_this_tick
                                .entry(product_key.clone())
                                .or_default()
                                .push(fill);
                        } else {
                            market_trades_this_tick
                                .entry(product_key.clone())
                                .or_default()
                                .push(fill);
                        }
                        if capture_outputs {
                            trade_rows.push(row);
                        }
                    }
                }
            }

            if capture_outputs {
                for product in products.iter().copied() {
                    let product_key = product.to_string();
                    let ledger = ledgers.get(&product_key).context("missing ledger for trace")?;
                    let fair = *fairs.get(&product_key).unwrap_or(&0.0);
                    trace_rows.push(TraceRow {
                        day,
                        timestamp,
                        product: product_key,
                        fair_value: fair,
                        position: ledger.position,
                        cash: ledger.cash,
                        mtm_pnl: ledger.cash + ledger.position as f64 * fair,
                    });
                }
            }

            let mut tick_total_mtm = 0.0;
            for product in products.iter().copied() {
                let product_key = product.to_string();
                let ledger = ledgers.get(&product_key).context("missing ledger for fit")?;
                let fair = *fairs.get(&product_key).unwrap_or(&0.0);
                let mtm = ledger.cash + ledger.position as f64 * fair;
                let session_x = global_step as f64;
                let day_x = day_step as f64;
                product_fits.get_mut(&product_key).unwrap().update(session_x, mtm);
                day_product_fits.get_mut(&product_key).unwrap().update(day_x, mtm);
                tick_total_mtm += mtm;
            }
            let session_x = global_step as f64;
            let day_x = day_step as f64;
            total_fit.update(session_x, tick_total_mtm);
            day_total_fit.update(day_x, tick_total_mtm);
            global_step += 1;
            day_step += 1;

            prev_own_trades = own_trades_this_tick;
            prev_market_trades = market_trades_this_tick;
        }

        // End-of-day liquidation: hidden FV per product class.
        // Delta-1: final simulated fair. Vouchers: BSM at live TTE with
        // per-strike IV (matches bot quoting convention; the alternative
        // intrinsic-only mode is left for a future flag).
        let hydrogel_final = hydrogel_path[config.ticks_per_day - 1];
        let velvet_final = velvet_path[config.ticks_per_day - 1];
        let mut day_product_stats: HashMap<String, ProductStats> = HashMap::new();
        let mut day_total_pnl = 0.0;
        for product in products.iter().copied() {
            let product_key = product.to_string();
            let ledger = ledgers.get(&product_key).context("missing ledger for eod")?;
            let fair = match product {
                "HYDROGEL_PACK" => hydrogel_final,
                "VELVETFRUIT_EXTRACT" => velvet_final,
                p if p.starts_with("VEV_") => {
                    let strike: i32 = p[4..].parse().unwrap_or(0);
                    bs_call(
                        velvet_final,
                        strike as f64,
                        R3_LIVE_TTE_YEARS,
                        vev_iv_for_strike(strike),
                    )
                }
                _ => 0.0,
            };
            let pnl = ledger.cash + ledger.position as f64 * fair;
            day_total_pnl += pnl;
            *product_totals.get_mut(&product_key).unwrap() += pnl;
            *product_cash.get_mut(&product_key).unwrap() += ledger.cash;
            *product_final_pos.get_mut(&product_key).unwrap() = ledger.position;
            let fit = day_product_fits.get(&product_key).unwrap();
            day_product_stats.insert(
                product_key.clone(),
                ProductStats {
                    pnl,
                    cash: ledger.cash,
                    position: ledger.position,
                    slope_per_step: fit.slope_per_step(),
                    r_squared: fit.r_squared(),
                },
            );
        }

        run_summaries.push(RunSummary {
            session_id,
            day,
            total_pnl: day_total_pnl,
            emerald_pnl: 0.0,
            tomato_pnl: 0.0,
            total_slope_per_step: day_total_fit.slope_per_step(),
            total_r2: day_total_fit.r_squared(),
            emerald_slope_per_step: 0.0,
            emerald_r2: 0.0,
            tomato_slope_per_step: 0.0,
            tomato_r2: 0.0,
            product_stats_json: serde_json::to_string(&day_product_stats)
                .unwrap_or_else(|_| "{}".to_string()),
        });

        day_outputs.push(DayOutput {
            day,
            price_rows,
            trade_rows,
            trace_rows,
        });
    }

    let mut session_stats: HashMap<String, ProductStats> = HashMap::new();
    for product in products.iter().copied() {
        let product_key = product.to_string();
        session_stats.insert(
            product_key.clone(),
            ProductStats {
                pnl: *product_totals.get(&product_key).unwrap_or(&0.0),
                cash: *product_cash.get(&product_key).unwrap_or(&0.0),
                position: *product_final_pos.get(&product_key).unwrap_or(&0),
                slope_per_step: product_fits.get(&product_key).unwrap().slope_per_step(),
                r_squared: product_fits.get(&product_key).unwrap().r_squared(),
            },
        );
    }
    let total_pnl: f64 = product_totals.values().sum();

    let summary = SessionSummary {
        session_id,
        total_pnl,
        emerald_pnl: 0.0,
        tomato_pnl: 0.0,
        emerald_position: 0,
        tomato_position: 0,
        emerald_cash: 0.0,
        tomato_cash: 0.0,
        total_slope_per_step: total_fit.slope_per_step(),
        total_r2: total_fit.r_squared(),
        emerald_slope_per_step: 0.0,
        emerald_r2: 0.0,
        tomato_slope_per_step: 0.0,
        tomato_r2: 0.0,
        product_stats_json: serde_json::to_string(&session_stats)
            .unwrap_or_else(|_| "{}".to_string()),
    };

    Ok(SessionOutput {
        session_id,
        summary,
        run_summaries,
        day_outputs,
    })
}
