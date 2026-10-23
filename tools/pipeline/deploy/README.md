# Deploying the Gateway (Ubuntu 24.04 ARM64, AWS Singapore)

The Gateway is a control plane: it authenticates teammates, queues jobs and relays signed results.
It never holds Claude credentials and never runs agents. Johan's Worker connects **out** to it over `wss://`.
Python 3.12 is the Ubuntu default; run the unit tests on the host (step 3) because development used 3.14.

## 0. AWS (console)
Security group inbound: 443/tcp from anywhere; 80/tcp only if using the domain variant; 22/tcp from your IP only.
Do not open 8000. Nothing else is needed inbound.

## 1. Packages and code
    sudo apt update && sudo apt install -y python3-venv git caddy
    sudo useradd --system --home /opt/synora --shell /usr/sbin/nologin synora-gateway
    sudo git clone --branch chore/agent-bridge-poc https://github.com/NEC-08240/Synora.git /opt/synora
    cd /opt/synora && sudo git checkout <DEPLOY_COMMIT>
    sudo python3 -m venv .venv && sudo .venv/bin/pip install -r tools/pipeline/requirements-gateway.txt

## 2. Directories
    sudo install -d -m 750 -o root -g synora-gateway /etc/synora-gateway
    sudo install -d -m 750 -o synora-gateway -g synora-gateway /var/lib/synora-gateway /var/log/synora-gateway

## 3. Test on this host
    cd /opt/synora && sudo .venv/bin/pip install -r tools/pipeline/requirements-client.txt
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest $(ls tools/pipeline/test_*.py | sed 's|/|.|g; s|\.py$||')
Expect all tests OK. Do not proceed on failures.

## 4. Configuration
    sudo cp tools/pipeline/deploy/gateway.env.example /etc/synora-gateway/gateway.env
    sudo chmod 640 /etc/synora-gateway/gateway.env && sudo chown root:synora-gateway /etc/synora-gateway/gateway.env
    sudo sed -i "s|REPLACE_ME|$(openssl rand -base64 48)|" /etc/synora-gateway/gateway.env

## 5. Enrol Johan's Worker and the first teammate (public keys only)
Each person runs `python -m tools.pipeline.admin_cli keygen --out-dir keys --name <name>` on their OWN machine
and sends only the printed public key. Then on the host:
    cd /opt/synora
    sudo .venv/bin/python -m tools.pipeline.admin_cli add-worker --registry /etc/synora-gateway/workers.json --worker-id worker-johan --public-key <JOHAN_WORKER_PUBKEY>
    sudo .venv/bin/python -m tools.pipeline.admin_cli add-developer --registry /etc/synora-gateway/team.json --developer-id <id> --name "<Name>" --github <gh> --public-key <PUBKEY> --modules docs/ --branches 'feature/*'
    sudo chown root:synora-gateway /etc/synora-gateway/*.json && sudo chmod 640 /etc/synora-gateway/*.json
Registries load at start: restart the service after every enrolment.

## 6. TLS front end (pick one)
Domain: copy `Caddyfile.domain` to /etc/caddy/Caddyfile, edit the name.
IP only:
    sudo install -d -m 750 -o root -g caddy /etc/caddy/tls
    sudo .venv/bin/python -m tools.pipeline.admin_cli gen-cert --out-dir /etc/caddy/tls --host <PUBLIC_IP> --days 90
    (rename/point the Caddyfile at the generated cert and key; chmod 640, group caddy)
    Give the .crt to Johan and teammates (SYNORA_CA_CERT) and compare the printed SHA-256 out of band.
Then `sudo systemctl reload caddy`.

## 7. Start
    sudo cp tools/pipeline/deploy/synora-gateway.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now synora-gateway
    curl -s http://127.0.0.1:8000/health
    curl -s https://<HOST>/health          # add --cacert gateway.crt for self-signed
    ss -ltn | grep 8000                    # must show 127.0.0.1:8000 only

## 8. Johan's Worker (Windows PC; needs no inbound access)
    set SYNORA_WORKER_ID=worker-johan
    set SYNORA_GATEWAY_URL=wss://<HOST>
    set SYNORA_WORKER_KEY_FILE=<path to worker-johan.key>
    set SYNORA_CA_CERT=<gateway.crt>            (self-signed only)
    set SYNORA_BRIDGE_REPO=<path to the Synora checkout the worktrees come from>
    python -m tools.pipeline.worker_daemon
Budget limits default to 10 jobs/hour, 50/day, 2 GiB, 2 worktrees (SYNORA_WORKER_JOBS_PER_HOUR, _PER_DAY, _MAX_DISK_MB, _MAX_WORKTREES).

## 9. First end-to-end teammate test
On the teammate machine (pip install -r tools/pipeline/requirements-client.txt):
    set SYNORA_GATEWAY_URL=https://<HOST>
    set SYNORA_DEVELOPER_ID=<id>
    set SYNORA_DEVELOPER_KEY_FILE=<path to private key>
    set SYNORA_CA_CERT=<gateway.crt>            (self-signed only)
    python -m tools.pipeline.teammate_cli smoke
Passes when all four steps print PASS: sign in, Worker online, job accepted, result returned. A non-zero exit code
names the failing step (3 = Worker offline, 4 = rejected, 5 = timeout, 6 = job failed).
