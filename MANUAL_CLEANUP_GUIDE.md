# 🛡️ Manual Cleanup Guide - Safe URL Management

Your ticketwatch now requires **manual approval** for removing past events, preventing accidental deletions due to date parsing errors or other issues.

## 🔄 How It Works Now

### 1. **Monitoring (No Auto-Removal)**
```bash
python3 ticketwatch_v2.py url_batches/batch1.txt
```

**What happens:**
- ✅ Processes all URLs (including past events)
- ✅ Detects price changes and notifications
- ✅ Auto-sorts URLs by date for organization  
- ⚠️ **Reports past events but doesn't remove them**
- 📱 Sends Telegram notification about past events found

### 2. **Telegram Notifications**
You'll receive messages like:
```
⚠️ Past Events Found (5)
These events could be removed manually:

• Taylor Swift Concert - Dec 15, 2024
• Post Malone Show - Dec 20, 2024
• Ed Sheeran Live - Jan 05, 2025

💡 To remove: python3 batch_manager.py clean --review
```

## 🔍 Manual Cleanup Commands

### **Preview What Would Be Removed**
```bash
# See all past events across all batches
python3 batch_manager.py preview

# Preview specific batch
python3 batch_manager.py preview --batch=1
```

**Example output:**
```
🔍 Preview of past events that could be removed:

📁 batch1 (3 past events):
  • Taylor Swift Concert - Dec 15, 2024
  • Post Malone Show - Dec 20, 2024
  • Ed Sheeran Live - Jan 05, 2025

📁 batch2 (2 past events):
  • Coldplay Tour - Dec 10, 2024
  • Billie Eilish - Dec 18, 2024

📊 Total: 5 past events could be removed
```

### **Safe Removal with Confirmation**
```bash
# Remove past events with confirmation prompts
python3 batch_manager.py clean --review

# Clean specific batch with confirmation
python3 batch_manager.py clean --review --batch=1
```

**Example interaction:**
```
🔍 Checking batch1...
  📅 Found 3 past events:
     1. Taylor Swift Concert - Dec 15, 2024
     2. Post Malone Show - Dec 20, 2024
     3. Ed Sheeran Live - Jan 05, 2025

  Remove 3 events from batch1? (y/N): y
  🗑️ Removed 3 events from batch1

📊 Summary:
  Past events found: 3
  Events removed: 3
```

### **Quick Removal (No Confirmation)**
```bash
# Remove all past events immediately
python3 batch_manager.py clean

# Remove from specific batch immediately  
python3 batch_manager.py clean --batch=2
```

## 🎯 Recommended Workflow

### **Daily Monitoring**
```bash
# Run your regular monitoring (reports past events)
python3 run_hourly.py --continuous
```

### **Weekly Cleanup**
```bash
# 1. Preview what could be removed
python3 batch_manager.py preview

# 2. Review and remove with confirmation
python3 batch_manager.py clean --review

# 3. Check statistics
python3 batch_manager.py stats
```

### **Monthly Maintenance**
```bash
# Full validation and cleanup
python3 batch_manager.py validate
python3 batch_manager.py clean --review
python3 batch_manager.py sort  # Re-sort by date
```

## 🔔 What Triggers Cleanup Suggestions

You'll get notified about past events when:
- ✅ Regular monitoring runs and finds past events
- ✅ Event dates are clearly in the past
- ⚠️ **But removal requires your manual action**

## 🛡️ Safety Features

### **Date Parsing Protection**
- Events with unparseable dates are **never** flagged for removal
- Only events with clear, valid past dates are suggested
- Date parsing errors keep events safe

### **Confirmation Prompts**
- `--review` flag shows exactly what will be removed
- Batch-by-batch confirmation for granular control
- Easy to skip batches you want to keep

### **Preview Mode**
- See exactly what would be removed before doing anything
- No accidental deletions
- Clear summary of past events

## 📱 Example Telegram Notifications

### **Past Events Found**
```
⚠️ Past Events Found (12)
These events could be removed manually:

• Concert A - Nov 15, 2024
• Festival B - Nov 22, 2024
• Show C - Dec 01, 2024
... and 9 more

💡 To remove: python3 batch_manager.py clean --review
```

### **Regular Status (No Past Events)**
```
✅ Ticketwatch Status

✅ No changes detected
📊 Monitored 347 events successfully
⏰ 14:30 EST
```

## 🎉 Benefits of Manual Approval

- **🛡️ No accidental removals** due to date parsing errors
- **🔍 Full control** over what gets removed and when
- **📊 Clear visibility** into past events before removal
- **🎯 Flexible timing** - clean up when convenient
- **⚠️ Safe defaults** - keeps events unless you explicitly remove them

Your URL management is now both **powerful and safe**! 🎫✨