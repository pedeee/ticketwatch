#!/bin/bash
# 🚀 Deploy Ticketwatch to GitHub

echo "🎟️ Ticketwatch Deployment Script"
echo "================================="

# Check if we're in a git repository
if [ ! -d ".git" ]; then
    echo "❌ Not in a git repository. Initialize with: git init"
    exit 1
fi

# Check for required files
required_files=("urls.txt" "state.json" "ticketwatch_v2.py" "run_hourly.py" ".github/workflows/ticketwatch-hourly.yml")
for file in "${required_files[@]}"; do
    if [ ! -f "$file" ]; then
        echo "❌ Missing required file: $file"
        exit 1
    fi
done

echo "✅ All required files present"

# Check URL count
url_count=$(grep -v '^#' urls.txt | grep -c 'http' || echo '0')
echo "📊 Found $url_count URLs to monitor"

if [ "$url_count" -eq 0 ]; then
    echo "⚠️  Warning: No URLs found in urls.txt"
    echo "   Add your Ticketweb URLs before deploying"
fi

# Check state file
state_lines=$(wc -l < state.json || echo '0')
echo "💾 State file has $state_lines lines"

# Prepare commit
echo ""
echo "🔄 Preparing deployment commit..."

git add .
git status

echo ""
echo "📝 Ready to commit and push to GitHub"
echo "   After pushing, set up these GitHub Secrets:"
echo "   - TG_TOKEN: Your Telegram bot token"
echo "   - TG_CHAT: Your Telegram chat ID"
echo ""
echo "🚀 Run these commands to deploy:"
echo "   git commit -m '🎟️ Deploy Ticketwatch with fixed state persistence'"
echo "   git push origin main"
echo ""
echo "✅ GitHub Actions will then run automatically every hour!"