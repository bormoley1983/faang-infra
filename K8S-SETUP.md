# Kubernetes Cluster Setup Guide

This guide explains how to connect your local Windows machine to your **K3s Homelab Cluster** (`k3s-control-plane`) so you can run the deployment scripts.

## Prerequisites
1. **kubectl** installed on your Windows machine.
2. **SSH access** to your K3s control plane node.
3. Your local machine must be able to resolve the hostname `k3s-control-plane` (via DNS or `hosts` file).

---
## Step 0: install the POC registry

```powershell
Copy-Item .\config\homelab.example.json .\config\homelab.local.json
# Edit the ignored local mapping, then run:
.\install-registry.ps1
```

Complete the CA trust procedure in `k8s/registry/README.md` on every k3s node before deploying workloads.


## Step 1: Extract the Kubeconfig
K3s stores its access configuration on the server. You need to copy this to your local machine.

Run the following in **PowerShell**:

```powershell
# Create the .kube directory if it doesn't exist
mkdir ".kube" -ErrorAction SilentlyContinue

# Copy the config from your k3s server (replace 'user' with your SSH username)
# This will save it as a separate file to avoid overwriting your default config
scp user@k3s-control-plane:/etc/rancher/k3s/k3s.yaml "$.kube\config-homelab"
```

---

## Step 2: Update the Server Address
By default, the K3s config points to `localhost`. You must change this to the network address of your server.

1. Open `$HOME\.kube\config-homelab` in a text editor (Notepad, VS Code, etc.).
2. Locate the `server:` line:
   ```yaml
   server: https://127.0.0.1:6443
   ```
3. Change it to your control plane address:
   ```yaml
   server: https://k3s-control-plane:6443
   ```
   *(Or use the FQDN: `https://k3s-control-plane.domain.local:6443`)*
4. Save and close the file.

---

## Step 3: Activate the Connection
You need to tell your terminal to use this configuration file.

**For the current session:**
```powershell
$env:KUBECONFIG = ".kube\config-homelab"
```

**To make it permanent:**
Add the line above to your PowerShell Profile (run `notepad $PROFILE` to edit it).

---

## Step 4: Verify Connectivity
Run the following command. If you see your nodes listed as `Ready`, you are connected!

```powershell
kubectl get nodes
```

---

## Step 5: Run Deployment
Now that you are connected, navigate to the `faang-infra` folder and run the deployment script:

```powershell
cd faang-infra
.\deploy.ps1
```

### Troubleshooting
* **Connection Refused:** Ensure your Windows firewall or the server's firewall allows traffic on port `6443`.
* **SSL Certificate Error:** If the certificate doesn't match the hostname, you may need to add `--insecure-skip-tls-verify` to your `kubectl` commands, or update the K3s server `tls-san` configuration.
* **DNS Issues:** If `k3s-control-plane` doesn't resolve, add it to `C:\Windows\System32\drivers\etc\hosts`.
