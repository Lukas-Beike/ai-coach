# Local Windows runtime

Because native Windows environments often lack compatible pre-compiled wheels for `sqlcipher3-binary`, the canonical development and testing environment is the local Docker container.

1. **Clone and Prepare**:
   ```powershell
   git clone https://github.com/Lukas-Beike/pacecraft.git
   cd pacecraft
   Copy-Item .env.example .env
   New-Item -ItemType Directory -Force .\data
   ```
2. **Build Local Image**:
   ```powershell
   docker build -t pacecraft:local .
   ```
3. **Run Local Container**:
   ```powershell
   docker run -d --name pacecraft `
     --restart unless-stopped `
     --read-only `
     --security-opt no-new-privileges:true `
     -p 8090:8090 `
     -v "${PWD}\data:/data" `
     --env-file .env `
     pacecraft:local
   ```
4. Access `http://localhost:8090` in your browser. Inspect logs using `docker logs -f pacecraft`.
