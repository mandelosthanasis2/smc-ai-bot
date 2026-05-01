# SMC AI Trading Bot — Bitget + Railway

## Τι κάνει
- Τρέχει 24/7 online στο Railway.app (δωρεάν)
- Παρακολουθεί BTC/USDT στο Bitget
- Previous Day High/Low Box strategy
- SMC confirmations: BOS, Liquidity Sweep, FVG, RSI
- Claude AI διαβάζει ειδήσεις πριν κάθε trade
- Web dashboard από οποιοδήποτε browser / κινητό

---

## Βήμα 1 — Δημιούργησε λογαριασμό στο Railway

1. Πήγαινε στο railway.app
2. Sign up με GitHub (δωρεάν)
3. Νέο project → Deploy from GitHub repo

---

## Βήμα 2 — Ανέβασε τον κώδικα στο GitHub

1. Δημιούργησε νέο repository στο github.com
2. Ανέβασε όλα τα αρχεία αυτού του φακέλου
3. Στο Railway → connect το GitHub repo

---

## Βήμα 3 — API Keys (Environment Variables στο Railway)

Στο Railway → Project → Variables, πρόσθεσε:

| Variable             | Value                        |
|----------------------|------------------------------|
| BITGET_API_KEY       | το key σου από Bitget        |
| BITGET_API_SECRET    | το secret σου                |
| BITGET_PASSPHRASE    | το passphrase σου            |
| ANTHROPIC_API_KEY    | το key σου από Anthropic     |
| TRADING_MODE         | PAPER (αρχικά!)              |

### Πώς παίρνεις Bitget API key:
1. bitget.com → Account → API Keys
2. Create API Key → "Personal" type
3. Permissions: Read + Spot & Futures Trade
4. Σώσε: API Key, Secret Key, Passphrase

### Πώς παίρνεις Anthropic key:
1. console.anthropic.com → API Keys
2. Create new key

---

## Βήμα 4 — Deploy

Το Railway κάνει αυτόματα deploy όταν κάνεις push στο GitHub.
Μετά το deploy θα δεις ένα URL όπως:
`https://smc-ai-bot-production.up.railway.app`

Αυτό είναι το dashboard σου — άνοιξέ το από οποιοδήποτε browser!

---

## Πώς λειτουργεί

```
Κάθε ώρα (στο κλείσιμο 1H candle):

1. Κατεβάζει candles από Bitget (1H + Daily)
2. Φτιάχνει Previous Day Box (PDH/PDL/MID)
3. Υπολογίζει RSI, BOS, Liquidity Sweep, FVG
4. Αν τιμή κοντά στο PDH:
   - RSI > 75; + SMC confirmation;
   → Ρωτάει Claude για ειδήσεις
   → Αν news score ≤ 0: PLACE SHORT
   → SL = PDH + 0.5×box | TP = MID (1:2 R/R)
5. Αν τιμή κοντά στο PDL:
   - RSI < 25; + SMC confirmation;
   → Ρωτάει Claude για ειδήσεις
   → Αν news score ≥ 0: PLACE LONG
6. Dashboard ενημερώνεται κάθε 20 δευτερόλεπτα
```

---

## AI News Filter

Πριν κάθε trade, το Claude:
1. Κατεβάζει τελευταία 20 headlines από:
   - CoinDesk, CoinTelegraph, CryptoNews, NewsBTC
2. Αναλύει το sentiment για BTC
3. Δίνει score: -2 (πολύ bearish) έως +2 (πολύ bullish)
4. SHORT trade → χρειάζεται score ≤ 0
5. LONG trade  → χρειάζεται score ≥ 0

---

## Προσοχή

⚠️  Κράτα TRADING_MODE=PAPER για τουλάχιστον 4 εβδομάδες
⚠️  Μελέτα τα αποτελέσματα στο dashboard πριν πας live
⚠️  Για LIVE trading: άλλαξε TRADING_MODE=LIVE στα Railway Variables
⚠️  Ποτέ μην ρισκάρεις χρήματα που δεν μπορείς να χάσεις
