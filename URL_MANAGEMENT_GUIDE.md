# 📅 Smart URL Management Guide

Your ticketwatch now automatically organizes URLs by concert date and notifies you when events should be removed. Here's how to manage your URL list efficiently!

## 🎯 Key Features

- **📅 Auto-sorting by date**: URLs automatically organized chronologically
- **🗑️ Smart cleanup**: Past events automatically detected and removed  
- **📊 Beautiful formatting**: URLs saved with event names and dates as comments
- **🔔 Removal notifications**: Get notified when events are cleaned up
- **⚠️ Date warnings**: Know which URLs are missing event dates

## 📋 URL Manager Commands

### Add URLs
```bash
# Add a single URL
python url_manager.py add https://example.ticketweb.com/event123

# Add multiple URLs at once
python url_manager.py add url1 url2 url3
```

### Remove URLs
```bash
python url_manager.py remove https://example.ticketweb.com/event123
```

### List & Organize
```bash
# View all URLs organized by month
python url_manager.py list

# Sort URLs by event date (fetches fresh data)
python url_manager.py sort

# Show statistics about your URLs
python url_manager.py stats
```

### Validation & Cleanup
```bash
# Check all URLs for issues
python url_manager.py validate

# Remove past events manually
python url_manager.py clean
```

## 📁 Organized URL File Format

Your `urls.txt` file now looks like this:

```
# Ticketwatch URLs - Automatically sorted by event date
# Format: URL  # Event Name - Date

# === December 2024 ===
https://example.ticketweb.com/event1  # Taylor Swift - Boston - Dec 15
https://example.ticketweb.com/event2  # Post Malone - NYC - Dec 20

# === January 2025 ===
https://example.ticketweb.com/event3  # Coldplay - Chicago - Jan 10

# === Events without dates ===
https://example.ticketweb.com/event4  # Mystery Show - No date found
```

## 🔔 Automatic Notifications

### When Events Are Removed
```
🗓️ Past Events Removed (3)

• Taylor Swift Concert - Dec 15, 2024
• Post Malone Show - Dec 20, 2024  
• Ed Sheeran Live - Jan 05, 2025
```

### Regular Status Updates
```
✅ No changes detected
📊 Monitored 487 events successfully
⏰ 14:30 EST
```

## 🚀 Daily Workflow Examples

### Adding New Events
```bash
# Found some new concerts to monitor
python url_manager.py add \
  https://ticketweb.com/event/coldplay-tour \
  https://ticketweb.com/event/taylor-swift-new

# Auto-sort by date  
python url_manager.py sort
```

### Weekly Maintenance
```bash
# Check for any issues
python url_manager.py validate

# See what you're monitoring
python url_manager.py stats

# Clean up if needed (though this happens automatically)
python url_manager.py clean
```

## 🎯 Pro Tips

### 1. **Batch Adding URLs**
Save URLs to a text file and add them all at once:
```bash
# Save URLs in new_events.txt (one per line)
cat new_events.txt | xargs python url_manager.py add
```

### 2. **Quick Stats Check**
```bash
python url_manager.py stats
```
Shows:
- Total events
- Upcoming vs past events  
- Events by month
- Missing dates

### 3. **Validation Before Important Runs**
```bash
python url_manager.py validate
```
Checks all URLs and reports:
- Failed/broken URLs
- Past events to remove
- Events missing dates

## 🔧 Integration with Main Script

The main `ticketwatch_v2.py` script now:

1. **Automatically sorts** your URLs by date after each run
2. **Notifies you** when past events are removed
3. **Saves URLs** with beautiful formatting and comments
4. **Handles missing dates** gracefully

## 🎉 Example: Managing 500 URLs

```bash
# Check your current status
python url_manager.py stats
# Output: Total URLs: 487, Upcoming: 456, Past: 31

# Run your monitoring (happens automatically every hour)  
python ticketwatch_v2.py
# Output: 🗑️ Removed 31 past events, 📅 Saved 456 URLs sorted by date

# Add new events you found
python url_manager.py add url1 url2 url3
python url_manager.py sort

# Quick validation check
python url_manager.py validate
```

## 🔄 Automatic Features

Every time you run `ticketwatch_v2.py`:
- ✅ URLs automatically sorted by date
- 🗑️ Past events automatically removed  
- 📱 Telegram notification of what was removed
- 💾 Clean, organized URL file saved
- 📊 Progress and statistics displayed

Your URL management is now completely automated and intelligent! 🎯