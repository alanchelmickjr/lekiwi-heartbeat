# 🚀 LeKiwi Deploy - Vercel for Robots

## End Your SSH Nightmare TODAY!

Transform your robot fleet deployment from manual SSH chaos to automated Git-based deployments. Push code, robots update automatically. Roll back instantly to any version. Just like Vercel, but for robots!

---

## 🎯 What This Solves

### Before (Your Current Nightmare 😱)
- Developers SSH into each robot manually via ZeroTier
- Inconsistent code across robots
- No version tracking
- No rollback capability
- Management nightmare!

### After (Your New Reality 🎉)
```bash
git push                    # All robots update automatically!
lekiwi-deploy rollback v2.0 # Instant rollback to any version!
```

---

## 📦 What's Included

```
lekiwi-heartbeat/
├── deployment-server/      # Central deployment server
│   ├── server.py          # FastAPI deployment server
│   └── install.sh         # One-command installation
├── deployment-agent/       # Robot agent
│   ├── agent.py           # Runs on each robot
│   └── install.sh         # Quick robot setup
├── deployment-cli/         # Developer tools
│   └── lekiwi-deploy      # CLI for deployments
└── docs/                   # Documentation
    ├── deployment-architecture.md
    ├── vercel-for-robots.md
    └── quick-start-deployment.md
```

---

## ⚡ Quick Start (Get Running in 30 Minutes!)

### Step 1: Install Deployment Server (5 minutes)

On your control server:

```bash
# Clone the repository
git clone https://github.com/your-org/lekiwi-heartbeat.git
cd lekiwi-heartbeat/deployment-server

# Run installation
sudo ./install.sh

# Configure your GitHub repo
sudo nano /etc/lekiwi-deploy/config.json
# Update: "github_repo": "https://github.com/YOUR-ORG/robot-code.git"

# Start the server
sudo systemctl start lekiwi-deploy

# Verify it's running
curl http://localhost:8000
```

Your deployment server is now running! 🎉

### Step 2: Install Agent on Robots (5 minutes per robot)

On each robot:

```bash
# Copy agent files to robot
scp -r deployment-agent/ lekiwi@192.168.88.21:~/

# SSH to robot and install
ssh lekiwi@192.168.88.21
cd deployment-agent
sudo DEPLOY_SERVER_URL=http://192.168.88.1:8000 ./install.sh

# Start the agent
sudo systemctl start lekiwi-deploy-agent

# Verify it's running
sudo systemctl status lekiwi-deploy-agent
```

Robot is now ready for automatic deployments! 🤖

### Step 3: Install CLI Tool (2 minutes)

On your development machine:

```bash
# Install the CLI
sudo cp deployment-cli/lekiwi-deploy /usr/local/bin/
sudo chmod +x /usr/local/bin/lekiwi-deploy

# Configure server URL
lekiwi-deploy config --server http://192.168.88.1:8000

# Test connection
lekiwi-deploy status
```

### Step 4: Deploy Your First Update! 🚀

```bash
# From your robot code repository
cd /path/to/robot-code

# Deploy current code
lekiwi-deploy deploy

# Or deploy with specific version
lekiwi-deploy deploy -v v2.1.0 -m "Fixed navigation bug"

# Watch the magic happen!
lekiwi-deploy status
```

**That's it! Your robots will automatically update!**

---

## 🎮 Usage Examples

### Deploy Code
```bash
# Deploy from current git HEAD
lekiwi-deploy deploy

# Deploy specific version to staging robots
lekiwi-deploy deploy -v v2.1.0 -g staging

# Deploy with custom message
lekiwi-deploy deploy -m "Emergency navigation fix"
```

### View Deployments
```bash
# List recent deployments
lekiwi-deploy list

# Output:
# 📦 Recent Deployments
# ================================================================================
# ID            Version    Branch    Author      Time              Status
# dep_a3f2c8b9  v2.1.0     main      john        2024-01-15 14:30  ✅
# dep_b7d4e2a1  v2.0.9     main      sarah       2024-01-15 13:15  ✅
# dep_c9f1a5d3  v2.0.8     staging   mike        2024-01-15 11:45  ✅ ↩️
```

### Check Robot Status
```bash
# View all robots
lekiwi-deploy status

# Output:
# 🤖 Robot Fleet Status
# ================================================================================
# Robot ID        Version    Deployment    Status      Health
# Lekiwi_A3F2C8   v2.1.0     dep_a3f2     success     🟢 Online
# Lekiwi_B7D4E2   v2.1.0     dep_a3f2     success     🟢 Online
# Lekiwi_C9F1A5   v2.0.9     dep_b7d4     success     🟡 Away
```

### Instant Rollback
```bash
# Rollback to specific deployment
lekiwi-deploy rollback dep_b7d4e2a1

# Rollback to version
lekiwi-deploy rollback v2.0.9

# Rollback to 2 hours ago
lekiwi-deploy rollback 2-hours-ago
```

---

## 🔧 Configuration

### Deployment Groups

Configure robots into groups for staged deployments:

```json
// /etc/lekiwi-deploy/agent.json on robot
{
  "group": "production",  // or "staging", "development"
  ...
}
```

Deploy to specific groups:
```bash
lekiwi-deploy deploy -g staging     # Only staging robots
lekiwi-deploy deploy -g production  # Only production robots
lekiwi-deploy deploy -g all         # All robots
```

### GitHub Integration

1. Go to your GitHub repository settings
2. Add webhook:
   - URL: `http://YOUR-SERVER-IP:8000/webhook/github`
   - Content type: `application/json`
   - Events: Just the push event
3. Save

Now every push to main will auto-deploy!

### Service Management

Configure which services to restart on deployment:

```json
// /etc/lekiwi-deploy/agent.json
{
  "services": ["teleop", "lekiwi", "navigation"],
  ...
}
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                   GitHub Repository                  │
│                  (Your Robot Code)                   │
└────────────────────┬────────────────────────────────┘
                     │ Push / Webhook
                     ▼
┌─────────────────────────────────────────────────────┐
│              Deployment Server (FastAPI)             │
│  • Builds deployment packages                        │
│  • Stores version history (last 100)                 │
│  • Manages rollbacks                                 │
└────────────────────┬────────────────────────────────┘
                     │ Poll for updates
                     ▼
┌─────────────────────────────────────────────────────┐
│                  Robot Fleet                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Robot 1  │  │ Robot 2  │  │ Robot 3  │  ...     │
│  │ • Agent  │  │ • Agent  │  │ • Agent  │          │
│  │ • v2.1.0 │  │ • v2.1.0 │  │ • v2.1.0 │          │
│  └──────────┘  └──────────┘  └──────────┘          │
└─────────────────────────────────────────────────────┘
```

---

## 🛠️ Advanced Features

### Health Checks & Auto-Rollback

The agent automatically:
- Checks if services start successfully
- Verifies health endpoints
- Rolls back if deployment fails

### Deployment Slots

Each robot keeps the last 10 deployments:
```
/opt/lekiwi-deploy/
├── current -> deployments/dep_a3f2c8b9  # Symlink to active
├── deployments/
│   ├── dep_a3f2c8b9/  # Current
│   ├── dep_b7d4e2a1/  # Previous
│   ├── dep_c9f1a5d3/  # Older
│   └── ...            # Up to 10 versions
```

### Zero-Downtime Deployment

Atomic symlink switching ensures:
- No partial updates
- Instant rollback
- Services restart with new code

---

## 📊 Monitoring

### View Logs
```bash
# Server logs
sudo journalctl -u lekiwi-deploy -f

# Agent logs (on robot)
sudo journalctl -u lekiwi-deploy-agent -f
```

### Check Service Status
```bash
# On server
sudo systemctl status lekiwi-deploy

# On robot
sudo systemctl status lekiwi-deploy-agent
```

---

## 🚨 Troubleshooting

### Agent Not Updating

1. Check agent is running:
   ```bash
   sudo systemctl status lekiwi-deploy-agent
   ```

2. Check connectivity to server:
   ```bash
   curl http://YOUR-SERVER:8000/api/check-update?robot_id=test&current_version=0.0.0
   ```

3. Check logs for errors:
   ```bash
   sudo tail -f /opt/lekiwi-deploy/logs/agent.log
   ```

### Deployment Fails

1. Check server logs:
   ```bash
   sudo journalctl -u lekiwi-deploy -n 50
   ```

2. Verify GitHub repo access:
   ```bash
   git clone https://github.com/YOUR-ORG/robot-code.git /tmp/test
   ```

3. Manual rollback if needed:
   ```bash
   lekiwi-deploy rollback dep_PREVIOUS_ID
   ```

---

## 🎯 Benefits Summary

### For Management
- ✅ **No More SSH Access**: Developers can't break production
- ✅ **Complete Audit Trail**: Know who deployed what and when
- ✅ **Consistent Fleet**: All robots run the same code
- ✅ **Easy Rollback**: One click to fix problems

### For Developers
- ✅ **Git Push = Deploy**: Familiar workflow
- ✅ **Instant Rollback**: Fix mistakes quickly
- ✅ **Version History**: See all deployments
- ✅ **No SSH Keys**: No access management headaches

### For Operations
- ✅ **Automatic Updates**: Robots self-update
- ✅ **Health Monitoring**: Auto-rollback on failures
- ✅ **Staged Rollouts**: Test on subset first
- ✅ **Zero Downtime**: Atomic deployments

---

## 📈 Next Steps

### Phase 1: Basic Deployment ✅
- [x] Deployment server
- [x] Robot agents
- [x] CLI tool
- [x] Rollback capability

### Phase 2: Enhanced Features (Next Week)
- [ ] Web dashboard UI
- [ ] Real-time log streaming
- [ ] PostgreSQL storage
- [ ] Deployment metrics

### Phase 3: Enterprise Features (Next Month)
- [ ] Staged rollouts (canary deployments)
- [ ] A/B testing support
- [ ] Deployment approval workflow
- [ ] Integration with CI/CD

---

## 🤝 Support

Need help? Check out:
- [Quick Start Guide](quick-start-deployment.md)
- [Architecture Documentation](deployment-architecture.md)
- [Vercel-Style Features](vercel-for-robots.md)

---

## 🎊 Congratulations!

You've just eliminated manual SSH deployments forever! 

Your robots now update automatically when you push code. You can roll back instantly to any version. Your management nightmare is over!

**Welcome to the future of robot fleet management!** 🚀

---

*Built with ❤️ to end SSH tomfoolery once and for all*