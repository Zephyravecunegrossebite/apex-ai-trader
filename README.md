# ⚡ APEX AI TRADER — Bot Python 24/7

Bot de trading automatisé qui surveille **XAU/USD, EUR/USD, BTC/USD** et envoie des alertes sur **Telegram** avec Stop Loss précis et ratio R:R minimum 1:2.

---

## 🚀 Déploiement sur Render.com (gratuit)

### Étape 1 — Préparer les fichiers
Assure-toi d'avoir ces 4 fichiers :
- `bot.py`
- `requirements.txt`
- `render.yaml`
- `.env.example`

### Étape 2 — Créer un dépôt GitHub
1. Va sur **github.com** → New repository
2. Nomme-le `apex-ai-trader`
3. Upload les 4 fichiers
4. Clique **Commit changes**

### Étape 3 — Déployer sur Render
1. Va sur **render.com** → Sign up (gratuit)
2. **New** → **Background Worker**
3. Connecte ton dépôt GitHub
4. Render détecte automatiquement le `render.yaml`

### Étape 4 — Variables d'environnement
Dans Render → **Environment** → ajoute :

| Variable | Valeur |
|---|---|
| `TELEGRAM_TOKEN` | Ton token BotFather |
| `TELEGRAM_CHAT_ID` | Ton Chat ID |
| `TWELVE_DATA_KEY` | Ta clé API Twelve Data |
| `RR_RATIO` | `2.0` |
| `SCAN_INTERVAL` | `300` |

### Étape 5 — Lancer
Clique **Deploy** → Le bot démarre et tourne 24/7 !

---

## 📊 API Prix gratuite

**Twelve Data** (gratuit) :
1. Va sur **twelvedata.com**
2. Crée un compte gratuit
3. Copie ta clé API dans `TWELVE_DATA_KEY`

Plan gratuit : 800 appels/jour (largement suffisant)

---

## 🎯 Logique des signaux

| Signal | Conditions |
|---|---|
| **ACHAT** | RSI < 40 + MACD haussier + EMA20 > EMA50 + prix près bande basse Bollinger |
| **VENTE** | RSI > 60 + MACD baissier + EMA20 < EMA50 + prix près bande haute Bollinger |
| **FERMER** | Signal inversé sur position ouverte |

---

## ⚠️ Avertissement

Ce bot est un outil d'aide à la décision. Le trading comporte des risques de perte en capital. Ne tradez jamais plus que ce que vous pouvez vous permettre de perdre.
