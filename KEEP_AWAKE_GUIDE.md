# Keeping Your Server Awake on Render.com

## Current Setup (Free Tier)

Three layers keep the service ahead of Render's 15-minute sleep timeout. They
are listed in order of how much you should rely on them.

### 1. In-process self-ping (`app/keepalive.py`)

The API pings its own public URL every `KEEPALIVE_INTERVAL_MINUTES` from one
background task started in the FastAPI lifespan. The request leaves the
container and re-enters through Render's router, so it counts as inbound
traffic and holds the idle timer open.

- **Holds an awake instance awake:** yes.
- **Wakes a stopped instance:** **no** — a stopped process pings nothing.
  This is why layer 2 is not optional.
- Failures are caught and logged, never raised; the interval is clamped to
  1–14 minutes and jittered to 85–100%.

```bash
KEEPALIVE_ENABLED=true            # default false
KEEPALIVE_INTERVAL_MINUTES=10     # clamped to 1-14
KEEPALIVE_PATH=/ping
# KEEPALIVE_URL unset on Render: RENDER_EXTERNAL_URL is used automatically
```

Check it with `curl -s https://your-app.onrender.com/ping` — the `keepalive`
block in the response reports `running`, `pings_ok`, `pings_failed` and
`last_error`. Full walkthrough in the README's **Keeping the API awake**.

### 2. cronjob.org External Wake-up (the only layer that can *wake* it)

- **Endpoint**: `https://your-app.onrender.com/ping`
- **Schedule**: Every 4 minutes (`*/4 * * * *`)
- **Purpose**: wakes a stopped instance, which nothing inside the container can
- **Response**: `{"status":"awake","timestamp":"...","keepalive":{...}}`

On a paid plan, the commented `type: cron` service in `render.yaml` does the
same job on Render itself.

### 3. Frontend Polling

The dashboard refreshes expenses while its tab is visible, which incidentally
counts as traffic. It is a side effect, not a keep-alive: polling stops when
the tab is hidden, backs off to 60s on repeated failures, and does nothing at
all when nobody has the app open.

- **`frontend/`** (the app you actually use): 15s base interval, exponential
  backoff to 60s on failure, paused while the tab is hidden, immediate refresh
  when it becomes visible again.
- **`app/static/index.html`** (the legacy server-rendered dashboard): this is
  the only consumer of `FRONTEND_POLL_INTERVAL_MS`, which `app/routes/view.py`
  injects into the page at request time.

### Configuration
```bash
ENVIRONMENT=production
KEEPALIVE_ENABLED=true            # layer 1
KEEPALIVE_INTERVAL_MINUTES=10
ENABLE_CRONJOB_PING=true          # layer 2's endpoint
CRONJOB_PING_INTERVAL_MINUTES=4   # interval /ping advertises to callers
FRONTEND_POLL_INTERVAL_MS=300000  # layer 3, legacy dashboard only
```

## Setting Up cronjob.org

1. Go to [cron-job.org](https://cron-job.org/) and create a free account
2. Create a new cron job with these settings:
   - **Title**: "Keep Expense App Awake"
   - **URL**: `https://your-app.onrender.com/ping`
   - **Execution schedule**: Every 4 minutes
   - **Cron expression**: `*/4 * * * *`
   - **Request method**: GET
   - **Timeout**: 30 seconds
3. Enable the cron job
4. Monitor the execution log to ensure it's working

## Limitations of Free Tier

Even with these optimizations, the free tier has limitations:
- **15-minute sleep timeout**: No activity for 15 minutes = server sleeps
- **Cold starts**: First request after sleep takes 10-30 seconds to respond
- **Resource limits**: Limited CPU and memory
- **No guarantee**: External pings can occasionally fail

## Paid Alternatives for 24/7 Uptime

### 1. Render.com Paid Plans
- **Starter ($7/month)**: 
  - No sleep timeout
  - 512MB RAM, 0.5 CPU
  - Always-on server
  - Better performance
  
- **Standard ($25/month)**:
  - More resources
  - Better performance
  - Dedicated resources

**Benefits**: Same platform, easy migration, no code changes needed

### 2. Alternative Platforms

#### Railway.app
- **Free tier**: $5 credit/month, then pay-as-you-go
- **Paid**: From $5/month
- **Benefits**: Similar deployment experience, no sleep on paid plans

#### Fly.io
- **Free tier**: Limited resources with sleep
- **Paid**: From ~$5-10/month
- **Benefits**: Global deployment, good performance

#### DigitalOcean App Platform
- **Basic**: $5/month
- **Benefits**: Reliable, good performance, no sleep

#### Heroku
- **Eco**: $5/month
- **Benefits**: Established platform, no sleep on paid plans

### 3. VPS Solutions (Full Control)
- **DigitalOcean Droplet**: $4-6/month
- **Linode**: $5/month
- **AWS Lightsail**: $3.50/month

**Benefits**: Full control, guaranteed uptime, can run multiple services
**Trade-off**: Requires server management, SSL setup, monitoring

## Recommendations

### For Personal Use (Current Setup)
- Continue with free tier + cronjob.org
- Accept occasional cold starts (10-30 seconds)
- Monitor uptime and adjust cronjob.org interval if needed

### For Critical/Production Use
- **Upgrade to Render.com Starter ($7/month)**: Best balance of cost/convenience
- Or **DigitalOcean App Platform ($5/month)**: Reliable alternative

### For Multiple Projects
- **VPS ($5-6/month)**: Most cost-effective for multiple apps
- Host this app + other services on same server

## Monitoring Your Setup

1. **Check cronjob.org logs**: Ensure pings are successful
2. **Monitor response times**: Note cold start duration
3. **Test manually**: Open app after 15+ minutes of inactivity
4. **Set up uptime monitoring**: Use UptimeRobot or similar

## Troubleshooting

### Keep-alive Not Running

`curl -s https://your-app.onrender.com/ping` and read the `keepalive` block:

- `"enabled": false` — `KEEPALIVE_ENABLED` never reached the process. Check the
  Render dashboard's Environment tab, then redeploy.
- `"url": null` — neither `KEEPALIVE_URL` nor `RENDER_EXTERNAL_URL` was set.
  Set `KEEPALIVE_URL` explicitly.
- `"last_error": "HTTP 404"` — `KEEPALIVE_PATH` is wrong, or it points at
  `/ping` while `ENABLE_CRONJOB_PING=false`.
- `"running": false` with `enabled: true` — the boot log says why; look for
  `keep-alive` lines in Render's logs.

Remember that a self-ping cannot wake a stopped instance, so an instance that
was asleep will show `pings_ok: 0` until something external wakes it.

### Server Still Sleeping
1. Check cronjob.org execution logs
2. Verify `/ping` endpoint is accessible
3. Ensure `ENABLE_CRONJOB_PING=true` in environment variables
4. Try reducing cronjob.org interval to 2-3 minutes

### High API Usage
1. Reduce `FRONTEND_POLL_INTERVAL_MS` in config
2. Consider upgrading to paid plan for peace of mind

### Performance Issues
1. Current setup adds minimal overhead
2. If issues persist, paid plans provide dedicated resources

## Environment Variables Summary

```bash
# Core settings
MONGODB_URI=your_mongodb_connection_string
SHORTCUT_API_KEY=your_api_key

# Keep-alive settings
ENVIRONMENT=production
KEEPALIVE_ENABLED=true            # in-process self-ping (default false)
KEEPALIVE_INTERVAL_MINUTES=10     # clamped to 1-14; Render sleeps at 15
KEEPALIVE_PATH=/ping              # use /health if ENABLE_CRONJOB_PING=false
# KEEPALIVE_URL=                  # unset on Render: RENDER_EXTERNAL_URL is used
ENABLE_CRONJOB_PING=true
CRONJOB_PING_INTERVAL_MINUTES=4  # cronjob.org setting
FRONTEND_POLL_INTERVAL_MS=300000  # legacy dashboard only
```

## Conclusion

Your current setup provides a cost-effective way to keep the server mostly awake using free services. For guaranteed 24/7 uptime without cold starts, upgrading to a paid plan (Render.com Starter at $7/month) is the recommended solution.