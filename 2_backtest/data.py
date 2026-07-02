"""Carga y resampleo de datos intradia para el backtest de la estrategia TJR.
Lee los CSV 1m del proyecto del usuario (NQ/ES) y los deja en zona horaria
America/New_York (mercado US), con resampleos HTF y etiquetas de sesion."""
import pandas as pd
import numpy as np

DATA_DIR = "/Users/sebastianmotta/Desktop/estrategia fede secees/bot_fede/data"
NY = "America/New_York"

# Sesiones (hora local NY). Killzones de TJR: London open y NY open.
SESSIONS = {
    "asia":   ("18:00", "02:00"),   # cruza medianoche
    "london": ("02:00", "05:00"),   # London killzone
    "ny_am":  ("09:30", "12:00"),   # New York AM killzone (open)
    "ny_pm":  ("12:00", "16:00"),
}
KILLZONES = ["london", "ny_am"]


def load_1m(symbol="NQ"):
    """Devuelve DataFrame 1m indexado por timestamp tz=America/New_York."""
    path = f"{DATA_DIR}/{symbol}_1m.csv"
    df = pd.read_csv(path)
    tcol = df.columns[0]
    ts = pd.to_datetime(df[tcol], utc=True)           # parsea con offset -> UTC
    df = df.rename(columns={tcol: "ts"})
    df["ts"] = ts.dt.tz_convert(NY)
    df = df.set_index("ts").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="first")]
    return df


def resample(df1m, rule):
    """Resampleo OHLCV. rule estilo pandas: '5min','15min','60min','240min','1D'."""
    o = df1m["open"].resample(rule, label="left", closed="left").first()
    h = df1m["high"].resample(rule, label="left", closed="left").max()
    l = df1m["low"].resample(rule, label="left", closed="left").min()
    c = df1m["close"].resample(rule, label="left", closed="left").last()
    v = df1m["volume"].resample(rule, label="left", closed="left").sum()
    out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})
    return out.dropna(subset=["open", "high", "low", "close"])


def tag_session(idx):
    """Etiqueta cada timestamp con su sesion (asia/london/ny_am/ny_pm/off)."""
    t = idx.hour * 60 + idx.minute
    lab = np.full(len(idx), "off", dtype=object)
    def win(a, b):
        am = int(a[:2]) * 60 + int(a[3:]); bm = int(b[:2]) * 60 + int(b[3:])
        return (am, bm)
    for name, (a, b) in SESSIONS.items():
        am, bm = win(a, b)
        if am < bm:
            mask = (t >= am) & (t < bm)
        else:  # cruza medianoche (asia)
            mask = (t >= am) | (t < bm)
        lab[mask] = name
    return lab


def session_levels(df1m):
    """Para cada dia calcula highs/lows de cada sesion y del dia previo.
    Devuelve dict por fecha -> niveles de liquidez (precio + tipo)."""
    sess = tag_session(df1m.index)
    d = df1m.copy()
    d["sess"] = sess
    d["date"] = d.index.tz_convert(NY).normalize()
    # high/low por (date, sesion)
    g = d.groupby(["date", "sess"]).agg(hi=("high", "max"), lo=("low", "min"))
    return g


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "NQ"
    df = load_1m(sym)
    print(f"{sym} 1m: {len(df):,} velas | {df.index[0]} -> {df.index[-1]}")
    print("precio min/max:", round(df['low'].min(), 1), round(df['high'].max(), 1))
    for rule in ["5min", "15min", "60min", "240min", "1D"]:
        r = resample(df, rule)
        print(f"  {rule:>6}: {len(r):,} velas")
    # cobertura por hora (para ver que las killzones tienen data)
    by_h = df.groupby(df.index.hour).size()
    print("velas por hora (0-23):")
    print(by_h.to_string())
    # chequeo de gaps grandes (dias sin data)
    days = df.index.normalize().nunique()
    print(f"dias con data: {days:,}")
