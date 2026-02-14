# Hosting CaseLinker for Public Access

## Quick Options for GitHub Users

### Option 1: Railway (Recommended - Easiest)
**Free tier available, auto-deploys from GitHub**

1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your CaseLinker repository
5. Railway auto-detects FastAPI and deploys
6. Get a public URL like: `https://caselinker-production.up.railway.app`

**Pros:**
- Free tier (500 hours/month)
- Auto-deploys on git push
- Handles database automatically
- Easy environment variables

**Cons:**
- Sleeps after inactivity (free tier)
- URL changes on each deploy (can use custom domain)

---

### Option 2: Render
**Free tier, similar to Railway**

1. Go to [render.com](https://render.com)
2. Sign up with GitHub
3. Click "New" → "Web Service"
4. Connect your GitHub repo
5. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `cd run && uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Environment:** Python 3
6. Deploy!

**Pros:**
- Free tier available
- Auto-deploys
- Custom domain support

**Cons:**
- Sleeps after 15 min inactivity (free tier)
- Slower cold starts

---

### Option 3: Fly.io
**Free tier, great for databases**

1. Install flyctl: `curl -L https://fly.io/install.sh | sh`
2. Run: `fly launch`
3. Follow prompts
4. Deploy: `fly deploy`

**Pros:**
- Free tier
- Good database support
- Fast

**Cons:**
- Requires CLI setup
- More configuration needed

---

### Option 4: Heroku (Paid now, but reliable)
**$7/month for hobby dyno**

1. Install Heroku CLI
2. `heroku create caselinker-app`
3. `git push heroku main`
4. Done!

---

## Required Changes for Hosting

### 1. Update `run/main.py` for Production

```python
# At the bottom of run/main.py, change:
if __name__ == "__main__":
    import uvicorn
    import os
    
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    
    uvicorn.run(app, host=host, port=port, reload=False)
```

### 2. Add `Procfile` (for Heroku/Railway)

Create `Procfile` in root:
```
web: cd run && uvicorn main:app --host 0.0.0.0 --port $PORT
```

### 3. Add `runtime.txt` (optional, for Python version)

```
python-3.11.0
```

### 4. Environment Variables

Set these in your hosting platform:
- `DATABASE_PATH=caselinker.db` (or use hosted database)
- `ENABLE_ENCRYPTION=False` (or configure SQLCipher on host)
- `API_HOST=0.0.0.0`
- `API_PORT=$PORT` (usually auto-set)

---

## Database Options

### Option A: Keep SQLite (Simple)
- Works for small datasets
- File-based, included in deployment
- **Limitation:** Not great for concurrent writes

### Option B: PostgreSQL (Recommended for production)
- Free tiers on Railway, Render, Supabase
- Better for multiple users
- Requires code changes to use `psycopg2` instead of SQLite

---

## Quick Start: Railway (5 minutes)

1. **Push to GitHub** (if not already):
   ```bash
   git add .
   git commit -m "Ready for deployment"
   git push origin main
   ```

2. **Deploy on Railway**:
   - Go to railway.app
   - Click "New Project" → "Deploy from GitHub"
   - Select CaseLinker repo
   - Wait 2-3 minutes
   - Get public URL!

3. **Share the link:**
   - Your CaseLinker will be live at: `https://your-app.railway.app`
   - Anyone can access it!

---

## Custom Domain (Optional)

Most platforms let you add a custom domain:
- Railway: Settings → Domains → Add custom domain
- Render: Settings → Custom Domains
- Point your DNS to their provided CNAME

Example: `caselinker.yourname.com` → Your Railway app

---

## Security Notes

⚠️ **Important for Production:**
- Don't expose sensitive data
- Use environment variables for secrets
- Consider adding authentication if needed
- Database encryption (SQLCipher) may not work on all platforms

---

## Testing Locally Before Deploy

```bash
# Test with production-like settings
PORT=8000 HOST=0.0.0.0 python3 run/main.py
```

Then visit: `http://localhost:8000`

---

## Recommended: Railway

**Why Railway:**
- ✅ Easiest setup
- ✅ Free tier
- ✅ Auto-deploys from GitHub
- ✅ Good documentation
- ✅ Handles Python/FastAPI automatically

**Steps:**
1. Sign up at railway.app (GitHub OAuth)
2. New Project → Deploy from GitHub
3. Select CaseLinker
4. Wait 2 minutes
5. Get public URL
6. Share!

Your CaseLinker will be live and accessible to anyone with the link! 🚀
