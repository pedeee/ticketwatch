# 🎟️ Ticketwatch

High-performance ticket price monitor for Ticketweb events with automated GitHub Actions deployment.

## ✨ Features

- **🔄 Automatic Monitoring**: Runs every hour via GitHub Actions
- **📱 Telegram Notifications**: Beautiful formatted alerts with emojis and urgency indicators
- **💾 State Persistence**: Remembers previous prices to detect real changes
- **🚀 High Performance**: Concurrent processing with intelligent rate limiting
- **📊 Smart Organization**: Auto-sorts events by date with cleanup suggestions
- **🎯 Change Detection**: Only notifies on actual price changes, not false positives

## 🚀 Quick Setup

### 1. Repository Setup
1. Fork this repository
2. Set up the required secrets in GitHub Settings → Secrets:
   - `TG_TOKEN`: Your Telegram bot token
   - `TG_CHAT`: Your Telegram chat ID

### 2. Add Your URLs
Edit `urls.txt` and add your Ticketweb event URLs (one per line):
```
https://www.ticketweb.ca/event/your-event-here/12345678
https://www.ticketweb.ca/event/another-event/87654321
```

### 3. Enable GitHub Actions
The workflow in `.github/workflows/ticketwatch-hourly.yml` will automatically:
- Run every hour
- Monitor all your events
- Send notifications on changes
- Commit state updates back to the repository

## 📱 Telegram Setup

1. Create a bot: Message [@BotFather](https://t.me/botfather) on Telegram
2. Get your chat ID: Message [@userinfobot](https://t.me/userinfobot)
3. Add the secrets to your GitHub repository

## 🏃 Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run once
python run_hourly.py

# Run continuously (for testing)
python run_hourly.py --continuous

# GitHub Actions mode
python run_hourly.py --github
```

## 📊 System Status

- **URLs Monitored**: $(grep -v '^#' urls.txt | grep -c 'http' || echo '0')
- **State Entries**: $(wc -l < state.json || echo '0') entries
- **Last Updated**: Automatically updated on each run

## 🔧 Configuration

Key settings in `ticketwatch_v2.py`:
- `MAX_CONCURRENT`: Number of parallel requests (default: 10)
- `REQUEST_DELAY`: Delay between requests (default: 0.5s)
- `PRICE_SELECTOR`: "lowest" or "highest" price selection

## 🎯 How It Works

1. **Fetch**: Concurrently fetches all event pages
2. **Parse**: Extracts prices, titles, and event dates
3. **Compare**: Compares against saved state to detect changes
4. **Notify**: Sends beautiful Telegram notifications for changes
5. **Save**: Updates state and commits back to repository

## 📈 Notification Types

- 🔥 **Urgent**: Events this week
- ⚡ **Soon**: Events this month  
- 📅 **Future**: Events later
- 🚫 **Sold Out**: No tickets available
- 📊 **Price Changes**: Price increases/decreases
- 🆕 **New Events**: First time seeing an event

## 🧹 Maintenance

The system automatically suggests cleanup of past events. Run locally:
```bash
python batch_manager.py preview  # See what would be cleaned
python batch_manager.py clean --review  # Clean with confirmation
```

## 🛠️ Troubleshooting

**No notifications?**
- Check your Telegram bot token and chat ID
- Verify the bot can send messages to your chat

**SSL errors?**
- Normal for some sites - the system has fallback mechanisms
- GitHub Actions may have different network behavior than local

**State not persisting?**
- GitHub Actions automatically commits changes
- Check the repository for updated `state.json`

## 📜 Recent Changes

✅ **Fixed State Persistence**: Consolidated batch system into unified state management  
✅ **GitHub Actions Ready**: Optimized for cloud deployment  
✅ **Enhanced Notifications**: Beautiful formatted messages with urgency indicators  
✅ **Improved Rate Limiting**: Reduced 403 errors and IP blocks  

---

Made with ❤️ for concert-goers who want to catch the best deals!