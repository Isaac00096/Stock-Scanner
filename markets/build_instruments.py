"""
Turns markets/trade_nation_raw.csv (what Trade Nation offers, typed in from the app)
into markets/instruments.csv: one row per tradable instrument with the symbol used
to download its price history (Yahoo Finance), its market group, and a TradingView
symbol for chart links.

Run:  python markets/build_instruments.py
Re-run it whenever trade_nation_raw.csv changes.
"""

import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- Indices: Trade Nation name -> Yahoo symbol (rolling-future duplicates map to the same index) ----
INDEX = {
    "US500": "^GSPC", "USTEC": "^NDX", "US30": "^DJI", "US2000": "^RUT",
    "UK100": "^FTSE", "DE40": "^GDAXI", "F40": "^FCHI", "STOXX50": "^STOXX50E",
    "IBEX": "^IBEX", "SMI": "^SSMI", "JP225": "^N225", "HK50": "^HSI", "AUS200": "^AXJO",
    "SA40": "STX40.JO",   # Satrix 40 ETF: tracks the JSE Top 40 index
}
INDEX_TV = {"US500": "SP:SPX", "USTEC": "NASDAQ:NDX", "US30": "DJ:DJI", "US2000": "TVC:RUT",
            "UK100": "TVC:UKX", "DE40": "XETR:DAX", "F40": "EURONEXT:PX1", "STOXX50": "TVC:SX5E",
            "IBEX": "BME:IBC", "SMI": "SIX:SMI", "JP225": "TVC:NI225", "HK50": "TVC:HSI",
            "AUS200": "ASX:XJO", "SA40": "JSE:J200"}

# ---- Commodities: Trade Nation name -> Yahoo futures symbol ----
COMMODITY = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "WTI": "CL=F", "BRENT": "BZ=F", "NATURALGAS": "NG=F",
    "COPPER": "HG=F", "CORN": "ZC=F", "WHEAT": "ZW=F", "SOYABEAN": "ZS=F", "COFFEE": "KC=F",
    "COCOA": "CC=F", "COTTON": "CT=F", "ORANGEJUICE": "OJ=F", "ALUMINIUM": "ALI=F",
    # No reliable free daily history: SUGARNO5 (London sugar), LEAD, ZINC (LME) -> skipped
}

CRYPTO = {"BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD", "LTCUSD": "LTC-USD", "SOLANA": "SOL-USD",
          "TRONUSD": "TRX-USD", "ADAUSD": "ADA-USD", "DASHCUSD": "DASH-USD", "EOSUSD": "EOS-USD",
          "XLMUSD": "XLM-USD"}

# ---- European shares listed without an exchange suffix ----
EU_FIX = {
    # Germany (Xetra)
    "BEI": "BEI.DE", "BNR": "BNR.DE", "CBK": "CBK.DE", "CON": "CON.DE", "DTG": "DTG.DE",
    "ENR": "ENR.DE", "FME": "FME.DE", "FRE": "FRE.DE", "G1A": "G1A.DE", "G24": "G24.DE",
    "HEI": "HEI.DE", "HEN3": "HEN3.DE", "HNR1": "HNR1.DE", "LHA": "LHA.DE", "MTX": "MTX.DE",
    "QIA": "QIA.DE", "RHM": "RHM.DE", "SHL": "SHL.DE", "SY1": "SY1.DE", "ZAL": "ZAL.DE",
    "PAH3": "PAH3.DE",
    # Portugal (Euronext Lisbon)
    "ALTR": "ALTR.LS", "BCP": "BCP.LS", "COR": "COR.LS", "CTT": "CTT.LS", "EDP": "EDP.LS",
    "EDPR": "EDPR.LS", "EGL": "EGL.LS", "GALP": "GALP.LS", "IBS": "IBS.LS", "JMT": "JMT.LS",
    "NOS": "NOS.LS", "NVG": "NVG.LS", "RENE": "RENE.LS", "SEM": "SEM.LS", "SON": "SON.LS",
    # Poland (Warsaw)
    "ALIOR": "ALR.WA", "ALLEGRO": "ALE.WA", "BUDIMEX": "BDX.WA", "CDPROJEKT": "CDR.WA",
    "DINOPL": "DNP.WA", "ERSTEPL": "SPL.WA", "KETY": "KTY.WA", "KGHM": "KGH.WA", "KRUK": "KRU.WA",
    "MBANK": "MBK.WA", "MODIVO": "MDV.WA", "PEKAO": "PEO.WA", "PEPCO": "PCO.WA", "PGE": "PGE.WA",
    "PKNORLEN": "PKN.WA", "PKOBP": "PKO.WA", "PZU": "PZU.WA", "TAURONPE": "TPE.WA", "ZABKA": "ZAB.WA",
    # Suffixed, but spelled differently on Yahoo
    "NOVOB.CO": "NOVO-B.CO", "CARL_B.CO": "CARL-B.CO", "MAERSK_B.CO": "MAERSK-B.CO",
    "AMBUB.CO": "AMBU-B.CO", "HLUNB.CO": "HLUN-B.CO", "ROCKB.CO": "ROCK-B.CO",
    "COLOB.CO": "COLO-B.CO", "DNORD.DC": "DNORD.CO", "KNEVB.HE": "KNEBV.HE", "ENEL.MX": "ENEL.MI",
}
US_FIX = {"BRK.B": "BRK-B", "RL.N": "RL", "SPOT.N": "SPOT", "SQ": "XYZ"}  # Block now trades as XYZ


def build() -> pd.DataFrame:
    raw = pd.read_csv(os.path.join(HERE, "trade_nation_raw.csv"))
    rows = []
    for r in raw.itertuples():
        tn, cls, name = r.tn_symbol, r._3, r.name
        y, market, tv = None, None, None
        if cls == "stock_us":
            y, market = US_FIX.get(tn, tn.replace(".", "-")), "us"
            tv = y.replace("-", ".")
        elif cls == "stock_jse":
            y, market, tv = tn, "jse", "JSE:" + tn.split(".")[0]
        elif cls == "stock_uk":
            y, market, tv = tn, "uk", "LSE:" + tn.split(".")[0]
        elif cls == "stock_eu":
            y, market = EU_FIX.get(tn, tn), "eu"
            tv = y.split(".")[0]
        elif cls == "forex":
            y, market, tv = f"{tn}=X", "forex", "FX:" + tn
        elif cls == "index":
            base = tn[:-2] if tn.endswith("FU") else tn
            if base in INDEX:
                y, market, tv = INDEX[base], "index", INDEX_TV.get(base)
        elif cls == "commodity":
            if tn in COMMODITY:
                y, market, tv = COMMODITY[tn], "commodity", tn
        elif cls == "crypto":
            if tn in CRYPTO:
                y, market, tv = CRYPTO[tn], "crypto", "CRYPTO:" + CRYPTO[tn].replace("-", "")
        if y:
            rows.append({"tn_symbol": tn, "yahoo": y, "market": market, "name": name, "tradingview": tv})
    out = pd.DataFrame(rows)
    # Rolling-future and cash versions of the same index -> keep one row (the cash/CFD name)
    out = out.sort_values("tn_symbol").drop_duplicates("yahoo", keep="first")
    return out.sort_values(["market", "tn_symbol"]).reset_index(drop=True)


if __name__ == "__main__":
    df = build()
    df.to_csv(os.path.join(HERE, "instruments.csv"), index=False)
    print(f"{len(df)} instruments")
    print(df["market"].value_counts().to_string())
