# Quickstart

Get Matchbox running on your Mac in 5 minutes.

## 1. Install Docker Desktop

Download and install from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/). Open Docker Desktop and wait for it to finish starting (you'll see a green icon in the menu bar).

## 2. Get an Anthropic API key

Sign up at [console.anthropic.com](https://console.anthropic.com/), add a payment method, then create an API key. Copy it — you'll paste it into Matchbox in step 5.

## 3. Download Matchbox

Open **Terminal** (press Cmd+Space, type "Terminal", hit Enter) and run:

```bash
git clone https://github.com/marcammann/matchbox.git
cd matchbox
```

If you see a popup about installing developer tools, click **Install** and wait for it to finish, then run the commands again.

## 4. Start Matchbox

```bash
docker compose up --build
```

The first build takes a few minutes. When you see `Uvicorn running on http://0.0.0.0:8000`, it's ready.

## 5. Set up your profile

Open [http://localhost:8000](http://localhost:8000) in your browser and go to **Settings**:

1. Paste your Anthropic API key
2. Paste your resume (markdown or plain text)
3. Click **Generate from Resume** to auto-fill your profile and search queries
4. Adjust target roles and search queries to your liking
5. Click **Save**

## 6. Run your first search

Go to **Jobs** and click **Run Search**. Matchbox will search across multiple job boards, score each job against your profile, and show the results ranked by fit.

Click any job to see why it matched, then click **Prepare Application** to generate a tailored resume and cover letter.

## Stopping and restarting

- **Stop:** Press Ctrl+C in Terminal, or run `docker compose down`
- **Restart:** Run `docker compose up` (no `--build` needed after the first time)

Your data (config, resume, jobs, applications) is saved in the `data/` folder and persists between restarts.
