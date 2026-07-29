#!/usr/bin/env python3
"""
Generate config/strategy_library.json — the inventory of every strategy
section in Kakushadze & Serur, "151 Trading Strategies" (SSRN 3247865),
scored for fit to the CURRENT market regime and sorted descending.

Each row: (section, name, printed_page, category, score, rationale).
PDF link pages are printed_page + 1 (the PDF has one front page before
printed page 1). Scores are 0-100 judgment calls for the regime described
in REGIME_NOTE — re-run with new scores when the regime changes.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "config", "strategy_library.json")

REGIME_NOTE = ("Scored for the market as of 2026-07-17: cautious risk-on — US equities "
               "grinding higher near highs with mixed breadth, VIX ~16-17 (calm, modest "
               "vol premium), G+E regime reads 'cautious'. Ordering is model judgment for "
               "this environment, not investment advice.")

R = []  # (section, name, page, category, score, rationale)

# ---- Chapter 3: Stocks -------------------------------------------------------
R += [
 ("3.6",  "Multifactor portfolio", 43, "Stocks", 82, "Blending momentum/value/quality is robust when no single style dominates — fits mixed breadth"),
 ("3.4",  "Low-volatility anomaly", 42, "Stocks", 80, "Defensive tilt historically shines in cautious, late-stage tape"),
 ("3.7",  "Residual momentum", 44, "Stocks", 79, "Idiosyncratic momentum with market beta stripped — less exposed to index chop"),
 ("3.1",  "Price-momentum", 40, "Stocks", 78, "Uptrend intact so momentum carries, but crowding risk in a narrow tape"),
 ("3.18", "Statistical arbitrage — optimization", 55, "Stocks", 77, "Market-neutral spread harvesting suits a cautious regime; needs execution discipline"),
 ("3.2",  "Earnings-momentum", 41, "Stocks", 76, "PEAD persists; earnings season dispersion gives it fresh fuel"),
 ("3.20", "Alpha combos", 59, "Stocks", 75, "Combining decorrelated alphas smooths regime sensitivity"),
 ("3.8",  "Pairs trading", 45, "Stocks", 74, "Choppy, rotation-heavy markets feed spread convergence"),
 ("3.9.1","Mean-reversion — multiple clusters", 47, "Stocks", 73, "Cluster-neutral reversion is steadier than single-cluster in rotation"),
 ("3.9",  "Mean-reversion — single cluster", 46, "Stocks", 72, "Short-horizon reversion does well when the index grinds instead of trends"),
 ("3.10", "Mean-reversion — weighted regression", 49, "Stocks", 71, "Regression-weighted variant; same edge, more estimation risk"),
 ("3.16", "Event-driven — M&A (merger arbitrage)", 52, "Stocks", 68, "Deal spreads are steady carry; depends on deal flow staying healthy"),
 ("3.19", "Market-making", 58, "Stocks", 64, "Regime-agnostic edge but infrastructure- and speed-intensive"),
 ("3.3",  "Value", 42, "Stocks", 62, "Cheapness alone lags in momentum-led tapes; slow-burn edge"),
 ("3.5",  "Implied volatility — stock selection", 43, "Stocks", 60, "IV-signal stock picking; modest documented edge"),
 ("3.12", "Two moving averages", 50, "Stocks", 58, "Simple trend filter; whipsaw cost rises in a grinding market"),
 ("3.13", "Three moving averages", 51, "Stocks", 57, "Extra filter cuts whipsaws slightly, adds lag"),
 ("3.11", "Single moving average", 49, "Stocks", 55, "Crude timing tool; fine as a filter, weak standalone"),
 ("3.14", "Support and resistance", 51, "Stocks", 54, "Discretionary levels; edge is thin without flow information"),
 ("3.15", "Channel", 52, "Stocks", 53, "Breakout channels whipsaw in range-bound singles"),
 ("3.17", "Machine learning — single-stock KNN", 53, "Stocks", 45, "Overfit-prone on single names without heavy feature discipline"),
]

# ---- Chapter 4: ETFs ---------------------------------------------------------
R += [
 ("4.6",  "Multi-asset trend following", 65, "ETFs", 84, "Diversified trend across asset classes — the all-weather workhorse; strong fit"),
 ("4.1.2","Dual-momentum sector rotation", 62, "ETFs", 82, "Relative + absolute momentum with a cash fallback — built for cautious uptrends"),
 ("4.1.1","Sector momentum rotation — MA filter", 62, "ETFs", 78, "Trend filter trims drawdown when rotation stalls"),
 ("4.1",  "Sector momentum rotation", 61, "ETFs", 77, "Sector leadership persists; watch concentration in a narrow market"),
 ("4.4",  "ETF mean-reversion", 64, "ETFs", 70, "Index-level reversion decent in a grind; thinner edge than single-stock"),
 ("4.2",  "Alpha rotation", 63, "ETFs", 60, "Chasing recent alpha across ETFs decays fast"),
 ("4.3",  "R-squared", 63, "ETFs", 58, "Regression-fit timing; modest, data-mined edge"),
 ("4.5",  "Leveraged ETFs (LETFs)", 64, "ETFs", 40, "Volatility decay punishes leveraged holds in choppy tape"),
]

# ---- Chapter 2: Options ------------------------------------------------------
R += [
 ("2.2",  "Covered call", 18, "Options", 79, "Income on longs in a slow grind higher — fits this tape and a long-only book"),
 ("2.53", "Collar", 37, "Options", 72, "Cheap downside protection while staying long — tailor-made for a cautious regime"),
 ("2.7",  "Bull put spread", 20, "Options", 68, "Defined-risk premium selling with an upward drift at your back"),
 ("2.50", "Long iron condor", 36, "Options", 65, "Defined-risk range income; VIX ~17 still pays acceptable credit"),
 ("2.6",  "Bull call spread", 19, "Options", 64, "Cheap directional upside with capped cost in a modest-IV market"),
 ("2.18", "Calendar call spread", 24, "Options", 63, "Harvests term-structure theta while vol is calm"),
 ("2.20", "Diagonal call spread", 25, "Options", 62, "Covered-call-like income with less capital"),
 ("2.19", "Calendar put spread", 24, "Options", 61, "Same theta harvest, put side"),
 ("2.4",  "Protective put", 19, "Options", 60, "Insurance is reasonably priced at VIX ~17; drag if the grind continues"),
 ("2.40", "Long call butterfly", 32, "Options", 58, "Cheap pin-risk income when the index goes nowhere fast"),
 ("2.54", "Bullish short seagull spread", 37, "Options", 58, "Financed upside with defined structure; fits mild bullishness"),
 ("2.40.1","Modified call butterfly", 32, "Options", 57, "Asymmetric wings tilt the fly bullish — matches the drift"),
 ("2.41", "Long put butterfly", 32, "Options", 56, "Same range bet from the put side"),
 ("2.44", "\"Long\" iron butterfly", 34, "Options", 56, "Tight-body premium capture; needs the pin"),
 ("2.26", "Short strangle", 27, "Options", 55, "VRP harvest works until it doesn't — undefined risk in a cautious regime"),
 ("2.41.1","Modified put butterfly", 33, "Options", 55, "Asymmetric put fly variant"),
 ("2.46", "Long call condor", 34, "Options", 55, "Wider body than the fly; modest range income"),
 ("2.57", "Bullish long seagull spread", 39, "Options", 55, "Protected bullish three-legger"),
 ("2.47", "Long put condor", 35, "Options", 54, "Put-side range structure"),
 ("2.21", "Diagonal put spread", 25, "Options", 53, "Put-side diagonal; income with bearish tilt"),
 ("2.8",  "Bear call spread", 20, "Options", 52, "Credit hedge against stalls; fights the drift"),
 ("2.25", "Short straddle", 27, "Options", 50, "Max theta, max tail risk — cautious regime argues for wings"),
 ("2.33", "Covered short strangle", 29, "Options", 48, "Aggressive income overlay on longs; assignment risk both ways"),
 ("2.12", "Long combo", 21, "Options", 48, "Synthetic bullish tilt at low cost"),
 ("2.36", "Call ratio backspread", 30, "Options", 47, "Long convexity if the melt-up accelerates; bleeds theta meanwhile"),
 ("2.23", "Long strangle", 26, "Options", 46, "Long vol is only mid-priced; needs a catalyst"),
 ("2.38", "Ratio call spread", 31, "Options", 46, "Premium-financed upside with naked tail beyond the strikes"),
 ("2.9",  "Bear put spread", 20, "Options", 45, "Defined-risk bearish bet — against the current trend"),
 ("2.27", "Short guts", 27, "Options", 45, "ITM premium sale; wide but capital-heavy"),
 ("2.22", "Long straddle", 26, "Options", 44, "Pure long vol; pays only on a regime break"),
 ("2.32", "Covered short straddle", 29, "Options", 44, "Doubles down on assignment; rich income, poor asymmetry"),
 ("2.37", "Put ratio backspread", 31, "Options", 44, "Crash convexity financed by near puts; cheap disaster hedge"),
 ("2.14", "Bull call ladder", 22, "Options", 45, "Income-financed upside that caps then reverses — awkward here"),
 ("2.39", "Ratio put spread", 31, "Options", 43, "Put-side ratio; naked downside tail in a cautious regime"),
 ("2.15", "Bull put ladder", 23, "Options", 42, "Multi-leg put structure; complexity outweighs edge"),
 ("2.51", "Short iron condor", 36, "Options", 42, "Long the wings — a breakout bet the grind doesn't favor"),
 ("2.28", "Long call synthetic straddle", 28, "Options", 42, "Synthetic long vol; simpler to buy the straddle"),
 ("2.29", "Long put synthetic straddle", 28, "Options", 41, "Same, put-constructed"),
 ("2.16", "Bear call ladder", 23, "Options", 40, "Upside-exposed credit ladder; mismatched to the tape"),
 ("2.24", "Long guts", 26, "Options", 40, "ITM strangle; expensive way to be long vol"),
 ("2.10", "Long synthetic forward", 21, "Options", 40, "Synthetic long future; cleaner to own delta directly"),
 ("2.56", "Bearish short seagull spread", 38, "Options", 42, "Bearish financed structure; against trend"),
 ("2.55", "Bearish long seagull spread", 38, "Options", 40, "Bearish three-legger; against trend"),
 ("2.17", "Bear put ladder", 23, "Options", 38, "Bearish ladder; against trend"),
 ("2.34", "Strap", 30, "Options", 38, "2:1 bullish vol bet; pricey without a catalyst"),
 ("2.30", "Short call synthetic straddle", 28, "Options", 38, "Synthetic short vol with extra legs"),
 ("2.31", "Short put synthetic straddle", 29, "Options", 37, "Same, put-constructed"),
 ("2.35", "Strip", 30, "Options", 36, "2:1 bearish vol bet; against trend and paying theta"),
 ("2.42", "Short call butterfly", 33, "Options", 35, "Small credit for a breakout bet; poor odds in a grind"),
 ("2.48", "Short call condor", 35, "Options", 36, "Breakout bet, wider; same problem"),
 ("2.43", "Short put butterfly", 33, "Options", 34, "Put-side breakout bet"),
 ("2.49", "Short put condor", 35, "Options", 35, "Put-side breakout bet, wider"),
 ("2.45", "\"Short\" iron butterfly", 34, "Options", 40, "Long the body — needs a move now"),
 ("2.13", "Short combo", 22, "Options", 35, "Synthetic short tilt; against trend"),
 ("2.5",  "Protective call", 19, "Options", 35, "Insures a short stock position — not the book to be running here"),
 ("2.11", "Short synthetic forward", 21, "Options", 30, "Synthetic short future; against trend"),
 ("2.3",  "Covered put", 18, "Options", 30, "Short stock + short put; unlimited upside risk in an uptrend"),
 ("2.52", "Long box", 37, "Options", 25, "Locked-in rate arb; fees and margin eat the edge for non-institutions"),
]

# ---- Chapter 10 & 9: Futures / Commodities ----------------------------------
R += [
 ("10.4", "Trend following (momentum) — futures", 96, "Futures", 80, "Managed-futures trend is the classic crisis-alpha diversifier; earns its slot in any regime"),
 ("10.3", "Contrarian trading (mean-reversion) — futures", 95, "Futures", 58, "Short-horizon futures reversion; execution-sensitive"),
 ("10.3.1","Contrarian trading — market activity filter", 95, "Futures", 57, "Volume-filtered variant"),
 ("10.2", "Calendar spread — futures", 94, "Futures", 55, "Term-structure carry; steadier than outright direction"),
 ("10.1", "Hedging risk with futures", 92, "Futures", 45, "Risk management, not alpha — score reflects return potential"),
 ("10.1.2","Interest rate risk hedging", 93, "Futures", 44, "Duration hedging utility"),
 ("10.1.1","Cross-hedging", 93, "Futures", 42, "Proxy-hedge basis risk without return"),
 ("9.1",  "Roll yields", 89, "Commodities", 63, "Backwardation carry harvest; curve-dependent but persistent"),
 ("9.2",  "Trading on hedging pressure", 90, "Commodities", 60, "Positioning-based premium; slow but real"),
 ("9.5",  "Skewness premium", 91, "Commodities", 57, "Selling lottery-skew commodities; niche but documented"),
 ("9.3",  "Portfolio diversification with commodities", 90, "Commodities", 58, "Inflation-hedge ballast more than alpha"),
 ("9.4",  "Value — commodities", 90, "Commodities", 55, "Long-cheap/short-rich baskets; long cycles"),
 ("9.6",  "Trading with pricing models", 91, "Commodities", 48, "Model-implied mispricing; estimation-heavy"),
]

# ---- Chapters 6 & 7: Indexes / Volatility -----------------------------------
R += [
 ("6.5",  "Index volatility targeting with risk-free asset", 80, "Indexes", 74, "Vol-scaled index exposure — systematic de-risking suits a cautious regime"),
 ("6.3",  "Dispersion trading in equity indexes", 77, "Indexes", 52, "Short index vol vs long single-name vol; correlation bet, institutional plumbing"),
 ("6.3.1","Dispersion trading — subset portfolio", 78, "Indexes", 53, "Cheaper subset implementation"),
 ("6.2",  "Cash-and-carry arbitrage — indexes", 77, "Indexes", 48, "Basis is tight; a financing-cost game now"),
 ("6.4",  "Intraday arbitrage between index ETFs", 79, "Indexes", 42, "Latency game owned by HFT"),
 ("7.4.1","Volatility risk premium — Gamma hedging", 83, "Volatility", 69, "Hedged VRP harvest — the cleaner way to be short vol at VIX ~17"),
 ("7.2",  "VIX futures basis trading", 81, "Volatility", 68, "Contango roll-down pays in calm regimes; size for the spike"),
 ("7.4",  "Volatility risk premium", 83, "Volatility", 67, "Implied>realized premium is on; tail discipline mandatory"),
 ("7.3.1","Hedging short VXX with VIX futures", 82, "Volatility", 66, "Hedged short-vol carry; basis still positive"),
 ("7.3",  "Volatility carry with two ETNs", 82, "Volatility", 62, "ETN pair carry; product/termination risk"),
 ("7.5",  "Volatility skew — long risk reversal", 84, "Volatility", 50, "Skew harvesting; crowded and path-dependent"),
 ("7.6",  "Volatility trading with variance swaps", 84, "Volatility", 40, "OTC access required"),
]

# ---- Chapter 5: Fixed Income -------------------------------------------------
R += [
 ("5.12", "Rolling down the yield curve", 74, "Fixed Income", 66, "Positive-slope rolldown carry is back on the table"),
 ("5.11", "Carry factor — bonds", 74, "Fixed Income", 63, "Cross-market bond carry; steady premium"),
 ("5.9",  "Low-risk factor — bonds", 73, "Fixed Income", 62, "Bond low-beta anomaly; quiet compounder"),
 ("5.4",  "Ladders", 70, "Fixed Income", 60, "Simple reinvestment-risk spreading; income floor for idle cash"),
 ("5.10", "Value factor — bonds", 73, "Fixed Income", 58, "Rich/cheap bond selection"),
 ("5.6",  "Dollar-duration-neutral butterfly", 71, "Fixed Income", 58, "Curve-shape RV without duration bets"),
 ("5.8",  "Regression-weighted butterfly", 72, "Fixed Income", 57, "Statistically weighted curve trade"),
 ("5.7",  "Fifty-fifty butterfly", 72, "Fixed Income", 56, "Simpler weighting, same curve bet"),
 ("5.8.1","Maturity-weighted butterfly", 73, "Fixed Income", 55, "Another weighting scheme"),
 ("5.3",  "Barbells", 69, "Fixed Income", 55, "Convexity tilt; useful if curve moves get violent"),
 ("5.13", "Yield curve spread (flatteners & steepeners)", 75, "Fixed Income", 55, "Directional curve bets; macro-call dependent"),
 ("5.5",  "Bond immunization", 70, "Fixed Income", 52, "Liability matching, not alpha"),
 ("5.2",  "Bullets", 69, "Fixed Income", 50, "Concentrated-maturity holding; building block"),
 ("5.14", "CDS basis arbitrage", 75, "Fixed Income", 45, "Basis is thin and balance-sheet-intensive"),
 ("5.15", "Swap-spread arbitrage", 76, "Fixed Income", 44, "LTCM's old trade; institutional repo required"),
]

# ---- Chapter 8: FX -----------------------------------------------------------
R += [
 ("8.4",  "Momentum & carry combo — FX", 88, "FX", 64, "Blended FX factors beat either alone; moderate fit"),
 ("8.2.1","High-minus-low carry", 87, "FX", 62, "Rate-differential ranking; works until risk-off"),
 ("8.2",  "Carry trade — FX", 86, "FX", 60, "Classic carry; crash-prone when vol spikes"),
 ("8.3",  "Dollar carry trade", 88, "FX", 55, "Timing the dollar leg; regime-sensitive"),
 ("8.1",  "Moving averages with HP filter — FX", 85, "FX", 52, "Filtered FX trend; modest standalone edge"),
 ("8.5",  "FX triangular arbitrage", 89, "FX", 20, "Microsecond arbitrage — HFT-only territory"),
]

# ---- Chapters 11-19: credit, misc, alternatives ------------------------------
R += [
 ("12.1", "Convertible arbitrage", 101, "Convertibles", 58, "Long convert / short stock gamma; decent when issuance is healthy"),
 ("12.2", "Convertible option-adjusted spread", 102, "Convertibles", 52, "OAS-based rich/cheap converts"),
 ("19.2", "Fundamental macro momentum", 122, "Global Macro", 66, "Macro-trend tilts across assets; robust discipline"),
 ("19.5", "Trading on economic announcements", 123, "Global Macro", 56, "Event drift around data prints; execution-sensitive"),
 ("19.4", "Global fixed-income strategy", 123, "Global Macro", 52, "Cross-country bond RV"),
 ("19.3", "Global macro inflation hedge", 122, "Global Macro", 48, "Inflation basket; less urgent with inflation off the boil"),
 ("15.3", "Distress risk puzzle", 110, "Distressed", 55, "Shorting high-distress equities exploits a documented anomaly"),
 ("15.3.1","Distress risk puzzle — risk management", 110, "Distressed", 56, "Risk-managed variant is the investable version"),
 ("15.1", "Buying and holding distressed debt", 108, "Distressed", 48, "Cycle-timing game; default cycle is quiet"),
 ("15.2", "Active distressed investing", 109, "Distressed", 42, "Control-oriented; specialist capital and courts"),
 ("15.2.2","Buying outstanding debt", 109, "Distressed", 36, "Sub-strategy of control investing"),
 ("15.2.1","Planning a reorganization", 109, "Distressed", 35, "Legal-process alpha; not a screen trade"),
 ("15.2.3","Loan-to-own", 110, "Distressed", 33, "Credit-to-equity control play; specialist"),
 ("11.7", "Mortgage-backed security (MBS) trading", 100, "Structured Assets", 45, "Prepayment-model RV; institutional data game"),
 ("11.3", "Carry, senior/mezzanine — index hedging", 99, "Structured Assets", 35, "Tranche carry; complexity premium mostly institutional"),
 ("11.2", "Carry, equity tranche — index hedging", 99, "Structured Assets", 34, "Equity-tranche correlation carry"),
 ("11.4", "Carry — tranche hedging", 99, "Structured Assets", 33, "Tranche-vs-tranche hedged carry"),
 ("11.5", "Carry — CDS hedging", 100, "Structured Assets", 32, "Single-name-hedged tranche carry"),
 ("11.6", "CDOs — curve trades", 100, "Structured Assets", 30, "Tranche curve RV; 2008 taught the liquidity lesson"),
 ("13.1", "Municipal bond tax arbitrage", 102, "Tax Arbitrage", 48, "Tax-exempt carry vs funding; bracket-dependent"),
 ("13.2", "Cross-border tax arbitrage", 103, "Tax Arbitrage", 30, "Dividend-withholding games; regulators keep closing them"),
 ("13.2.1","Cross-border tax arbitrage with options", 104, "Tax Arbitrage", 28, "Options-implemented variant; same shrinkage"),
 ("14.2", "TIPS-Treasury arbitrage", 105, "Miscellaneous", 42, "Famous basis trade; capital-intensive, episodic"),
 ("14.1", "Inflation hedging — inflation swaps", 104, "Miscellaneous", 40, "OTC inflation exposure; hedging utility"),
 ("14.4", "Energy — spark spread", 108, "Miscellaneous", 30, "Generator economics; physical/OTC market"),
 ("14.3", "Weather risk — demand hedging", 106, "Miscellaneous", 25, "Weather derivatives; thin, specialist market"),
 ("16.4", "Real estate momentum — regional approach", 113, "Real Estate", 52, "Regional price momentum persists in housing data"),
 ("16.2", "Mixed-asset diversification with real estate", 111, "Real Estate", 50, "Allocation ballast via REITs"),
 ("16.5", "Inflation hedging with real estate", 113, "Real Estate", 47, "Long-horizon hedge; less urgent now"),
 ("16.3.3","Property type and geographic diversification", 113, "Real Estate", 46, "Diversification within RE"),
 ("16.3", "Intra-asset diversification within real estate", 112, "Real Estate", 45, "Same, general form"),
 ("16.3.1","Property type diversification", 112, "Real Estate", 44, "Sub-variant"),
 ("16.3.2","Economic diversification", 112, "Real Estate", 43, "Sub-variant"),
 ("16.6", "Fix-and-flip", 114, "Real Estate", 38, "Operationally heavy; rate-sensitive margins"),
 ("18.3", "Crypto sentiment — naive Bayes Bernoulli", 120, "Cryptocurrencies", 38, "Sentiment classifier on a noisy asset; fragile edge"),
 ("18.2", "Crypto — artificial neural network (ANN)", 116, "Cryptocurrencies", 35, "ML on crypto prices; overfit risk is the strategy"),
 ("17.3", "Liquidity management", 115, "Cash", 45, "Cash optimization — worth doing, not alpha"),
 ("17.4", "Repurchase agreement (REPO)", 115, "Cash", 40, "Institutional funding market"),
 ("17.5", "Pawnbroking", 115, "Cash", 22, "A lending business, not a trading strategy"),
 ("17.6", "Loan sharking", 116, "Cash", 1, "Illegal — in the book for completeness only"),
 ("17.2", "Money laundering — the dark side of cash", 114, "Cash", 0, "Illegal — in the book as a cautionary description only"),
]


# Sections that map onto a deployed strategy's engines -> badge in the UI.
GE_MAP = {
    "3.1":   "Genesis engine — own-the-leaders RS momentum",
    "3.11":  "Genesis trend template — MA stacking filter",
    "3.12":  "Genesis trend template — MA stacking filter",
    "3.13":  "Genesis trend template — MA stacking filter",
    "3.9":   "Exodus cousin — quality-pullback mean-reversion",
    "3.15":  "Turtle engine — Donchian channel breakout",
    "4.1.2": "Regime gate — absolute momentum with cash fallback",
}


def main():
    seen = set()
    items = []
    for sec, name, page, cat, score, why in R:
        key = sec.rstrip("b")
        if key in seen:
            raise SystemExit(f"duplicate section {sec}")
        seen.add(key)
        item = {
            "section": key,
            "name": name,
            "category": cat,
            "page": page,
            "pdf_page": page + 1,
            "score": score,
            "rationale": why,
        }
        if key in GE_MAP:
            item["ge"] = GE_MAP[key]
        items.append(item)
    items.sort(key=lambda x: -x["score"])
    for i, it in enumerate(items, 1):
        it["rank"] = i
    out = {
        "source": {
            "title": "151 Trading Strategies",
            "authors": "Zura Kakushadze & Juan Andres Serur",
            "ssrn": "https://ssrn.com/abstract=3247865",
            "local_pdf": "/paper.pdf",
        },
        "regime_note": REGIME_NOTE,
        "count": len(items),
        "strategies": items,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {OUT}: {len(items)} strategies")


if __name__ == "__main__":
    main()
