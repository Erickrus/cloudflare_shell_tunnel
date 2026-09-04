# Cloudflare Shell Tunnel

A lightweight remote shell service that exposes a local HTTP shell over a public Cloudflare Tunnel URL.  
Designed for agent-based remote invocation (e.g. Claude Code, Cursor, Aider, etc.) so an AI agent can execute commands, upload, and download files on a remote machine (Colab, VPS, laptop, etc.).

- **Server side**: Python HTTP server (`shell_tunnel.py`) + Cloudflare Tunnel  
- **Client side**: Simple Bash CLI (`shell_tunnel.sh`) that talks to the public tunnel URL

## Features

- `POST /exec` – run any shell command and get `stdout`, `stderr`, `returncode`
- `POST /upload` – upload a file (base64 encoded)
- `GET /download?path=...` – download a file
- Automatic download of the correct `cloudflared` binary
- Temporary public URL via Cloudflare Tunnel (no account required for quick tunnels)
- Zero configuration beyond running the server

## Repository Structure

```
.
├── shell_tunnel.py    # HTTP shell server + Cloudflare Tunnel
├── shell_tunnel.sh    # Client CLI (Bash)
└── site.txt           # (created by you) contains the tunnel URL
```

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Erickrus/cloudflare_shell_tunnel.git
cd cloudflare_shell_tunnel
```

### 2. Make the client executable

```bash
chmod +x shell_tunnel.sh
```

### 3. (Optional) Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

No extra Python packages are required (uses only the standard library).

## Quick Start

### Server side (the machine you want to control)

```bash
python3 shell_tunnel.py
```

The script will:

1. Download `cloudflared` if it is not present
2. Start an HTTP server on port `8787`
3. Create a Cloudflare quick tunnel
4. Print the public URL, for example:

```
============================================================
  TUNNEL URL: https://random-words-1234.trycloudflare.com
============================================================
```

**Copy that URL.**

### Client side – set up `site.txt`

Create a file named `site.txt` in the **same directory** as the `shell` script and put the tunnel URL inside it (one line, no trailing slash):

```bash
echo "https://random-words-1234.trycloudflare.com" > site.txt
```

Or simply:

```
https://random-words-1234.trycloudflare.com
```

The `shell_tunnel.sh` client reads this file to know where the server is.

> **Tip**: You can keep multiple `site.txt` files or use symlinks if you manage several remote machines.

## Usage

All commands are run from the directory that contains the `shell` script and `site.txt`.

### Execute a command

```bash
./shell_tunnel.sh exec "ls -la"
./shell_tunnel.sh exec "uname -a"
./shell_tunnel.sh exec "python3 --version"
./shell_tunnel.sh exec "pwd && whoami"
```

The exit code of the remote command is preserved.

### Upload a file

```bash
./shell_tunnel.sh upload ./local_script.py /tmp/remote_script.py
./shell_tunnel.sh upload ./data.csv /home/user/data.csv
```

### Download a file

```bash
./shell_tunnel.sh download /tmp/remote_script.py
./shell_tunnel.sh download /var/log/syslog ./local_syslog
```

### Examples with agents

Once the tunnel is running and `site.txt` is set, any agent that can run shell commands can use the remote machine:

```bash
# Claude Code / Cursor / Aider style
./shell_tunnel.sh exec "pip install torch"
./shell_tunnel.sh exec "python train.py --epochs 10"
./shell_tunnel.sh upload model.py /content/model.py
./shell_tunnel.sh download /content/checkpoints/best.pt
```

## API Reference (for custom clients)

### Health check
```
GET /
→ {"status": "ok", "message": "Shell tunnel active"}
```

### Execute command
```
POST /exec
Content-Type: application/json

{
  "cmd": "ls -la",
  "timeout": 30,          # optional, default 30
  "cwd": "/tmp"           # optional
}
```

### Upload file
```
POST /upload
Content-Type: application/json

{
  "path": "/tmp/hello.txt",
  "content": "aGVsbG8=",   # base64
  "mode": "644"            # optional (octal string)
}
```

### Download file
```
GET /download?path=/tmp/hello.txt
```

## Security Notes

- The tunnel URL is **public** and anyone who knows it can execute commands on the server.
- Only use this on trusted networks / temporary environments (Colab, short-lived VMs, etc.).
- Cloudflare quick tunnels expire after some inactivity / time.
- For production use, consider authenticating the endpoints or using a Cloudflare Zero Trust tunnel with access policies.

## Platform Support

| Platform       | cloudflared binary          | Status      |
|----------------|-----------------------------|-------------|
| Linux x86_64   | cloudflared-linux-amd64     | Supported   |
| Linux ARM64    | cloudflared-linux-arm64     | Supported   |
| macOS          | cloudflared-darwin-amd64.tgz| Supported   |
| Windows        | –                           | Not yet     |

## License

MIT
