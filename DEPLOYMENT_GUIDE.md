# 🚀 GitHub Deployment Guide

## 🔧 What Was Fixed

### ❌ **Original Problem**
Your system was showing all prices as "unknown" every scan because:
- Main `urls.txt` had only 3 URLs
- Main `state.json` contained data for 300+ different URLs  
- State mismatch meant no price history was found
- System treated every scan as "first time"

### ✅ **Solution Applied**
1. **Consolidated System**: Merged all batch data into unified `urls.txt` and `state.json`
2. **Fixed State Persistence**: Now properly saves and loads price history
3. **GitHub Actions Ready**: Optimized for cloud deployment
4. **Enhanced Monitoring**: Better error handling and rate limiting

## 📋 Deployment Checklist  

### 🔐 Required GitHub Secrets
Set these in Repository Settings → Secrets and variables → Actions:

| Secret | Description | How to Get |
|--------|-------------|------------|
| `TG_TOKEN` | Telegram Bot Token | Message [@BotFather](https://t.me/botfather) |
| `TG_CHAT` | Your Telegram Chat ID | Message [@userinfobot](https://t.me/userinfobot) |

### 📂 File Structure
```
ticketwatch/
├── .github/workflows/ticketwatch-hourly.yml  # ✅ GitHub Actions workflow
├── ticketwatch_v2.py                         # ✅ Main monitoring script  
├── run_hourly.py                             # ✅ Enhanced runner
├── urls.txt                                  # ✅ Consolidated URLs (359 events)
├── state.json                                # ✅ Unified state (379 entries)
├── requirements.txt                          # ✅ Dependencies
└── README.md                                 # ✅ Documentation
```

### 🧹 Cleanup Completed
- ✅ Consolidated 5 batch files into main `urls.txt`
- ✅ Merged all state data into main `state.json`  
- ✅ Created backup in `url_batches_backup/`
- ✅ Fixed state persistence issue
- ✅ Updated rate limiting for GitHub Actions

## 🎯 Verification Steps

### 1. Test State Persistence (✅ Verified)
```bash
python run_hourly.py
```
**Expected**: Should show price changes like `$45.00 → $45.00` (not `unknown → $45.00`)

### 2. Check GitHub Actions
After pushing to GitHub:
- Go to Actions tab
- Verify workflow runs every hour
- Check for successful completions

### 3. Telegram Notifications  
- First run may show many "new" events (🆕 emojis)
- Subsequent runs should only show real changes
- Look for beautiful formatted messages with urgency indicators

## 🔄 System Behavior

### First Run After Deployment
- May detect many "changes" as URLs are processed with new state
- This is normal - subsequent runs will be clean

### Ongoing Operation  
- Runs every hour automatically
- Only reports actual price changes
- Commits state updates back to repository
- Suggests cleanup of past events

## 📊 Performance Tuning

Current settings optimized for GitHub Actions:
```python
MAX_CONCURRENT = 10      # Reduced to avoid rate limits
REQUEST_DELAY = 0.5      # Increased for stability  
RETRY_ATTEMPTS = 3       # Fallback to CloudScraper
```

## 🚨 Common Issues & Solutions

### Issue: SSL Certificate Errors
```
✖ certificate verify failed: unable to get local issuer certificate
```
**Solution**: Normal behavior - system has CloudScraper fallback

### Issue: 403 Forbidden Responses
```  
✖ 403, message='Forbidden'
```
**Solution**: Rate limiting in effect - system will retry and fallback

### Issue: No Telegram Notifications
**Check**:
1. Bot token is correct in GitHub Secrets
2. Chat ID includes the minus sign if it's a group (e.g., `-123456789`)
3. Bot has been started by sending `/start` command

### Issue: State Not Persisting
**GitHub Actions**: Automatic commit should happen after each run
**Local Testing**: Changes saved to local `state.json`

## 🎉 Success Indicators

✅ **Working Correctly When You See:**
- Price changes show as `$X.XX → $Y.YY` (not `unknown`)
- Telegram messages with proper emojis and formatting
- GitHub commits after each hourly run
- Events sorted by date in `urls.txt`

## 📞 Support

If issues persist:
1. Check GitHub Actions logs for detailed error messages
2. Verify all secrets are properly set
3. Test locally with `python run_hourly.py --github`

---

Your Ticketwatch system is now ready for production deployment! 🚀