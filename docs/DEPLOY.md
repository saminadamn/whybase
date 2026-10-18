# Deploying WhyBase

WhyBase is two pieces: **FalkorDB** (the graph) and the **app** (one Docker image: FastAPI + static frontend). Pick one option.

## Option A — one VM with Docker Compose (simplest, everything in one place)

Any Linux VM with Docker (AWS EC2, GCP, Azure, DigitalOcean, Hetzner). 1 vCPU / 2 GB RAM is enough.

```bash
git clone <your-repo-url> whybase && cd whybase
cp .env.example .env          # set LLM_MODEL and GEMINI_API_KEY (or leave empty for offline mode)
docker compose up -d --build  # the app seeds Kettle Labs on first start
```

- Open port **8000** in the VM firewall or security group. Do **not** expose 6379 (FalkorDB) or 3000 (FalkorDB Browser) to the internet. To keep them private, change their `ports:` lines in `docker-compose.yml` to `"127.0.0.1:6379:6379"` and `"127.0.0.1:3000:3000"`.
- For HTTPS and a domain, put Caddy or nginx in front of the app.

## Option B — FalkorDB Cloud + a container host (Render / Railway / Fly.io)

1. **Database:** create a free instance at [FalkorDB Cloud](https://app.falkordb.cloud). Note its host, port, username and password.
2. **App:** push this repo to GitHub, then create a service from it on Render (*Web Service → Docker*), Railway or Fly.io. The `Dockerfile` is detected automatically, and the app listens on whatever `$PORT` the platform provides.
3. **Environment variables** on the service:

   | Variable | Value |
   |---|---|
   | `FALKOR_HOST` / `FALKOR_PORT` | from FalkorDB Cloud |
   | `FALKOR_USERNAME` / `FALKOR_PASSWORD` | from FalkorDB Cloud |
   | `FALKOR_SSL` | `true` if the instance requires TLS |
   | `GRAPH_NAME` | `whybase` |
   | `LLM_MODEL` | `gemini/gemini-3.1-flash-lite` (or leave empty for offline mode) |
   | `GEMINI_API_KEY` | your key, as a secret |

4. Deploy and open the service URL. On first start the app sees an empty graph and seeds Kettle Labs. Check `/api/health`; it should report `"falkordb": "ok"`.

## Before you share the link

- **`POST /api/reset` is public.** Anyone can wipe and reseed the demo graph. That's harmless for a demo (it only restores Kettle Labs), but remove the route or put it behind auth for anything else.
- **Public visitors use your LLM quota.** On the Gemini free tier it runs out quickly. When it does, the app switches to offline answers and the header shows *LLM quota hit · offline*, so the demo keeps working. Use a paid key, or leave `LLM_MODEL` empty for instant offline answers.
- **Data is synthetic** (Kettle Labs). Don't load real company data into a public deployment.
- Secrets live only in the platform's environment settings or the server's `.env`. Never commit `.env`.
