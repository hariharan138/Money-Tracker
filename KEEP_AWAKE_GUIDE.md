# Keeping Your Server Awake on Render.com

## Current Setup (Free Tier)

Your expense tracking app is configured with multiple layers of keep-alive mechanisms to prevent Render.com's 15-minute sleep timeout:

### 1. Frontend Polling Strategy
- **Active Tab**: Polls every 5 minutes for expense updates
- **Hidden Tab**: Lightweight `/ping` requests every 2 minutes
- **Tab Visibility**: Immediate refresh when tab becomes visible
- **Window Focus**: Instant refresh when window regains focus

### 2. cronjob.org External Wake-up
- **Endpoint**: `https://your-app.onrender.com/ping`
- **Schedule**: Every 4 minutes (`*/4 * * * *`)
- **Purpose**: External backup to wake server even when no users are active
- **Response**: `{"status":"awake","timestamp":"..."}`

### 3. Configuration
```bash
ENVIRONMENT=production
FRONTEND_POLL_INTERVAL_MS=300000  # 5 minutes
ENABLE_CRONJOB_PING=true
CRONJOB_PING_INTERVAL_MINUTES=4  # Recommended cronjob.org interval
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
FRONTEND_POLL_INTERVAL_MS=300000  # 5 minutes
ENABLE_CRONJOB_PING=true
CRONJOB_PING_INTERVAL_MINUTES=4  # cronjob.org setting
```

## Conclusion

Your current setup provides a cost-effective way to keep the server mostly awake using free services. For guaranteed 24/7 uptime without cold starts, upgrading to a paid plan (Render.com Starter at $7/month) is the recommended solution.